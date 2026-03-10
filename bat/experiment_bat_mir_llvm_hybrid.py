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
    bench_path = os.path.join(project_root, "benchmark_data.rs")
    desired_bytes = 10 * 1024 * 1024 # 10MB
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
    
    # Use some Rust code to trigger syntax highlighting
    chunk = ("pub fn example() {\n"
             "    let x = 42;\n"
             "    println!(\"Hello, world! {}\", x);\n"
             "    // This is a comment to test highlighting\n"
             "    if x > 10 {\n"
             "        vec![1, 2, 3].iter().map(|i| i * 2).collect::<Vec<_>>();\n"
             "    }\n"
             "}\n") * 100
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
        # bat uses workspace, so we build the 'bat' binary specifically or just 'cargo build --release' if it's the main member
        # Assuming standard cargo build works
        r = subprocess.run(["cargo", "+nightly", "build", "--release", "--quiet"], cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
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
    # bat binary location
    exe = os.path.join(cwd, "target", "release", "bat")
    return exe if os.path.exists(exe) else None

def run_benchmark(exe_path, bench_file, repeats):
    total = 0.0
    for _ in range(repeats):
        t0 = time.perf_counter()
        # bat specific flags: force color and style, disable paging (dump to stdout)
        # Redirect stdout to /dev/null to measure processing time only
        p = subprocess.run([exe_path, "--style=full", "--color=always", "--paging=never", bench_file], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        t1 = time.perf_counter()
        if p.returncode != 0:
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
    cargo_bin = os.path.expanduser("~/.cargo/bin")
    if cargo_bin and cargo_bin not in env.get("PATH", ""):
        env["PATH"] = f"{cargo_bin}:{env.get('PATH', '')}"
        
    rustflags = compose_rustflags_from_combo(combo)
    env["RUSTFLAGS"] = rustflags
    
    compile_total = 0.0
    
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
        compile_total += (t1 - t0)
        
        if not ok:
            if status == "Skipped":
                print(f"[Skip] Build skipped due to environment contention")
            return {"ConfigName": name, "RunID": i, "LLVM_Pass": llvm_pass_label, "MIR_Pass": mir_pass_label, "BinarySize(Bytes)": 0, "TotalRuntime(s)": 0, "CompileTime(s)": 0, "Status": status}
    
    exe_path = get_exe_path(cwd)
    if not exe_path:
        return {"ConfigName": name, "RunID": runs, "LLVM_Pass": llvm_pass_label, "MIR_Pass": mir_pass_label, "BinarySize(Bytes)": 0, "TotalRuntime(s)": 0, "CompileTime(s)": 0, "Status": "NoBinary"}
        
    try:
        size = os.path.getsize(exe_path)
    except Exception:
        size = 0
        
    avg_search = run_benchmark(exe_path, bench_file, runs)
    compile_avg = compile_total / max(runs, 1)
    
    if avg_search is None:
        print(f"[Run] Failed for {name}")
        return {"ConfigName": name, "RunID": runs, "LLVM_Pass": llvm_pass_label, "MIR_Pass": mir_pass_label, "BinarySize(Bytes)": size, "TotalRuntime(s)": 0, "CompileTime(s)": f"{compile_avg:.6f}", "Status": "RunFailed"}
        
    print(f"[Result] Size={size}B, CompileAvg={compile_avg:.6f}s, RunAvg={avg_search:.6f}s")
    return {"ConfigName": name, "RunID": runs, "LLVM_Pass": llvm_pass_label, "MIR_Pass": mir_pass_label, "BinarySize(Bytes)": size, "TotalRuntime(s)": f"{avg_search:.6f}", "CompileTime(s)": f"{compile_avg:.6f}", "Status": "Success"}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-path", default="/mnt/fjx/Compiler_Experiment/table/table_json/combined_experiment_matrix.json")
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--output-dir", default="")
    args = parser.parse_args()
    
    project_root = "/mnt/fjx/Compiler_Experiment/bat"
    
    # Ensure project root exists
    if not os.path.exists(project_root):
        print(f"Error: Project root {project_root} does not exist.")
        return

    bench_file = ensure_bench_file(project_root)
    
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_out = args.output_dir or os.path.join(project_root, "mir_llvm_hybrid_py", ts)
    os.makedirs(base_out, exist_ok=True)
    
    results_csv = os.path.join(base_out, "experiment_results.csv")
    exec_log = os.path.join(base_out, "experiment_execution.log")
    
    combos = get_combinations(args.json_path)
    
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
                res = measure_combination(combo, args.runs, project_root, bench_file, logf)
                writer.writerow(res)
                outcsv.flush()

if __name__ == "__main__":
    main()
