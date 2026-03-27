import os
import subprocess
import argparse
import shutil
from datetime import datetime
import re
PROJECT_ROOT = "/mnt/fjx/Compiler_Experiment/serde_test"
TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
RESULTS_BASE_DIR = os.path.join(PROJECT_ROOT, "results_baseline_opt3")
BINARY_PATH = os.path.join(PROJECT_ROOT, "target", "release", "serde_test")
ITERATIONS = "3000"
LOG_PATH = ""
CSV_PATH = ""
def log(message):
    print(message)
    if LOG_PATH:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(message + "\n")
def setup_environment(config_name, custom_output_dir=None):
    global LOG_PATH, CSV_PATH
    if custom_output_dir:
        base_dir = os.path.join(custom_output_dir, TIMESTAMP)
    else:
        base_dir = os.path.join(RESULTS_BASE_DIR, f"{config_name}_{TIMESTAMP}")
    if not os.path.exists(base_dir):
        os.makedirs(base_dir)
    LOG_PATH = os.path.join(base_dir, "experiment_execution.log")
    CSV_PATH = os.path.join(base_dir, "experiment_results.csv")
    with open(LOG_PATH, "w", encoding="utf-8") as f:
        f.write(f"Experiment Execution Log - {config_name}\n")
    if not os.path.exists(CSV_PATH):
        with open(CSV_PATH, "w", encoding="utf-8") as f:
            f.write("ConfigName,RunID,LLVM_Pass,MIR_Pass,BinarySize(Bytes),TotalRuntime(s),CompileTime(s),Status\n")
def run_command(command, env=None, cwd=PROJECT_ROOT):
    try:
        log(f"[EXEC] {command}")
        result = subprocess.run(command, cwd=cwd, env=env, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            if result.stdout:
                log(f"[STDOUT] {result.stdout.strip()}")
            if result.stderr:
                log(f"[STDERR] {result.stderr.strip()}")
        return result
    except Exception as e:
        log(f"[ERROR] {e}")
        return None
def parse_duration(text):
    m = re.search(r"took:\s+([0-9\.]+)(s|ms|µs|ns)", text)
    if not m:
        return 0.0
    val = float(m.group(1))
    unit = m.group(2)
    if unit == "s":
        return val
    if unit == "ms":
        return val / 1000.0
    if unit == "µs":
        return val / 1_000_000.0
    if unit == "ns":
        return val / 1_000_000_000.0
    return 0.0
def clean_project(env=None):
    target_dir = os.path.join(PROJECT_ROOT, "target")
    if os.path.exists(target_dir):
        try:
            shutil.rmtree(target_dir)
        except Exception:
            if env is None:
                env = os.environ.copy()
            subprocess.run(["cargo", "clean"], cwd=PROJECT_ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
def measure_baseline(name, runs=1, skip_clean=False):
    llvm_pass = "baseline"
    mir_pass = "baseline"
    env = os.environ.copy()
    env["RUSTFLAGS"] = "-C opt-level=3"
    cargo_bin = os.path.expanduser("~/.cargo/bin")
    if cargo_bin not in env["PATH"]:
        env["PATH"] = f"{cargo_bin}:{env['PATH']}"
    for r in range(1, runs + 1):
        log(f"  Iteration {r}/{runs}...")
        if not skip_clean:
            clean_project(env)
        log(f"    Building with flags: {env['RUSTFLAGS']}")
        start_compile = datetime.now()
        build_res = run_command("cargo build --release --quiet", env=env)
        compile_duration = (datetime.now() - start_compile).total_seconds()
        if build_res is None or build_res.returncode != 0:
            log("    Build Failed!")
            with open(CSV_PATH, "a", encoding="utf-8") as f:
                f.write(f"{name},{r},{llvm_pass},{mir_pass},0,0,0,BuildFailed\n")
            continue
        if not os.path.exists(BINARY_PATH):
            log("    Binary missing!")
            with open(CSV_PATH, "a", encoding="utf-8") as f:
                f.write(f"{name},{r},{llvm_pass},{mir_pass},0,0,0,BuildFailed\n")
            continue
        size_bytes = os.path.getsize(BINARY_PATH)
        log(f"    Size: {size_bytes} Bytes")
        run_res = run_command(f"{BINARY_PATH} {ITERATIONS}")
        total_time = 0.0
        status = "RunFailed"
        if run_res and run_res.returncode == 0:
            ser_time = 0.0
            de_time = 0.0
            ser_match = re.search(r"Serialize Time:\s+([0-9\.]+)\s*s", run_res.stdout)
            if ser_match:
                ser_time = float(ser_match.group(1))
            else:
                ser_old = re.search(r"Serialization took:\s+(.+)", run_res.stdout)
                if ser_old:
                    ser_time = parse_duration("took: " + ser_old.group(1))
            de_match = re.search(r"Deserialize Time:\s+([0-9\.]+)\s*s", run_res.stdout)
            if de_match:
                de_time = float(de_match.group(1))
            else:
                de_old = re.search(r"Deserialization took:\s+(.+)", run_res.stdout)
                if de_old:
                    de_time = parse_duration("took: " + de_old.group(1))
            total_time = ser_time + de_time
            status = "Success"
            log(f"    Total: {total_time:.6f}s")
        with open(CSV_PATH, "a", encoding="utf-8") as f:
            f.write(f"{name},{r},{llvm_pass},{mir_pass},{size_bytes},{total_time:.6f},{compile_duration:.6f},{status}\n")
def main():
    parser = argparse.ArgumentParser(description="Baseline opt-level=3 experiment")
    parser.add_argument("--output-dir", help="Custom output directory for results")
    parser.add_argument("--runs", type=int, default=200)
    parser.add_argument("--skip-clean", action="store_true")
    args = parser.parse_args()
    config_name = "BASELINE_OPT3"
    setup_environment(config_name, args.output_dir)
    log(f"Running baseline opt-level=3 for {args.runs} times")
    measure_baseline(config_name, runs=args.runs, skip_clean=args.skip_clean)
    log("Experiment Completed.")
if __name__ == "__main__":
    main()
