import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)

PROJECT_ROOT = SCRIPT_DIR
DEFAULT_JSON_PATH = "/mnt/MIR_LLVM_Experiment/table/table_json/combined_experiment_matrix.json"
if not os.path.exists(DEFAULT_JSON_PATH):
    DEFAULT_JSON_PATH = os.path.join(REPO_ROOT, "table", "table_json", "combined_experiment_matrix.json")

DEFAULT_BENCH_NAME = "trait_inline"
DEFAULT_BENCH_FILTERS = ["easy_case", "mir_dependent_case"]


def get_combinations(json_path):
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("combinations", [])


def get_core4_combinations():
    return [
        {
            "name": "CORE_BASELINE",
            "group": "Baseline",
            "llvm": {"pass": "baseline", "switches": [], "parameters": {}},
            "mir": None,
        },
        {
            "name": "CORE_NO_MIR_INLINE",
            "group": "No-MIR-Inline",
            "llvm": {"pass": "baseline", "switches": [], "parameters": {}},
            "mir": {"pass": "Inline", "switches": ["-Inline"], "parameters": {}},
        },
        {
            "name": "CORE_NO_LLVM_INLINE_INSTCOMBINE",
            "group": "No-LLVM-Inline/InstCombine",
            "llvm": {"pass": "NoLLVM", "switches": ["--inline-threshold=0"], "parameters": {}},
            "mir": None,
            "RUSTFLAGS": "-C no-prepopulate-passes",
        },
        {
            "name": "CORE_DUAL_DISABLE",
            "group": "Dual-disable",
            "llvm": {"pass": "NoLLVM", "switches": ["--inline-threshold=0"], "parameters": {}},
            "mir": {"pass": "Inline", "switches": ["-Inline"], "parameters": {}},
            "RUSTFLAGS": "-C no-prepopulate-passes",
        },
    ]


def clean_project(env=None):
    target_dir = os.path.join(PROJECT_ROOT, "target")
    if os.path.exists(target_dir):
        try:
            shutil.rmtree(target_dir)
        except Exception:
            if env is None:
                env = os.environ.copy()
            subprocess.run(
                ["cargo", "clean"],
                cwd=PROJECT_ROOT,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )


def compose_rustflags_from_combo(combo):
    parts = ["-C opt-level=3"]
    if combo.get("mir") and isinstance(combo["mir"], dict) and combo["mir"].get("switches"):
        switches = ",".join(combo["mir"]["switches"])
        parts.append(f"-Z mir-enable-passes={switches}")
    if combo.get("llvm") and isinstance(combo["llvm"], dict) and combo["llvm"].get("switches"):
        for switch in combo["llvm"]["switches"]:
            parts.append(f"-C llvm-args={switch}")
    if "RUSTFLAGS" in combo and combo["RUSTFLAGS"]:
        parts.append(combo["RUSTFLAGS"])
    return " ".join(parts)


def extract_ir_blocks(raw_text, wanted_substrings):
    blocks = []
    current = []
    keep = False
    for line in raw_text.splitlines(True):
        if line.startswith("; *** IR Dump After "):
            if current and keep:
                blocks.append("".join(current))
            current = [line]
            keep = any(s in line for s in wanted_substrings)
            continue
        if current:
            current.append(line)
    if current and keep:
        blocks.append("".join(current))
    return "".join(blocks)


