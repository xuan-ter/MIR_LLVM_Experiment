import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime


PROJECT_ROOT = "/mnt/fjx/Compiler_Experiment/CFG_test"
DEFAULT_JSON_PATH = "/mnt/fjx/Compiler_Experiment/table/table_json/combined_experiment_matrix.json"


def get_combinations(json_path):
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("combinations", [])


def safe_dir_name(s):
    s = str(s)
    s = s.strip().replace(" ", "_")
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", s)
    return s[:180] if len(s) > 180 else s


def labels_from_combo(combo):
    mir_pass_label = "N/A"
    if combo.get("mir"):
        if isinstance(combo["mir"], dict):
            mir_pass_label = combo["mir"].get("pass", "N/A")
        else:
            mir_pass_label = str(combo["mir"])

    llvm_pass_label = "None"
    if combo.get("llvm"):
        if isinstance(combo["llvm"], dict):
            llvm_pass_label = combo["llvm"].get("pass", "None")
        else:
            llvm_pass_label = str(combo["llvm"])

    return llvm_pass_label, mir_pass_label


def compose_rustflags_from_combo(combo):
    flags = ["-C opt-level=3"]

    if combo.get("mir") and isinstance(combo["mir"], dict) and combo["mir"].get("switches"):
        switches = ",".join(combo["mir"]["switches"])
        flags.append(f"-Z mir-enable-passes={switches}")

    if combo.get("llvm") and isinstance(combo["llvm"], dict) and combo["llvm"].get("switches"):
        for switch in combo["llvm"]["switches"]:
            flags.append(f"-C llvm-args={switch}")

    if combo.get("RUSTFLAGS"):
        flags.append(str(combo["RUSTFLAGS"]))

    return " ".join(flags)


def list_files_by_mtime(root_dir, suffixes):
    results = []
    for dirpath, _, filenames in os.walk(root_dir):
        for fn in filenames:
            if any(fn.endswith(suf) for suf in suffixes):
                fp = os.path.join(dirpath, fn)
                try:
                    st = os.stat(fp)
                except OSError:
                    continue
                results.append((st.st_mtime, fp))
    results.sort(key=lambda x: x[0])
    return [fp for _, fp in results]


def parse_mir_counts(mir_text):
    bb = 0
    for line in mir_text.splitlines():
        if re.match(r"^\s*bb\d+:", line):
            bb += 1
    goto = len(re.findall(r"\bgoto\b", mir_text))
    switch_int = len(re.findall(r"\bswitchInt\b", mir_text))
    terminator = len(re.findall(r"^\s*(goto|switchInt|return|resume|unreachable)\b", mir_text, flags=re.MULTILINE))
    return {
        "bb": bb,
        "goto": goto,
        "switchInt": switch_int,
        "terminatorBlocks": terminator,
    }


def collect_mir_evidence(mir_dump_dir):
    mir_files = list_files_by_mtime(mir_dump_dir, (".mir",))
    if not mir_files:
        return None

    built_after = None
    runtime_opt_after = None
    for fp in mir_files:
        base = os.path.basename(fp)
        if base.endswith(".built.after.mir"):
            built_after = fp
        elif base.endswith(".runtime-optimized.after.mir"):
            runtime_opt_after = fp

    first_fp = built_after or mir_files[0]
    last_fp = runtime_opt_after or mir_files[-1]

    try:
        with open(first_fp, "r", encoding="utf-8", errors="replace") as f:
            first_text = f.read()
        with open(last_fp, "r", encoding="utf-8", errors="replace") as f:
            last_text = f.read()
    except OSError:
        return None

    first = parse_mir_counts(first_text)
    last = parse_mir_counts(last_text)
    return {
        "mir_first_file": os.path.basename(first_fp),
        "mir_last_file": os.path.basename(last_fp),
        "mir_first_path": first_fp,
        "mir_last_path": last_fp,
        "mir_bb_first": first["bb"],
        "mir_bb_last": last["bb"],
        "mir_goto_first": first["goto"],
        "mir_goto_last": last["goto"],
        "mir_switch_first": first["switchInt"],
        "mir_switch_last": last["switchInt"],
        "mir_term_blocks_first": first["terminatorBlocks"],
        "mir_term_blocks_last": last["terminatorBlocks"],
    }


