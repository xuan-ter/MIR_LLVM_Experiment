import argparse
import csv
import math
import os
from typing import Dict, List, Optional, Sequence, Tuple

import matplotlib.pyplot as plt

try:
    import pandas as pd

    HAVE_PANDAS = True
except Exception:
    HAVE_PANDAS = False


def _clean_pass_name(x: object) -> str:
    if x is None:
        return "None"
    s = str(x).strip()
    if s == "" or s.lower() in {"none", "baseline", "nan", "n/a", "na"}:
        return "None"
    if s.lower() == "all":
        return "All"
    return s


def _read_float(r: Dict[str, str], key: str) -> Optional[float]:
    try:
        s = str(r.get(key, "")).strip()
        if s == "" or s.lower() == "nan":
            return None
        return float(s)
    except Exception:
        return None


def _mean(xs: Sequence[float]) -> float:
    if not xs:
        return float("nan")
    return float(sum(xs) / len(xs))


def _load_groups(*, experiment_csv: str, metric_col: str) -> Dict[Tuple[str, str], List[float]]:
    groups: Dict[Tuple[str, str], List[float]] = {}
    with open(experiment_csv, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            status = str(r.get("Status", "")).strip()
            if status and status != "Success":
                continue
            y = _read_float(r, metric_col)
            if y is None or not (y > 0.0):
                continue
            mir_p = _clean_pass_name(r.get("MIR_Pass"))
            llvm_p = _clean_pass_name(r.get("LLVM_Pass"))
            groups.setdefault((mir_p, llvm_p), []).append(math.log(y))
    return groups


def _compute_pairwise_deltas(
    *,
    groups: Dict[Tuple[str, str], List[float]],
) -> List[Dict[str, object]]:
    z00 = groups.get(("None", "None"), [])
    if not z00:
        return []
    base_mean = _mean(z00)

    mir_list = sorted({m for (m, _) in groups.keys() if m not in {"None", "All"}})
    llvm_list = sorted({l for (_, l) in groups.keys() if l not in {"None", "All"}})

    rows: List[Dict[str, object]] = []
    for m in mir_list:
        z10 = groups.get((m, "None"), [])
        if not z10:
            mu10 = base_mean
        else:
            mu10 = _mean(z10)
        for l in llvm_list:
            z01 = groups.get(("None", l), [])
            z11 = groups.get((m, l), [])
            if not z01 or not z11:
                continue
            mu01 = _mean(z01)
            mu11 = _mean(z11)
            delta = (mu01 - mu11) - (base_mean - mu10)
            if not (delta == delta):
                continue
            rows.append({"mir_pass": m, "llvm_pass": l, "delta": float(delta)})
    return rows


def _strength_from_delta(delta: float, strength: str) -> float:
    if strength == "rel":
        return abs(math.exp(delta) - 1.0)
    return abs(delta)


def _workload_csvs(benchmark_dir: str) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    for name in sorted(os.listdir(benchmark_dir)):
        if not name.lower().endswith(".csv"):
            continue
        p = os.path.join(benchmark_dir, name)
        if os.path.isfile(p):
            out.append((os.path.splitext(name)[0], p))
    return out


def _build_share_table(
    *,
    benchmark_dir: str,
    metric_col: str,
    strength: str,
) -> Tuple[Dict[str, Dict[str, float]], Dict[str, float]]:
    mass_by_workload_mir: Dict[str, Dict[str, float]] = {}
    total_by_workload: Dict[str, float] = {}
    for workload, csv_path in _workload_csvs(benchmark_dir):
        groups = _load_groups(experiment_csv=csv_path, metric_col=metric_col)
        rows = _compute_pairwise_deltas(groups=groups)
        if not rows:
            continue
        for r in rows:
            m = str(r.get("mir_pass", "")).strip()
            d = float(r.get("delta", 0.0))
            s = _strength_from_delta(d, strength)
            if not (s > 0.0):
                continue
            mass_by_workload_mir.setdefault(workload, {})
            mass_by_workload_mir[workload][m] = mass_by_workload_mir[workload].get(m, 0.0) + s
            total_by_workload[workload] = total_by_workload.get(workload, 0.0) + s
    return mass_by_workload_mir, total_by_workload


def _to_matrix(
    *,
    shares_by_workload_mir: Dict[str, Dict[str, float]],
    total_by_workload: Dict[str, float],
    top_k: int,
) -> Tuple[List[str], List[str], List[List[float]]]:
    all_mirs: Dict[str, float] = {}
    for w, ms in shares_by_workload_mir.items():
        for m, mass in ms.items():
            all_mirs[m] = all_mirs.get(m, 0.0) + float(mass)
    top_mirs = [m for (m, _) in sorted(all_mirs.items(), key=lambda kv: kv[1], reverse=True)[: max(1, int(top_k))]]

    workloads = sorted(shares_by_workload_mir.keys())
    cols = list(top_mirs) + ["Other"]
    H: List[List[float]] = []
    for w in workloads:
        tot = float(total_by_workload.get(w, 0.0))
        row: List[float] = []
        other = 0.0
        for m in top_mirs:
            v = float(shares_by_workload_mir.get(w, {}).get(m, 0.0))
            row.append(v / tot if tot > 0 else 0.0)
        for m, v in shares_by_workload_mir.get(w, {}).items():
            if m not in set(top_mirs):
                other += float(v)
        row.append(other / tot if tot > 0 else 0.0)
        H.append(row)

    max_share_by_row = [(workloads[i], max(H[i]) if H[i] else 0.0) for i in range(len(workloads))]
    row_order = [w for (w, _) in sorted(max_share_by_row, key=lambda kv: kv[1], reverse=True)]
    order_idx = {w: i for i, w in enumerate(workloads)}
    H = [H[order_idx[w]] for w in row_order]
    workloads = row_order

    col_sums = [(j, sum(row[j] for row in H)) for j in range(len(cols))]
    other_idx = cols.index("Other")
    col_order_idx = [j for (j, _) in sorted(col_sums, key=lambda kv: kv[1], reverse=True) if j != other_idx] + [other_idx]
    cols = [cols[j] for j in col_order_idx]
    H = [[row[j] for j in col_order_idx] for row in H]

    return workloads, cols, H


def plot_heatmap(
    *,
    workloads: List[str],
    mir_cols: List[str],
    H: List[List[float]],
    out_pdf: str,
    out_png: str,
    title: str,
    annot_threshold: float,
    font_scale: float,
    annot_scale: float,
    height_scale: float,
) -> None:
    if not workloads or not mir_cols or not H:
        return
    s = float(font_scale)
    a_s = float(annot_scale)
    hs = float(height_scale)
    fig_w = max(10.0, (0.85 * len(mir_cols)) * (0.85 + 0.15 * s))
    fig_h = max(5.0, (0.65 * len(workloads)) * (0.85 + 0.15 * s) * hs)
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    im = ax.imshow(H, aspect="auto", vmin=0.0, vmax=1.0, cmap="viridis", interpolation="nearest")

    ax.set_xticks(range(len(mir_cols)))
    ax.set_xticklabels(mir_cols, rotation=45, ha="right", fontsize=12 * s)
    ax.set_yticks(range(len(workloads)))
    ax.set_yticklabels(workloads, fontsize=12 * s)
    ax.set_xlabel("MIR pass", fontsize=14 * s)
    ax.set_ylabel("Workload", fontsize=14 * s)
    ax.set_title(title, fontsize=16 * s)

    thr = float(annot_threshold)
    for i in range(len(workloads)):
        for j in range(len(mir_cols)):
            v = float(H[i][j])
            if v >= thr and (v > 0.0 or thr > 0.0):
                r, g, b, _a = im.cmap(im.norm(v))
                lum = 0.299 * r + 0.587 * g + 0.114 * b
                fg = "black" if lum > 0.62 else "white"
                bg = (1.0, 1.0, 1.0, 0.45) if fg == "black" else (0.0, 0.0, 0.0, 0.28)
                ax.text(
                    j,
                    i,
                    f"{v:.2f}",
                    ha="center",
                    va="center",
                    fontsize=11 * a_s,
                    color=fg,
                    bbox={"boxstyle": "round,pad=0.15", "facecolor": bg, "edgecolor": "none"},
                )

    cbar = fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02)
    cbar.set_label("Share of total |Δ| mass within workload", fontsize=12 * s)
    cbar.ax.tick_params(labelsize=11 * s)

    fig.tight_layout()
    os.makedirs(os.path.dirname(out_pdf), exist_ok=True)
    fig.savefig(out_pdf, bbox_inches="tight")
    fig.savefig(out_png, dpi=450, bbox_inches="tight")
    plt.close(fig)


