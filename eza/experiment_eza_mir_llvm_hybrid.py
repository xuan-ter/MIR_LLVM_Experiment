import argparse
import csv
import json
import os
import shutil
import subprocess
import time
from datetime import datetime


PROJECT_ROOT = "/mnt/fjx/Compiler_Experiment/eza"
DEFAULT_JSON_PATH = "/mnt/fjx/Compiler_Experiment/table/table_json/combined_experiment_matrix.json"


def get_combinations(json_path):
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("combinations", [])


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


def labels_from_combo(combo):
    mir_pass_label = "N/A"
    llvm_pass_label = "None"
    if combo.get("mir"):
        if isinstance(combo["mir"], dict):
            mir_pass_label = combo["mir"].get("pass", "N/A")
        else:
            mir_pass_label = str(combo["mir"])
    if combo.get("llvm"):
        if isinstance(combo["llvm"], dict):
            llvm_pass_label = combo["llvm"].get("pass", "None")
        else:
            llvm_pass_label = str(combo["llvm"])
    return llvm_pass_label, mir_pass_label


def clean_project(env=None):
    target_dir = os.path.join(PROJECT_ROOT, "target")
    if os.path.exists(target_dir):
        try:
            shutil.rmtree(target_dir)
            return
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


def build_project(env, logf, retries=2):
    backoff = 0.5
    last_err = ""
    cmd = ["cargo", "+nightly", "build", "--release", "--quiet"]
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
            return True, "Success"
        err = r.stderr or ""
        last_err = err
        if err.strip():
            logf.write(err + "\n")
            logf.flush()
        if ("Text file busy (os error 26)" in err) or ("never executed" in err):
            time.sleep(backoff)
            backoff = min(backoff * 2, 4.0)
            continue
        return False, "BuildFailed"

    if ("Text file busy (os error 26)" in last_err) or ("never executed" in last_err) or ("failed to run custom build command" in last_err):
        return False, "Skipped"
    return False, "BuildFailed"


def get_exe_path():
    exe_path = os.path.join(PROJECT_ROOT, "target", "release", "eza")
    return exe_path if os.path.exists(exe_path) else None


def run_benchmark(exe_path, list_path, repeats, warmup, extra_args):
    args = [
        exe_path,
        "--color=never",
        "--icons=never",
        "--no-git",
        "-R",
        "--level=4",
        "-l",
        list_path,
    ]
    if extra_args:
        args = [exe_path] + extra_args + [list_path]

    for _ in range(max(warmup, 0)):
        p = subprocess.run(args, cwd=PROJECT_ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if p.returncode != 0:
            return None

    total = 0.0
    for _ in range(repeats):
        t0 = time.perf_counter()
        p = subprocess.run(args, cwd=PROJECT_ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        t1 = time.perf_counter()
        if p.returncode != 0:
            return None
        total += (t1 - t0)
    return total


def measure_combination(combo, runs, skip_clean, list_path, run_repeats, warmup, extra_args, logf):
    name = combo.get("name") or combo.get("Experiment_ID") or "Unknown"
    llvm_pass_label, mir_pass_label = labels_from_combo(combo)

    env = os.environ.copy()
    cargo_bin = os.path.expanduser("~/.cargo/bin")
    if cargo_bin and cargo_bin not in env.get("PATH", ""):
        env["PATH"] = f"{cargo_bin}:{env.get('PATH', '')}"

    rustflags = compose_rustflags_from_combo(combo)
    env["RUSTFLAGS"] = rustflags

    results = []
    for run_id in range(1, runs + 1):
        msg1 = f"[Exp] {name} Iteration {run_id}/{runs}"
        msg2 = f"[Flags] {rustflags}"
        msg3 = f"[Run] repeats={run_repeats}, warmup={warmup}, path={list_path}"
        print(msg1)
        print(msg2)
        print(msg3)
        logf.write(msg1 + "\n")
        logf.write(msg2 + "\n")
        logf.write(msg3 + "\n")
        logf.flush()

        if not skip_clean:
            clean_project(env)

        t0 = time.perf_counter()
        ok, status = build_project(env, logf)
        t1 = time.perf_counter()
        compile_time = t1 - t0

        if not ok:
            results.append(
                {
                    "ConfigName": name,
                    "RunID": run_id,
                    "LLVM_Pass": llvm_pass_label,
                    "MIR_Pass": mir_pass_label,
                    "BinarySize(Bytes)": 0,
                    "TotalRuntime(s)": 0,
                    "CompileTime(s)": f"{compile_time:.6f}",
                    "Status": status,
                }
            )
            break

        exe_path = get_exe_path()
        if not exe_path:
            results.append(
                {
                    "ConfigName": name,
                    "RunID": run_id,
                    "LLVM_Pass": llvm_pass_label,
                    "MIR_Pass": mir_pass_label,
                    "BinarySize(Bytes)": 0,
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

        avg_runtime = run_benchmark(exe_path, list_path, run_repeats, warmup, extra_args)
        if avg_runtime is None:
            results.append(
                {
                    "ConfigName": name,
                    "RunID": run_id,
                    "LLVM_Pass": llvm_pass_label,
                    "MIR_Pass": mir_pass_label,
                    "BinarySize(Bytes)": size,
                    "TotalRuntime(s)": 0,
                    "CompileTime(s)": f"{compile_time:.6f}",
                    "Status": "RunFailed",
                }
            )
            break

        print(f"[Result] Size={size}B, Compile={compile_time:.6f}s, RunAvg={avg_runtime:.6f}s")
        results.append(
            {
                "ConfigName": name,
                "RunID": run_id,
                "LLVM_Pass": llvm_pass_label,
                "MIR_Pass": mir_pass_label,
                "BinarySize(Bytes)": size,
                "TotalRuntime(s)": f"{avg_runtime:.6f}",
                "CompileTime(s)": f"{compile_time:.6f}",
                "Status": "Success",
            }
        )

    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-path", default=DEFAULT_JSON_PATH)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--skip-clean", action="store_true")
    parser.add_argument("--list-path", default="/mnt/fjx/Compiler_Experiment/bat")
    parser.add_argument("--run-repeats", type=int, default=100)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--eza-args", default="")
    args = parser.parse_args()

    extra_args = []
    if args.eza_args.strip():
        extra_args = args.eza_args.strip().split()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_out = args.output_dir or os.path.join(PROJECT_ROOT, "mir_llvm_hybrid_py", ts)
    os.makedirs(base_out, exist_ok=True)

    results_csv = os.path.join(base_out, "experiment_results.csv")
    exec_log = os.path.join(base_out, "experiment_execution.log")

    combos = get_combinations(args.json_path)
    if args.start > 0:
        combos = combos[args.start:]
    if args.limit and args.limit > 0:
        combos = combos[: args.limit]

    with open(exec_log, "w", encoding="utf-8") as logf:
        print(f"Total Rows: {len(combos)}")
        logf.write(f"Total Rows: {len(combos)}\n")
        logf.flush()

        with open(results_csv, "w", encoding="utf-8", newline="") as outcsv:
            writer = csv.DictWriter(
                outcsv,
                fieldnames=[
                    "ConfigName",
                    "RunID",
                    "LLVM_Pass",
                    "MIR_Pass",
                    "BinarySize(Bytes)",
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
                    args.skip_clean,
                    args.list_path,
                    args.run_repeats,
                    args.warmup,
                    extra_args,
                    logf,
                )
                for row in rows:
                    writer.writerow(row)
                outcsv.flush()


if __name__ == "__main__":
    main()
