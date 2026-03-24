import argparse
import csv
import math
import os
import re
from collections import Counter, defaultdict


def _is_success(status):
    s = (status or "").strip().lower()
    return s in {"success", "ok", "pass", "passed", "true", "1"}


def _to_float(x):
    try:
        return float(x)
    except Exception:
        return None


def _read_csv_rows(path):
    with open(path, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _pick_best_row(rows, metric_key):
    best = None
    best_val = None
    for r in rows:
        v = _to_float(r.get(metric_key))
        if v is None:
            continue
        if best is None or v < best_val:
            best = r
            best_val = v
    return best


def _aggregate_by_configname(rows):
    by_cfg = defaultdict(list)
    for r in rows:
        cfg = (r.get("ConfigName") or "").strip()
        if not cfg:
            continue
        by_cfg[cfg].append(r)

    agg = []
    for cfg, rs in by_cfg.items():
        best_runtime = _pick_best_row(rs, "TotalRuntime(s)")
        best_size = _pick_best_row(rs, "BinarySize(Bytes)")
        best_compile = _pick_best_row(rs, "CompileTime(s)")
        if not (best_runtime and best_size and best_compile):
            continue
        agg.append(
            {
                "ConfigName": cfg,
                "BestRuntime(s)": _to_float(best_runtime.get("TotalRuntime(s)")),
                "BestSize(Bytes)": _to_float(best_size.get("BinarySize(Bytes)")),
                "BestCompile(s)": _to_float(best_compile.get("CompileTime(s)")),
                "BestRuntimeRow": best_runtime,
                "BestSizeRow": best_size,
                "BestCompileRow": best_compile,
            }
        )
    return agg


def _pick_top_rows(agg_rows, metric_key, row_key, top_k):
    rows = [r for r in agg_rows if isinstance(r.get(metric_key), (int, float))]
    rows.sort(key=lambda r: r[metric_key])
    picked = []
    for r in rows[: max(0, top_k)]:
        picked.append(r[row_key])
    return picked


def _merge_topk_summaries(exp_to_source_csv, top_k):
    out_rows = []
    for exp, source_csv in exp_to_source_csv.items():
        if not os.path.exists(source_csv):
            raise SystemExit(f"CSV not found: {source_csv}")
        raw = [r for r in _read_csv_rows(source_csv) if _is_success(r.get("Status"))]
        agg = _aggregate_by_configname(raw)

        metric_specs = [
            ("Fastest TotalRuntime(s)", "BestRuntime(s)", "BestRuntimeRow"),
            ("Smallest BinarySize(Bytes)", "BestSize(Bytes)", "BestSizeRow"),
            ("Shortest CompileTime(s)", "BestCompile(s)", "BestCompileRow"),
        ]

        for criterion, metric_key, row_key in metric_specs:
            top_rows = _pick_top_rows(agg, metric_key, row_key, top_k)
            for rank, r in enumerate(top_rows, 1):
                out_rows.append(
                    {
                        "Experiment": exp,
                        "Criterion": criterion,
                        "Rank": rank,
                        "SourceCSV": source_csv,
                        "ConfigName": r.get("ConfigName"),
                        "RunID": r.get("RunID"),
                        "LLVM_Pass": r.get("LLVM_Pass"),
                        "MIR_Pass": r.get("MIR_Pass"),
                        "BinarySize(Bytes)": r.get("BinarySize(Bytes)"),
                        "NsPerIter": r.get("NsPerIter", ""),
                        "MBps": r.get("MBps", ""),
                        "TotalRuntime(s)": r.get("TotalRuntime(s)"),
                        "CompileTime(s)": r.get("CompileTime(s)"),
                        "Status": r.get("Status"),
                    }
                )
    return out_rows


def _write_best_configs_summary_all(out_path, rows):
    fieldnames = [
        "Experiment",
        "Criterion",
        "Rank",
        "SourceCSV",
        "ConfigName",
        "RunID",
        "LLVM_Pass",
        "MIR_Pass",
        "BinarySize(Bytes)",
        "NsPerIter",
        "MBps",
        "TotalRuntime(s)",
        "CompileTime(s)",
        "Status",
    ]
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _compute_pass_frequency(exp_to_source_csv, topk_rows, top_k):
    base_total = 0
    base_counts = {
        "LLVM": Counter(),
        "MIR": Counter(),
    }

    for source_csv in exp_to_source_csv.values():
        for r in _read_csv_rows(source_csv):
            if not _is_success(r.get("Status")):
                continue
            base_total += 1
            lp = (r.get("LLVM_Pass") or "").strip()
            mp = (r.get("MIR_Pass") or "").strip()
            if lp:
                base_counts["LLVM"][lp] += 1
            if mp:
                base_counts["MIR"][mp] += 1

    criteria = sorted({r["Criterion"] for r in topk_rows})
    top_total_by_criterion = Counter()
    top_counts = defaultdict(int)
    top_weights = defaultdict(int)
    cover_exps = defaultdict(set)

    for r in topk_rows:
        criterion = r["Criterion"]
        exp = r["Experiment"]
        rank = int(r["Rank"])
        weight = max(1, top_k - rank + 1)
        top_total_by_criterion[criterion] += 1

        lp = (r.get("LLVM_Pass") or "").strip()
        mp = (r.get("MIR_Pass") or "").strip()
        if lp:
            key = ("LLVM", lp, criterion)
            top_counts[key] += 1
            top_weights[key] += weight
            cover_exps[key].add(exp)
        if mp:
            key = ("MIR", mp, criterion)
            top_counts[key] += 1
            top_weights[key] += weight
            cover_exps[key].add(exp)

    out = []
    for criterion in criteria:
        top_total = top_total_by_criterion[criterion]
        if top_total <= 0:
            continue
        for pass_type in ("LLVM", "MIR"):
            for pass_name, base_cnt in base_counts[pass_type].items():
                key = (pass_type, pass_name, criterion)
                top_cnt = top_counts.get(key, 0)
                if top_cnt <= 0:
                    continue
                top_share = top_cnt / top_total if top_total else 0.0
                base_share = base_cnt / base_total if base_total else 0.0
                lift = (top_share / base_share) if base_share > 0 else math.inf
                out.append(
                    {
                        "PassType": pass_type,
                        "PassName": pass_name,
                        "Criterion": criterion,
                        "TopCount": top_cnt,
                        "TopWeight": top_weights.get(key, 0),
                        "TopShare": f"{top_share:.6f}",
                        "BaseCount": base_cnt,
                        "BaseShare": f"{base_share:.6f}",
                        "Lift": f"{lift:.6f}" if math.isfinite(lift) else "inf",
                        "Cover": len(cover_exps.get(key, set())),
                        "Experiments": ";".join(sorted(cover_exps.get(key, set()))),
                    }
                )

    out.sort(key=lambda r: (r["Criterion"], r["PassType"], -float(r["Lift"]) if r["Lift"] != "inf" else -1e99, -int(r["Cover"]), -int(r["TopCount"]), r["PassName"]))
    return out


def _write_pass_frequency_csv(out_path, rows):
    fieldnames = [
        "PassType",
        "PassName",
        "Criterion",
        "TopCount",
        "TopWeight",
        "TopShare",
        "BaseCount",
        "BaseShare",
        "Lift",
        "Cover",
        "Experiments",
    ]
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _safe_slug(s):
    s = (s or "").strip()
    if not s:
        return "unknown"
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", s)
    s = re.sub(r"_+", "_", s)
    return s.strip("_") or "unknown"


def _to_num_or_inf(v):
    if v is None:
        return None
    s = str(v).strip().lower()
    if s in {"inf", "+inf", "infinity", "+infinity"}:
        return float("inf")
    try:
        return float(s)
    except Exception:
        return None


def _plot_pass_frequency(freq_rows, out_dir, top_n, sort_by, min_cover, img_format):
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:
        raise SystemExit(f"matplotlib is required for plotting: {e}")

    os.makedirs(out_dir, exist_ok=True)

    criteria = sorted({r.get("Criterion") for r in freq_rows if r.get("Criterion")})
    pass_types = sorted({r.get("PassType") for r in freq_rows if r.get("PassType")})

    def sort_value(r):
        if sort_by == "lift":
            return _to_num_or_inf(r.get("Lift"))
        if sort_by == "topcount":
            return _to_num_or_inf(r.get("TopCount"))
        if sort_by == "topweight":
            return _to_num_or_inf(r.get("TopWeight"))
        return _to_num_or_inf(r.get("Lift"))

    for criterion in criteria:
        for pass_type in pass_types:
            rs = [
                r
                for r in freq_rows
                if r.get("Criterion") == criterion
                and r.get("PassType") == pass_type
                and int(r.get("Cover") or 0) >= min_cover
            ]
            rs = [r for r in rs if sort_value(r) is not None]
            rs.sort(key=lambda r: (sort_value(r), int(r.get("Cover") or 0), int(r.get("TopCount") or 0)), reverse=True)
            rs = rs[: max(0, top_n)]
            if not rs:
                continue

            labels = [r.get("PassName") or "" for r in rs][::-1]
            values = [sort_value(r) for r in rs][::-1]
            covers = [int(r.get("Cover") or 0) for r in rs][::-1]

            fig_h = max(4.5, 0.35 * len(labels) + 2.0)
            fig, ax = plt.subplots(figsize=(12, fig_h))
            ax.barh(labels, values)

            ax.set_title(f"{pass_type} / {criterion} (Top {len(rs)} by {sort_by}, cover>={min_cover})")
            ax.set_xlabel(sort_by)
            ax.set_ylabel("Pass")
            ax.grid(axis="x", linestyle=":", alpha=0.5)

            for i, (v, c) in enumerate(zip(values, covers)):
                txt = f"cover={c}"
                try:
                    ax.text(v, i, f" {txt}", va="center", fontsize=9)
                except Exception:
                    pass

            fname = f"passfreq_{_safe_slug(criterion)}_{_safe_slug(pass_type)}_{_safe_slug(sort_by)}_cover{min_cover}.{img_format}"
            out_path = os.path.join(out_dir, fname)
            plt.tight_layout()
            plt.savefig(out_path, dpi=200)
            plt.close(fig)

    return out_dir


def _plot_pass_frequency_paper(freq_rows, out_dir, top_n, sort_by, min_cover, img_format, out_name):
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:
        raise SystemExit(f"matplotlib is required for plotting: {e}")

    os.makedirs(out_dir, exist_ok=True)

    criteria_order = [
        "Fastest TotalRuntime(s)",
        "Shortest CompileTime(s)",
        "Smallest BinarySize(Bytes)",
    ]
    criteria = [c for c in criteria_order if any(r.get("Criterion") == c for r in freq_rows)]
    pass_types_order = ["LLVM", "MIR"]
    pass_types = [pt for pt in pass_types_order if any(r.get("PassType") == pt for r in freq_rows)]

    def sort_value(r):
        if sort_by == "lift":
            return _to_num_or_inf(r.get("Lift"))
        if sort_by == "topcount":
            return _to_num_or_inf(r.get("TopCount"))
        if sort_by == "topweight":
            return _to_num_or_inf(r.get("TopWeight"))
        return _to_num_or_inf(r.get("Lift"))

    nrows = max(1, len(criteria))
    ncols = max(1, len(pass_types))
    fig, axes = plt.subplots(
        nrows=nrows,
        ncols=ncols,
        figsize=(16, max(7.5, 3.8 * nrows)),
        constrained_layout=True,
    )
    if nrows == 1 and ncols == 1:
        axes = [[axes]]
    elif nrows == 1:
        axes = [list(axes)]
    elif ncols == 1:
        axes = [[ax] for ax in axes]

    def short_criterion(c):
        if c == "Fastest TotalRuntime(s)":
            return "Runtime"
        if c == "Shortest CompileTime(s)":
            return "Compile"
        if c == "Smallest BinarySize(Bytes)":
            return "Size"
        return c

    def x_label():
        if sort_by == "lift":
            return "Lift (TopK share / Base share)"
        if sort_by == "topcount":
            return "TopCount"
        if sort_by == "topweight":
            return "TopWeight"
        return sort_by

    for i, criterion in enumerate(criteria):
        for j, pass_type in enumerate(pass_types):
            ax = axes[i][j]
            rs = [
                r
                for r in freq_rows
                if r.get("Criterion") == criterion
                and r.get("PassType") == pass_type
                and int(r.get("Cover") or 0) >= min_cover
            ]
            rs = [r for r in rs if sort_value(r) is not None]
            rs.sort(
                key=lambda r: (
                    sort_value(r),
                    int(r.get("Cover") or 0),
                    int(r.get("TopCount") or 0),
                    r.get("PassName") or "",
                ),
                reverse=True,
            )
            rs = rs[: max(0, top_n)]
            if not rs:
                ax.axis("off")
                continue

            labels = [r.get("PassName") or "" for r in rs][::-1]
            values = [sort_value(r) for r in rs][::-1]
            covers = [int(r.get("Cover") or 0) for r in rs][::-1]

            cmap = plt.get_cmap("viridis")
            max_cover = max(covers) if covers else 1
            colors = [cmap((c - 1) / max(1, max_cover - 1)) for c in covers]
            ax.barh(labels, values, color=colors)

            ax.set_title(f"{short_criterion(criterion)} / {pass_type}", fontsize=12)
            ax.grid(axis="x", linestyle=":", alpha=0.35)
            ax.tick_params(axis="y", labelsize=9)
            ax.tick_params(axis="x", labelsize=9)
            if i == nrows - 1:
                ax.set_xlabel(x_label(), fontsize=10)

            for idx, (v, c) in enumerate(zip(values, covers)):
                txt = f"{c}"
                try:
                    ax.text(v, idx, f"  cover={txt}", va="center", fontsize=8, alpha=0.85)
                except Exception:
                    pass

    title = f"Pass enrichment across experiments (top_n={top_n}, sort={sort_by}, min_cover={min_cover})"
    fig.suptitle(title, fontsize=14)

    out_name = out_name or f"pass_frequency_paper_top{top_n}_{_safe_slug(sort_by)}_cover{min_cover}.{img_format}"
    out_path = os.path.join(out_dir, out_name)
    plt.savefig(out_path, dpi=300)
    plt.close(fig)
    return out_path


def _infer_sources_from_existing_summary(summary_all_csv):
    if not os.path.exists(summary_all_csv):
        raise SystemExit(
            f"Missing {summary_all_csv}. Provide --sources or generate the summary first."
        )
    rows = _read_csv_rows(summary_all_csv)
    exp_to_source = {}
    for r in rows:
        exp = (r.get("Experiment") or "").strip()
        src = (r.get("SourceCSV") or "").strip()
        if exp and src and exp not in exp_to_source:
            exp_to_source[exp] = src
    if not exp_to_source:
        raise SystemExit(f"Could not infer sources from: {summary_all_csv}")
    return exp_to_source


def _parse_sources_arg(items):
    out = {}
    for it in items:
        if "=" not in it:
            raise SystemExit(f"Invalid --sources item: {it} (expected name=path)")
        name, path = it.split("=", 1)
        name = name.strip()
        path = path.strip().strip('"')
        if not name or not path:
            raise SystemExit(f"Invalid --sources item: {it} (expected name=path)")
        out[name] = path
    return out


def main():
    p = argparse.ArgumentParser(
        description="Generate best_configs_summary_all.csv (top-k) and pass_frequency_all.csv (count/cover/lift)."
    )
    p.add_argument("--top-k", type=int, default=10, help="Top K per experiment per criterion")
    p.add_argument(
        "--summary-all",
        default=r"d:\MIR_LLVM\mir_-llvm\best_configs_summary_all.csv",
        help="Path to write merged top-k summary CSV",
    )
    p.add_argument(
        "--pass-frequency-out",
        default=r"d:\MIR_LLVM\mir_-llvm\pass_frequency_all.csv",
        help="Path to write pass frequency CSV",
    )
    p.add_argument(
        "--sources",
        nargs="*",
        default=None,
        help='Optional list like hyper="...\\experiment_results.csv" regex="...\\experiment_results.csv"',
    )
    p.add_argument("--plot", action="store_true", help="Export plots for pass_frequency_all.csv")
    p.add_argument(
        "--plot-dir",
        default=r"d:\MIR_LLVM\mir_-llvm\pass_frequency_plots",
        help="Directory to write plots",
    )
    p.add_argument("--plot-top-n", type=int, default=20, help="Top N passes to plot per group")
    p.add_argument(
        "--plot-sort",
        default="lift",
        choices=["lift", "topcount", "topweight"],
        help="Sort key for selecting passes to plot",
    )
    p.add_argument("--plot-min-cover", type=int, default=1, help="Minimum Cover to include in plots")
    p.add_argument("--plot-format", default="png", choices=["png", "svg"], help="Image format")
    p.add_argument("--plot-paper", action="store_true", help="Export a single paper-style multi-panel figure")
    p.add_argument(
        "--plot-paper-name",
        default="pass_frequency_paper.png",
        help="Output filename for the paper-style figure (inside --plot-dir)",
    )
    args = p.parse_args()

    if args.sources is None:
        exp_to_source = _infer_sources_from_existing_summary(args.summary_all)
        exp_to_source.update(
            {
                "hyper": r"d:\MIR_LLVM\mir_-llvm\hyper\mir_llvm_hybrid_py\20260319_180449\experiment_results.csv",
                "tokio": r"d:\MIR_LLVM\mir_-llvm\tokio\mir_llvm_hybrid_py\20260315_201152\experiment_results.csv",
            }
        )
    else:
        exp_to_source = _parse_sources_arg(args.sources)

    topk_rows = _merge_topk_summaries(exp_to_source, args.top_k)
    _write_best_configs_summary_all(args.summary_all, topk_rows)

    freq_rows = _compute_pass_frequency(exp_to_source, topk_rows, args.top_k)
    _write_pass_frequency_csv(args.pass_frequency_out, freq_rows)

    print(f"Wrote: {args.summary_all}")
    print(f"Wrote: {args.pass_frequency_out}")
    if args.plot:
        out_dir = _plot_pass_frequency(
            freq_rows,
            args.plot_dir,
            args.plot_top_n,
            args.plot_sort,
            args.plot_min_cover,
            args.plot_format,
        )
        print(f"Wrote plots to: {out_dir}")
    if args.plot_paper:
        out_path = _plot_pass_frequency_paper(
            freq_rows,
            args.plot_dir,
            args.plot_top_n,
            args.plot_sort,
            args.plot_min_cover,
            args.plot_format,
            args.plot_paper_name,
        )
        print(f"Wrote paper figure to: {out_path}")


if __name__ == "__main__":
    main()
