import json
import subprocess
import os
import time
import sys

# Configuration
PROJECT_DIR = os.path.abspath("serde_test")
CONFIG_FILE = os.path.abspath("compiler_config.json")
BINARY_PATH = os.path.join(PROJECT_DIR, "target", "release", "serde_test")

def get_binary_size(path):
    if os.path.exists(path):
        return os.path.getsize(path)
    return 0

def run_experiment(config):
    name = config["name"]
    flags = config["rustflags"]
    
    print(f"Running experiment: {name}")
    
    # Environment with Rust flags
    env = os.environ.copy()
    env["RUSTFLAGS"] = flags
    # Ensure cargo is in path
    cargo_bin = os.path.expanduser("~/.cargo/bin")
    if cargo_bin not in env["PATH"]:
        env["PATH"] = f"{cargo_bin}:{env['PATH']}"
        
    # Clean
    try:
        subprocess.run(["cargo", "clean"], cwd=PROJECT_DIR, env=env, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        print("Warning: cargo clean failed")
    except FileNotFoundError:
        print("Error: cargo not found. Please install Rust.")
        return None
    
    # Build
    # We use --release to ensure we are in the release profile, but flags override
    cmd = ["cargo", "build", "--release"]
    start_compile = time.time()
    try:
        result = subprocess.run(cmd, cwd=PROJECT_DIR, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except FileNotFoundError:
        print("Error: cargo not found during build.")
        return None

    compile_time = time.time() - start_compile
    
    if result.returncode != 0:
        print(f"Build failed for {name}")
        print(result.stderr.decode())
        return None

    # Measure size
    size = get_binary_size(BINARY_PATH)
    
    # Measure execution time
    start_run = time.time()
    try:
        run_result = subprocess.run([BINARY_PATH], cwd=PROJECT_DIR, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        exec_time = time.time() - start_run
    except Exception as e:
        print(f"Execution failed: {e}")
        return None
    
    if run_result.returncode != 0:
        print(f"Execution failed for {name} with return code {run_result.returncode}")
        return None
        
    return {
        "name": name,
        "flags": flags,
        "binary_size_bytes": size,
        "execution_time_seconds": exec_time,
        "compile_time_seconds": compile_time
    }

def main():
    if not os.path.exists(CONFIG_FILE):
        print(f"Config file not found: {CONFIG_FILE}")
        return

    with open(CONFIG_FILE, 'r') as f:
        configs = json.load(f)
        
    results = []
    print(f"{'Name':<25} | {'Size (Bytes)':<12} | {'Time (s)':<10} | {'Compile (s)':<10}")
    print("-" * 65)
    
    for config in configs:
        res = run_experiment(config)
        if res:
            results.append(res)
            print(f"{res['name']:<25} | {res['binary_size_bytes']:<12} | {res['execution_time_seconds']:<10.4f} | {res['compile_time_seconds']:<10.4f}")
            
    # Save results
    with open("results.json", "w") as f:
        json.dump(results, f, indent=4)
    print("\nResults saved to results.json")

if __name__ == "__main__":
    main()
