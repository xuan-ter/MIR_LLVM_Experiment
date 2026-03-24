import argparse
import csv
import math
import os
import runpy
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

import matplotlib.pyplot as plt

try:
    import pandas as pd

    HAVE_PANDAS = True
except Exception:
    HAVE_PANDAS = False

try:
    import seaborn as sns

    HAVE_SEABORN = True
except Exception:
    HAVE_SEABORN = False

try:
    import networkx as nx

    HAVE_NETWORKX = True
except Exception:
    HAVE_NETWORKX = False


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_EXPERIMENT_CSV = r"d:\MIR_LLVM\mir_-llvm\regex\mir_llvm_hybrid_py\20260310_224816\experiment_results.csv"
DID_DIR = os.path.join(BASE_DIR, "did")
INTERACTION_RESULTS_CSV = os.path.join(DID_DIR, "interaction_results.csv")
COUPLING_PLOTS_DIR = os.path.join(DID_DIR, "coupling_plots")


def _clean_pass_name(value, *, is_mir: bool) -> str:
    if value is None:
        return "None"
    s = str(value).strip()
    if s == "" or s.lower() in {"none", "baseline", "nan"}:
        return "None"
    if is_mir and s == "N/A":
        return "None"
    return s


def _mean(xs: Sequence[float]) -> float:
    if not xs:
        return math.nan
    return sum(xs) / len(xs)


def _var(xs: Sequence[float], mean_x: float) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    s2 = sum((x - mean_x) ** 2 for x in xs) / (n - 1)
    if s2 != s2:
        return 0.0
    return max(0.0, s2)


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _two_sided_p_from_z(z: float) -> float:
    az = abs(z)
    return max(0.0, min(1.0, 2.0 * (1.0 - _norm_cdf(az))))


def _bh_fdr(p_values: Sequence[float]) -> List[float]:
    m = len(p_values)
    if m == 0:
        return []
    order = sorted(range(m), key=lambda i: (p_values[i], i))
    adj = [1.0] * m
    prev = 1.0
    for rank, _idx in enumerate(reversed(order), start=1):
        i = order[-rank]
        p = p_values[i]
        k = m - rank + 1
        val = (p * m) / k if k > 0 else 1.0
        if val > prev:
            val = prev
        prev = val
        adj[i] = min(1.0, max(0.0, val))
    return adj


def _trend(r: float, eps: float) -> str:
    if r != r:
        return "unknown"
    if r < 1.0 - eps:
        return "better"
    if r > 1.0 + eps:
        return "worse"
    return "neutral"