def plot_table(
    *,
    workloads: List[str],
    mir_cols: List[str],
    H: List[List[float]],
    out_pdf: str,
    out_png: str,
    title: str,
    font_scale: float,
    height_scale: float,
) -> None:
    if not workloads or not mir_cols or not H:
        return

    s = float(font_scale)
    hs = float(height_scale)
    n_rows = len(workloads)
    n_cols = len(mir_cols)

    fig_w = max(10.0, 1.25 * n_cols * (0.85 + 0.15 * s))
    fig_h = max(4.0, (0.62 * n_rows + 1.8) * (0.85 + 0.15 * s) * hs)
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    ax.axis("off")

    cmap = plt.get_cmap("viridis")
    cell_text = [[f"{float(v):.2f}" for v in row] for row in H]
    table = ax.table(
        cellText=cell_text,
        rowLabels=workloads,
        colLabels=mir_cols,
        cellLoc="center",
        loc="center",
    )

    table.auto_set_font_size(False)
    body_fs = 11.0 * s
    header_fs = 12.5 * s
    rowlabel_fs = 12.0 * s

    for (r, c), cell in table.get_celld().items():
        if r == 0 and c >= 0:
            cell.set_text_props(fontsize=header_fs, fontweight="bold", color="#111111")
            cell.set_facecolor((0.97, 0.97, 0.97, 1.0))
            cell.set_edgecolor((0.2, 0.2, 0.2, 1.0))
            cell.set_linewidth(0.8)
            continue
        if c == -1 and r >= 1:
            cell.set_text_props(fontsize=rowlabel_fs, fontweight="bold", color="#111111")
            cell.set_facecolor((0.98, 0.98, 0.98, 1.0))
            cell.set_edgecolor((0.2, 0.2, 0.2, 1.0))
            cell.set_linewidth(0.8)
            continue
        if r >= 1 and c >= 0:
            try:
                v = float(H[r - 1][c])
            except Exception:
                v = 0.0
            rr, gg, bb, _aa = cmap(min(1.0, max(0.0, v)))
            lum = 0.299 * rr + 0.587 * gg + 0.114 * bb
            fg = "#111111" if lum > 0.62 else "#ffffff"
            cell.set_text_props(fontsize=body_fs, color=fg)
            cell.set_facecolor((rr, gg, bb, 1.0))
            cell.set_edgecolor((1.0, 1.0, 1.0, 0.65))
            cell.set_linewidth(0.6)

    table.scale(1.0, 1.35 * (0.85 + 0.15 * s))
    fig.suptitle(title, fontsize=16.0 * s, fontweight="bold", y=0.98)

    fig.tight_layout(rect=[0, 0, 1, 0.965])
    os.makedirs(os.path.dirname(out_pdf), exist_ok=True)
    fig.savefig(out_pdf, bbox_inches="tight")
    fig.savefig(out_png, dpi=450, bbox_inches="tight")
    plt.close(fig)

    table_csv_path = out_png.replace(".png", "_table.csv")
    with open(table_csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["workload"] + mir_cols)
        for i, row in enumerate(H):
            w.writerow([workloads[i]] + [f"{float(v):.2f}" for v in row])