def dump_ir_sample(combo, bench_name, base_out, logf, passes):
    name = combo.get("name") or combo.get("Experiment_ID") or "Unknown"
    group = combo.get("group") or "Matrix"
    ir_dir = os.path.join(base_out, "ir_samples")
    os.makedirs(ir_dir, exist_ok=True)

    env = os.environ.copy()
    cargo_bin = os.path.expanduser("~/.cargo/bin")
    if cargo_bin and cargo_bin not in env.get("PATH", ""):
        env["PATH"] = f"{cargo_bin}:{env.get('PATH', '')}"

    extra = [
        "-Z unstable-options",
        "-C symbol-mangling-version=legacy",
    ]
    for p in passes:
        extra.append(f"-C llvm-args=-print-after={p}")

    rustflags = compose_rustflags_from_combo(combo) + " " + " ".join(extra)
    env["RUSTFLAGS"] = rustflags

    msg = f"[IRSample] {name} ({group}) passes={','.join(passes)}"
    print(msg)
    logf.write(msg + "\n")
    logf.flush()

    clean_project(env)
    cmd = ["cargo", "+nightly", "bench", "--bench", bench_name, "--no-run"]
    r = subprocess.run(
        cmd,
        cwd=PROJECT_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    raw_path = os.path.join(ir_dir, f"{name}__{group}__raw_ir_dump.txt")
    with open(raw_path, "w", encoding="utf-8") as f:
        f.write((r.stdout or "") + "\n")
        f.write(r.stderr or "")

    if r.returncode != 0:
        logf.write(f"[IRSampleError] rustc failed for {name} ({group})\n")
        logf.write((r.stderr or "").strip() + "\n")
        logf.flush()
        return False

    wanted = ["trait_test", "kernel_", "wrap_", "apply_", "transform"]
    filtered = extract_ir_blocks(r.stderr or "", wanted)
    filtered_path = os.path.join(ir_dir, f"{name}__{group}__filtered_ir_dump.txt")
    with open(filtered_path, "w", encoding="utf-8") as f:
        f.write(filtered)
    logf.write(f"[IRSampleSaved] raw={raw_path} filtered={filtered_path}\n")
    logf.flush()
    return True


def build_bench(env, bench_name, logf, retries=2):
    backoff = 0.5
    last_err = ""
    cmd = [
        "cargo",
        "+nightly",
        "bench",
        "--bench",
        bench_name,
        "--no-run",
        "--quiet",
    ]
    for _ in range(retries + 1):
        r = subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if r.returncode == 0:
            return True, "Success", ""
        err = r.stderr or ""
        last_err = err
        logf.write(err + "\n")
        logf.flush()
        if ("Text file busy (os error 26)" in err) or ("never executed" in err):
            time.sleep(backoff)
            backoff = min(backoff * 2, 4.0)
            continue
        return False, "BuildFailed", err.strip()
    if ("Text file busy (os error 26)" in last_err) or ("never executed" in last_err) or ("failed to run custom build command" in last_err):
        return False, "Skipped", last_err.strip()
    return False, "BuildFailed", last_err.strip()


def find_bench_exe(bench_name):
    deps_dir = os.path.join(PROJECT_ROOT, "target", "release", "deps")
    if not os.path.isdir(deps_dir):
        return None
    prefix = f"{bench_name}-"
    candidates = []
    for name in os.listdir(deps_dir):
        if not name.startswith(prefix):
            continue
        if name.endswith(".d"):
            continue
        path = os.path.join(deps_dir, name)
        if not os.path.isfile(path):
            continue
        if not os.access(path, os.X_OK):
            continue
        try:
            mtime = os.path.getmtime(path)
        except Exception:
            mtime = 0
        candidates.append((mtime, path))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def run_benchmark(exe_path, bench_filter, repeat):
    total_wall = 0.0
    last_out = ""
    last_err = ""
    ns_per_iter = ""
    mbps = ""
    for _ in range(repeat):
        t0 = time.perf_counter()
        p = subprocess.run(
            [exe_path, "--bench", bench_filter, "--exact", "--test-threads", "1", "-q"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        t1 = time.perf_counter()
        if p.returncode != 0:
            last_err = (p.stdout or "").strip()
            return None, "", "", last_err
        last_out = p.stdout or ""
        total_wall += (t1 - t0)

        m_ns = re.search(r"bench:\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*ns/iter", last_out)
        if m_ns:
            ns_per_iter = m_ns.group(1).replace(",", "")
        m_mbps = re.search(r"=\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*MB/s", last_out)
        if m_mbps:
            mbps = m_mbps.group(1).replace(",", "")

    if not ns_per_iter:
        last_err = last_out.strip()
        return None, "", "", last_err

    return total_wall, ns_per_iter, mbps, last_err


def measure_combination(combo, runs, bench_name, bench_filters, bench_repeat, logf):
    name = combo.get("name") or combo.get("Experiment_ID") or "Unknown"
    group = combo.get("group") or "Matrix"

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

    env = os.environ.copy()
    cargo_bin = os.path.expanduser("~/.cargo/bin")
    if cargo_bin and cargo_bin not in env.get("PATH", ""):
        env["PATH"] = f"{cargo_bin}:{env.get('PATH', '')}"

    rustflags = compose_rustflags_from_combo(combo)
    env["RUSTFLAGS"] = rustflags

    total_iters = runs + 1
    rows = []
    for n in range(total_iters):
        is_warmup = (n == 0)
        run_id = n

        msg1 = f"[Exp] {name} Warmup 1/1" if is_warmup else f"[Exp] {name} Iteration {run_id}/{runs}"
        msg2 = f"[Flags] {rustflags}"
        msg3 = f"[Bench] {bench_name}::{','.join(bench_filters)} x{bench_repeat}"
        print(msg1)
        print(msg2)
        print(msg3)
        logf.write(msg1 + "\n")
        logf.write(msg2 + "\n")
        logf.write(msg3 + "\n")
        logf.flush()

        clean_project(env)

        t0 = time.perf_counter()
        ok, status, build_err = build_bench(env, bench_name, logf)
        t1 = time.perf_counter()
        compile_time = t1 - t0

        if not ok:
            if is_warmup:
                logf.write(f"[SkipConfig] Warmup build failed: {status}\n")
                if build_err:
                    logf.write("[BuildError] " + build_err + "\n")
                logf.flush()
                break

            for bench_filter in bench_filters:
                rows.append(
                    {
                        "ConfigName": name,
                        "Group": group,
                        "Case": bench_filter,
                        "RunID": run_id,
                        "LLVM_Pass": llvm_pass,
                        "MIR_Pass": mir_pass,
                        "BinarySize(Bytes)": 0,
                        "NsPerIter": "",
                        "MBps": "",
                        "TotalRuntime(s)": 0,
                        "CompileTime(s)": f"{compile_time:.6f}",
                        "Status": status,
                    }
                )
            break

        exe_path = find_bench_exe(bench_name)
        if not exe_path:
            if is_warmup:
                logf.write("[SkipConfig] Warmup produced no bench binary\n")
                logf.flush()
                break
            for bench_filter in bench_filters:
                rows.append(
                    {
                        "ConfigName": name,
                        "Group": group,
                        "Case": bench_filter,
                        "RunID": run_id,
                        "LLVM_Pass": llvm_pass,
                        "MIR_Pass": mir_pass,
                        "BinarySize(Bytes)": 0,
                        "NsPerIter": "",
                        "MBps": "",
                        "TotalRuntime(s)": 0,
                        "CompileTime(s)": f"{compile_time:.6f}",
                        "Status": "NoBinary",
                    }
                )
            break

        try:
            size = os.path.getsize(exe_path)
        except Exception:
            size = 0

        for bench_filter in bench_filters:
            wall_time, ns_per_iter, mbps, run_err = run_benchmark(exe_path, bench_filter, bench_repeat)
            if wall_time is None:
                if run_err:
                    logf.write(f"[RunError:{bench_filter}] " + run_err + "\n")
                    logf.flush()
                if is_warmup:
                    logf.write(f"[SkipConfig] Warmup run failed for {bench_filter}\n")
                    logf.flush()
                    return rows
                rows.append(
                    {
                        "ConfigName": name,
                        "Group": group,
                        "Case": bench_filter,
                        "RunID": run_id,
                        "LLVM_Pass": llvm_pass,
                        "MIR_Pass": mir_pass,
                        "BinarySize(Bytes)": size,
                        "NsPerIter": "",
                        "MBps": "",
                        "TotalRuntime(s)": 0,
                        "CompileTime(s)": f"{compile_time:.6f}",
                        "Status": "RunFailed",
                    }
                )
                continue

            if is_warmup:
                print(
                    f"[WarmupResult:{bench_filter}] Size={size}B, Compile={compile_time:.6f}s, Wall={wall_time:.6f}s, NsPerIter={ns_per_iter}, MBps={mbps}"
                )
                continue

            print(
                f"[Result:{bench_filter}] Size={size}B, Compile={compile_time:.6f}s, Wall={wall_time:.6f}s, NsPerIter={ns_per_iter}, MBps={mbps}"
            )
            rows.append(
                {
                    "ConfigName": name,
                    "Group": group,
                    "Case": bench_filter,
                    "RunID": run_id,
                    "LLVM_Pass": llvm_pass,
                    "MIR_Pass": mir_pass,
                    "BinarySize(Bytes)": size,
                    "NsPerIter": ns_per_iter,
                    "MBps": mbps,
                    "TotalRuntime(s)": f"{wall_time:.6f}",
                    "CompileTime(s)": f"{compile_time:.6f}",
                    "Status": "Success",
                }
            )

    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-path", default=DEFAULT_JSON_PATH)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--bench-name", default=DEFAULT_BENCH_NAME)
    parser.add_argument("--bench-repeat", type=int, default=1)
    parser.add_argument("--core4", action="store_true")
    parser.add_argument("--ir-sample-count", type=int, default=-1)
    parser.add_argument("--ir-passes", default="inline,instcombine")
    args = parser.parse_args()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_out = args.output_dir or os.path.join(PROJECT_ROOT, "mir_llvm_hybrid_py", ts)
    os.makedirs(base_out, exist_ok=True)

    results_csv = os.path.join(base_out, "experiment_results.csv")
    exec_log = os.path.join(base_out, "experiment_execution.log")

    if args.core4:
        combos = get_core4_combinations()
    else:
        if not os.path.exists(args.json_path):
            print(f"Error: JSON path {args.json_path} does not exist.")
            return
        combos = get_combinations(args.json_path)
    if args.start > 0:
        combos = combos[args.start:]
    if args.limit and args.limit > 0:
        combos = combos[: args.limit]

    with open(exec_log, "w", encoding="utf-8") as logf:
        print(f"Total Rows: {len(combos)}")
        logf.write(f"Total Rows: {len(combos)}\n")
        logf.flush()

        passes = [p.strip() for p in args.ir_passes.split(",") if p.strip()]
        sample_count = args.ir_sample_count
        if sample_count < 0:
            sample_count = 4 if args.core4 else 0
        for combo in combos[:sample_count]:
            dump_ir_sample(combo, args.bench_name, base_out, logf, passes)

        with open(results_csv, "w", encoding="utf-8", newline="") as outcsv:
            writer = csv.DictWriter(
                outcsv,
                fieldnames=[
                    "ConfigName",
                    "Group",
                    "Case",
                    "RunID",
                    "LLVM_Pass",
                    "MIR_Pass",
                    "BinarySize(Bytes)",
                    "NsPerIter",
                    "MBps",
                    "TotalRuntime(s)",
                    "CompileTime(s)",
                    "Status",
                ],
            )
            writer.writeheader()
            outcsv.flush()

            for combo in combos:
                rows = measure_combination(
                    combo,
                    args.runs,
                    args.bench_name,
                    DEFAULT_BENCH_FILTERS,
                    args.bench_repeat,
                    logf,
                )
                for row in rows:
                    writer.writerow(row)
                outcsv.flush()


if __name__ == "__main__":
    main()
