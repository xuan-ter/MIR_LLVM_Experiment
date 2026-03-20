import argparse
import csv
import glob
import json
import os
import re
import subprocess
import time
from collections import defaultdict
from datetime import datetime
from math import ceil
from statistics import median


PROJECT_ROOT = "/mnt/fjx/Compiler_Experiment/async_state_machine_bench"
BINARY_PATH = os.path.join(PROJECT_ROOT, "target", "release", "async_state_machine_bench")
DEFAULT_JSON_PATH = "/mnt/fjx/Compiler_Experiment/table/table_json/combined_experiment_matrix.json"


def safe_dir_name(s):
    s = str(s)
    s = re.sub(r"[^a-zA-Z0-9._-]+", "_", s)
    return s[:160] or "x"


def run_cmd(cmd, cwd, env, quiet=True):
    if isinstance(cmd, str):
        p = subprocess.run(
            cmd,
            cwd=cwd,
            shell=True,
            env=env,
            stdout=subprocess.DEVNULL if quiet else None,
            stderr=subprocess.DEVNULL if quiet else None,
        )
        return p.returncode
    p = subprocess.run(
        cmd,
        cwd=cwd,
        shell=False,
        env=env,
        stdout=subprocess.DEVNULL if quiet else None,
        stderr=subprocess.DEVNULL if quiet else None,
    )
    return p.returncode


def clean_project(env):
    return run_cmd("cargo clean", PROJECT_ROOT, env, quiet=True) == 0


def get_combinations(json_path):
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("combinations", [])


def labels_from_combo(combo):
    mir_pass = "N/A"
    if combo.get("mir"):
        if isinstance(combo["mir"], dict):
            mir_pass = combo["mir"].get("pass", "N/A")
        else:
            mir_pass = str(combo["mir"])

    llvm_pass = "None"
    if combo.get("llvm"):
        if isinstance(combo["llvm"], dict):
            llvm_pass = combo["llvm"].get("pass", "None")
        else:
            llvm_pass = str(combo["llvm"])

    return llvm_pass, mir_pass


def compose_rustflags_from_combo(combo):
    parts = ["-C opt-level=3"]

    if combo.get("mir") and isinstance(combo["mir"], dict) and combo["mir"].get("switches"):
        switches = ",".join(combo["mir"]["switches"])
        parts.append(f"-Z mir-enable-passes={switches}")

    if combo.get("llvm") and isinstance(combo["llvm"], dict) and combo["llvm"].get("switches"):
        for switch in combo["llvm"]["switches"]:
            parts.append(f"-C llvm-args={switch}")

    if combo.get("RUSTFLAGS"):
        parts.append(str(combo["RUSTFLAGS"]))

    parts.append("-C codegen-units=1")
    parts.append("--emit=llvm-ir,link")
    return " ".join(parts)


def build_project(env, rustflags):
    env2 = dict(env)
    env2["RUSTFLAGS"] = rustflags
    env2["CARGO_INCREMENTAL"] = "0"
    t0 = time.perf_counter()
    ok = run_cmd("cargo +nightly build --release --quiet", PROJECT_ROOT, env2, quiet=True) == 0
    t1 = time.perf_counter()
    return ok, (t1 - t0), env2


def newest_llvm_ir_path():
    cand = glob.glob(os.path.join(PROJECT_ROOT, "target", "release", "deps", "async_state_machine_bench-*.ll"))
    if not cand:
        return ""
    cand.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return cand[0]