def write_summary_csv(
    *,
    workloads: List[str],
    mir_cols: List[str],
    H: List[List[float]],
    out_csv: str,
) -> None:
    os.makedirs(os.path.dirname(out_csv), exist_ok=True)
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["workload", "top_mir_pass", "top_mir_share", "other_share"])
        for i, wl in enumerate(workloads):
            row = H[i]
            if not row:
                continue
            other_share = 0.0
            if "Other" in mir_cols:
                other_share = float(row[mir_cols.index("Other")])
            cand = [(k, float(row[k])) for k in range(len(row)) if mir_cols[k] != "Other"]
            if not cand:
                w.writerow([wl, "Other", "0.000000", f"{other_share:.6f}"])
                continue
            j, v = max(cand, key=lambda kv: kv[1])
            w.writerow([wl, mir_cols[j], f"{v:.6f}", f"{other_share:.6f}"])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--benchmark-dir", default=r"d:\MIR_LLVM\mir_llvm\benchmark_results")
    ap.add_argument("--out-dir", default=r"d:\MIR_LLVM\mir_llvm\benchmark_results\analysis")
    ap.add_argument("--metric-col", default="TotalRuntime(s)")
    ap.add_argument("--strength", choices=["delta", "rel"], default="delta")
    ap.add_argument("--top-k", type=int, default=10)
    ap.add_argument("--annot-threshold", type=float, default=0.0)
    ap.add_argument("--title", default="MIR-pass dominance across workloads")
    ap.add_argument("--font-scale", type=float, default=1.0)
    ap.add_argument("--annot-scale", type=float, default=1.0)
    ap.add_argument("--height-scale", type=float, default=1.0)
    ap.add_argument("--render", choices=["heatmap", "table"], default="heatmap")
    args = ap.parse_args()

    benchmark_dir = os.path.abspath(str(args.benchmark_dir))
    out_dir = os.path.abspath(str(args.out_dir))
    metric_col = str(args.metric_col)
    strength = str(args.strength)
    top_k = int(args.top_k)
    annot_threshold = float(args.annot_threshold)
    title = str(args.title)
    font_scale = float(args.font_scale)
    annot_scale = float(args.annot_scale)
    height_scale = float(args.height_scale)
    render = str(args.render)

    mass_by_workload_mir, total_by_workload = _build_share_table(
        benchmark_dir=benchmark_dir, metric_col=metric_col, strength=strength
    )
    workloads, mir_cols, H = _to_matrix(
        shares_by_workload_mir=mass_by_workload_mir, total_by_workload=total_by_workload, top_k=top_k
    )

    out_pdf = os.path.join(out_dir, f"mir_pass_dominance_heatmap_{metric_col.replace('/', '_')}_{strength}_top{top_k}.pdf")
    out_png = os.path.join(out_dir, f"mir_pass_dominance_heatmap_{metric_col.replace('/', '_')}_{strength}_top{top_k}.png")
    out_csv = os.path.join(out_dir, f"mir_pass_dominance_summary_{metric_col.replace('/', '_')}_{strength}_top{top_k}.csv")

    if render == "table":
        plot_table(
            workloads=workloads,
            mir_cols=mir_cols,
            H=H,
            out_pdf=out_pdf,
            out_png=out_png,
            title=title,
            font_scale=font_scale,
            height_scale=height_scale,
        )
    else:
        plot_heatmap(
            workloads=workloads,
            mir_cols=mir_cols,
            H=H,
            out_pdf=out_pdf,
            out_png=out_png,
            title=title,
            annot_threshold=annot_threshold,
            font_scale=font_scale,
            annot_scale=annot_scale,
            height_scale=height_scale,
        )
    write_summary_csv(workloads=workloads, mir_cols=mir_cols, H=H, out_csv=out_csv)

    if HAVE_PANDAS and os.path.exists(out_csv):
        try:
            df = pd.read_csv(out_csv)
            if not df.empty:
                print(df.sort_values("top_mir_share", ascending=False).to_string(index=False))
        except Exception:
            pass
    print(out_pdf)


if __name__ == "__main__":
    main()
