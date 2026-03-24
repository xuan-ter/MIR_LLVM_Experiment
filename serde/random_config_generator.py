"""
功能：生成随机 MIR/LLVM Pass 禁用配置
输入：无（硬编码 Pass 列表与概率 q）
输出：random_configs.json（N 个随机配置）
描述：
    根据设定的禁用概率（q≈0.3），生成 N 个独立的随机开关组合。
    每个配置包含待禁用的 MIR passes 和 LLVM passes 列表。
    生成的 JSON 用于 experiment_expanded_llvm_mir.py 运行实验。
"""
import json
import random
import csv
import os
from pathlib import Path

# Configuration
N_CONFIGS = 1000
DISABLE_PROB = 0.3
OUTPUT_JSON = "random_configs.json"
SUMMARY_CSV = "config_summary.csv"
MIR_COVERAGE_FILE = "/mnt/fjx/Compiler_Experiment/analysis/lasso/results/mir_coverage.csv"
LLVM_COVERAGE_FILE = "/mnt/fjx/Compiler_Experiment/analysis/lasso/results/llvm_coverage.csv"

def load_passes(csv_file, column_name):
    passes = []
    if not os.path.exists(csv_file):
        print(f"Warning: {csv_file} not found.")
        return []
    with open(csv_file, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            pass_name = row.get(column_name, "").strip()
            if pass_name and pass_name.lower() != "nan":
                passes.append(pass_name)
    return passes

def main():
    print(f"Loading passes from {MIR_COVERAGE_FILE} and {LLVM_COVERAGE_FILE}...")
    mir_passes = load_passes(MIR_COVERAGE_FILE, "MIR_Pass")
    llvm_passes = load_passes(LLVM_COVERAGE_FILE, "LLVM_Pass")

    print(f"Found {len(mir_passes)} MIR passes and {len(llvm_passes)} LLVM passes.")

    configs = []
    summary_data = []

    print(f"Generating {N_CONFIGS} random configurations with disable probability {DISABLE_PROB}...")

    for i in range(N_CONFIGS):
        config_name = f"RANDOM_CONFIG_{i:04d}"
        
        # Determine disabled passes
        disabled_mir = [p for p in mir_passes if random.random() < DISABLE_PROB]
        disabled_llvm = [p for p in llvm_passes if random.random() < DISABLE_PROB]
        
        # Create switch lists
        mir_switches = [f"-{p}" for p in disabled_mir]
        # For LLVM, we assume the switch is -disable-<passname> based on previous files
        llvm_switches = [f"-disable-{p}" for p in disabled_llvm]
        
        config_entry = {
            "name": config_name,
            "description": f"Random config {i} (Disabled: {len(disabled_mir)} MIR, {len(disabled_llvm)} LLVM)",
            "llvm": {
                "pass": "random_set", # Just a label
                "switches": llvm_switches,
                "parameters": {}
            },
            "mir": {
                "pass": "random_set", # Just a label
                "switches": mir_switches,
                "parameters": {}
            }
        }
        configs.append(config_entry)
        
        summary_data.append({
            "config_id": i,
            "config_name": config_name,
            "mir_disabled_count": len(disabled_mir),
            "llvm_disabled_count": len(disabled_llvm),
            "mir_disabled_list": ";".join(disabled_mir),
            "llvm_disabled_list": ";".join(disabled_llvm)
        })

    # Write JSON output
    output_data = {
        "description": f"Randomly generated configurations (N={N_CONFIGS}, p={DISABLE_PROB})",
        "combinations": configs
    }
    
    with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2)
    print(f"Saved {N_CONFIGS} configurations to {OUTPUT_JSON}")

    # Write Summary CSV
    with open(SUMMARY_CSV, 'w', encoding='utf-8', newline='') as f:
        fieldnames = ["config_id", "config_name", "mir_disabled_count", "llvm_disabled_count", "mir_disabled_list", "llvm_disabled_list"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(summary_data)
    print(f"Saved summary to {SUMMARY_CSV}")

    # Instructions
    print("\nTo run the experiment, use the following command:")
    print(f"python3 experiment_expanded_llvm_mir.py {OUTPUT_JSON} --runs 5")

if __name__ == "__main__":
    main()
