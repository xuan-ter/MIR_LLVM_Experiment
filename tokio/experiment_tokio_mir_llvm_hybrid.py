import argparse
import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime
from glob import glob


PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
WORKSPACE_ROOT = os.path.abspath(os.path.join(PROJECT_ROOT, os.pardir))
DEFAULT_JSON_PATH = os.path.join(WORKSPACE_ROOT, "table", "table_json", "combined_experiment_matrix.json")
DEFAULT_TOOLCHAIN = "nightly"


def get_combinations(json_path):
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("combinations", [])


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


def run_capture(cmd, env, logf, log_streams):
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
    if log_streams or p.returncode != 0:
        if p.stdout:
            out = p.stdout
            if not log_streams:
                out = out[-4000:]
            logf.write(f"[STDOUT] {out}\n")
        if p.stderr:
            err = p.stderr
            if not log_streams:
                err = err[-4000:]
            logf.write(f"[STDERR] {err}\n")
    logf.flush()
    return p


def build_bench(env, bench_name, logf, log_cargo_output, retries=3):
    cmd = f"cargo bench -p benches --bench {bench_name} --no-run"
    last_err = ""
    backoff = 0.5
    for _ in range(max(retries, 1)):
        t0 = time.perf_counter()
        p = run_capture(cmd, env, logf, log_cargo_output)
        t1 = time.perf_counter()
        if p.returncode == 0:
            exe = extract_bench_exe_path(p.stdout + "\n" + p.stderr, bench_name)
            return True, (t1 - t0), exe

        last_err = (p.stderr or "") + "\n" + (p.stdout or "")
        if "Text file busy (os error 26)" in last_err:
            time.sleep(backoff)
            backoff = min(backoff * 2, 4.0)
            continue
        break

    if "Text file busy (os error 26)" in last_err:
        return False, 0.0, "Skipped"
    return False, 0.0, "BuildFailed"


def extract_bench_exe_path(build_output, bench_name):
    m = re.findall(r"Executable\s+.+?\s+\((target[\\/].+?)\)", build_output)
    if m:
        rel = m[-1].strip().replace("/", os.sep).replace("\\", os.sep)
        return os.path.join(PROJECT_ROOT, rel)

    candidates = []
    for path in glob(os.path.join(PROJECT_ROOT, "target", "release", "deps", f"{bench_name}-*")):
        if path.endswith(".d"):
            continue
        if os.path.isfile(path) and os.access(path, os.X_OK):
            candidates.append(path)

    if candidates:
        candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        return candidates[0]
    return None


def run_benchmark(exe_path, repeats, warmup, bench_args):
    args = [exe_path] + bench_args

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


