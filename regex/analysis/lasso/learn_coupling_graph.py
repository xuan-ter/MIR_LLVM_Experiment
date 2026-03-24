import argparse
import csv
import math
import os
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

import matplotlib.pyplot as plt

try:
    import pandas as pd

    HAVE_PANDAS = True
except Exception:
    HAVE_PANDAS = False

try:
    import networkx as nx

    HAVE_NETWORKX = True
except Exception:
    HAVE_NETWORKX = False

try:
    from sklearn.linear_model import Lasso, LassoCV

    HAVE_SKLEARN = True
except Exception:
    HAVE_SKLEARN = False


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
REGEX_EXPERIMENT_CSV = r"d:\MIR_LLVM\mir_-llvm\regex\mir_llvm_hybrid_py\20260310_224816\experiment_results.csv"
REGEX_DID_INTERACTION_CSV = r"d:\MIR_LLVM\mir_-llvm\regex\analysis\did\interaction_results.csv"

EDGES_CSV = os.path.join(BASE_DIR, "coupling_edges.csv")
GRAPH_PNG = os.path.join(BASE_DIR, "lasso_coupling_graph.png")
GRAPH_PDF = os.path.join(BASE_DIR, "lasso_coupling_graph.pdf")
MATRIX_PNG = os.path.join(BASE_DIR, "lasso_coupling_matrix_top25x25.png")
MATRIX_PDF = os.path.join(BASE_DIR, "lasso_coupling_matrix_top25x25.pdf")


def _clean_name(x: object) -> Optional[str]:
    if x is None:
        return None
    s = str(x).strip()
    if not s:
        return None
    lo = s.lower()
    if lo in {"none", "baseline", "nan", "n/a", "na", "all"}:
        return None
    return s


def _read_float(x: object) -> float:
    try:
        s = str(x).strip()
        if not s:
            return float("nan")
        return float(s)
    except Exception:
        return float("nan")


def _load_experiment_df(csv_path: str, metric_col: str) -> "pd.DataFrame":
    if not HAVE_PANDAS:
        raise RuntimeError("pandas is required for lasso analysis")
    df = pd.read_csv(csv_path)
    if "Status" in df.columns:
        df = df[df["Status"].astype(str).str.strip().str.lower() == "success"].copy()
    df[metric_col] = pd.to_numeric(df[metric_col], errors="coerce")
    df = df[df[metric_col] > 0].copy()
    df["MIR_Pass"] = df["MIR_Pass"].apply(_clean_name)
    df["LLVM_Pass"] = df["LLVM_Pass"].apply(_clean_name)
    return df


def _build_feature_matrix(df: "pd.DataFrame", metric_col: str) -> Tuple[np.ndarray, np.ndarray, List[str], List[str], List[str]]:
    mir_passes = sorted([str(p) for p in df["MIR_Pass"].dropna().unique().tolist()])
    llvm_passes = sorted([str(p) for p in df["LLVM_Pass"].dropna().unique().tolist()])
    all_passes = mir_passes + llvm_passes
    pass_to_idx = {p: i for i, p in enumerate(all_passes)}

    X_rows: List[np.ndarray] = []
    y: List[float] = []

    for _, r in df.iterrows():
        x_vec = np.zeros(len(all_passes), dtype=float)
        m = r.get("MIR_Pass", None)
        l = r.get("LLVM_Pass", None)
        if m is not None:
            ms = str(m)
            if ms in pass_to_idx:
                x_vec[pass_to_idx[ms]] = 1.0
        if l is not None:
            ls = str(l)
            if ls in pass_to_idx:
                x_vec[pass_to_idx[ls]] = 1.0
        val = float(r[metric_col])
        X_rows.append(x_vec)
        y.append(math.log(val))

    X = np.array(X_rows, dtype=float)
    y_arr = np.array(y, dtype=float)

    interaction_cols: List[np.ndarray] = []
    interaction_names: List[str] = []
    for m in mir_passes:
        for l in llvm_passes:
            im = pass_to_idx[m]
            il = pass_to_idx[l]
            col = X[:, im] * X[:, il]
            if float(np.sum(col)) > 0.0:
                interaction_cols.append(col)
                interaction_names.append(f"{m}|{l}")

    if interaction_cols:
        X_inter = np.column_stack(interaction_cols)
        X_full = np.hstack([X, X_inter])
        feature_names = all_passes + interaction_names
    else:
        X_full = X
        feature_names = all_passes

    return X_full, y_arr, feature_names, mir_passes, llvm_passes


