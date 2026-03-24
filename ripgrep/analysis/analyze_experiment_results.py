import argparse
import csv
import math
import os
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
DEFAULT_EXPERIMENT_CSV = r"d:\MIR_LLVM\mir_-llvm\ripgrep\results\experiment_results.csv"
DID_DIR = os.path.join(BASE_DIR, "did")
INTERACTION_RESULTS_CSV = os.path.join(DID_DIR, "interaction_results.csv")
COUPLING_PLOTS_DIR = os.path.join(DID_DIR, "coupling_plots")
CLASSIFIED_RESULTS_DIR = os.path.join(DID_DIR, "classified_results")


def _clean_pass_name(x: object, *, is_mir: bool) -> str:
    if x is None:
        return "None"
    s = str(x).strip()
    if s == "" or s.lower() in {"none", "baseline", "nan", "n/a", "na"}:
        return "None"
    if s.lower() == "all":
        return "All"
    return s


def _mean(xs: Sequence[float]) -> float:
    if not xs:
        return float("nan")
    return float(sum(xs) / len(xs))


def _var(xs: Sequence[float], mu: float) -> float:
    n = len(xs)
    if n <= 1:
        return float("nan")
    return float(sum((x - mu) ** 2 for x in xs) / (n - 1))


def _welch_t_pvalue(*, mu1: float, v1: float, n1: int, mu2: float, v2: float, n2: int) -> float:
    if n1 <= 1 or n2 <= 1:
        return 1.0
    if not (v1 == v1) or not (v2 == v2):
        return 1.0
    denom = v1 / n1 + v2 / n2
    if denom <= 0:
        return 1.0
    t = (mu1 - mu2) / math.sqrt(denom)
    df_num = denom * denom
    df_den = (v1 * v1) / (n1 * n1 * (n1 - 1)) + (v2 * v2) / (n2 * n2 * (n2 - 1))
    if df_den <= 0:
        return 1.0
    df = df_num / df_den
    try:
        import scipy.stats as stats

        p = 2.0 * float(stats.t.sf(abs(t), df))
        if p != p:
            return 1.0
        return max(0.0, min(1.0, p))
    except Exception:
        return 1.0


def _bh_fdr(pvals: Sequence[float]) -> List[float]:
    m = len(pvals)
    if m == 0:
        return []
    idx = sorted(range(m), key=lambda i: (pvals[i], i))
    adj = [1.0] * m
    prev = 1.0
    for rank, i in enumerate(reversed(idx), start=1):
        p = float(pvals[i])
        r = m - rank + 1
        val = (p * m) / max(1, r)
        if val > prev:
            val = prev
        prev = val
        adj[i] = max(0.0, min(1.0, val))
    return adj


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
        mu10 = _mean(z10)
        v10 = _var(z10, mu10)
        n10 = len(z10)
        for l in llvm_list:
            z01 = groups.get(("None", l), [])
            z11 = groups.get((m, l), [])
            if not z01 or not z11:
                continue
            mu01 = _mean(z01)
            mu11 = _mean(z11)
            v01 = _var(z01, mu01)
            v11 = _var(z11, mu11)
            n01 = len(z01)
            n11 = len(z11)

            delta = (mu01 - mu11) - (base_mean - mu10)

            var_delta = (v01 / n01 if n01 > 1 and v01 == v01 else 0.0) + (v11 / n11 if n11 > 1 and v11 == v11 else 0.0)
            var_delta += (base_var / base_n if base_n > 1 and base_var == base_var else 0.0) + (v10 / n10 if n10 > 1 and v10 == v10 else 0.0)
            se = math.sqrt(var_delta) if var_delta > 0 else float("nan")
            ci_low = delta - 1.96 * se if se == se else float("nan")
            ci_high = delta + 1.96 * se if se == se else float("nan")

            p = _welch_t_pvalue(mu1=mu01 - mu11, v1=(v01 if v01 == v01 else 0.0) + (v11 if v11 == v11 else 0.0), n1=min(n01, n11), mu2=base_mean - mu10, v2=(base_var if base_var == base_var else 0.0) + (v10 if v10 == v10 else 0.0), n2=min(base_n, n10))

            out_rows.append(
                {
                    "mir_pass": m,
                    "llvm_pass": l,
                    "y00_mean": float(math.exp(base_mean)),
                    "y10_mean": float(math.exp(mu10)),
                    "y01_mean": float(math.exp(mu01)),
                    "y11_mean": float(math.exp(mu11)),
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

    out_rows.sort(key=lambda rr: (float(rr.get("p_adj", 1.0)), -abs(float(rr.get("delta", 0.0)))))
    return out_rows


def save_interaction_results_csv(rows: Sequence[Dict[str, object]], out_csv: str) -> None:
    os.makedirs(os.path.dirname(out_csv), exist_ok=True)
    fieldnames = [
        "mir_pass",
        "llvm_pass",
        "y00_mean",
        "y10_mean",
        "y01_mean",
        "y11_mean",
        "delta",
        "ci_low",
        "ci_high",
        "p_value",
        "p_adj",
        "significant",
    ]
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})


