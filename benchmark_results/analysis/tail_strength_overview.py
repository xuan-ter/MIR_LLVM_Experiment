import argparse
import csv
import math
import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import matplotlib.pyplot as plt


def _clean_pass_name(x: object) -> str:
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


def _normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _welch_pvalue_normal_approx(*, mu1: float, v1: float, n1: int, mu2: float, v2: float, n2: int) -> float:
    if n1 <= 1 or n2 <= 1:
        return 1.0
    if not (v1 == v1) or not (v2 == v2):
        return 1.0
    denom = v1 / n1 + v2 / n2
    if denom <= 0:
        return 1.0
    z = (mu1 - mu2) / math.sqrt(denom)
    p = 2.0 * (1.0 - _normal_cdf(abs(z)))
    if not (p == p):
        return 1.0
    return max(0.0, min(1.0, p))


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


def _quantile_sorted(xs_sorted: Sequence[float], q: float) -> float:
    if not xs_sorted:
        return float("nan")
    q = float(q)
    if q <= 0:
        return float(xs_sorted[0])
    if q >= 1:
        return float(xs_sorted[-1])
    n = len(xs_sorted)
    if n == 1:
        return float(xs_sorted[0])
    pos = q * (n - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return float(xs_sorted[lo])
    frac = pos - lo
    return float(xs_sorted[lo] * (1.0 - frac) + xs_sorted[hi] * frac)


def _read_float(r: Dict[str, str], key: str) -> Optional[float]:
    try:
        s = str(r.get(key, "")).strip()
        if s == "" or s.lower() == "nan":
            return None
        return float(s)
    except Exception:
        return None


def compute_interaction_deltas(
    *,
    experiment_csv: str,
    metric_col: str,
    alpha: float,
) -> Tuple[List[float], List[float]]:
    groups: Dict[Tuple[str, str], List[float]] = {}
    mir_passes = set()
    llvm_passes = set()

    with open(experiment_csv, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            status = str(r.get("Status", "")).strip()
            if status and status != "Success":
                continue

            y = _read_float(r, metric_col)
            if y is None or not (y > 0.0):
                continue

            llvm_p = _clean_pass_name(r.get("LLVM_Pass"))
            mir_p = _clean_pass_name(r.get("MIR_Pass"))

            mir_passes.add(mir_p)
            llvm_passes.add(llvm_p)

            key = (mir_p, llvm_p)
            groups.setdefault(key, []).append(math.log(y))

    mir_list = sorted(p for p in mir_passes if p not in {"None", "All"})
    llvm_list = sorted(p for p in llvm_passes if p not in {"None", "All"})

    z00 = groups.get(("None", "None"), [])
    if not z00:
        return [], []

    base_mean = _mean(z00)
    base_var = _var(z00, base_mean)
    base_n = len(z00)

    deltas_all: List[float] = []
    pvals: List[float] = []

    for m in mir_list:
        z10 = groups.get((m, "None"), [])
        if not z10:
            mu10 = base_mean
            v10 = base_var
            n10 = base_n
        else:
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
            if delta == delta:
                deltas_all.append(float(delta))

            p = _welch_pvalue_normal_approx(
                mu1=mu01 - mu11,
                v1=(v01 if v01 == v01 else 0.0) + (v11 if v11 == v11 else 0.0),
                n1=min(n01, n11),
                mu2=base_mean - mu10,
                v2=(base_var if base_var == base_var else 0.0) + (v10 if v10 == v10 else 0.0),
                n2=min(base_n, n10),
            )
            pvals.append(float(p))

    if not deltas_all:
        return [], []

    padj = _bh_fdr(pvals)
    deltas_sig: List[float] = []
    for d, a in zip(deltas_all, padj):
        if float(a) <= float(alpha):
            deltas_sig.append(d)

    return deltas_all, deltas_sig


@dataclass(frozen=True)
class WorkloadProfile:
    workload: str
    n_all: int
    n_sig: int
    p50: float
    p90: float
    p99: float
    max_v: float
    tail_ratio: float
    extreme_ratio: float


def _profile_from_strengths(workload: str, strengths_all: List[float], strengths_sig: List[float], *, subset: str) -> Optional[WorkloadProfile]:
    xs = strengths_sig if subset == "significant" else strengths_all
    xs = [float(x) for x in xs if x is not None and x == x and x >= 0.0]
    if not xs:
        return None
    xs.sort()
    p50 = _quantile_sorted(xs, 0.50)
    p90 = _quantile_sorted(xs, 0.90)
    p99 = _quantile_sorted(xs, 0.99)
    mx = float(xs[-1])
    eps = 1e-12
    tail_ratio = p99 / max(eps, p50)
    extreme_ratio = mx / max(eps, p90)
    return WorkloadProfile(
        workload=workload,
        n_all=len(strengths_all),
        n_sig=len(strengths_sig),
        p50=float(p50),
        p90=float(p90),
        p99=float(p99),
        max_v=float(mx),
        tail_ratio=float(tail_ratio),
        extreme_ratio=float(extreme_ratio),
    )


def _strength_from_delta(delta: float, xmode: str) -> float:
    if xmode == "rel":
        return abs(math.exp(delta) - 1.0)
    if xmode == "log1p_rel":
        return math.log10(1.0 + abs(math.exp(delta) - 1.0))
    if xmode == "log1p_delta":
        return math.log10(1.0 + abs(delta))
    return abs(delta)


def _x_label(xmode: str, metric_col: str) -> str:
    if xmode == "rel":
        return f"Interaction strength |exp(Δ) - 1| on {metric_col} (relative, DID)"
    if xmode == "log1p_rel":
        return f"log10(1 + |exp(Δ) - 1|) on {metric_col} (relative, DID)"
    if xmode == "log1p_delta":
        return f"log10(1 + |Δ|) where Δ is DID on ln({metric_col})"
    return f"Interaction strength |Δ| where Δ is DID on ln({metric_col})"


def plot_profiles(
    profiles: List[WorkloadProfile],
    *,
    out_png: str,
    out_pdf: str,
    xmode: str,
    metric_col: str,
    sort_by: str,
    title: str,
) -> None:
    if not profiles:
        return

    def _key(p: WorkloadProfile) -> float:
        if sort_by == "p99":
            return p.p99
        if sort_by == "max":
            return p.max_v
        if sort_by == "p90":
            return p.p90
        if sort_by == "p50":
            return p.p50
        if sort_by == "extreme_ratio":
            return p.extreme_ratio
        return p.tail_ratio

    profiles = sorted(profiles, key=_key, reverse=True)
    n = len(profiles)

    fig_h = max(6.0, 0.9 * n + 3.0)
    fig, ax = plt.subplots(figsize=(13, fig_h))

    ys = list(range(n))
    labels = [p.workload for p in profiles]
    x_max_raw = max((p.max_v for p in profiles), default=1.0)

    for i, p in enumerate(profiles):
        y = ys[i]
        ax.hlines(y=y, xmin=p.p50, xmax=p.max_v, color="#9aa0a6", linewidth=3.75, alpha=0.7, zorder=1)
        ax.hlines(y=y, xmin=p.p50, xmax=p.p99, color="#5f6368", linewidth=5.25, alpha=0.7, zorder=2)
        ax.scatter([p.p50], [y], s=135, marker="o", color="#1f77b4", label="p50" if i == 0 else None, zorder=3)
        ax.scatter([p.p90], [y], s=165, marker="s", color="#ff7f0e", label="p90" if i == 0 else None, zorder=3)
        ax.scatter([p.p99], [y], s=195, marker="D", color="#2ca02c", label="p99" if i == 0 else None, zorder=3)
        ax.scatter([p.max_v], [y], s=225, marker="X", color="#d62728", label="max" if i == 0 else None, zorder=3)
        ax.text(
            p.p50,
            y + 0.28,
            f"TR={p.tail_ratio:.2f}  ER={p.extreme_ratio:.2f}",
            fontsize=18.0,
            color="#202124",
            ha="left",
            va="center",
        )

    ax.set_yticks(ys)
    ax.set_yticklabels(labels, fontsize=23.04)
    ax.invert_yaxis()
    ax.set_ylim(n - 0.5, -0.5)

    ax.set_xlabel(_x_label(xmode, metric_col), fontsize=24.0)
    ax.set_title(title, fontsize=26.4)
    ax.grid(axis="x", linestyle="--", alpha=0.25)
    ax.legend(loc="lower right", fontsize=21.0, frameon=True, markerscale=1.5)

    ax.set_xlim(left=0.0, right=x_max_raw * 1.12)
    ax.tick_params(axis="x", labelsize=24.0)

    fig.tight_layout()
    os.makedirs(os.path.dirname(out_png), exist_ok=True)
    fig.savefig(out_png, dpi=250)
    fig.savefig(out_pdf)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--benchmark-dir", default=r"d:\MIR_LLVM\mir_llvm\benchmark_results")
    ap.add_argument("--out-dir", default=r"d:\MIR_LLVM\mir_llvm\benchmark_results\analysis")
    ap.add_argument("--metric-col", default="TotalRuntime(s)")
    ap.add_argument("--xmode", choices=["delta", "rel", "log1p_delta", "log1p_rel"], default="delta")
    ap.add_argument("--subset", choices=["all", "significant"], default="all")
    ap.add_argument("--alpha", type=float, default=0.05)
    ap.add_argument("--sort-by", choices=["tail_ratio", "extreme_ratio", "p50", "p90", "p99", "max"], default="tail_ratio")
    ap.add_argument("--title", default="Tail Strength Quantile Profile across Workloads")
    args = ap.parse_args()

    bench_dir = os.path.abspath(str(args.benchmark_dir))
    out_dir = os.path.abspath(str(args.out_dir))
    metric_col = str(args.metric_col)
    xmode = str(args.xmode)
    subset = str(args.subset)
    alpha = float(args.alpha)
    sort_by = str(args.sort_by)
    title = str(args.title)

    workloads: List[Tuple[str, str]] = []
    for name in sorted(os.listdir(bench_dir)):
        if not name.lower().endswith(".csv"):
            continue
        if name.lower() in {"summary.csv", "summary_all.csv"}:
            continue
        p = os.path.join(bench_dir, name)
        if os.path.isfile(p):
            workloads.append((os.path.splitext(name)[0], p))

    profiles: List[WorkloadProfile] = []
    skipped: List[Tuple[str, str]] = []
    for w, p in workloads:
        deltas_all, deltas_sig = compute_interaction_deltas(experiment_csv=p, metric_col=metric_col, alpha=alpha)
        if not deltas_all:
            skipped.append((w, "missing baseline/single/double groups for DID interaction"))
            continue
        strengths_all = [_strength_from_delta(d, xmode) for d in deltas_all]
        strengths_sig = [_strength_from_delta(d, xmode) for d in deltas_sig]
        prof = _profile_from_strengths(w, strengths_all, strengths_sig, subset=subset)
        if prof is not None:
            profiles.append(prof)

    out_png = os.path.join(out_dir, f"tail_strength_overview_{metric_col.replace('/', '_')}_{xmode}_{subset}.png")
    out_pdf = os.path.join(out_dir, f"tail_strength_overview_{metric_col.replace('/', '_')}_{xmode}_{subset}.pdf")
    plot_profiles(profiles, out_png=out_png, out_pdf=out_pdf, xmode=xmode, metric_col=metric_col, sort_by=sort_by, title=title)

    profiles_sorted = sorted(profiles, key=lambda p: getattr(p, sort_by) if hasattr(p, sort_by) else p.tail_ratio, reverse=True)
    for p in profiles_sorted:
        print(
            f"{p.workload:12s} n_all={p.n_all:6d} n_sig={p.n_sig:6d} p50={p.p50:.4f} p90={p.p90:.4f} p99={p.p99:.4f} max={p.max_v:.4f} tail_ratio={p.tail_ratio:.3f} extreme_ratio={p.extreme_ratio:.3f}"
        )
    for w, why in skipped:
        print(f"{w:12s} skipped: {why}")
    print(out_pdf)


if __name__ == "__main__":
    main()