def _classify_pattern(*, y00: float, y10: float, y01: float, y11: float, delta: float, significant: bool) -> Tuple[str, str]:
    if not significant:
        return "independent", "线性/无显著交互"
    if any(v != v for v in [y00, y10, y01, y11, delta]):
        return "unknown", "未知"
    if y00 <= 0 or y10 <= 0 or y01 <= 0 or y11 <= 0:
        return "unknown", "未知"

    eps = 0.05
    eps2 = 0.03

    r10 = y10 / y00
    r01 = y01 / y00
    r11 = y11 / y00

    t10 = _trend(r10, eps)
    t01 = _trend(r01, eps)
    t11 = _trend(r11, eps)

    if delta > 0:
        if t01 == "worse" and t11 == "better":
            if r11 < 1.0 - eps2:
                return "recovery_to_gain_by_mir", "恢复效应→获益（MIR 修复并反超基线）"
            if r11 <= 1.0 + eps2:
                return "recovery_to_baseline_by_mir", "恢复效应→回归基线（MIR 抵消 LLVM 侧退化）"
            return "recovery_partial_by_mir", "恢复效应→部分恢复（仍差于基线但显著缓解）"
        if t10 == "worse" and t11 == "better":
            if r11 < 1.0 - eps2:
                return "recovery_to_gain_by_llvm", "恢复效应→获益（LLVM 修复并反超基线）"
            if r11 <= 1.0 + eps2:
                return "recovery_to_baseline_by_llvm", "恢复效应→回归基线（LLVM 抵消 MIR 侧退化）"
            return "recovery_partial_by_llvm", "恢复效应→部分恢复（仍差于基线但显著缓解）"
        if t10 == "better" and t01 == "better" and r11 < min(r10, r01) * (1.0 - eps2):
            return "synergy_amplification", "协同放大（双侧均改进且联合更超预期）"
        if t10 == "neutral" and t01 == "better" and r11 < r01 * (1.0 - eps2):
            return "gating_by_mir", "门控/解锁（MIR 使 LLVM 改进进一步生效）"
        if t01 == "neutral" and t10 == "better" and r11 < r10 * (1.0 - eps2):
            return "gating_by_llvm", "门控/解锁（LLVM 使 MIR 改进进一步生效）"
        if t10 == "worse" and t01 == "worse" and r11 <= 1.0 + eps2:
            return "mutual_mitigation", "相互缓解（单独更差，联合接近基线或更好）"
        if t11 == "better" and (t10 != "better" or t01 != "better"):
            return "combined_only_gain", "联合获益（单独不明显，联合显著变好）"
        return "positive_other", "正向交互（其它形态）"

    if delta < 0:
        if t10 == "better" and t01 == "better" and t11 == "worse":
            return "collapse_interference", "崩塌型负交互（单独改进，联合反而更差）"
        if (t10 == "better" or t01 == "better") and t11 == "worse":
            return "benefit_suppressed", "收益被抑制（单独改进，联合削弱或反转）"
        if t10 == "worse" and t01 == "worse" and t11 == "worse":
            return "harm_amplification", "危害放大（单独更差，联合更差且超预期）"
        return "negative_other", "负向交互（其它形态）"

    return "zero_delta", "Δ≈0（可加性）"