def _rows_from_interaction_csv(path: str) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append(r)
    return rows


def _ffloat(x: object) -> float:
    try:
        s = str(x).strip()
        if s == "" or s.lower() == "nan":
            return float("nan")
        return float(s)
    except Exception:
        return float("nan")


def _fbool(x: object) -> bool:
    return str(x).strip().lower() == "true"


def plot_interaction_heatmap(interaction_csv: str, output_png: str, output_pdf: str) -> None:
    if HAVE_PANDAS and HAVE_SEABORN:
        df = pd.read_csv(interaction_csv)
        if df.empty:
            return
        pivot_delta = df.pivot(index="mir_pass", columns="llvm_pass", values="delta")
        non_empty_rows = pivot_delta.index[pivot_delta.notna().any(axis=1)]
        non_empty_cols = pivot_delta.columns[pivot_delta.notna().any(axis=0)]
        pivot_delta = pivot_delta.loc[non_empty_rows, non_empty_cols]
        if pivot_delta.empty:
            return
        plt.figure(figsize=(12, 10))
        sns.heatmap(
            pivot_delta,
            cmap="RdBu_r",
            center=0,
            annot=False,
            linewidths=0.5,
            linecolor="gray",
        )
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


def plot_top_interactions_forest(interaction_csv: str, output_png: str, output_pdf: str, *, top_k: int) -> None:
    if HAVE_PANDAS and isinstance(top_k, int) and top_k > 0:
        df = pd.read_csv(interaction_csv) if HAVE_PANDAS else None
        if df is None or df.empty:
            return
        sig = df[df["significant"] == True].copy()
        use_df = sig if not sig.empty else df.copy()
        use_df["abs_delta"] = use_df["delta"].abs()
        top = use_df.sort_values("abs_delta", ascending=False).head(top_k).copy()
        top["label"] = top["mir_pass"] + " + " + top["llvm_pass"]

        items: List[Tuple[float, float, float, float, str]] = []
        for _, r in top.iterrows():
            d = float(r["delta"])
            lo = float(r["ci_low"]) if "ci_low" in r else d
            hi = float(r["ci_high"]) if "ci_high" in r else d
            items.append((abs(d), d, lo, hi, str(r["label"])))
        items.sort(key=lambda t: t[0], reverse=True)
        items = items[:top_k]

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
        if sig.empty:
            plt.title(f"Top Interactions by |Δ| (Top {len(items)})")
        else:
            plt.title(f"Top Significant Interactions (Top {len(items)})")
        plt.tight_layout()
        plt.savefig(output_png, bbox_inches="tight")
        plt.savefig(output_pdf, bbox_inches="tight")
        plt.close()
        return


