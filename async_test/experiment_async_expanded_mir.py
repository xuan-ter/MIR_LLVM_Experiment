import csv
import json
import os
import subprocess
import sys
import re
import argparse
import time
from datetime import datetime

# Configuration
PROJECT_ROOT = "/mnt/fjx/Compiler_Experiment/async_test"

# Default CSV path (Modified to use the MIR OFF matrix)
DEFAULT_CSV_PATH = "/mnt/fjx/Compiler_Experiment/table/mir_experiment_matrix_off.csv"

# Create timestamped results directory
TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
# We will set RESULTS_DIR based on the input filename to keep them separate
RESULTS_BASE_DIR = os.path.join(PROJECT_ROOT, "results_expanded_mir")

BINARY_PATH = os.path.join(PROJECT_ROOT, "target", "release", "async_test")
TASK_COUNT = "10000"
COMPLEXITY = "1000"

# Global variables for logging, initialized in main/setup
LOG_PATH = ""
CSV_PATH = ""

def log(message):
    print(message)
    if LOG_PATH:
        try:
            with open(LOG_PATH, 'a', encoding='utf-8') as f:
                f.write(message + "\n")
        except Exception as e:
            print(f"Error writing to log: {e}")

def setup_environment(config_name):
    global LOG_PATH, CSV_PATH
    
    # Create specific result dir for this run
    if not os.path.exists(RESULTS_BASE_DIR):
        os.makedirs(RESULTS_BASE_DIR)
        
    run_dir = os.path.join(RESULTS_BASE_DIR, f"{config_name}_{TIMESTAMP}")
    if not os.path.exists(run_dir):
        os.makedirs(run_dir)
        
    LOG_PATH = os.path.join(run_dir, "experiment_execution.log")
    CSV_PATH = os.path.join(run_dir, "experiment_results.csv")
    
    # Initialize Log
    with open(LOG_PATH, 'w', encoding='utf-8') as f:
        f.write(f"Experiment Execution Log - {config_name}\n========================================\n")

    # Initialize CSV if not exists
    if not os.path.exists(CSV_PATH):
        with open(CSV_PATH, 'w', encoding='utf-8') as f:
            f.write("ConfigName,RunID,LLVM_Pass,MIR_Pass,BinarySize(Bytes),TotalRuntime(s),CompileTime(s),Status\n")

    return run_dir

def get_combinations_from_csv(csv_path):
    combinations = []
    if not os.path.exists(csv_path):
        print(f"Error: CSV file {csv_path} not found.")
        return combinations
        
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                combinations.append(row)
    except Exception as e:
        print(f"Error reading CSV: {e}")
        
    return combinations

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
            # Limit stdout log size
            log(f"[STDOUT] {result.stdout.strip()[:1000]}")
        if result.stderr:
            log(f"[STDERR] {result.stderr.strip()[:1000]}")
        return result
    except Exception as e:
        log(f"[ERROR] {e}")
        return None

def clean_project():
    subprocess.run(["cargo", "clean"], cwd=PROJECT_ROOT, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def measure_combination(combo, run_id):
    # Map CSV columns to experiment variables
    # Expected CSV columns based on user file:
    # Experiment_ID, Description, Target_Pass, RUSTFLAGS, Notes
    
    name = combo.get("Experiment_ID", "Unknown")
    target_pass = combo.get("Target_Pass", "N/A")
    rustflags_csv = combo.get("RUSTFLAGS", "")
    
    # Parse RUSTFLAGS to extract MIR pass info for logging
    # Example: -Z mir-enable-passes=-DeadStoreElimination-final
    mir_pass = target_pass
    llvm_pass = "None" 

    log(f"\n--- Running Experiment: {name} (Run {run_id}) ---")
    log(f"Target Pass: {target_pass}")
    log(f"RUSTFLAGS: {rustflags_csv}")

    # 1. Clean
    clean_project()

    # 2. Build with RUSTFLAGS
    # Use nightly toolchain as -Z flags require it
    env = os.environ.copy()
    if rustflags_csv and rustflags_csv.strip():
        env["RUSTFLAGS"] = rustflags_csv
    
    # Ensure using nightly
    build_cmd = "cargo +nightly build --release"
    
    start_time = time.time()
    build_result = run_command(build_cmd, env=env)
    compile_time = time.time() - start_time

    if build_result is None or build_result.returncode != 0:
        log(f"Build failed for {name}")
        record_result(name, run_id, llvm_pass, mir_pass, 0, 0, compile_time, "BuildFailed")
        return

    # 3. Measure Binary Size
    binary_size = 0
    if os.path.exists(BINARY_PATH):
        binary_size = os.path.getsize(BINARY_PATH)
        log(f"Binary Size: {binary_size} bytes")
    else:
        log("Binary not found!")
        record_result(name, run_id, llvm_pass, mir_pass, 0, 0, compile_time, "BinaryMissing")
        return

    # 4. Run Benchmark
    # async_test takes args: <task_count> <complexity>
    run_cmd = f"{BINARY_PATH} {TASK_COUNT} {COMPLEXITY}"
    
    # Run multiple times for stability? The requirement implies just running it.
    # We'll run once per 'run_id' call.
    
    start_run = time.time()
    run_result = run_command(run_cmd)
    total_runtime = time.time() - start_run

    if run_result is None or run_result.returncode != 0:
        log(f"Runtime failed for {name}")
        record_result(name, run_id, llvm_pass, mir_pass, binary_size, 0, compile_time, "RuntimeFailed")
        return
    
    # Try to parse specific output from the binary if it prints metrics
    # But for now, we use the wall clock time of the process
    
    log(f"Runtime: {total_runtime:.4f}s")
    record_result(name, run_id, llvm_pass, mir_pass, binary_size, total_runtime, compile_time, "Success")

def record_result(config_name, run_id, llvm_pass, mir_pass, size, runtime, compile_time, status):
    if not CSV_PATH:
        return
    
    with open(CSV_PATH, 'a', encoding='utf-8') as f:
        # ConfigName,RunID,LLVM_Pass,MIR_Pass,BinarySize(Bytes),TotalRuntime(s),CompileTime(s),Status
        f.write(f"{config_name},{run_id},{llvm_pass},{mir_pass},{size},{runtime:.6f},{compile_time:.6f},{status}\n")

def main():
    parser = argparse.ArgumentParser(description="Run Async Experiment with MIR Flags")
    parser.add_argument("--csv", help="Path to experiment matrix CSV", default=DEFAULT_CSV_PATH)
    parser.add_argument("--runs", help="Number of runs per configuration", type=int, default=3)
    args = parser.parse_args()

    csv_file = args.csv
    runs = args.runs

    print(f"Starting Experiment with CSV: {csv_file}")
    
    # Setup environment
    config_name = os.path.splitext(os.path.basename(csv_file))[0]
    run_dir = setup_environment(config_name)
    print(f"Results will be saved to: {run_dir}")

    # Load combinations
    combinations = get_combinations_from_csv(csv_file)
    print(f"Found {len(combinations)} configurations.")

    # Run experiments
    for i, combo in enumerate(combinations):
        print(f"Processing config {i+1}/{len(combinations)}: {combo.get('Experiment_ID', 'Unknown')}")
        for r in range(runs):
            measure_combination(combo, r+1)

    print("Experiment completed.")

if __name__ == "__main__":
    main()