def measure_combination(combo, runs, skip_clean, bench_name, run_repeats, warmup, bench_args, csv_path, logf, toolchain, log_cargo_output):
    name = combo.get("name") or combo.get("Experiment_ID") or "Unknown"
    llvm_pass_label, mir_pass_label = labels_from_combo(combo)

    if already_done(csv_path, name, runs):
        msg = f"[Skip] {name} (Already done)"
        print(msg)
        logf.write(msg + "\n")
        logf.flush()
        return

    env = os.environ.copy()
    cargo_bin = os.path.join(os.path.expanduser("~"), ".cargo", "bin")
    if os.path.isdir(cargo_bin):
        current_path = env.get("PATH", "")
        parts = current_path.split(os.pathsep) if current_path else []
        if cargo_bin not in parts:
            env["PATH"] = cargo_bin + (os.pathsep + current_path if current_path else "")

    if toolchain:
        env.setdefault("RUSTUP_TOOLCHAIN", toolchain)

    rustflags = compose_rustflags_from_combo(combo)
    env["RUSTFLAGS"] = rustflags

    for run_id in range(1, runs + 1):
        msg1 = f"[Exp] {name} Iteration {run_id}/{runs}"
        msg2 = f"[Flags] {rustflags}"
        msg3 = f"[Bench] {bench_name} repeats={run_repeats}, warmup={warmup}"
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
                with open(csv_path, "a", encoding="utf-8") as f:
                    f.write(f"{name},{run_id},{llvm_pass_label},{mir_pass_label},0,0,0,CleanFailed\n")
                continue

        ok, compile_time, exe_path = build_bench(env, bench_name, logf, log_cargo_output)
        if not ok:
            with open(csv_path, "a", encoding="utf-8") as f:
                f.write(f"{name},{run_id},{llvm_pass_label},{mir_pass_label},0,0,{compile_time:.6f},{exe_path}\n")
            continue

        if not exe_path or not os.path.exists(exe_path):
            with open(csv_path, "a", encoding="utf-8") as f:
                f.write(f"{name},{run_id},{llvm_pass_label},{mir_pass_label},0,0,{compile_time:.6f},BuildFailed\n")
            continue

        size_bytes = os.path.getsize(exe_path)
        runtime_total = run_benchmark(exe_path, run_repeats, warmup, bench_args)
        if runtime_total is None:
            with open(csv_path, "a", encoding="utf-8") as f:
                f.write(f"{name},{run_id},{llvm_pass_label},{mir_pass_label},{size_bytes},0,{compile_time:.6f},RunFailed\n")
            continue

        with open(csv_path, "a", encoding="utf-8") as f:
            f.write(f"{name},{run_id},{llvm_pass_label},{mir_pass_label},{size_bytes},{runtime_total:.6f},{compile_time:.6f},Success\n")

        msg4 = f"[Result] Size={size_bytes}B, Compile={compile_time:.6f}s, RunTotal={runtime_total:.6f}s"
        print(msg4)
        logf.write(msg4 + "\n")
        logf.flush()


def parse_bench_args(raw):
    if not raw.strip():
        return ["--bench"]
    return raw.strip().split()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-path", default=DEFAULT_JSON_PATH)
    parser.add_argument("--toolchain", default=DEFAULT_TOOLCHAIN)
    parser.add_argument("--log-cargo-output", action="store_true")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--start-name", default="")
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--skip-clean", action="store_true")
    parser.add_argument("--bench-name", default="spawn")
    parser.add_argument("--bench-args", default="--bench --warm-up-time 1 --measurement-time 1 --sample-size 30 --noplot")
    parser.add_argument("--run-repeats", type=int, default=1)
    parser.add_argument("--warmup", type=int, default=0)
    args = parser.parse_args()

    combos = get_combinations(args.json_path)
    start_name = args.start_name.strip()
    if start_name:
        start_idx = None
        for i, combo in enumerate(combos):
            name = combo.get("name") or combo.get("Experiment_ID") or ""
            if name == start_name:
                start_idx = i
                break
        if start_idx is None:
            print(f"[Warn] start-name not found: {start_name}")
        else:
            combos = combos[start_idx:]
    elif args.start > 0:
        combos = combos[args.start:]
    if args.limit and args.limit > 0:
        combos = combos[: args.limit]

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_out = args.output_dir or os.path.join(PROJECT_ROOT, "mir_llvm_hybrid_py", ts)
    os.makedirs(base_out, exist_ok=True)
    results_csv = os.path.join(base_out, "experiment_results.csv")
    exec_log = os.path.join(base_out, "experiment_execution.log")

    if not os.path.exists(results_csv):
        with open(results_csv, "w", encoding="utf-8") as f:
            f.write("ConfigName,RunID,LLVM_Pass,MIR_Pass,BinarySize(Bytes),TotalRuntime(s),CompileTime(s),Status\n")

    bench_args = parse_bench_args(args.bench_args)

    with open(exec_log, "w", encoding="utf-8") as logf:
        logf.write(f"Total Rows: {len(combos)}\n")
        logf.flush()
        print(f"Total Rows: {len(combos)}")
        for combo in combos:
            measure_combination(
                combo=combo,
                runs=args.runs,
                skip_clean=args.skip_clean,
                bench_name=args.bench_name,
                run_repeats=args.run_repeats,
                warmup=args.warmup,
                bench_args=bench_args,
                csv_path=results_csv,
                logf=logf,
                toolchain=args.toolchain,
                log_cargo_output=args.log_cargo_output,
            )


if __name__ == "__main__":
    main()