def plot_filtered_heatmap(data: object, output_png: str, output_pdf: str) -> None:
    if HAVE_PANDAS and HAVE_SEABORN and HAVE_PANDAS and isinstance(data, pd.DataFrame):
        df = data
        sig_df = df[df["significant"] == True]
        selected_pairs = None
        if sig_df.empty:
            tmp = df.copy()
            tmp["abs_delta"] = tmp["delta"].abs()
            top_pairs = tmp.sort_values("abs_delta", ascending=False).head(200)
            if top_pairs.empty:
                return
            relevant_mir = top_pairs["mir_pass"].unique()
            relevant_llvm = top_pairs["llvm_pass"].unique()
            selected_pairs = {(str(r["mir_pass"]), str(r["llvm_pass"])) for _, r in top_pairs.iterrows()}
        else:
            relevant_mir = sig_df["mir_pass"].unique()
            relevant_llvm = sig_df["llvm_pass"].unique()

        pivot_delta = df.pivot(index="mir_pass", columns="llvm_pass", values="delta")
        pivot_sig = df.pivot(index="mir_pass", columns="llvm_pass", values="significant")

        pivot_delta = pivot_delta.loc[relevant_mir, relevant_llvm]
        pivot_sig = pivot_sig.loc[relevant_mir, relevant_llvm]

        if selected_pairs is None:
            mask = ~pivot_sig.fillna(False).astype(bool)
        else:
            mask = np.ones(pivot_delta.shape, dtype=bool)
            mir_idx = {m: i for i, m in enumerate(pivot_delta.index.tolist())}
            llvm_idx = {l: j for j, l in enumerate(pivot_delta.columns.tolist())}
            for m, l in selected_pairs:
                if m in mir_idx and l in llvm_idx:
                    mask[mir_idx[m], llvm_idx[l]] = False

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
        if sig_df.empty:
            ax.set_title("Top Interaction Heatmap (Top |Δ| Cells Highlighted)")
        else:
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
    top = []
    for r in rows:
        d = _ffloat(r.get("delta"))
        if not (d == d):
            continue
        m = str(r.get("mir_pass", "")).strip()
        l = str(r.get("llvm_pass", "")).strip()
        if not m or not l:
            continue
        top.append((abs(d), m, l, d, bool(_fbool(r.get("significant")))))
    if not top:
        return
    top.sort(key=lambda t: t[0], reverse=True)

    use_sig = [t for t in top if t[4]]
    if use_sig:
        chosen = use_sig[:200]
    else:
        chosen = top[:200]

    chosen_pairs = {(t[1], t[2]) for t in chosen}
    for _, m, l, _, _ in chosen:
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
        mir = str(r.get("mir_pass", "")).strip()
        llvm = str(r.get("llvm_pass", "")).strip()
        if mir not in mir_order or llvm not in llvm_order:
            continue
        if (mir, llvm) not in chosen_pairs:
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
    use_df = sig_df if not sig_df.empty else df.copy()
    if use_df.empty:
        return

    use_df["abs_delta"] = use_df["delta"].abs()
    top_interactions = use_df.sort_values("abs_delta", ascending=False).head(top_n)

    B = nx.Graph()
    mir_nodes = top_interactions["mir_pass"].unique()
    llvm_nodes = top_interactions["llvm_pass"].unique()

    B.add_nodes_from(mir_nodes, bipartite=0)
    B.add_nodes_from(llvm_nodes, bipartite=1)

    for _, row in top_interactions.iterrows():
        B.add_edge(row["mir_pass"], row["llvm_pass"], weight=row["delta"])

    pos: Dict[str, Tuple[float, float]] = {}
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

    if sig_df.empty:
        plt.title(f"Top {top_n} Cross-Layer Couplings by |Δ| (Bipartite)\nBlue=Negative, Red=Positive")
    else:
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
    top_interactions = sig_df.copy() if not sig_df.empty else df.copy()
    if top_interactions.empty:
        return
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

    if sig_df.empty:
        plt.title("Optimization Coupling Knowledge Graph (Top |Δ| Pairs)", fontsize=16)
    else:
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


def _write_csv(df: "pd.DataFrame", path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_csv(path, index=False)


def classify_and_save(interaction_csv: str) -> None:
    if not HAVE_PANDAS:
        return
    df = pd.read_csv(interaction_csv)
    if df is None or df.empty:
        return

    neg_dir = os.path.join(CLASSIFIED_RESULTS_DIR, "negative_interaction")
    pos_dir = os.path.join(CLASSIFIED_RESULTS_DIR, "positive_interaction")
    ind_dir = os.path.join(CLASSIFIED_RESULTS_DIR, "independent")

    neg_df = df[(df["significant"] == True) & (df["delta"] < 0)].copy()
    pos_df = df[(df["significant"] == True) & (df["delta"] > 0)].copy()
    ind_df = df[df["significant"] == False].copy()

    _write_csv(neg_df.sort_values("delta", ascending=True), os.path.join(neg_dir, "negative_interactions.csv"))
    _write_csv(pos_df.sort_values("delta", ascending=False), os.path.join(pos_dir, "positive_interactions.csv"))
    _write_csv(ind_df.sort_values("p_value", ascending=True), os.path.join(ind_dir, "independent_pairs.csv"))

    deltas = []
    if not neg_df.empty:
        deltas.append(("negative", neg_df["delta"].astype(float)))
    if not pos_df.empty:
        deltas.append(("positive", pos_df["delta"].astype(float)))
    if not ind_df.empty:
        deltas.append(("independent", ind_df["delta"].astype(float)))
    if not deltas:
        return

    out_png = os.path.join(CLASSIFIED_RESULTS_DIR, "interaction_delta_dist_by_type.png")
    out_pdf = os.path.join(CLASSIFIED_RESULTS_DIR, "interaction_delta_dist_by_type.pdf")
    plt.figure(figsize=(12, 6))
    if HAVE_SEABORN:
        for name, series in deltas:
            xs = series.dropna().values
            if len(xs) == 0:
                continue
            sns.kdeplot(xs, label=name, fill=False)
    else:
        for name, series in deltas:
            xs = series.dropna().values
            if len(xs) == 0:
                continue
            plt.hist(xs, bins=50, alpha=0.35, label=name, density=True)
    plt.axvline(x=0.0, color="black", linestyle="--", linewidth=1)
    plt.xlabel("Delta")
    plt.title("Distribution of Interaction Effects (Delta) by Type")
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_png, bbox_inches="tight")
    plt.savefig(out_pdf, bbox_inches="tight")
    plt.close()


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
    classify_and_save(INTERACTION_RESULTS_CSV)

    print(f"Saved interaction results: {INTERACTION_RESULTS_CSV}")
    print(f"Saved coupling plots: {COUPLING_PLOTS_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