def compute_interaction_results(
    *,
    experiment_csv: str,
    metric_col: str,
    alpha: float,
) -> List[Dict[str, object]]:
    groups: Dict[Tuple[str, str], List[float]] = {}
    mir_passes = set()
    llvm_passes = set()

    with open(experiment_csv, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            status = str(r.get("Status", "")).strip()
            if status and status != "Success":
                continue

            try:
                y = float(str(r.get(metric_col, "")).strip())
            except Exception:
                continue
            if not (y > 0.0):
                continue

            llvm_p = _clean_pass_name(r.get("LLVM_Pass"), is_mir=False)
            mir_p = _clean_pass_name(r.get("MIR_Pass"), is_mir=True)

            mir_passes.add(mir_p)
            llvm_passes.add(llvm_p)

            key = (mir_p, llvm_p)
            groups.setdefault(key, []).append(math.log(y))

    mir_list = sorted(p for p in mir_passes if p not in {"None", "All"})
    llvm_list = sorted(p for p in llvm_passes if p not in {"None", "All"})

    z00 = groups.get(("None", "None"), [])
    if not z00:
        raise RuntimeError("baseline group (MIR=None, LLVM=None) not found")

    base_mean = _mean(z00)
    base_var = _var(z00, base_mean)
    base_n = len(z00)

    out_rows: List[Dict[str, object]] = []
    for m in mir_list:
        z10 = groups.get((m, "None"), [])
        if not z10:
            continue
        mean10 = _mean(z10)
        var10 = _var(z10, mean10)
        n10 = len(z10)

        for l in llvm_list:
            z01 = groups.get(("None", l), [])
            z11 = groups.get((m, l), [])
            if not z01 or not z11:
                continue

            mean01 = _mean(z01)
            var01 = _var(z01, mean01)
            n01 = len(z01)

            mean11 = _mean(z11)
            var11 = _var(z11, mean11)
            n11 = len(z11)

            delta = (mean01 - mean11) - (base_mean - mean10)

            se2 = 0.0
            if base_n > 0:
                se2 += base_var / base_n
            if n10 > 0:
                se2 += var10 / n10
            if n01 > 0:
                se2 += var01 / n01
            if n11 > 0:
                se2 += var11 / n11
            se = math.sqrt(se2) if se2 > 0 else 0.0
            z = (delta / se) if se > 0 else (math.inf if delta != 0 else 0.0)
            p = 0.0 if z == math.inf else _two_sided_p_from_z(z)
            ci_low = delta - 1.96 * se
            ci_high = delta + 1.96 * se

            out_rows.append(
                {
                    "mir_pass": m,
                    "llvm_pass": l,
                    "y00_mean": math.exp(base_mean),
                    "y10_mean": math.exp(mean10),
                    "y01_mean": math.exp(mean01),
                    "y11_mean": math.exp(mean11),
                    "delta": float(delta),
                    "ci_low": float(ci_low),
                    "ci_high": float(ci_high),
                    "p_value": float(p),
                }
            )

    pvals = [float(r["p_value"]) for r in out_rows]
    padj = _bh_fdr(pvals)
    for r, a in zip(out_rows, padj):
        r["p_adj"] = float(a)
        r["significant"] = bool(a <= alpha)
        y00 = float(r["y00_mean"])
        y10 = float(r["y10_mean"])
        y01 = float(r["y01_mean"])
        y11 = float(r["y11_mean"])
        y_pred = (y10 * y01 / y00) if y00 > 0 else math.nan
        r["y_pred_mean"] = float(y_pred) if y_pred == y_pred else math.nan
        r["ratio_y11_over_pred"] = float(y11 / y_pred) if (y_pred == y_pred and y_pred > 0) else math.nan
        r["ratio_y11_over_base"] = float(y11 / y00) if y00 > 0 else math.nan
        r["ratio_pred_over_base"] = float(y_pred / y00) if (y00 > 0 and y_pred == y_pred) else math.nan
        pat, pat_cn = _classify_pattern(
            y00=y00,
            y10=y10,
            y01=y01,
            y11=y11,
            delta=float(r["delta"]),
            significant=bool(r["significant"]),
        )
        r["pattern"] = pat
        r["pattern_cn"] = pat_cn

    out_rows.sort(key=lambda rr: (float(rr.get("p_adj", 1.0)), -abs(float(rr.get("delta", 0.0)))))
    return out_rows


def save_interaction_results_csv(rows: Sequence[Dict[str, object]], output_csv: str) -> None:
    os.makedirs(os.path.dirname(output_csv), exist_ok=True)
    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "mir_pass",
                "llvm_pass",
                "y00_mean",
                "y10_mean",
                "y01_mean",
                "y11_mean",
                "y_pred_mean",
                "ratio_y11_over_pred",
                "ratio_y11_over_base",
                "ratio_pred_over_base",
                "delta",
                "ci_low",
                "ci_high",
                "p_value",
                "p_adj",
                "significant",
                "pattern",
                "pattern_cn",
            ],
        )
        w.writeheader()
        for r in rows:
            w.writerow(r)


def _rows_from_interaction_csv(csv_path: str) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append(r)
    return rows


def _fbool(x: object) -> bool:
    return str(x).strip().lower() == "true"


def _ffloat(x: object) -> float:
    try:
        s = str(x).strip()
        if s == "" or s.lower() == "nan":
            return float("nan")
        return float(s)
    except Exception:
        return float("nan")


