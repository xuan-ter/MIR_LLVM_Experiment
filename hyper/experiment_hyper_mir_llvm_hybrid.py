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


def get_combinations(json_path):
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("combinations", [])


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


def build_bench(env, bench_name, logf, retries=2):
    backoff = 0.5
    last_err = ""
    cmd = [
        "cargo",
        "+nightly",
        "bench",
        "--bench",
        bench_name,
        "--features",
        "full",
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
            return True, "Success"
        err = r.stderr or ""
        last_err = err
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


def resolve_bench_filter(exe_path, requested_filter):
    p = subprocess.run([exe_path, "--list"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if p.returncode != 0:
        return requested_filter

    names = []
    for line in (p.stdout or "").splitlines():
        if ":" not in line:
            continue
        name, kind = line.split(":", 1)
        kind = kind.strip()
        if kind.startswith("bench") or kind.startswith("benchmark"):
            names.append(name.strip())

    if not names:
        return requested_filter
    if requested_filter in names:
        return requested_filter
    return names[0]


def run_benchmark(exe_path, bench_filter, repeat):
    total_wall = 0.0
    last_err = ""
    last_out = ""
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


def measure_combination(combo, runs, bench_name, bench_filter, bench_repeat, logf):
    name = combo.get("name") or combo.get("Experiment_ID") or "Unknown"

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

    results = []
    resolved_bench_filter = None
    total_iters = runs + 1
    for n in range(total_iters):
        is_warmup = (n == 0)
        run_id = n

        msg1 = f"[Exp] {name} Warmup 1/1" if is_warmup else f"[Exp] {name} Iteration {run_id}/{runs}"
        msg2 = f"[Flags] {rustflags}"
        msg3 = f"[Bench] {bench_name}::{bench_filter} x{bench_repeat}"
        print(msg1)
        print(msg2)
        print(msg3)
        logf.write(msg1 + "\n")
        logf.write(msg2 + "\n")
        logf.write(msg3 + "\n")
        logf.flush()

        clean_project(env)

        t0 = time.perf_counter()
        ok, status = build_bench(env, bench_name, logf)
        t1 = time.perf_counter()
        compile_time = t1 - t0

        if not ok:
            if is_warmup:
                logf.write(f"[SkipConfig] Warmup build failed: {status}\n")
                logf.flush()
                break

            results.append(
                {
                    "ConfigName": name,
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
                logf.write("[SkipConfig] Warmup produced no binary\n")
                logf.flush()
                break

            results.append(
                {
                    "ConfigName": name,
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

        if resolved_bench_filter is None:
            resolved_bench_filter = resolve_bench_filter(exe_path, bench_filter)
            if resolved_bench_filter != bench_filter:
                msg = f"[BenchFilterResolved] {bench_filter} -> {resolved_bench_filter}"
                print(msg)
                logf.write(msg + "\n")
                logf.flush()

        wall_time, ns_per_iter, mbps, run_err = run_benchmark(exe_path, resolved_bench_filter, bench_repeat)
        if wall_time is None:
            if run_err:
                logf.write("[RunError] " + run_err + "\n")
                logf.flush()
            if is_warmup:
                logf.write("[SkipConfig] Warmup run failed\n")
                logf.flush()
                break

            results.append(
                {
                    "ConfigName": name,
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
            break

        if is_warmup:
            print(f"[WarmupResult] Size={size}B, Compile={compile_time:.6f}s, Wall={wall_time:.6f}s, NsPerIter={ns_per_iter}, MBps={mbps}")
            continue

        print(f"[Result] Size={size}B, Compile={compile_time:.6f}s, Wall={wall_time:.6f}s, NsPerIter={ns_per_iter}, MBps={mbps}")
        results.append(
            {
                "ConfigName": name,
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

    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-path", default=DEFAULT_JSON_PATH)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--bench-name", default="end_to_end")
    parser.add_argument("--bench-filter", default="http1_consecutive_x1_both_10mb")
    parser.add_argument("--bench-repeat", type=int, default=1)
    args = parser.parse_args()

    if not os.path.exists(args.json_path):
        print(f"Error: JSON path {args.json_path} does not exist.")
        return

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
                results = measure_combination(
                    combo,
                    args.runs,
                    args.bench_name,
                    args.bench_filter,
                    args.bench_repeat,
                    logf,
                )
                for row in results:
                    writer.writerow(row)
                outcsv.flush()


if __name__ == "__main__":
    main()
