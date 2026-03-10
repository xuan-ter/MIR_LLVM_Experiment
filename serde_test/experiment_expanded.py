"""
功能：LLVM Pass 随机/遍历实验脚本
描述：
    专注于 LLVM 层的 Pass 组合实验。
    用于在固定 MIR 配置下分析 LLVM 优化的影响。
"""
import json
import os
import subprocess
import sys
import re
import argparse
import shutil
from datetime import datetime

# Configuration
# Adjust to your actual project root
PROJECT_ROOT = "/mnt/fjx/Compiler_Experiment/serde_test"

# Default to one of them, but we should use args
DEFAULT_SEARCH_SPACE = "/mnt/fjx/Compiler_Experiment/table/table_json/mir_llvm_double_disable_matrix.json"

# Create timestamped results directory
TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
# We will set RESULTS_DIR based on the input filename to keep them separate
RESULTS_BASE_DIR = os.path.join(PROJECT_ROOT, "results_expanded")

BINARY_PATH = os.path.join(PROJECT_ROOT, "target", "release", "serde_test")
# Note: The serde_test main.rs hardcodes iteration count inside, 
# but if it accepted args we would pass this. 
# For now this variable might be unused or passed if main.rs supports it.
ITERATIONS = "3000"

# Global variables for logging, initialized in main/setup
LOG_PATH = ""
CSV_PATH = ""

def log(message):
    print(message)
    if LOG_PATH:
        with open(LOG_PATH, 'a', encoding='utf-8') as f:
            f.write(message + "\n")

def setup_environment(config_name, custom_output_dir=None):
    global LOG_PATH, CSV_PATH
    
    # Determine base directory
    if custom_output_dir:
        # Create timestamped subdirectory inside the custom output directory
        base_dir = os.path.join(custom_output_dir, TIMESTAMP)
    else:
        base_dir = os.path.join(RESULTS_BASE_DIR, f"{config_name}_{TIMESTAMP}")
    
    if not os.path.exists(base_dir):
        os.makedirs(base_dir)
        
    LOG_PATH = os.path.join(base_dir, "experiment_execution.log")
    CSV_PATH = os.path.join(base_dir, "experiment_results.csv")
    
    # Initialize Log
    with open(LOG_PATH, 'w', encoding='utf-8') as f:
        f.write(f"Experiment Execution Log - {config_name}\n========================================\n")

    # Initialize CSV if not exists
    if not os.path.exists(CSV_PATH):
        with open(CSV_PATH, 'w', encoding='utf-8') as f:
            f.write("ConfigName,RunID,LLVM_Pass,MIR_Pass,BinarySize(Bytes),TotalRuntime(s),CompileTime(s),Status\n")

def get_combinations(json_path):
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data.get("combinations", [])

def run_command(command, env=None, cwd=PROJECT_ROOT):
    try:
        log(f"[EXEC] {command}")
        result = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        # Avoid logging massive stdout for speed, unless error
        if result.returncode != 0:
             if result.stdout: log(f"[STDOUT] {result.stdout.strip()}")
             if result.stderr: log(f"[STDERR] {result.stderr.strip()}")
        return result
    except Exception as e:
        log(f"[ERROR] {e}")
        return None