def count_llvm_ir_metrics(ll_path):
    metrics = {
        "IR_alloca": 0,
        "IR_load": 0,
        "IR_store": 0,
        "IR_gep": 0,
        "IR_phi": 0,
        "IR_bb": 0,
    }
    if not ll_path or not os.path.exists(ll_path):
        return metrics
    with open(ll_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            if " alloca " in line:
                metrics["IR_alloca"] += 1
            if re.search(r"\bload\b", line):
                metrics["IR_load"] += 1
            if re.search(r"\bstore\b", line):
                metrics["IR_store"] += 1
            if "getelementptr" in line:
                metrics["IR_gep"] += 1
            if re.search(r"\bphi\b", line):
                metrics["IR_phi"] += 1
            if s.endswith(":") and not s.startswith(";") and "!" not in s:
                metrics["IR_bb"] += 1
    return metrics


def run_binary_repeated(env, variant, n, depth, repeats):
    repeats = int(repeats) if repeats is not None else 1
    repeats = max(1, repeats)
    args = [BINARY_PATH, "--variant", variant, "--n", str(n), "--depth", str(depth)]
    total = 0.0
    for _ in range(repeats):
        t0 = time.perf_counter()
        p = subprocess.run(args, cwd=PROJECT_ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        t1 = time.perf_counter()
        if p.returncode != 0:
            return None, (p.stderr.decode("utf-8", errors="ignore")[:2000] if p.stderr else "RunFailed")
        total += (t1 - t0)
    return total, ""


def run_binary_once(env, variant, n, depth):
    args = [BINARY_PATH, "--variant", variant, "--n", str(n), "--depth", str(depth)]
    t0 = time.perf_counter()
    p = subprocess.run(args, cwd=PROJECT_ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    t1 = time.perf_counter()
    if p.returncode != 0:
        return None, (p.stderr.decode("utf-8", errors="ignore")[:2000] if p.stderr else "RunFailed")
    return (t1 - t0), ""


def pick_baseline_combo(combos):
    for c in combos:
        name = c.get("name") or c.get("Experiment_ID") or ""
        if name == "EXP_DBL_000_BASELINE":
            return c
    for c in combos:
        name = c.get("name") or c.get("Experiment_ID") or ""
        if name == "EXP_000_ALL_OFF":
            return c
    return combos[0] if combos else None


def calibrate_repeats(env_base, baseline_combo, variants, n, depth, target_seconds, max_repeats, skip_clean):
    repeats_by_variant = {v: 1 for v in variants}
    if not baseline_combo:
        return repeats_by_variant
    if target_seconds is None or float(target_seconds) <= 0:
        return repeats_by_variant

    rustflags = compose_rustflags_from_combo(baseline_combo)
    if not skip_clean:
        clean_project(env_base)
    ok, _, env2 = build_project(env_base, rustflags)
    if not ok:
        return repeats_by_variant

    for v in variants:
        t, _ = run_binary_once(env2, v, n, depth)
        if t is None or t <= 0:
            repeats_by_variant[v] = 1
            continue
        r = int(ceil(float(target_seconds) / float(t)))
        repeats_by_variant[v] = max(1, min(int(max_repeats), r))

    return repeats_by_variant


def aggregate_medians(rows):
    by = defaultdict(list)
    for r in rows:
        key = (r["Variant"], r["ConfigName"])
        if r["Status"] != "Success":
            continue
        by[key].append(r)

    out = []
    for (variant, cfg), rs in sorted(by.items()):
        def meds(k, cast=float):
            xs = []
            for r in rs:
                try:
                    xs.append(cast(r[k]))
                except Exception:
                    pass
            return median(xs) if xs else None

        out.append(
            {
                "Variant": variant,
                "ConfigName": cfg,
                "n": str(len(rs)),
                "runtime_med": f"{meds('TotalRuntime(s)'):.6f}" if meds("TotalRuntime(s)") is not None else "",
                "compile_med": f"{meds('CompileTime(s)'):.6f}" if meds("CompileTime(s)") is not None else "",
                "size_med": f"{meds('BinarySize(Bytes)', int):.0f}" if meds("BinarySize(Bytes)", int) is not None else "",
                "alloca_med": f"{meds('IR_alloca', int):.0f}" if meds("IR_alloca", int) is not None else "",
                "load_med": f"{meds('IR_load', int):.0f}" if meds("IR_load", int) is not None else "",
                "store_med": f"{meds('IR_store', int):.0f}" if meds("IR_store", int) is not None else "",
                "gep_med": f"{meds('IR_gep', int):.0f}" if meds("IR_gep", int) is not None else "",
                "phi_med": f"{meds('IR_phi', int):.0f}" if meds("IR_phi", int) is not None else "",
                "bb_med": f"{meds('IR_bb', int):.0f}" if meds("IR_bb", int) is not None else "",
            }
        )
    return out


def compute_interaction(summary_rows, metric_key, smaller_is_better=True):
    idx = {(r["Variant"], r["ConfigName"]): r for r in summary_rows}
    out = []
    for variant in sorted({r["Variant"] for r in summary_rows}):
        def get(cfg):
            r = idx.get((variant, cfg))
            if not r:
                return None
            v = r.get(metric_key, "")
            if v == "":
                return None
            try:
                return float(v)
            except Exception:
                return None

        a = get("M_on_L_on")
        b = get("M_on_L_off")
        c = get("M_off_L_on")
        d = get("M_off_L_off")
        if None in (a, b, c, d):
            continue

        if smaller_is_better:
            eff = lambda x: -x
        else:
            eff = lambda x: x
        delta = eff(a) - eff(b) - eff(c) + eff(d)
        out.append(
            {
                "Variant": variant,
                "metric": metric_key,
                "delta": f"{delta:.6f}",
                "M_on_L_on": f"{a:.6f}",
                "M_on_L_off": f"{b:.6f}",
                "M_off_L_on": f"{c:.6f}",
                "M_off_L_off": f"{d:.6f}",
            }
        )
    return out


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--json-path", default=DEFAULT_JSON_PATH)
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--warmup", type=int, default=0)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--start", type=int, default=0)
    p.add_argument("--output-dir", default="")
    p.add_argument("--skip-clean", action="store_true")
    p.add_argument("--n", type=int, default=1_000_000)
    p.add_argument("--depth", type=int, default=12)
    p.add_argument("--target-seconds", type=float, default=4.0)
    p.add_argument("--max-repeats", type=int, default=1000)
    args = p.parse_args()

    variants = ["S", "B", "L"]

    combos = get_combinations(args.json_path)
    if args.start > 0:
        combos = combos[args.start:]
    if args.limit and args.limit > 0:
        combos = combos[: args.limit]

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = args.output_dir or os.path.join(PROJECT_ROOT, "results", f"run_{ts}")
    os.makedirs(out_dir, exist_ok=True)
    results_csv = os.path.join(out_dir, "experiment_results.csv")
    summary_csv = os.path.join(out_dir, "summary_medians.csv")
    inter_csv = os.path.join(out_dir, "interaction_summary.csv")

    env_base = dict(os.environ)
    cargo_bin = os.path.expanduser("~/.cargo/bin")
    if cargo_bin and cargo_bin not in env_base.get("PATH", ""):
        env_base["PATH"] = f"{cargo_bin}:{env_base.get('PATH', '')}"

    baseline_combo = pick_baseline_combo(combos)
    repeats_by_variant = calibrate_repeats(
        env_base=env_base,
        baseline_combo=baseline_combo,
        variants=variants,
        n=args.n,
        depth=args.depth,
        target_seconds=args.target_seconds,
        max_repeats=args.max_repeats,
        skip_clean=args.skip_clean,
    )

    fields = [
        "ConfigName",
        "Variant",
        "RunID",
        "LLVM_Pass",
        "MIR_Pass",
        "BinarySize(Bytes)",
        "TotalRuntime(s)",
        "CompileTime(s)",
        "IR_alloca",
        "IR_load",
        "IR_store",
        "IR_gep",
        "IR_phi",
        "IR_bb",
        "LLVM_IR_Path",
        "RunRepeats",
        "TargetSeconds",
        "Status",
    ]

    with open(results_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()

        for combo in combos:
            name = combo.get("name") or combo.get("Experiment_ID") or "Unknown"
            llvm_pass, mir_pass = labels_from_combo(combo)
            rustflags = compose_rustflags_from_combo(combo)
            total_iters = max(args.warmup, 0) + max(args.runs, 1)

            for it in range(total_iters):
                is_warmup = it < max(args.warmup, 0)
                run_id = 0 if is_warmup else (it - max(args.warmup, 0) + 1)

                if not args.skip_clean:
                    clean_project(env_base)
                ok, compile_time, env2 = build_project(env_base, rustflags)
                if not ok:
                    if not is_warmup:
                        for variant in variants:
                            w.writerow(
                                {
                                    "ConfigName": name,
                                    "Variant": variant,
                                    "RunID": run_id,
                                    "LLVM_Pass": llvm_pass,
                                    "MIR_Pass": mir_pass,
                                    "BinarySize(Bytes)": 0,
                                    "TotalRuntime(s)": 0,
                                    "CompileTime(s)": f"{compile_time:.6f}",
                                    "IR_alloca": "",
                                    "IR_load": "",
                                    "IR_store": "",
                                    "IR_gep": "",
                                    "IR_phi": "",
                                    "IR_bb": "",
                                    "LLVM_IR_Path": "",
                                    "Status": "BuildFailed",
                                }
                            )
                    continue

                size = os.path.getsize(BINARY_PATH) if os.path.exists(BINARY_PATH) else 0
                ll_path = newest_llvm_ir_path()
                ir_metrics = count_llvm_ir_metrics(ll_path)

                if is_warmup:
                    continue

                for variant in variants:
                    repeats = repeats_by_variant.get(variant, 1)
                    wall, _ = run_binary_repeated(env2, variant, args.n, args.depth, repeats)
                    if wall is None:
                        w.writerow(
                            {
                                "ConfigName": name,
                                "Variant": variant,
                                "RunID": run_id,
                                "LLVM_Pass": llvm_pass,
                                "MIR_Pass": mir_pass,
                                "BinarySize(Bytes)": size,
                                "TotalRuntime(s)": 0,
                                "CompileTime(s)": f"{compile_time:.6f}",
                                "IR_alloca": ir_metrics["IR_alloca"],
                                "IR_load": ir_metrics["IR_load"],
                                "IR_store": ir_metrics["IR_store"],
                                "IR_gep": ir_metrics["IR_gep"],
                                "IR_phi": ir_metrics["IR_phi"],
                                "IR_bb": ir_metrics["IR_bb"],
                                "LLVM_IR_Path": ll_path,
                                "RunRepeats": repeats,
                                "TargetSeconds": f"{args.target_seconds:.6f}",
                                "Status": "RunFailed",
                            }
                        )
                        continue

                    w.writerow(
                        {
                            "ConfigName": name,
                            "Variant": variant,
                            "RunID": run_id,
                            "LLVM_Pass": llvm_pass,
                            "MIR_Pass": mir_pass,
                            "BinarySize(Bytes)": size,
                            "TotalRuntime(s)": f"{wall:.6f}",
                            "CompileTime(s)": f"{compile_time:.6f}",
                            "IR_alloca": ir_metrics["IR_alloca"],
                            "IR_load": ir_metrics["IR_load"],
                            "IR_store": ir_metrics["IR_store"],
                            "IR_gep": ir_metrics["IR_gep"],
                            "IR_phi": ir_metrics["IR_phi"],
                            "IR_bb": ir_metrics["IR_bb"],
                            "LLVM_IR_Path": ll_path,
                            "RunRepeats": repeats,
                            "TargetSeconds": f"{args.target_seconds:.6f}",
                            "Status": "Success",
                        }
                    )

    rows = []
    with open(results_csv, "r", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            rows.append(row)

    summary = aggregate_medians(rows)
    with open(summary_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "Variant",
                "ConfigName",
                "n",
                "runtime_med",
                "compile_med",
                "size_med",
                "alloca_med",
                "load_med",
                "store_med",
                "gep_med",
                "phi_med",
                "bb_med",
            ],
        )
        w.writeheader()
        for r0 in summary:
            w.writerow(r0)

    inter = []
    inter += compute_interaction(summary, "runtime_med", smaller_is_better=True)
    for k in ("alloca_med", "load_med", "store_med", "gep_med", "phi_med", "bb_med"):
        inter += compute_interaction(summary, k, smaller_is_better=True)

    if inter:
        with open(inter_csv, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(
                f,
                fieldnames=["Variant", "metric", "delta", "M_on_L_on", "M_on_L_off", "M_off_L_on", "M_off_L_off"],
            )
            w.writeheader()
            for r0 in inter:
                w.writerow(r0)

    print(out_dir)


if __name__ == "__main__":
    main()