def parse_llvm_function_block(ir_text, func_name):
    m = re.search(rf"^define\b.*@{re.escape(func_name)}\b.*\{{\s*$", ir_text, flags=re.MULTILINE)
    if not m:
        m = re.search(rf"^define\b.*@.*{re.escape(func_name)}.*\{{\s*$", ir_text, flags=re.MULTILINE)
    if not m:
        return None
    start = m.end()
    end = ir_text.find("\n}\n", start)
    if end == -1:
        end = ir_text.find("\n}", start)
        if end == -1:
            return None
    return ir_text[start:end]


def parse_llvm_counts(ir_text, func_name):
    body = parse_llvm_function_block(ir_text, func_name)
    if body is None:
        return None
    bb = 0
    br = 0
    switch = 0
    for line in body.splitlines():
        if re.match(r"^[A-Za-z$._][A-Za-z0-9$._-]*:\s*(;.*)?$", line):
            bb += 1
        if re.search(r"^\s*br\s", line):
            br += 1
        if re.search(r"^\s*switch\s", line):
            switch += 1
    return {"llvm_bb": bb, "llvm_br": br, "llvm_switch": switch}


def parse_asm_counts(asm_text, sym):
    m = re.search(rf"^{re.escape(sym)}:\s*$", asm_text, flags=re.MULTILINE)
    if not m:
        return None
    start = m.end()
    body_lines = []
    for line in asm_text[start:].splitlines():
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*:\s*$", line) and (not line.startswith(".L")):
            break
        body_lines.append(line)
    body = "\n".join(body_lines)
    jmp = 0
    for line in body.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("."):
            continue
        if s.startswith("#"):
            continue
        op = s.split(None, 1)[0]
        if op.startswith("j"):
            jmp += 1
    return {"asm_jmp": jmp}