def plot_interaction_heatmap(interaction_csv: str, output_png: str, output_pdf: str) -> None:
    if HAVE_PANDAS and HAVE_SEABORN:
        df = pd.read_csv(interaction_csv)
        if df.empty:
            return
        pivot_delta = df.pivot(index="mir_pass", columns="llvm_pass", values="delta")
        plt.figure(figsize=(12, 10))
        sns.heatmap(pivot_delta, cmap="RdBu_r", center=0, annot=False)
        plt.title("Interaction Effect (Delta) Heatmap")
        plt.tight_layout()
        plt.savefig(output_png, bbox_inches="tight")
        plt.savefig(output_pdf, bbox_inches="tight")
        plt.close()
        return

    rows = _rows_from_interaction_csv(interaction_csv)
    mir_list = sorted({str(r.get("mir_pass", "")).strip() for r in rows if str(r.get("mir_pass", "")).strip()})
    llvm_list = sorted({str(r.get("llvm_pass", "")).strip() for r in rows if str(r.get("llvm_pass", "")).strip()})
    if not mir_list or not llvm_list:
        return
    mir_idx = {m: i for i, m in enumerate(mir_list)}
    llvm_idx = {l: j for j, l in enumerate(llvm_list)}
    mat = np.full((len(mir_list), len(llvm_list)), np.nan, dtype=float)
    for r in rows:
        m = str(r.get("mir_pass", "")).strip()
        l = str(r.get("llvm_pass", "")).strip()
        if m not in mir_idx or l not in llvm_idx:
            continue
        d = _ffloat(r.get("delta"))
        if d != d:
            continue
        mat[mir_idx[m], llvm_idx[l]] = d

    max_abs = float(np.nanmax(np.abs(mat))) if np.isfinite(mat).any() else 0.0
    if not (max_abs > 0):
        return
    from matplotlib.colors import TwoSlopeNorm

    masked = np.ma.array(mat, mask=np.isnan(mat))
    cmap = plt.get_cmap("RdBu_r").copy()
    cmap.set_bad(color="white")
    norm = TwoSlopeNorm(vmin=-max_abs, vcenter=0.0, vmax=max_abs)

    fig, ax = plt.subplots(figsize=(14, 10))
    im = ax.imshow(masked, cmap=cmap, norm=norm, aspect="auto", interpolation="nearest")
    ax.set_title("Interaction Effect (Delta) Heatmap")
    ax.set_xticks(range(len(llvm_list)))
    ax.set_yticks(range(len(mir_list)))
    ax.set_xticklabels(llvm_list, rotation=90, fontsize=6)
    ax.set_yticklabels(mir_list, fontsize=6)
    cbar = fig.colorbar(im, ax=ax, orientation="horizontal", pad=0.08, shrink=0.8)
    cbar.set_label("Interaction Delta (log scale)")
    cbar.ax.xaxis.set_label_position("bottom")
    cbar.ax.xaxis.set_ticks_position("bottom")
    fig.tight_layout()
    fig.savefig(output_png, bbox_inches="tight")
    fig.savefig(output_pdf, bbox_inches="tight")
    plt.close(fig)


def plot_top_interactions_forest(interaction_csv: str, output_png: str, output_pdf: str, top_k: int) -> None:
    rows = _rows_from_interaction_csv(interaction_csv)
    items = []
    for r in rows:
        if not _fbool(r.get("significant")):
            continue
        d = _ffloat(r.get("delta"))
        lo = _ffloat(r.get("ci_low"))
        hi = _ffloat(r.get("ci_high"))
        if any(v != v for v in [d, lo, hi]):
            continue
        label = f"{str(r.get('mir_pass', '')).strip()} + {str(r.get('llvm_pass', '')).strip()}"
        items.append((abs(d), d, lo, hi, label))
    items.sort(key=lambda t: (-t[0], t[4]))
    items = items[: max(0, int(top_k))]
    if not items:
        return

    ys = list(range(len(items)))
    deltas = [t[1] for t in items]
    xerr_low = [t[1] - t[2] for t in items]
    xerr_high = [t[3] - t[1] for t in items]
    labels = [t[4] for t in items]

    fig_h = max(10.0, 0.38 * len(items) + 2.0)
    plt.figure(figsize=(12, fig_h))
    plt.errorbar(
        x=deltas,
        y=ys,
        xerr=[xerr_low, xerr_high],
        fmt="o",
        capsize=4,
        markersize=4,
        elinewidth=1.2,
    )
    plt.yticks(ys, labels, fontsize=8)
    plt.axvline(x=0, color="r", linestyle="--", linewidth=1.2)
    plt.xlabel("Interaction Effect (Delta)")
    plt.title(f"Top Significant Interactions (Top {len(items)})")
    plt.tight_layout()
    plt.savefig(output_png, bbox_inches="tight")
    plt.savefig(output_pdf, bbox_inches="tight")
    plt.close()