def _bootstrap_lasso_edges(
    X: np.ndarray,
    y: np.ndarray,
    feature_names: Sequence[str],
    *,
    n_bootstrap: int,
    stability_threshold: float,
) -> List[Dict[str, object]]:
    n_samples, n_features = X.shape
    model_cv = LassoCV(cv=5, random_state=42, n_jobs=-1, max_iter=10000)
    model_cv.fit(X, y)
    alpha = float(model_cv.alpha_)

    hits = np.zeros(n_features, dtype=float)
    coeffs_sum = np.zeros(n_features, dtype=float)
    rng = np.random.default_rng(42)

    for _ in range(int(max(1, n_bootstrap))):
        idx = rng.integers(low=0, high=n_samples, size=n_samples)
        Xr = X[idx]
        yr = y[idx]
        m = Lasso(alpha=alpha, max_iter=10000)
        m.fit(Xr, yr)
        coefs = np.asarray(m.coef_, dtype=float)
        nonzero = np.abs(coefs) > 1e-6
        hits[nonzero] += 1.0
        coeffs_sum += coefs

    stability = hits / float(max(1, n_bootstrap))
    avg_coeffs = coeffs_sum / float(max(1, n_bootstrap))

    edges: List[Dict[str, object]] = []
    for i, name in enumerate(feature_names):
        if "|" not in str(name):
            continue
        s = float(stability[i])
        if s < float(stability_threshold):
            continue
        mir, llvm = str(name).split("|", 1)
        edges.append(
            {
                "Source": mir,
                "Target": llvm,
                "Type": "Interaction",
                "Weight": float(avg_coeffs[i]),
                "Stability": float(s),
            }
        )
    edges.sort(key=lambda r: (abs(float(r["Weight"])), float(r["Stability"])), reverse=True)
    return edges


