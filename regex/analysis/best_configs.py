import argparse
import csv
import math
import os


DEFAULT_CSV_PATH = r"d:\MIR_LLVM\mir_-llvm\regex\mir_llvm_hybrid_py\20260310_224816\experiment_results.csv"
DEFAULT_OUT_PATH = r"d:\MIR_LLVM\mir_-llvm\regex\analysis\best_configs_summary.csv"


def _to_float(value):
    if value is None:
        return math.nan
    s = str(value).strip()
    if not s:
        return math.nan
    try:
        return float(s)
    except ValueError:
        return math.nan


def _to_int(value):
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        try:
            return int(float(s))
        except ValueError:
            return None


def _is_success(status):
    s = (status or "").strip().lower()
    return s == "success"


def _pick_best_row(rows, metric_key, better):
    best = None
    best_val = None
    for row in rows:
        v = row.get(metric_key)
        if v is None:
            continue
        if isinstance(v, float) and math.isnan(v):
            continue
        if best is None:
            best = row
            best_val = v
            continue
        if better(v, best_val):
            best = row
            best_val = v
    return best


def _top_k(rows, metric_key, k):
    scored = []
    for row in rows:
        v = row.get(metric_key)
        if v is None:
            continue
        if isinstance(v, float) and math.isnan(v):
            continue
        scored.append((v, row))
    scored.sort(key=lambda t: t[0])
    return [row for _, row in scored[: max(0, k)]]


def _fmt_row(row):
    return (
        f"ConfigName={row.get('ConfigName')}, "
        f"RunID={row.get('RunID')}, "
        f"LLVM_Pass={row.get('LLVM_Pass')}, "
        f"MIR_Pass={row.get('MIR_Pass')}, "
        f"BinarySize(Bytes)={row.get('BinarySize(Bytes)')}, "
        f"TotalRuntime(s)={row.get('TotalRuntime(s)')}, "
        f"CompileTime(s)={row.get('CompileTime(s)')}, "
        f"Status={row.get('Status')}"
    )


def load_rows(csv_path):
    rows = []
    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            row = dict(r)
            row["BinarySize(Bytes)"] = _to_int(row.get("BinarySize(Bytes)"))
            row["TotalRuntime(s)"] = _to_float(row.get("TotalRuntime(s)"))
            row["CompileTime(s)"] = _to_float(row.get("CompileTime(s)"))
            row["RunID"] = _to_int(row.get("RunID"))
            rows.append(row)
    return rows


def _write_summary_csv(out_path, source_csv, best_rows):
    out_dir = os.path.dirname(out_path)
    if out_dir and not os.path.exists(out_dir):
        os.makedirs(out_dir)

    fieldnames = [
        "Criterion",
        "Rank",
        "SourceCSV",
        "ConfigName",
        "RunID",
        "LLVM_Pass",
        "MIR_Pass",
        "BinarySize(Bytes)",
        "TotalRuntime(s)",
        "CompileTime(s)",
        "Status",
    ]

    with open(out_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for criterion, rank, row in best_rows:
            writer.writerow(
                {
                    "Criterion": criterion,
                    "Rank": rank,
                    "SourceCSV": source_csv,
                    "ConfigName": row.get("ConfigName"),
                    "RunID": row.get("RunID"),
                    "LLVM_Pass": row.get("LLVM_Pass"),
                    "MIR_Pass": row.get("MIR_Pass"),
                    "BinarySize(Bytes)": row.get("BinarySize(Bytes)"),
                    "TotalRuntime(s)": row.get("TotalRuntime(s)"),
                    "CompileTime(s)": row.get("CompileTime(s)"),
                    "Status": row.get("Status"),
                }
            )


def main():
    parser = argparse.ArgumentParser(description="Find best configs from experiment_results.csv (regex)")
    parser.add_argument("csv_file", nargs="?", default=DEFAULT_CSV_PATH, help="Path to experiment_results.csv")
    parser.add_argument("--status", default="success", choices=["success", "all"], help="Filter by Status")
    parser.add_argument("--aggregate", default="min", choices=["min"], help="Aggregate per ConfigName")
    parser.add_argument("--top-k", type=int, default=3, help="Top K configs for each criterion")
    parser.add_argument("--out", default=DEFAULT_OUT_PATH, help="Write summary CSV to this path")
    args = parser.parse_args()

    csv_path = args.csv_file
    if not os.path.exists(csv_path):
        raise SystemExit(f"CSV not found: {csv_path}")

    rows = load_rows(csv_path)
    if args.status == "success":
        rows = [r for r in rows if _is_success(r.get("Status"))]

    by_cfg = {}
    for r in rows:
        cfg = (r.get("ConfigName") or "").strip()
        if not cfg:
            continue
        by_cfg.setdefault(cfg, []).append(r)

    agg_rows = []
    for cfg, rs in by_cfg.items():
        best_runtime = _pick_best_row(rs, "TotalRuntime(s)", lambda a, b: a < b)
        best_size = _pick_best_row(rs, "BinarySize(Bytes)", lambda a, b: a < b)
        best_compile = _pick_best_row(rs, "CompileTime(s)", lambda a, b: a < b)

        if not (best_runtime and best_size and best_compile):
            continue

        agg_rows.append(
            {
                "ConfigName": cfg,
                "BestRuntimeRow": best_runtime,
                "BestSizeRow": best_size,
                "BestCompileRow": best_compile,
                "BestRuntime(s)": best_runtime["TotalRuntime(s)"],
                "MinBinarySize(Bytes)": best_size["BinarySize(Bytes)"],
                "BestCompileTime(s)": best_compile["CompileTime(s)"],
            }
        )

    k = max(1, args.top_k)
    best_runtime_cfgs = _top_k(agg_rows, "BestRuntime(s)", k)
    best_size_cfgs = _top_k(agg_rows, "MinBinarySize(Bytes)", k)
    best_compile_cfgs = _top_k(agg_rows, "BestCompileTime(s)", k)

    best_rows = []

    print(f"CSV: {csv_path}")
    print(f"Rows considered: {len(rows)}")
    print(f"Configs considered: {len(agg_rows)}")
    print("")

    if best_runtime_cfgs:
        print("Fastest TotalRuntime(s):")
        for i, cfg in enumerate(best_runtime_cfgs, start=1):
            r = cfg["BestRuntimeRow"]
            print(f"#{i} { _fmt_row(r) }")
            best_rows.append(("Fastest TotalRuntime(s)", i, r))
        print("")
    else:
        print("Fastest TotalRuntime(s): <none>")
        print("")

    if best_size_cfgs:
        print("Smallest BinarySize(Bytes):")
        for i, cfg in enumerate(best_size_cfgs, start=1):
            r = cfg["BestSizeRow"]
            print(f"#{i} { _fmt_row(r) }")
            best_rows.append(("Smallest BinarySize(Bytes)", i, r))
        print("")
    else:
        print("Smallest BinarySize(Bytes): <none>")
        print("")

    if best_compile_cfgs:
        print("Shortest CompileTime(s):")
        for i, cfg in enumerate(best_compile_cfgs, start=1):
            r = cfg["BestCompileRow"]
            print(f"#{i} { _fmt_row(r) }")
            best_rows.append(("Shortest CompileTime(s)", i, r))
        print("")
    else:
        print("Shortest CompileTime(s): <none>")
        print("")

    if best_rows:
        _write_summary_csv(args.out, csv_path, best_rows)
        print(f"Wrote: {args.out}")


if __name__ == "__main__":
    main()