def clean_project(env):
    target_dir = os.path.join(PROJECT_ROOT, "target")
    if os.path.exists(target_dir):
        try:
            shutil.rmtree(target_dir)
            return True
        except Exception:
            pass
    p = subprocess.run(["cargo", "clean"], cwd=PROJECT_ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return p.returncode == 0


def run_capture(cmd, env, logf):
    logf.write(f"[EXEC] {cmd}\n")
    logf.flush()
    p = subprocess.run(
        cmd,
        cwd=PROJECT_ROOT,
        env=env,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if p.stdout:
        logf.write(f"[STDOUT] {p.stdout}\n")
    if p.stderr:
        logf.write(f"[STDERR] {p.stderr}\n")
    logf.flush()
    return p


def build_project(env, logf, retries=3):
    cmd = "cargo build --release --quiet"
    last_err = ""
    backoff = 0.5
    for _ in range(max(retries, 1)):
        t0 = time.perf_counter()
        p = run_capture(cmd, env, logf)
        t1 = time.perf_counter()
        if p.returncode == 0:
            return True, (t1 - t0)
        last_err = (p.stderr or "") + "\n" + (p.stdout or "")
        if "Text file busy (os error 26)" in last_err:
            time.sleep(backoff)
            backoff = min(backoff * 2, 4.0)
            continue
        break
    if "Text file busy (os error 26)" in last_err:
        return False, 0.0
    return False, 0.0


def get_exe_path():
    exe_path = os.path.join(PROJECT_ROOT, "target", "release", "cfg_test")
    return exe_path if os.path.exists(exe_path) else None


def run_benchmark(exe_path, repeats, warmup, run_args):
    args = [exe_path] + run_args

    for _ in range(max(warmup, 0)):
        p = subprocess.run(args, cwd=PROJECT_ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if p.returncode != 0:
            return None

    total = 0.0
    for _ in range(max(repeats, 1)):
        t0 = time.perf_counter()
        p = subprocess.run(args, cwd=PROJECT_ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        t1 = time.perf_counter()
        if p.returncode != 0:
            return None
        total += (t1 - t0)

    return total


def collect_recent_save_temps_files(modified_after):
    exts = (".ll", ".s")
    search_roots = [
        os.path.join(PROJECT_ROOT, "target", "release"),
        os.path.join(PROJECT_ROOT, "target", "release", "deps"),
    ]
    found = []
    for root in search_roots:
        if not os.path.isdir(root):
            continue
        for dirpath, _, filenames in os.walk(root):
            for fn in filenames:
                if not fn.endswith(exts):
                    continue
                if "cfg_test" not in fn:
                    continue
                fp = os.path.join(dirpath, fn)
                try:
                    st = os.stat(fp)
                except OSError:
                    continue
                if st.st_mtime >= modified_after:
                    found.append((st.st_mtime, fp))
    found.sort(key=lambda x: x[0])
    return [fp for _, fp in found]


def already_done(csv_path, name, runs_needed):
    if not os.path.exists(csv_path):
        return False
    count = 0
    with open(csv_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.startswith(f"{name},"):
                count += 1
                if count >= runs_needed:
                    return True
    return False


def parse_run_args(variant, n, iters, seed):
    return [
        "--variant",
        variant,
        "--n",
        str(n),
        "--iters",
        str(iters),
        "--seed",
        str(seed),
    ]


def measure_combination(
    combo,
    runs,
    skip_clean,
    run_repeats,
    warmup,
    variant,
    n,
    iters,
    seed,
    csv_path,
    logf,
    evidence,
    keep_ir,
    base_out,
):
    name = combo.get("name") or combo.get("Experiment_ID") or "Unknown"
    llvm_pass_label, mir_pass_label = labels_from_combo(combo)

    if already_done(csv_path, name, runs):
        msg = f"[Skip] {name} (Already done)"
        print(msg)
        logf.write(msg + "\n")
        logf.flush()
        return

    env = os.environ.copy()
    cargo_bin = os.path.expanduser("~/.cargo/bin")
    if cargo_bin and cargo_bin not in env.get("PATH", ""):
        env["PATH"] = f"{cargo_bin}:{env.get('PATH', '')}"

    rustflags = compose_rustflags_from_combo(combo)
    env_rustflags = rustflags
    env.pop("CARGO_INCREMENTAL", None)
    env["CARGO_INCREMENTAL"] = "0"

    run_args = parse_run_args(variant, n, iters, seed)
    dump_item = "workload_a" if variant.lower() == "a" else "workload_b"

    for run_id in range(1, runs + 1):
        evidence_dir = os.path.join(base_out, "evidence", safe_dir_name(name), f"run_{run_id}")
        mir_dump_dir = os.path.join(evidence_dir, "mir_dump")
        if evidence:
            os.makedirs(mir_dump_dir, exist_ok=True)
            env_rustflags_run = (
                env_rustflags
                + f" --emit=llvm-ir,asm,link"
                + f" -Z dump-mir={dump_item}"
                + f" -Z dump-mir-dir={mir_dump_dir}"
                + f" -Z dump-mir-exclude-pass-number=yes"
                + f" -Z dump-mir-exclude-alloc-bytes=yes"
            )
        else:
            env_rustflags_run = env_rustflags

        env["RUSTFLAGS"] = env_rustflags_run

        msg1 = f"[Exp] {name} Iteration {run_id}/{runs}"
        msg2 = f"[Flags] {env_rustflags_run}"
        msg3 = f"[Run] repeats={run_repeats}, warmup={warmup}, args={' '.join(run_args)}"
        print(msg1)
        print(msg2)
        print(msg3)
        logf.write(msg1 + "\n")
        logf.write(msg2 + "\n")
        logf.write(msg3 + "\n")
        logf.flush()

        if not skip_clean:
            clean_ok = clean_project(env)
            if not clean_ok:
                with open(csv_path, "a", encoding="utf-8", newline="") as f:
                    w = csv.writer(f)
                    w.writerow([name, run_id, llvm_pass_label, mir_pass_label, 0, 0, 0, "CleanFailed", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""])
                continue

        build_start_ts = time.time()
        ok, compile_time = build_project(env, logf)
        exe_path = get_exe_path()
        if (not ok) or (not exe_path):
            with open(csv_path, "a", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow([name, run_id, llvm_pass_label, mir_pass_label, 0, 0, f"{compile_time:.6f}", "BuildFailed", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""])
            continue

        size_bytes = os.path.getsize(exe_path)

        mir_ev = None
        llvm_ev = None
        asm_ev = None
        llvm_file = ""
        asm_file = ""
        if evidence:
            mir_ev = collect_mir_evidence(mir_dump_dir)
            recent = collect_recent_save_temps_files(build_start_ts - 1.0)
            ll_candidates = [p for p in recent if p.endswith(".ll")]
            s_candidates = [p for p in recent if p.endswith(".s")]
            ll_fp = ll_candidates[-1] if ll_candidates else ""
            s_fp = s_candidates[-1] if s_candidates else ""
            llvm_file = os.path.basename(ll_fp) if ll_fp else ""
            asm_file = os.path.basename(s_fp) if s_fp else ""

            if ll_fp:
                try:
                    with open(ll_fp, "r", encoding="utf-8", errors="replace") as f:
                        ll_text = f.read()
                    llvm_ev = parse_llvm_counts(ll_text, "workload_a" if variant.lower() == "a" else "workload_b")
                except OSError:
                    llvm_ev = None
            if s_fp:
                try:
                    with open(s_fp, "r", encoding="utf-8", errors="replace") as f:
                        s_text = f.read()
                    asm_ev = parse_asm_counts(s_text, "workload_a" if variant.lower() == "a" else "workload_b")
                except OSError:
                    asm_ev = None

            if mir_ev and (not keep_ir):
                keep = {mir_ev.get("mir_first_path"), mir_ev.get("mir_last_path")}
                for dirpath, _, filenames in os.walk(mir_dump_dir):
                    for fn in filenames:
                        fp = os.path.join(dirpath, fn)
                        if fp in keep:
                            continue
                        try:
                            os.remove(fp)
                        except OSError:
                            pass

            if not keep_ir:
                for fp in [ll_fp, s_fp]:
                    if fp and os.path.isfile(fp):
                        try:
                            os.remove(fp)
                        except OSError:
                            pass
                llvm_file = ""
                asm_file = ""

        runtime_total = run_benchmark(exe_path, run_repeats, warmup, run_args)
        if runtime_total is None:
            with open(csv_path, "a", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                w.writerow([name, run_id, llvm_pass_label, mir_pass_label, size_bytes, 0, f"{compile_time:.6f}", "RunFailed", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""])
            continue

        mir_first_file = mir_ev["mir_first_file"] if mir_ev else ""
        mir_last_file = mir_ev["mir_last_file"] if mir_ev else ""
        mir_bb_first = mir_ev["mir_bb_first"] if mir_ev else ""
        mir_bb_last = mir_ev["mir_bb_last"] if mir_ev else ""
        mir_goto_first = mir_ev["mir_goto_first"] if mir_ev else ""
        mir_goto_last = mir_ev["mir_goto_last"] if mir_ev else ""
        mir_switch_first = mir_ev["mir_switch_first"] if mir_ev else ""
        mir_switch_last = mir_ev["mir_switch_last"] if mir_ev else ""
        mir_term_blocks_first = mir_ev["mir_term_blocks_first"] if mir_ev else ""
        mir_term_blocks_last = mir_ev["mir_term_blocks_last"] if mir_ev else ""

        llvm_bb = llvm_ev["llvm_bb"] if llvm_ev else ""
        llvm_br = llvm_ev["llvm_br"] if llvm_ev else ""
        llvm_switch = llvm_ev["llvm_switch"] if llvm_ev else ""

        asm_jmp = asm_ev["asm_jmp"] if asm_ev else ""

        with open(csv_path, "a", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(
                [
                    name,
                    run_id,
                    llvm_pass_label,
                    mir_pass_label,
                    size_bytes,
                    f"{runtime_total:.6f}",
                    f"{compile_time:.6f}",
                    "Success",
                    mir_first_file,
                    mir_last_file,
                    mir_bb_first,
                    mir_bb_last,
                    mir_term_blocks_first,
                    mir_term_blocks_last,
                    mir_goto_first,
                    mir_goto_last,
                    mir_switch_first,
                    mir_switch_last,
                    llvm_file,
                    llvm_bb,
                    llvm_br,
                    llvm_switch,
                    asm_file,
                    asm_jmp,
                ]
            )

        msg4 = f"[Result] Size={size_bytes}B, Compile={compile_time:.6f}s, RunTotal={runtime_total:.6f}s"
        print(msg4)
        logf.write(msg4 + "\n")
        logf.flush()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-path", default=DEFAULT_JSON_PATH)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--skip-clean", action="store_true")
    parser.add_argument("--variant", default="b")
    parser.add_argument("--n", type=int, default=5_000_000)
    parser.add_argument("--iters", type=int, default=100)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--run-repeats", type=int, default=1)
    parser.add_argument("--warmup", type=int, default=0)
    parser.add_argument("--no-evidence", action="store_true")
    parser.add_argument("--keep-ir", action="store_true")
    args = parser.parse_args()

    combos = get_combinations(args.json_path)
    if args.start > 0:
        combos = combos[args.start:]
    if args.limit and args.limit > 0:
        combos = combos[: args.limit]

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_out = args.output_dir or os.path.join(PROJECT_ROOT, "mir_llvm_hybrid_py", ts)
    os.makedirs(base_out, exist_ok=True)
    results_csv = os.path.join(base_out, "experiment_results.csv")
    exec_log = os.path.join(base_out, "experiment_execution.log")

    if not os.path.exists(results_csv):
        with open(results_csv, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(
                [
                    "ConfigName",
                    "RunID",
                    "LLVM_Pass",
                    "MIR_Pass",
                    "BinarySize(Bytes)",
                    "TotalRuntime(s)",
                    "CompileTime(s)",
                    "Status",
                    "MIR_First_File",
                    "MIR_Last_File",
                    "MIR_BB_First",
                    "MIR_BB_Last",
                    "MIR_TermBlocks_First",
                    "MIR_TermBlocks_Last",
                    "MIR_Goto_First",
                    "MIR_Goto_Last",
                    "MIR_SwitchInt_First",
                    "MIR_SwitchInt_Last",
                    "LLVM_LL_File",
                    "LLVM_BB",
                    "LLVM_br",
                    "LLVM_switch",
                    "ASM_S_File",
                    "ASM_JmpLike",
                ]
            )

    with open(exec_log, "w", encoding="utf-8") as logf:
        logf.write(f"Total Rows: {len(combos)}\n")
        logf.flush()
        print(f"Total Rows: {len(combos)}")
        for combo in combos:
            measure_combination(
                combo=combo,
                runs=args.runs,
                skip_clean=args.skip_clean,
                run_repeats=args.run_repeats,
                warmup=args.warmup,
                variant=args.variant,
                n=args.n,
                iters=args.iters,
                seed=args.seed,
                csv_path=results_csv,
                logf=logf,
                evidence=(not args.no_evidence),
                keep_ir=args.keep_ir,
                base_out=base_out,
            )


if __name__ == "__main__":
    main()