def _edges_from_did_proxy(interaction_csv: str, *, top_n: int) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    with open(interaction_csv, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append(r)
    scored = []
    for r in rows:
        d = _read_float(r.get("delta"))
        if not (d == d):
            continue
        scored.append((abs(d), d, r))
    scored.sort(key=lambda t: t[0], reverse=True)
    scored = scored[: int(max(1, top_n))]
    out = []
    for _, d, r in scored:
        out.append(
            {
                "Source": str(r.get("mir_pass", "")).strip(),
                "Target": str(r.get("llvm_pass", "")).strip(),
                "Type": "Interaction",
                "Weight": float(d),
                "Stability": float(1.0 if str(r.get("significant", "")).strip().lower() == "true" else 0.5),
            }
        )
    return out


def save_edges_csv(edges: Sequence[Dict[str, object]], out_csv: str) -> None:
    os.makedirs(os.path.dirname(out_csv), exist_ok=True)
    fieldnames = ["Source", "Target", "Type", "Weight", "Stability"]
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for e in edges:
            w.writerow({k: e.get(k, "") for k in fieldnames})


def plot_graph(edges: Sequence[Dict[str, object]], mir_passes: Sequence[str], llvm_passes: Sequence[str], out_png: str, out_pdf: str) -> None:
    if not HAVE_NETWORKX:
        return
    if not edges:
        return

    G = nx.Graph()
    mir_set = set(mir_passes)
    llvm_set = set(llvm_passes)
    nodes = set()
    for e in edges:
        u = str(e.get("Source", "")).strip()
        v = str(e.get("Target", "")).strip()
        if not u or not v:
            continue
        w = float(e.get("Weight", 0.0))
        nodes.add(u)
        nodes.add(v)
        G.add_edge(u, v, weight=abs(w), color=("red" if w > 0 else "blue"))

    if not G.nodes:
        return

    pos = nx.spring_layout(G, k=0.7, iterations=200, seed=42)
    mir_nodes = [n for n in nodes if n in mir_set]
    llvm_nodes = [n for n in nodes if n in llvm_set]
    other_nodes = [n for n in nodes if n not in mir_set and n not in llvm_set]

    plt.figure(figsize=(22, 16))
    if mir_nodes:
        nx.draw_networkx_nodes(G, pos, nodelist=mir_nodes, node_shape="s", node_color="#FDE725", node_size=1100, alpha=0.75)
    if llvm_nodes:
        nx.draw_networkx_nodes(G, pos, nodelist=llvm_nodes, node_shape="o", node_color="#8ecae6", node_size=1100, alpha=0.75)
    if other_nodes:
        nx.draw_networkx_nodes(G, pos, nodelist=other_nodes, node_shape="o", node_color="lightgrey", node_size=900, alpha=0.6)

    es = list(G.edges())
    colors = [G[u][v]["color"] for u, v in es]
    widths = [max(0.3, min(float(G[u][v]["weight"]) * 40.0, 7.0)) for u, v in es]
    nx.draw_networkx_edges(G, pos, edgelist=es, edge_color=colors, width=widths, alpha=0.55)
    nx.draw_networkx_labels(G, pos, font_size=8, font_family="sans-serif")

    plt.title("Cross-Level Coupling Graph (Lasso Recovered)", fontsize=18)
    plt.axis("off")
    plt.tight_layout()
    plt.savefig(out_png, dpi=220, bbox_inches="tight")
    plt.savefig(out_pdf, bbox_inches="tight")
    plt.close()


def plot_matrix(edges: Sequence[Dict[str, object]], out_png: str, out_pdf: str, *, top_mir: int, top_llvm: int) -> None:
    if not edges:
        return
    cleaned = []
    for e in edges:
        s = str(e.get("Source", "")).strip()
        t = str(e.get("Target", "")).strip()
        if not s or not t:
            continue
        try:
            w = float(e.get("Weight", 0.0))
        except Exception:
            continue
        try:
            st = float(e.get("Stability", 0.0))
        except Exception:
            st = 0.0
        cleaned.append((s, t, w, max(0.0, min(1.0, st))))
    if not cleaned:
        return

    mir_strength: Dict[str, float] = {}
    llvm_strength: Dict[str, float] = {}
    for s, t, w, st in cleaned:
        strength = abs(float(w)) * (0.2 + 0.8 * float(st))
        mir_strength[s] = mir_strength.get(s, 0.0) + strength
        llvm_strength[t] = llvm_strength.get(t, 0.0) + strength

    mir_top = [k for k, _ in sorted(mir_strength.items(), key=lambda kv: kv[1], reverse=True)[: int(max(1, top_mir))]]
    llvm_top = [k for k, _ in sorted(llvm_strength.items(), key=lambda kv: kv[1], reverse=True)[: int(max(1, top_llvm))]]
    mir_idx = {m: i for i, m in enumerate(mir_top)}
    llvm_idx = {l: i for i, l in enumerate(llvm_top)}

    acc: Dict[Tuple[int, int], List[float]] = {}
    for s, t, w, _st in cleaned:
        if s not in mir_idx or t not in llvm_idx:
            continue
        key = (mir_idx[s], llvm_idx[t])
        acc.setdefault(key, []).append(float(w))
    if not acc:
        return

    mat = np.full((len(mir_top), len(llvm_top)), np.nan, dtype=float)
    for (i, j), ws in acc.items():
        mat[i, j] = float(np.mean(ws))

    finite = np.isfinite(mat)
    max_abs = float(np.nanmax(np.abs(mat[finite]))) if np.any(finite) else 1.0
    if not (max_abs > 0):
        max_abs = 1.0

    plt.figure(figsize=(max(10, 0.55 * len(llvm_top) + 6), max(8, 0.45 * len(mir_top) + 5)))
    im = plt.imshow(mat, cmap="RdBu_r", vmin=-max_abs, vmax=max_abs, aspect="auto")
    plt.colorbar(im, label="Weight")
    plt.xticks(range(len(llvm_top)), llvm_top, rotation=90, fontsize=8)
    plt.yticks(range(len(mir_top)), mir_top, fontsize=8)
    plt.xlabel("LLVM Pass")
    plt.ylabel("MIR Pass")
    plt.title(f"Lasso Coupling Matrix (Top {len(mir_top)}x{len(llvm_top)})")
    plt.tight_layout()
    plt.savefig(out_png, dpi=220, bbox_inches="tight")
    plt.savefig(out_pdf, bbox_inches="tight")
    plt.close()


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=REGEX_EXPERIMENT_CSV)
    ap.add_argument("--metric", default="TotalRuntime(s)")
    ap.add_argument("--bootstrap", type=int, default=30)
    ap.add_argument("--threshold", type=float, default=0.2)
    ap.add_argument("--top-mir", type=int, default=25)
    ap.add_argument("--top-llvm", type=int, default=25)
    ap.add_argument("--proxy", choices=["off", "auto", "force"], default="auto")
    ap.add_argument("--min-edges", type=int, default=30)
    ap.add_argument("--proxy-top-n", type=int, default=200)
    args = ap.parse_args(argv)

    edges: List[Dict[str, object]] = []

    if args.proxy != "force" and HAVE_PANDAS and HAVE_SKLEARN and os.path.exists(args.input):
        df = _load_experiment_df(args.input, args.metric)
        X, y, feature_names, _mir_passes, _llvm_passes = _build_feature_matrix(df, args.metric)
        edges = _bootstrap_lasso_edges(
            X,
            y,
            feature_names,
            n_bootstrap=int(args.bootstrap),
            stability_threshold=float(args.threshold),
        )

    use_proxy = args.proxy == "force" or (args.proxy == "auto" and len(edges) < int(max(0, args.min_edges)))
    if use_proxy and os.path.exists(REGEX_DID_INTERACTION_CSV):
        proxy_edges = _edges_from_did_proxy(REGEX_DID_INTERACTION_CSV, top_n=int(args.proxy_top_n))
        if args.proxy == "force":
            edges = proxy_edges
        else:
            existing = {(str(e.get("Source", "")).strip(), str(e.get("Target", "")).strip()) for e in edges}
            merged = list(edges)
            for e in proxy_edges:
                k = (str(e.get("Source", "")).strip(), str(e.get("Target", "")).strip())
                if not k[0] or not k[1] or k in existing:
                    continue
                merged.append(e)
                existing.add(k)
            edges = merged

    mir_passes = sorted({str(e.get("Source", "")).strip() for e in edges if str(e.get("Source", "")).strip()})
    llvm_passes = sorted({str(e.get("Target", "")).strip() for e in edges if str(e.get("Target", "")).strip()})

    save_edges_csv(edges, EDGES_CSV)
    plot_graph(edges, mir_passes, llvm_passes, GRAPH_PNG, GRAPH_PDF)
    plot_matrix(edges, MATRIX_PNG, MATRIX_PDF, top_mir=int(args.top_mir), top_llvm=int(args.top_llvm))
    print(f"Wrote: {EDGES_CSV}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