def clean_project(env=None):
    target_dir = os.path.join(PROJECT_ROOT, "target")
    if os.path.exists(target_dir):
        try:
            shutil.rmtree(target_dir)
        except Exception as e:
            # If shutil fails (e.g. permissions/locks), try cargo clean as backup,
            # but usually shutil is better.
            if env is None:
                env = os.environ.copy()
            subprocess.run(["cargo", "clean"], cwd=PROJECT_ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def parse_duration(text):
    match = re.search(r"took:\s+([0-9\.]+)(s|ms|µs|ns)", text)
    if match:
        val = float(match.group(1))
        unit = match.group(2)
        if unit == "s": return val
        if unit == "ms": return val / 1000.0
        if unit == "µs": return val / 1_000_000.0
        if unit == "ns": return val / 1_000_000_000.0
    return 0.0

def measure_combination(combo, runs=1):
    name = combo["name"]
    
    # Handle None/Missing keys safely
    llvm_data = combo.get("llvm")
    mir_data = combo.get("mir")
    
    llvm_pass = llvm_data["pass"] if llvm_data else "None"
    llvm_switches = llvm_data["switches"] if llvm_data and "switches" in llvm_data else []
    
    mir_pass = mir_data["pass"] if mir_data else "None"
    mir_switches = mir_data["switches"] if mir_data and "switches" in mir_data else []
    
    log(f"\n[Exp] Testing: {name}")
    
    # Check if already run (Simplistic check: if name exists runs times?)
    # Since we use timestamped dirs, this is mostly for resuming within same session if crashed
    # But with runs > 1, simple existence check is insufficient.
    # For now, we skip if ANY row with this name exists. 
    # Better: Skip if we have 'runs' entries for this name.
    if os.path.exists(CSV_PATH):
        with open(CSV_PATH, 'r', encoding='utf-8') as f:
            count = sum(1 for line in f if line.startswith(f"{name},"))
            if count >= runs:
                log("  Skipping (Already done)")
                return

    # Construct Flags
    llvm_args = []
    if llvm_switches:
        for switch in llvm_switches:
            # switch is like "-disable-foo"
            llvm_args.append(f"-C llvm-args={switch}")
    
    mir_args = []
    if mir_switches:
        for switch in mir_switches:
            # switch is like "+CopyProp" or "-CopyProp"
            mir_args.append(f"-Z mir-enable-passes={switch}")
            
    # Combine flags
    # We use opt-level=3 as base.
    # Note: If we need LTO, it should be added here or in the JSON switches.
    # For now, we stick to O3 baseline unless JSON says otherwise.
    rustflags_parts = ["-C opt-level=3"] + llvm_args + mir_args
    rustflags = " ".join(rustflags_parts)
    
    # Environment
    env = os.environ.copy()
    env["RUSTFLAGS"] = rustflags
    
    # Ensure cargo path
    cargo_bin = os.path.expanduser("~/.cargo/bin")
    if cargo_bin not in env["PATH"]:
        env["PATH"] = f"{cargo_bin}:{env['PATH']}"
    
    # Loop runs: Clean -> Build -> Measure Size -> Run
    for r in range(1, runs + 1):
        log(f"  Iteration {r}/{runs}...")
        
        # Clean and Build
        clean_project(env)
        log(f"    Building with flags: {rustflags}")
        
        start_compile = datetime.now()
        build_res = run_command("cargo build --release --quiet", env=env)
        compile_duration = (datetime.now() - start_compile).total_seconds()
        
        if build_res.returncode != 0:
            log("    Build Failed!")
            with open(CSV_PATH, 'a', encoding='utf-8') as f:
                f.write(f"{name},{r},{llvm_pass},{mir_pass},0,0,0,BuildFailed\n")
            continue  # Continue to next iteration even if this one failed

        # Measure Size
        if not os.path.exists(BINARY_PATH):
            log("    Binary missing!")
            with open(CSV_PATH, 'a', encoding='utf-8') as f:
                f.write(f"{name},{r},{llvm_pass},{mir_pass},0,0,0,BuildFailed\n")
            continue
            
        size_bytes = os.path.getsize(BINARY_PATH)
        log(f"    Size: {size_bytes} Bytes")
        
        # Run
        run_res = run_command(f"{BINARY_PATH} {ITERATIONS}")
        
        ser_time = 0
        de_time = 0
        total_time = 0
        status = "RunFailed"
        
        if run_res and run_res.returncode == 0:
            # Try to match "Serialize Time: 1.2345 s" (new format) or "Serialization took: ..." (old format)
            ser_match = re.search(r"Serialize Time:\s+([0-9\.]+)\s*s", run_res.stdout)
            if ser_match:
                ser_time = float(ser_match.group(1))
            else:
                # Fallback to old format
                ser_match = re.search(r"Serialization took:\s+(.+)", run_res.stdout)
                if ser_match:
                    ser_time = parse_duration("took: " + ser_match.group(1))

            de_match = re.search(r"Deserialize Time:\s+([0-9\.]+)\s*s", run_res.stdout)
            if de_match:
                de_time = float(de_match.group(1))
            else:
                de_match = re.search(r"Deserialization took:\s+(.+)", run_res.stdout)
                if de_match:
                    de_time = parse_duration("took: " + de_match.group(1))
            
            total_time = ser_time + de_time
            log(f"    Total: {total_time:.6f}s (Ser: {ser_time:.6f}s, De: {de_time:.6f}s)")
            status = "Success"
        else:
            log("    Runtime Failed")
            
        # Save Result
        with open(CSV_PATH, 'a', encoding='utf-8') as f:
            f.write(f"{name},{r},{llvm_pass},{mir_pass},{size_bytes},{total_time:.6f},{compile_duration:.6f},{status}\n")

def main():
    parser = argparse.ArgumentParser(description="Run LLVM/MIR ablation experiment")
    parser.add_argument("config_file", nargs="?", default=DEFAULT_SEARCH_SPACE, help="Path to JSON config file")
    parser.add_argument("--output-dir", help="Custom output directory for results")
    parser.add_argument("--runs", type=int, default=3, help="Number of iterations per configuration (Compile + Run)")
    args = parser.parse_args()
    
    json_path = args.config_file
    if not os.path.exists(json_path):
        print(f"Error: Config file {json_path} not found.")
        return

    config_name = os.path.splitext(os.path.basename(json_path))[0]
    setup_environment(config_name, args.output_dir)
    
    combinations = get_combinations(json_path)
    
    log(f"Found {len(combinations)} combinations to test from {json_path}")
    log(f"Running each configuration {args.runs} times")
    
    start_processing = False
    target_start_name = "EXP_DBL_1246"
    target_end_name = "EXP_DBL_1280"
    log(f"Skipping combinations until: {target_start_name}")
    log(f"Stopping after: {target_end_name}")

    for combo in combinations:
        if combo["name"] == target_start_name:
            start_processing = True
            log(f"Found starting point: {target_start_name}. Resuming experiments...")
        
        if not start_processing:
            continue

        measure_combination(combo, args.runs)
        if combo["name"] == target_end_name:
            log(f"Reached end point: {target_end_name}. Stopping experiments...")
            break
        
    if not start_processing:
        log(f"Warning: Start point '{target_start_name}' not found in combinations.")

    log("\nExperiment Completed.")

if __name__ == "__main__":
    main()
