import csv
import json
import os
import shutil
import subprocess
import sys
import re
import argparse
import time
from datetime import datetime

# Configuration
PROJECT_ROOT = "/mnt/fjx/Compiler_Experiment/async_test"

# Default JSON path
DEFAULT_JSON_PATH = "/mnt/fjx/Compiler_Experiment/table/table_json/combined_experiment_matrix.json"

# Create timestamped results directory
TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
# We will set RESULTS_DIR based on the input filename to keep them separate
RESULTS_BASE_DIR = os.path.join(PROJECT_ROOT, "results_expanded")

BINARY_PATH = os.path.join(PROJECT_ROOT, "target", "release", "async_test")
TASK_COUNT = "30000"
COMPLEXITY = "3000"

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
        if result.stdout:
            log(f"[STDOUT] {result.stdout.strip()}")
        if result.stderr:
            log(f"[STDERR] {result.stderr.strip()}")
        return result
    except Exception as e:
        log(f"[ERROR] {e}")
        return None

def clean_project(env=None):
    target_dir = os.path.join(PROJECT_ROOT, "target")
    if os.path.exists(target_dir):
        try:
            shutil.rmtree(target_dir)
        except Exception:
            if env is None:
                env = os.environ.copy()
            subprocess.run(["cargo", "clean"], cwd=PROJECT_ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def measure_combination(combo, runs=1, skip_clean=False):
    name = combo.get("name") or combo.get("Experiment_ID") or "Unknown"
    
    # Extract passes for logging
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

    log(f"\n[Exp] Testing: {name}")
    
    # Check if already run (Simplistic check: if name exists runs times?)
    if os.path.exists(CSV_PATH):
        with open(CSV_PATH, 'r', encoding='utf-8') as f:
            count = sum(1 for line in f if line.startswith(f"{name},"))
            if count >= runs:
                log("  Skipping (Already done)")
                return

    # Construct Flags
    flags = ["-C opt-level=3"]
    
    # MIR Flags
    if combo.get("mir") and isinstance(combo["mir"], dict) and combo["mir"].get("switches"):
        switches = ",".join(combo["mir"]["switches"])
        flags.append(f"-Z mir-enable-passes={switches}")
        
    # LLVM Flags
    if combo.get("llvm") and isinstance(combo["llvm"], dict) and combo["llvm"].get("switches"):
        for switch in combo["llvm"]["switches"]:
            # rustc expects -C llvm-args="arg1 arg2" or -C llvm-args=arg1 -C llvm-args=arg2
            # Passing individually is safer to avoid quoting issues
            flags.append(f"-C llvm-args={switch}")

    # Legacy CSV RUSTFLAGS support
    if "RUSTFLAGS" in combo and combo["RUSTFLAGS"]:
         flags.append(combo["RUSTFLAGS"])

    rustflags = " ".join(flags)
    
    # Environment
    env = os.environ.copy()
    env["RUSTFLAGS"] = rustflags
    
    # Ensure cargo path
    cargo_bin = os.path.expanduser("~/.cargo/bin")
    if cargo_bin not in env["PATH"]:
        env["PATH"] = f"{cargo_bin}:{env['PATH']}"
        
    for r in range(1, runs + 1):
        log(f"  Iteration {r}/{runs}...")

        # Clean and Build
        if not skip_clean:
            clean_project(env)
        log(f"  Building with flags: {rustflags}")
        
        start_compile = datetime.now()
        build_res = run_command("cargo build --release --quiet", env=env)
        compile_duration = (datetime.now() - start_compile).total_seconds()
        
        if build_res.returncode != 0:
            log("    Build Failed!")
            with open(CSV_PATH, 'a', encoding='utf-8') as f:
                f.write(f"{name},{r},{llvm_pass},{mir_pass},0,0,0,BuildFailed\n")
            continue

        # Measure Size
        if not os.path.exists(BINARY_PATH):
            log("    Binary missing!")
            with open(CSV_PATH, 'a', encoding='utf-8') as f:
                f.write(f"{name},{r},{llvm_pass},{mir_pass},0,0,0,BuildFailed\n")
            continue
            
        size_bytes = os.path.getsize(BINARY_PATH)
        log(f"    Size: {size_bytes} Bytes")
        
        # Run
        run_res = run_command(f"{BINARY_PATH} {TASK_COUNT} {COMPLEXITY}")
        
        time_val = 0.0
        status = "RunFailed"
        
        if run_res and run_res.returncode == 0:
            # Parse output for "Total Time: X s" and "Throughput: Y tasks/s"
            match_time = re.search(r"Total Time:\s+([\d\.]+)\s+s", run_res.stdout)
            match_throughput = re.search(r"Throughput:\s+([\d\.]+)\s+tasks/s", run_res.stdout)
            
            if match_time:
                time_val = float(match_time.group(1))
                throughput_val = float(match_throughput.group(1)) if match_throughput else 0
                log(f"    Time: {time_val} s, Throughput: {throughput_val} tasks/s")
                status = "Success"
            else:
                log("    Time/Throughput parse failed")
                status = "ParseFailed"
        else:
            log("    Runtime Failed")
            
        # Save Result
        with open(CSV_PATH, 'a', encoding='utf-8') as f:
            f.write(f"{name},{r},{llvm_pass},{mir_pass},{size_bytes},{time_val:.6f},{compile_duration:.6f},{status}\n")

def main():
    parser = argparse.ArgumentParser(description="Run LLVM/MIR ablation experiment for Async")
    parser.add_argument("config_file", nargs="?", default=DEFAULT_JSON_PATH, help="Path to config file (JSON)")
    parser.add_argument("--output-dir", help="Custom output directory for results")
    parser.add_argument("--runs", type=int, default=3, help="Number of iterations per configuration (Compile + Run)")
    parser.add_argument("--skip-clean", action="store_true", help="Do not remove target/ between runs/configs")
    args = parser.parse_args()
    
    config_path = args.config_file
    if not os.path.exists(config_path):
        print(f"Error: Config file {config_path} not found.")
        return

    config_name = os.path.splitext(os.path.basename(config_path))[0]
    setup_environment(config_name, args.output_dir)
    
    combinations = get_combinations(config_path)

    log(f"Found {len(combinations)} combinations to test from {config_path}")
    log(f"Running each configuration {args.runs} times")
    
    for combo in combinations:
        measure_combination(combo, args.runs, skip_clean=args.skip_clean)
        
    log("\nExperiment Completed.")

if __name__ == "__main__":
    main()