def plot_filtered_heatmap(data: object, output_png: str, output_pdf: str) -> None:
    if HAVE_PANDAS and HAVE_SEABORN and HAVE_PANDAS and isinstance(data, pd.DataFrame):
        df = data
        sig_df = df[df["significant"] == True]
        if sig_df.empty:
            return

        relevant_mir = sig_df["mir_pass"].unique()
        relevant_llvm = sig_df["llvm_pass"].unique()

        pivot_delta = df.pivot(index="mir_pass", columns="llvm_pass", values="delta")
        pivot_sig = df.pivot(index="mir_pass", columns="llvm_pass", values="significant")

        pivot_delta = pivot_delta.loc[relevant_mir, relevant_llvm]
        pivot_sig = pivot_sig.loc[relevant_mir, relevant_llvm]

        mask = ~pivot_sig.fillna(False).astype(bool)

        fig, ax = plt.subplots(figsize=(20, 15))
        sns.heatmap(
            pivot_delta,
            mask=mask,
            center=0,
            cmap="RdBu_r",
            annot=False,
            cbar_kws={
                "label": "Interaction Delta (Significant Only)",
                "orientation": "vertical",
                "pad": 0.02,
                "shrink": 0.3,
                "aspect": 30,
            },
            square=True,
            linewidths=0.5,
            linecolor="gray",
            ax=ax,
        )
        ax.set_title("Filtered Interaction Heatmap (Non-Significant Masked)")
        fig.tight_layout()
        try:
            fig.canvas.draw()
            cbar = ax.collections[0].colorbar
            cax = cbar.ax
            ax_pos = ax.get_position()
            cax_pos = cax.get_position()
            new_y0 = ax_pos.y0 + (ax_pos.height - cax_pos.height) * 0.5 - ax_pos.height * 0.15
            if new_y0 < 0.0:
                new_y0 = 0.0
            cax.set_position([cax_pos.x0, new_y0, cax_pos.width, cax_pos.height])
        except Exception:
            pass
        fig.savefig(output_png, bbox_inches="tight", pad_inches=0.02)
        fig.savefig(output_pdf, bbox_inches="tight", pad_inches=0.02)
        plt.close(fig)
        return

    rows = data

    mir_order: Dict[str, int] = {}
    llvm_order: Dict[str, int] = {}
    for r in rows:
        if not _fbool(r.get("significant")):
            continue
        m = str(r.get("mir_pass", "")).strip()
        l = str(r.get("llvm_pass", "")).strip()
        if m and m not in mir_order:
            mir_order[m] = len(mir_order)
        if l and l not in llvm_order:
            llvm_order[l] = len(llvm_order)

    mir_list = list(mir_order.keys())
    llvm_list = list(llvm_order.keys())
    if not mir_list or not llvm_list:
        return

    m = len(mir_list)
    n = len(llvm_list)
    mat = np.full((m, n), np.nan, dtype=float)
    for r in rows:
        if not _fbool(r.get("significant")):
            continue
        mir = str(r.get("mir_pass", "")).strip()
        llvm = str(r.get("llvm_pass", "")).strip()
        if mir not in mir_order or llvm not in llvm_order:
            continue
        d = _ffloat(r.get("delta"))
        if d != d:
            continue
        mat[mir_order[mir], llvm_order[llvm]] = d

    max_abs = float(np.nanmax(np.abs(mat)))
    if not (max_abs > 0):
        return

    from matplotlib.colors import TwoSlopeNorm

    masked = np.ma.array(mat, mask=np.isnan(mat))
    cmap = plt.get_cmap("RdBu_r").copy()
    cmap.set_bad(color="white")
    norm = TwoSlopeNorm(vmin=-max_abs, vcenter=0.0, vmax=max_abs)

    fig, ax = plt.subplots(figsize=(20, 15))
    im = ax.imshow(masked, cmap=cmap, norm=norm, aspect="equal", interpolation="nearest")
    ax.set_title("Filtered Interaction Heatmap (Non-Significant Masked)")

    ax.set_xticks(range(n))
    ax.set_yticks(range(m))
    ax.set_xticklabels(llvm_list, rotation=90, fontsize=6)
    ax.set_yticklabels(mir_list, fontsize=6)

    ax.set_xticks(np.arange(-0.5, n, 1), minor=True)
    ax.set_yticks(np.arange(-0.5, m, 1), minor=True)
    ax.grid(which="minor", color="gray", linestyle="-", linewidth=0.3)
    ax.tick_params(which="minor", bottom=False, left=False)

    cbar = fig.colorbar(im, ax=ax, orientation="vertical", pad=0.02, shrink=0.3, aspect=30)
    cbar.set_label("Interaction Delta (Significant Only)")

    fig.tight_layout()
    try:
        fig.canvas.draw()
        cax = cbar.ax
        ax_pos = ax.get_position()
        cax_pos = cax.get_position()
        new_y0 = ax_pos.y0 + (ax_pos.height - cax_pos.height) * 0.5 - ax_pos.height * 0.15
        if new_y0 < 0.0:
            new_y0 = 0.0
        cax.set_position([cax_pos.x0, new_y0, cax_pos.width, cax_pos.height])
    except Exception:
        pass
    fig.savefig(output_png, bbox_inches="tight", pad_inches=0.02)
    fig.savefig(output_pdf, bbox_inches="tight", pad_inches=0.02)
    plt.close(fig)


