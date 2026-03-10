import os
import csv
import re

# Input file paths
LLVM_FILE = r"c:\Users\21101\Desktop\实验\llvm_dummy\classification\llvm_args_categorized_7_classes.txt"
MIR_FILE = r"c:\Users\21101\Desktop\实验\mir_dummy\classify\mir_tunable_optimizations.txt"
OUTPUT_DIR = r"c:\Users\21101\Desktop\实验\Ablation experiment\table_llvm_classify"

def parse_llvm_categories(filepath):
    """
    Parses the categorized LLVM args file.
    Returns a dict: { "CategoryName": ["-disable-arg1", "-disable-arg2", ...] }
    """
    categories = {}
    current_category = None
    
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
                
            # Check for category header: === Category (Count) ===
            match = re.match(r"^===\s+(.+?)\s+\(\d+\)\s+===$", line)
            if match:
                current_category = match.group(1)
                categories[current_category] = []
            elif line.startswith("-disable-") and current_category:
                categories[current_category].append(line)
                
    return categories

def parse_mir_passes(filepath):
    """
    Parses the MIR passes file.
    Returns a list of pass names.
    """
    passes = []
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            if '| Tunable Optimization' in line:
                pass_name = line.split('|')[0].strip()
                if pass_name and pass_name != "Pass Name":
                    passes.append(pass_name)
    return passes

def main():
    # Ensure output directory exists
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 1. Parse Inputs
    llvm_categories = parse_llvm_categories(LLVM_FILE)
    mir_passes = parse_mir_passes(MIR_FILE)
    
    print(f"Found {len(llvm_categories)} LLVM categories.")
    print(f"Found {len(mir_passes)} MIR passes.")

    total_experiments = 0

    # 2. Generate CSV for each category
    for category, llvm_args in llvm_categories.items():
        safe_category = re.sub(r'[\\/*?:"<>|]', "_", category) # Sanitize filename
        output_csv = os.path.join(OUTPUT_DIR, f"experiment_matrix_{safe_category}.csv")
        
        headers = ["Experiment_ID", "Type", "Category", "LLVM_Arg", "MIR_Pass", "RUSTFLAGS", "Description"]
        rows = []
        
        # 2.1 Baseline (Global for this file, repeated for convenience)
        rows.append({
            "Experiment_ID": f"EXP_{safe_category}_000_BASELINE",
            "Type": "Baseline",
            "Category": category,
            "LLVM_Arg": "None",
            "MIR_Pass": "None",
            "RUSTFLAGS": "",
            "Description": "Default settings"
        })
        
        count = 1
        
        # 2.2 Single Disable (LLVM Only) - Pure Ablation
        for llvm in llvm_args:
            rows.append({
                "Experiment_ID": f"EXP_{safe_category}_SGL_{count:04d}",
                "Type": "Single_Disable_LLVM",
                "Category": category,
                "LLVM_Arg": llvm,
                "MIR_Pass": "None",
                "RUSTFLAGS": f"-C llvm-args={llvm}",
                "Description": f"Disable LLVM {llvm}"
            })
            count += 1
            
        # 2.3 Double Disable (LLVM in Category x All MIR Passes)
        for llvm in llvm_args:
            for mir in mir_passes:
                rows.append({
                    "Experiment_ID": f"EXP_{safe_category}_DBL_{count:04d}",
                    "Type": "Double_Disable",
                    "Category": category,
                    "LLVM_Arg": llvm,
                    "MIR_Pass": mir,
                    "RUSTFLAGS": f"-C llvm-args={llvm} -Z mir-enable-passes=-{mir}",
                    "Description": f"Disable LLVM {llvm} AND MIR {mir}"
                })
                count += 1
        
        # Write CSV
        with open(output_csv, 'w', encoding='utf-8', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rows)
            
        print(f"Generated {len(rows)} experiments for category '{category}' in {output_csv}")
        total_experiments += len(rows)

    print(f"Total experiments generated: {total_experiments}")

if __name__ == "__main__":
    main()
