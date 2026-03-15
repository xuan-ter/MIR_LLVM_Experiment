import os
import csv
import sys
import json
import time
import argparse
import shutil
import subprocess
from datetime import datetime

def ensure_bench_file(project_root):
    bench_path = os.path.join(project_root, "benchmark_data.txt")
    desired_bytes = 500 * 1024 * 1024 # 500MB for regex
    if os.path.exists(bench_path):
        try:
            size = os.path.getsize(bench_path)
        except Exception:
            size = 0
        if size >= desired_bytes and size < desired_bytes * 1.5:
            return bench_path
        else:
             # Remove if size mismatch to force regeneration
             try:
                 os.remove(bench_path)
             except:
                 pass
    
    # Use text with patterns to trigger regex matching
    # Pattern to search later: "Sherlock", "email@example.com", dates like "2023-10-27"
    chunk = ("Sherlock Holmes took his bottle from the corner of the mantelpiece, "
             "and his hypodermic syringe from its neat morocco case. "
             "Contact us at support@example.com or visit 192.168.1.1 on 2023-10-27.\n") * 500
    chunk_bytes = len(chunk.encode("utf-8"))
    chunks_needed = (desired_bytes // chunk_bytes) + 1
    
    print(f"Generating benchmark file at {bench_path} (~{desired_bytes/1024/1024:.0f}MB)...")
    with open(bench_path, "w", encoding="utf-8") as f:
        for _ in range(chunks_needed):
            f.write(chunk)
    return bench_path

def get_combinations(json_path):
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("combinations", [])

def find_start_index_by_name(combos, start_name):
    if not start_name:
        return None
    if start_name.upper() in {"BEGIN", "START", "ALL"}:
        return None
    for i, combo in enumerate(combos):
        name = combo.get("name") or combo.get("Experiment_ID")
        if name == start_name:
            return i
    return None

def clean_project(cwd, env):
    target_dir = os.path.join(cwd, "target")
    if os.path.exists(target_dir):
        try:
            shutil.rmtree(target_dir)
        except Exception:
            subprocess.run(["cargo", "clean"], cwd=cwd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        subprocess.run(["cargo", "clean"], cwd=cwd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.25)

def build_project(cwd, env, logf, retries=2):
    backoff = 0.5
    last_err = ""
    for attempt in range(retries + 1):
        # Build the regex-cli binary from the workspace
        # We target regex-cli specifically since 'regex' is a library workspace
        r = subprocess.run(["cargo", "+nightly", "build", "--release", "--package", "regex-cli", "--bin", "regex-cli", "--quiet"], cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
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
    
    # If we exhausted retries on busy error, return Skipped
    if ("Text file busy (os error 26)" in last_err) or ("never executed" in last_err) or ("failed to run custom build command" in last_err):
        return False, "Skipped"
    return False, "BuildFailed"

def get_exe_path(cwd):
    # regex-cli binary location
    exe = os.path.join(cwd, "target", "release", "regex-cli")
    return exe if os.path.exists(exe) else None

def run_benchmark(exe_path, bench_file, repeats):
    total = 0.0
    for _ in range(repeats):
        t0 = time.perf_counter()
        # regex-cli usage: regex-cli find match regex <pattern> <file>
        # Searching for "Sherlock" which appears frequently
        # Redirect stdout to /dev/null to measure processing time only
        # We use 'find match regex' to use the standard regex engine
        # Added --no-utf8-syntax (-b) because regex-cli complains about UTF-8 syntax mode
        p = subprocess.run([exe_path, "find", "match", "regex", "--no-utf8-syntax", "-p", "Sherlock", bench_file], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        t1 = time.perf_counter()
        if p.returncode != 0:
            print(f"[RunError] {p.stderr}")
            # Try alternative command if "find" isn't supported or fails
            return None
        total += (t1 - t0)
    return total / repeats

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

def measure_combination(combo, runs, cwd, bench_file, logf):
    name = combo.get("name") or combo.get("Experiment_ID") or "Unknown"
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
            
    env = os.environ.copy()
    
    # Ensure cargo is in PATH
    cargo_bin = os.path.expanduser("~/.cargo/bin")
    if cargo_bin and cargo_bin not in env.get("PATH", ""):
        env["PATH"] = f"{cargo_bin}:{env.get('PATH', '')}"
        
    rustflags = compose_rustflags_from_combo(combo)
    env["RUSTFLAGS"] = rustflags
    
    results = []
    
    for i in range(1, runs + 1):
        clean_project(cwd, env)
        
        msg1 = f"[Exp] {name} Iteration {i}/{runs}"
        msg2 = f"[Flags] {rustflags}"
        print(msg1)
        print(msg2)
        logf.write(msg1 + "\n")
        logf.write(msg2 + "\n")
        logf.flush()
        
        t0 = time.perf_counter()
        ok, status = build_project(cwd, env, logf)
        t1 = time.perf_counter()
        compile_time = (t1 - t0)
        
        if not ok:
            if status == "Skipped":
                print(f"[Skip] Build skipped due to environment contention")
            results.append({"ConfigName": name, "RunID": i, "LLVM_Pass": llvm_pass_label, "MIR_Pass": mir_pass_label, "BinarySize(Bytes)": 0, "TotalRuntime(s)": 0, "CompileTime(s)": 0, "Status": status})
            continue

        exe_path = get_exe_path(cwd)
        if not exe_path:
            results.append({"ConfigName": name, "RunID": i, "LLVM_Pass": llvm_pass_label, "MIR_Pass": mir_pass_label, "BinarySize(Bytes)": 0, "TotalRuntime(s)": 0, "CompileTime(s)": 0, "Status": "NoBinary"})
            continue

        try:
            size = os.path.getsize(exe_path)
        except Exception:
            size = 0
            
        runtime = run_benchmark(exe_path, bench_file, 1) # Run once per iteration since we loop runs times
        
        if runtime is None:
            print(f"[Run] Failed for {name}")
            results.append({"ConfigName": name, "RunID": i, "LLVM_Pass": llvm_pass_label, "MIR_Pass": mir_pass_label, "BinarySize(Bytes)": size, "TotalRuntime(s)": 0, "CompileTime(s)": f"{compile_time:.6f}", "Status": "RunFailed"})
            continue

        print(f"[Result] Size={size}B, Compile={compile_time:.6f}s, Run={runtime:.6f}s")
        results.append({"ConfigName": name, "RunID": i, "LLVM_Pass": llvm_pass_label, "MIR_Pass": mir_pass_label, "BinarySize(Bytes)": size, "TotalRuntime(s)": f"{runtime:.6f}", "CompileTime(s)": f"{compile_time:.6f}", "Status": "Success"})
    
    return results

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.abspath(os.path.join(script_dir, ".."))
    default_json_path = os.path.join(repo_root, "table", "table_json", "combined_experiment_matrix.json")

    parser = argparse.ArgumentParser()
    parser.add_argument("--json-path", default=default_json_path)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--start-name", default="EXP_DBL_0540")
    parser.add_argument("--output-dir", default="")
    
    args = parser.parse_args()
    
    project_root = script_dir
    bench_file = ensure_bench_file(project_root)
    
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_out = args.output_dir or os.path.join(project_root, "mir_llvm_hybrid_py", ts)
    os.makedirs(base_out, exist_ok=True)
    
    results_csv = os.path.join(base_out, "experiment_results.csv")
    exec_log = os.path.join(base_out, "experiment_execution.log")
    
    combos = get_combinations(args.json_path)

    start_idx = find_start_index_by_name(combos, args.start_name)
    if start_idx is not None:
        combos = combos[start_idx:]
    
    if args.start > 0:
        combos = combos[args.start:]
        
    if args.limit and args.limit > 0:
        combos = combos[:args.limit]
        
    with open(exec_log, "w", encoding="utf-8") as logf:
        print(f"Total Rows: {len(combos)}")
        logf.write(f"Total Rows: {len(combos)}\n")
        logf.flush()
        
        with open(results_csv, "w", encoding="utf-8", newline="") as outcsv:
            writer = csv.DictWriter(outcsv, fieldnames=["ConfigName","RunID","LLVM_Pass","MIR_Pass","BinarySize(Bytes)","TotalRuntime(s)","CompileTime(s)","Status"])
            writer.writeheader()
            outcsv.flush()
            
            for combo in combos:
                results = measure_combination(combo, args.runs, project_root, bench_file, logf)
                for res in results:
                    writer.writerow(res)
                outcsv.flush()

if __name__ == "__main__":
    main()