def plot_clustermap(df: "pd.DataFrame", output_png: str, output_pdf: str) -> None:
    sig_df = df[df["significant"] == True]
    if sig_df.empty:
        return

    relevant_mir = sig_df["mir_pass"].unique()
    relevant_llvm = sig_df["llvm_pass"].unique()

    pivot_delta = df.pivot(index="mir_pass", columns="llvm_pass", values="delta")
    pivot_sig = df.pivot(index="mir_pass", columns="llvm_pass", values="significant").fillna(False)

    pivot_delta = pivot_delta.loc[relevant_mir, relevant_llvm]
    pivot_sig = pivot_sig.loc[relevant_mir, relevant_llvm]

    data_for_clustering = pivot_delta.copy()
    data_for_clustering[~pivot_sig] = 0
    data_for_clustering = data_for_clustering.fillna(0)

    g = sns.clustermap(
        data_for_clustering,
        center=0,
        cmap="RdBu_r",
        figsize=(20, 20),
        method="ward",
        cbar_kws={"label": "Interaction Delta"},
    )
    g.fig.suptitle("Clustered Interaction Map (Significant Only)", y=1.02)
    plt.savefig(output_png, bbox_inches="tight")
    plt.savefig(output_pdf, bbox_inches="tight")
    plt.close()


def plot_bipartite_network(df: "pd.DataFrame", output_png: str, output_pdf: str, top_n: int) -> None:
    sig_df = df[df["significant"] == True].copy()
    if sig_df.empty:
        return

    sig_df["abs_delta"] = sig_df["delta"].abs()
    top_interactions = sig_df.sort_values("abs_delta", ascending=False).head(top_n)

    B = nx.Graph()
    mir_nodes = top_interactions["mir_pass"].unique()
    llvm_nodes = top_interactions["llvm_pass"].unique()

    B.add_nodes_from(mir_nodes, bipartite=0)
    B.add_nodes_from(llvm_nodes, bipartite=1)

    for _, row in top_interactions.iterrows():
        B.add_edge(row["mir_pass"], row["llvm_pass"], weight=row["delta"])

    pos = {}
    mir_nodes_sorted = sorted(mir_nodes)
    llvm_nodes_sorted = sorted(llvm_nodes)
    for i, node in enumerate(mir_nodes_sorted):
        y = 1.0 - (i / (len(mir_nodes_sorted) - 1)) if len(mir_nodes_sorted) > 1 else 0.5
        pos[node] = (0.2, y)
    for i, node in enumerate(llvm_nodes_sorted):
        y = 1.0 - (i / (len(llvm_nodes_sorted) - 1)) if len(llvm_nodes_sorted) > 1 else 0.5
        pos[node] = (0.8, y)

    plt.figure(figsize=(12, 12))
    nx.draw_networkx_nodes(B, pos, nodelist=mir_nodes, node_color="lightblue", node_shape="s", node_size=500, label="MIR")
    nx.draw_networkx_nodes(B, pos, nodelist=llvm_nodes, node_color="lightgreen", node_shape="o", node_size=500, label="LLVM")

    edges = B.edges(data=True)
    neg_edges = [(u, v) for u, v, d in edges if d["weight"] < 0]
    pos_edges = [(u, v) for u, v, d in edges if d["weight"] > 0]

    width_scale = 30
    weights_neg = [abs(B[u][v]["weight"]) * width_scale for u, v in neg_edges]
    weights_pos = [abs(B[u][v]["weight"]) * width_scale for u, v in pos_edges]

    nx.draw_networkx_edges(B, pos, edgelist=neg_edges, edge_color="blue", width=weights_neg, alpha=0.6)
    nx.draw_networkx_edges(B, pos, edgelist=pos_edges, edge_color="red", width=weights_pos, alpha=0.6)
    nx.draw_networkx_labels(B, pos, font_size=8, font_family="sans-serif")

    plt.title(f"Top {top_n} Strongest Cross-Layer Couplings (Bipartite Graph)\nBlue=Negative (Redundant), Red=Positive (Interference)")
    plt.axis("off")

    from matplotlib.lines import Line2D

    legend_elements = [
        Line2D([0], [0], color="blue", lw=2, label="Negative Interaction (Redundancy)"),
        Line2D([0], [0], color="red", lw=2, label="Positive Interaction (Interference)"),
        Line2D([0], [0], marker="s", color="w", markerfacecolor="lightblue", markersize=10, label="MIR Pass"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor="lightgreen", markersize=10, label="LLVM Pass"),
    ]
    plt.legend(handles=legend_elements, loc="upper center", bbox_to_anchor=(0.5, -0.05), ncol=2)
    plt.tight_layout()
    plt.savefig(output_png, bbox_inches="tight")
    plt.savefig(output_pdf, bbox_inches="tight")
    plt.close()


