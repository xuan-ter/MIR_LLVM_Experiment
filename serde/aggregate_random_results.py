"""
功能：聚合随机实验的 CSV 结果
输入：experiment_expanded_llvm_mir.py 产出的分散结果目录
输出：config_summary.csv（汇总的禁用统计与结果路径）
描述：
    扫描 results_expanded 目录下的所有运行子目录。
    提取每个配置的禁用 Pass 列表、运行 ID 与性能指标。
    将分散的单次运行数据汇总为一张宽表，供后续 Lasso 分析使用。
"""
import csv
import os
import sys
from pathlib import Path

BASE = Path("/mnt/fjx/Compiler_Experiment/serde_test")
RESULTS_BASE = BASE / "results_expanded"
SUMMARY_CSV = BASE / "config_summary.csv"

def find_latest_results_dir():
    if not RESULTS_BASE.exists():
        return None
    dirs = [d for d in RESULTS_BASE.iterdir() if d.is_dir() and d.name.startswith("random_configs_")]
    if not dirs:
        return None
    return sorted(dirs)[-1]

def load_config_summary():
    m = {}
    if not SUMMARY_CSV.exists():
        return m
    with open(SUMMARY_CSV, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            name = row.get("config_name", "").strip()
            mir_list = [x for x in row.get("mir_disabled_list", "").split(";") if x]
            llvm_list = [x for x in row.get("llvm_disabled_list", "").split(";") if x]
            m[name] = {"mir": mir_list, "llvm": llvm_list}
    return m

def aggregate_results(results_csv_path, summary_map, out_dir):
    out_path = out_dir / "aggregated_results.csv"
    with open(results_csv_path, newline="", encoding="utf-8") as f_in, open(out_path, "w", newline="", encoding="utf-8") as f_out:
        reader = csv.DictReader(f_in)
        fns = reader.fieldnames + ["mir_disabled_count", "llvm_disabled_count", "mir_disabled_list", "llvm_disabled_list"]
        writer = csv.DictWriter(f_out, fieldnames=fns)
        writer.writeheader()
        for row in reader:
            name = row.get("ConfigName", "")
            s = summary_map.get(name, {"mir": [], "llvm": []})
            row["mir_disabled_count"] = str(len(s["mir"]))
            row["llvm_disabled_count"] = str(len(s["llvm"]))
            row["mir_disabled_list"] = ";".join(s["mir"])
            row["llvm_disabled_list"] = ";".join(s["llvm"])
            writer.writerow(row)
    return out_path

def compute_cooccurrence(summary_map, out_dir):
    mir_all = sorted({p for v in summary_map.values() for p in v["mir"]})
    llvm_all = sorted({p for v in summary_map.values() for p in v["llvm"]})
    counts = {}
    for m in mir_all:
        for l in llvm_all:
            counts[(m, l)] = 0
    for s in summary_map.values():
        ms = set(s["mir"])
        ls = set(s["llvm"])
        for m in ms:
            for l in ls:
                counts[(m, l)] += 1
    out_path = out_dir / "cooccurrence_count_from_random.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["MIR_Pass", "LLVM_Pass", "co_count"])
        for (m, l), c in counts.items():
            w.writerow([m, l, c])
    return out_path

def summarize_runs(results_csv_path, out_dir):
    total = 0
    ok = 0
    with open(results_csv_path, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            total += 1
            if row.get("Status", "") == "Success":
                ok += 1
    out_path = out_dir / "run_summary.txt"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(f"rows={total}\n")
        f.write(f"success={ok}\n")
        rate = (ok / total) if total else 0.0
        f.write(f"success_rate={rate:.6f}\n")
    return out_path

def main():
    if len(sys.argv) > 1:
        res_dir = Path(sys.argv[1])
    else:
        res_dir = find_latest_results_dir()
    if not res_dir:
        print("No results directory found.")
        return
    results_csv = res_dir / "experiment_results.csv"
    if not results_csv.exists():
        print(f"Missing {results_csv}")
        return
    summary_map = load_config_summary()
    aggr_path = aggregate_results(results_csv, summary_map, res_dir)
    co_path = compute_cooccurrence(summary_map, res_dir)
    sum_path = summarize_runs(results_csv, res_dir)
    print(str(res_dir))
    print(str(aggr_path))
    print(str(co_path))
    print(str(sum_path))

if __name__ == "__main__":
    main()