def plot_knowledge_graph(df: "pd.DataFrame", output_png: str, output_pdf: str) -> None:
    sig_df = df[df["significant"] == True].copy()
    if sig_df.empty:
        return

    top_interactions = sig_df.copy()
    top_interactions["abs_delta"] = top_interactions["delta"].abs()

    G = nx.Graph()
    mir_nodes = set()
    llvm_nodes = set()
    node_strength: Dict[str, float] = {}

    for _, row in top_interactions.iterrows():
        mir = row["mir_pass"]
        llvm = row["llvm_pass"]
        weight = float(row["delta"])
        abs_weight = abs(weight)
        mir_nodes.add(mir)
        llvm_nodes.add(llvm)
        G.add_edge(mir, llvm, weight=weight, abs_weight=abs_weight)
        node_strength[mir] = node_strength.get(mir, 0.0) + abs_weight
        node_strength[llvm] = node_strength.get(llvm, 0.0) + abs_weight

    pos = nx.spring_layout(G, k=0.5, iterations=100, seed=42)

    plt.figure(figsize=(16, 16))
    edges = G.edges(data=True)
    neg_edges = [(u, v) for u, v, d in edges if d["weight"] < 0]
    pos_edges = [(u, v) for u, v, d in edges if d["weight"] > 0]

    width_scale = 15
    weights_neg = [G[u][v]["abs_weight"] * width_scale for u, v in neg_edges]
    weights_pos = [G[u][v]["abs_weight"] * width_scale for u, v in pos_edges]

    nx.draw_networkx_edges(G, pos, edgelist=neg_edges, edge_color="royalblue", alpha=0.6, width=weights_neg)
    nx.draw_networkx_edges(G, pos, edgelist=pos_edges, edge_color="crimson", alpha=0.6, width=weights_pos)

    base_size = 300
    size_scale = 3000
    mir_sizes = [base_size + node_strength.get(n, 0.0) * size_scale for n in mir_nodes if n in G]
    llvm_sizes = [base_size + node_strength.get(n, 0.0) * size_scale for n in llvm_nodes if n in G]

    nx.draw_networkx_nodes(
        G,
        pos,
        nodelist=list(mir_nodes),
        node_shape="s",
        node_color="#87CEEB",
        node_size=mir_sizes,
        label="MIR Pass (Source)",
    )
    nx.draw_networkx_nodes(
        G,
        pos,
        nodelist=list(llvm_nodes),
        node_shape="o",
        node_color="#98FB98",
        node_size=llvm_sizes,
        label="LLVM Pass (Target)",
    )
    nx.draw_networkx_labels(G, pos, font_size=9, font_family="sans-serif", font_weight="bold")

    plt.title("Optimization Coupling Knowledge Graph (Force-Directed)", fontsize=16)
    plt.axis("off")

    from matplotlib.lines import Line2D

    legend_elements = [
        Line2D([0], [0], color="royalblue", lw=3, label="Negative Coupling (Redundancy)"),
        Line2D([0], [0], color="crimson", lw=3, label="Positive Coupling (Interference)"),
        Line2D([0], [0], marker="s", color="w", markerfacecolor="#87CEEB", markersize=15, label="MIR Pass"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor="#98FB98", markersize=15, label="LLVM Pass"),
    ]
    plt.legend(handles=legend_elements, loc="lower right", fontsize=12)

    plt.tight_layout()
    plt.savefig(output_png, bbox_inches="tight")
    plt.savefig(output_pdf, bbox_inches="tight")
    plt.close()


def generate_plots(*, interaction_csv: str, top_k: int, top_n_network: int) -> None:
    os.makedirs(DID_DIR, exist_ok=True)
    os.makedirs(COUPLING_PLOTS_DIR, exist_ok=True)

    plot_interaction_heatmap(
        interaction_csv,
        os.path.join(DID_DIR, "interaction_heatmap.png"),
        os.path.join(DID_DIR, "interaction_heatmap.pdf"),
    )
    plot_top_interactions_forest(
        interaction_csv,
        os.path.join(DID_DIR, "top_interactions_forest.png"),
        os.path.join(DID_DIR, "top_interactions_forest.pdf"),
        top_k=top_k,
    )

    if HAVE_PANDAS:
        df = pd.read_csv(interaction_csv)
        plot_filtered_heatmap(
            df,
            os.path.join(COUPLING_PLOTS_DIR, "filtered_heatmap.png"),
            os.path.join(COUPLING_PLOTS_DIR, "filtered_heatmap.pdf"),
        )
        if HAVE_SEABORN:
            plot_clustermap(
                df,
                os.path.join(COUPLING_PLOTS_DIR, "clustered_heatmap.png"),
                os.path.join(COUPLING_PLOTS_DIR, "clustered_heatmap.pdf"),
            )
        if HAVE_NETWORKX:
            plot_bipartite_network(
                df,
                os.path.join(COUPLING_PLOTS_DIR, "coupling_network_top50.png"),
                os.path.join(COUPLING_PLOTS_DIR, "coupling_network_top50.pdf"),
                top_n=top_n_network,
            )
            plot_knowledge_graph(
                df,
                os.path.join(COUPLING_PLOTS_DIR, "coupling_knowledge_graph.png"),
                os.path.join(COUPLING_PLOTS_DIR, "coupling_knowledge_graph.pdf"),
            )
        return

    rows = _rows_from_interaction_csv(interaction_csv)
    plot_filtered_heatmap(
        rows,
        os.path.join(COUPLING_PLOTS_DIR, "filtered_heatmap.png"),
        os.path.join(COUPLING_PLOTS_DIR, "filtered_heatmap.pdf"),
    )


def run_classify_and_plot_if_available() -> None:
    did_script = os.path.join(DID_DIR, "classify_and_plot.py")
    if not os.path.exists(did_script):
        return
    try:
        runpy.run_path(did_script, run_name="__main__")
    except Exception:
        return


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=DEFAULT_EXPERIMENT_CSV)
    ap.add_argument("--metric", default="TotalRuntime(s)")
    ap.add_argument("--alpha", default=0.05, type=float)
    ap.add_argument("--top-k", default=50, type=int)
    ap.add_argument("--top-n-network", default=50, type=int)
    args = ap.parse_args(argv)

    if not os.path.exists(args.input):
        raise FileNotFoundError(args.input)

    rows = compute_interaction_results(experiment_csv=args.input, metric_col=args.metric, alpha=float(args.alpha))
    save_interaction_results_csv(rows, INTERACTION_RESULTS_CSV)

    generate_plots(interaction_csv=INTERACTION_RESULTS_CSV, top_k=int(args.top_k), top_n_network=int(args.top_n_network))
    run_classify_and_plot_if_available()

    print(f"Saved interaction results: {INTERACTION_RESULTS_CSV}")
    print(f"Saved coupling plots: {COUPLING_PLOTS_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
