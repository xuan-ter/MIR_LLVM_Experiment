import argparse
import csv
import math
import os
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

plt.rcParams.update(
    {
        "font.size": 14,
        "axes.titlesize": 16,
        "axes.labelsize": 14,
        "xtick.labelsize": 13.2,
        "ytick.labelsize": 12,
        "legend.fontsize": 11,
        "figure.titlesize": 25,
    }
)


@dataclass(frozen=True)
class BenchConfig:
    name: str
    scenario_field: str | None


def _safe_float(v: str) -> float | None:
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    try:
        return float(s)
    except Exception:
        return None


def _safe_int(v: str) -> int | None:
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    try:
        return int(float(s))
    except Exception:
        return None


def _scenario_field(fieldnames: list[str]) -> str | None:
    for c in ["Variant", "Case", "Mode"]:
        if c in fieldnames:
            return c
    return None


def _median(xs: list[float]) -> float | None:
    if not xs:
        return None
    return statistics.median(xs)


def _sym_rel(x: float, b: float) -> float | None:
    d = x + b
    if d <= 0:
        return None
    return 2.0 * (x - b) / d


def _quantile(vals_sorted: list[float], q: float) -> float | None:
    if not vals_sorted:
        return None
    if len(vals_sorted) == 1:
        return vals_sorted[0]
    pos = (len(vals_sorted) - 1) * q
    lo = int(math.floor(pos))
    hi = min(lo + 1, len(vals_sorted) - 1)
    frac = pos - lo
    return vals_sorted[lo] * (1.0 - frac) + vals_sorted[hi] * frac


def list_benchmarks(micro_results_dir: str) -> list[BenchConfig]:
    benches: list[BenchConfig] = []
    for entry in sorted(os.listdir(micro_results_dir)):
        p = os.path.join(micro_results_dir, entry)
        if not os.path.isdir(p):
            continue
        if entry == "figures_cross_layer":
            continue
        csv_path = os.path.join(p, "experiment_results.csv")
        if not os.path.exists(csv_path):
            continue
        with open(csv_path, newline="") as f:
            r = csv.reader(f)
            header = next(r, None)
        if not header:
            continue
        benches.append(BenchConfig(name=entry, scenario_field=_scenario_field(header)))
    return benches


def load_bench_medians(micro_results_dir: str, bench: BenchConfig):
    csv_path = os.path.join(micro_results_dir, bench.name, "experiment_results.csv")
    with open(csv_path, newline="") as f:
        r = csv.DictReader(f)
        scenario_field = bench.scenario_field if bench.scenario_field in (r.fieldnames or []) else None

        runtime_samples: dict[tuple[str, str], list[float]] = defaultdict(list)
        compile_samples: dict[tuple[str, str], list[float]] = defaultdict(list)
        size_samples: dict[tuple[str, str], list[int]] = defaultdict(list)
        pass_samples: dict[str, Counter[tuple[str, str]]] = defaultdict(Counter)

        for row in r:
            if row.get("Status") and row.get("Status") != "Success":
                continue
            config = (row.get("ConfigName") or "").strip()
            if not config:
                continue

            scenario = ""
            if scenario_field:
                scenario = (row.get(scenario_field) or "").strip()

            rt = _safe_float(row.get("TotalRuntime(s)") or row.get("TotalRuntime_s"))
            if rt is not None:
                runtime_samples[(config, scenario)].append(rt)

            ct = _safe_float(row.get("CompileTime(s)") or row.get("CompileTime_s"))
            if ct is not None:
                compile_samples[(config, scenario)].append(ct)

            bs = _safe_int(row.get("BinarySize(Bytes)") or row.get("BinarySize_Bytes"))
            if bs is not None:
                size_samples[(config, scenario)].append(bs)

            mir = (row.get("MIR_Pass") or "N/A").strip()
            llvm = (row.get("LLVM_Pass") or "None").strip()
            pass_samples[config][(mir, llvm)] += 1

    scenarios = sorted({sc for (_, sc) in runtime_samples.keys()} | {sc for (_, sc) in compile_samples.keys()} | {sc for (_, sc) in size_samples.keys()})

    med_runtime: dict[tuple[str, str], float] = {}
    med_compile: dict[tuple[str, str], float] = {}
    med_size: dict[tuple[str, str], float] = {}

    for key, xs in runtime_samples.items():
        m = _median(xs)
        if m is not None:
            med_runtime[key] = m
    for key, xs in compile_samples.items():
        m = _median(xs)
        if m is not None:
            med_compile[key] = m
    for key, xs in size_samples.items():
        m = _median([float(x) for x in xs])
        if m is not None:
            med_size[key] = m

    config_to_pass: dict[str, tuple[str, str]] = {}
    for cfg, c in pass_samples.items():
        if c:
            config_to_pass[cfg] = c.most_common(1)[0][0]

    return scenarios, med_runtime, med_compile, med_size, config_to_pass


def pick_baseline_config(med_runtime: dict[tuple[str, str], float]) -> str:
    configs = {cfg for (cfg, _) in med_runtime.keys()}
    if "EXP_000_DEFAULT" in configs:
        return "EXP_000_DEFAULT"
    if "EXP_DBL_000_BASELINE" in configs:
        return "EXP_DBL_000_BASELINE"
    if "EXP_000_ALL_OFF" in configs:
        return "EXP_000_ALL_OFF"
    return "EXP_000_DEFAULT"


def compute_rel_per_bench(micro_results_dir: str, bench: BenchConfig):
    scenarios, med_rt, med_ct, med_bs, cfg_pass = load_bench_medians(micro_results_dir, bench)
    baseline_cfg = pick_baseline_config(med_rt)

    rel_rt: list[float] = []
    rel_ct: list[float] = []
    rel_bs: list[float] = []

    rel_rt_by_cfg_scn: dict[tuple[str, str], float] = {}

    for scn in scenarios:
        b_rt = med_rt.get((baseline_cfg, scn))
        b_ct = med_ct.get((baseline_cfg, scn))
        b_bs = med_bs.get((baseline_cfg, scn))
        if b_rt is None:
            continue

        for (cfg, cfg_scn), rt in med_rt.items():
            if cfg_scn != scn:
                continue
            if not cfg.startswith("EXP_DBL_"):
                continue
            if cfg == "EXP_DBL_000_BASELINE":
                continue

            r = _sym_rel(rt, b_rt)
            if r is not None:
                rel_rt.append(r)
                rel_rt_by_cfg_scn[(cfg, scn)] = r

            if b_ct is not None:
                ct = med_ct.get((cfg, scn))
                if ct is not None:
                    rc = _sym_rel(ct, b_ct)
                    if rc is not None:
                        rel_ct.append(rc)

            if b_bs is not None:
                bs = med_bs.get((cfg, scn))
                if bs is not None:
                    rs = _sym_rel(bs, b_bs)
                    if rs is not None:
                        rel_bs.append(rs)

    return {
        "bench": bench.name,
        "baseline": baseline_cfg,
        "rel_runtime": rel_rt,
        "rel_compile": rel_ct,
        "rel_size": rel_bs,
        "rel_runtime_by_cfg_scn": rel_rt_by_cfg_scn,
        "cfg_pass": cfg_pass,
        "scenario_field": bench.scenario_field,
    }


def plot_rel_histograms_clipped(per_bench: list[dict], out_dir: str):
    title = "rel distribution per benchmark (clipped for readability)"
    benches = [d["bench"] for d in per_bench]
    n = len(benches)
    nrows = 3
    ncols = 2

    fig, axes = plt.subplots(nrows=nrows, ncols=ncols, figsize=(12, 7), sharex=True)
    axes = np.array(axes).reshape(-1)

    bins = np.linspace(-2.0, 2.0, 120)
    for i, d in enumerate(per_bench):
        ax = axes[i]
        vals = np.array(d["rel_runtime"], dtype=float)
        if vals.size == 0:
            ax.set_title(d["bench"])
            continue
        vals = np.clip(vals, -2.0, 2.0)
        ax.hist(vals, bins=bins, color="#4C72B0", alpha=0.85)
        ax.axvline(0.0, color="black", linewidth=1)
        ax.set_title(d["bench"])
        ax.grid(True, axis="y", linestyle="-", alpha=0.12)

    for j in range(n, len(axes)):
        axes[j].axis("off")

    for ax in axes[:n]:
        ax.set_ylabel("count")
    for ax in axes[:n]:
        ax.set_xlabel("rel (clipped to [-2, 2])")

    fig.suptitle(title)
    fig.tight_layout(rect=[0, 0, 1, 0.95])

    png_path = os.path.join(out_dir, "rel_histograms_clipped.png")
    pdf_path = os.path.join(out_dir, "rel_histograms_clipped.pdf")
    fig.savefig(png_path, dpi=200)
    fig.savefig(pdf_path)
    plt.close(fig)


def plot_rel_histograms_unclipped_logy_symlogx(per_bench: list[dict], out_dir: str):
    title = "rel distribution per benchmark (unclipped)"
    title_pad = 24
    suptitle_rect_top = 0.99
    nrows = 1
    ncols = max(1, len(per_bench))
    fig, axes = plt.subplots(nrows=nrows, ncols=ncols, figsize=(3.2 * ncols, 7.04), sharex=False)
    axes = np.array(axes).reshape(-1)

    for i, d in enumerate(per_bench):
        ax = axes[i]
        vals = np.array(d["rel_runtime"], dtype=float)
        if vals.size == 0:
            if d["bench"] == "trait_monomorphization_bench":
                ax.set_title(d["bench"], pad=title_pad, fontweight="bold", fontsize=float(plt.rcParams["axes.titlesize"]) * 0.9)
            else:
                ax.set_title(d["bench"], pad=title_pad, fontweight="bold")
            continue
        ax.hist(vals, bins=200, color="#4C72B0", alpha=0.85)
        ax.axvline(0.0, color="black", linewidth=1)
        ax.set_title(d["bench"], pad=title_pad, fontweight="bold")
        ax.set_yscale("log")
        ax.set_xscale("symlog", linthresh=0.02, linscale=1.0)
        import matplotlib.ticker as ticker
        def custom_formatter(x, pos):
            val = round(x, 4)
            if abs(val) == 0.01:
                return ""
            return f"{x:g}"
        ax.xaxis.set_major_formatter(ticker.FuncFormatter(custom_formatter))
        for label in ax.get_xticklabels():
            label.set_fontweight("bold")
        for label in ax.get_yticklabels():
            label.set_fontweight("bold")
        ax.grid(True, which="both", axis="y", linestyle="-", alpha=0.12)

    for j in range(len(per_bench), len(axes)):
        axes[j].axis("off")

    for i, ax in enumerate(axes[: len(per_bench)]):
        if i == 0:
            ax.set_ylabel("count (log)")
        ax.set_xlabel("rel (symlog x)")

    fig.suptitle(title)
    fig.tight_layout(rect=[0, 0, 1, suptitle_rect_top])

    out_path = os.path.join(out_dir, "rel_histograms_unclipped_logy_symlogx.png")
    fig.savefig(out_path, dpi=200)
    plt.close(fig)

    nrows_pdf = 3
    ncols_pdf = 2
    scale = 1.5
    pdf_rc = {
        "font.size": float(plt.rcParams["font.size"]) * scale,
        "axes.titlesize": float(plt.rcParams["axes.titlesize"]) * scale,
        "axes.labelsize": float(plt.rcParams["axes.labelsize"]) * scale * 1.2,
        "xtick.labelsize": float(plt.rcParams["xtick.labelsize"]) * scale,
        "ytick.labelsize": float(plt.rcParams["ytick.labelsize"]) * scale,
        "legend.fontsize": float(plt.rcParams["legend.fontsize"]) * scale,
        "figure.titlesize": float(plt.rcParams["figure.titlesize"]) * scale,
    }

    with plt.rc_context(pdf_rc):
        fig, axes = plt.subplots(nrows=nrows_pdf, ncols=ncols_pdf, figsize=(12, 13.75), sharex=False)
        axes = np.array(axes).reshape(-1)

        for i, d in enumerate(per_bench[: nrows_pdf * ncols_pdf]):
            ax = axes[i]
            vals = np.array(d["rel_runtime"], dtype=float)
            if vals.size == 0:
                if d["bench"] == "trait_monomorphization_bench":
                    ax.set_title(d["bench"], pad=title_pad, fontweight="bold", fontsize=float(plt.rcParams["axes.titlesize"]) * 0.9)
                else:
                    ax.set_title(d["bench"], pad=title_pad, fontweight="bold")
                continue
            ax.hist(vals, bins=200, color="#4C72B0", alpha=0.85)
            ax.axvline(0.0, color="black", linewidth=1)
            if d["bench"] == "trait_monomorphization_bench":
                ax.set_title(d["bench"], pad=title_pad, fontweight="bold", fontsize=float(plt.rcParams["axes.titlesize"]) * 0.9)
            else:
                ax.set_title(d["bench"], pad=title_pad, fontweight="bold")
            ax.set_yscale("log")
            ax.set_xscale("symlog", linthresh=0.02, linscale=1.0)
            import matplotlib.ticker as ticker
            def custom_formatter(x, pos):
                val = round(x, 4)
                if abs(val) == 0.01:
                    return ""
                return f"{x:g}"
            ax.xaxis.set_major_formatter(ticker.FuncFormatter(custom_formatter))
            for label in ax.get_xticklabels():
                label.set_fontweight("bold")
            for label in ax.get_yticklabels():
                label.set_fontweight("bold")
            ax.grid(True, which="both", axis="y", linestyle="-", alpha=0.12)

        for j in range(min(len(per_bench), nrows_pdf * ncols_pdf), len(axes)):
            axes[j].axis("off")

        for i, ax in enumerate(axes[: min(len(per_bench), nrows_pdf * ncols_pdf)]):
            if i % ncols_pdf == 0:
                ax.set_ylabel("count (log)")
            ax.set_xlabel("rel (symlog x)")

        fig.suptitle(title)
        fig.tight_layout(rect=[0, 0, 1, suptitle_rect_top])

        out_path_pdf = os.path.join(out_dir, "rel_histograms_unclipped_logy_symlogx_3x2.pdf")
        fig.savefig(out_path_pdf)
        plt.close(fig)


def write_abs_rel_quantiles(per_bench: list[dict], out_dir: str):
    out_path = os.path.join(out_dir, "abs_rel_quantiles.csv")
    with open(out_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["benchmark", "n_pairs", "abs_rel_p50", "abs_rel_p90", "abs_rel_p99", "abs_rel_max"])
        for d in per_bench:
            abs_rel = sorted([abs(float(x)) for x in d["rel_runtime"]])
            w.writerow(
                [
                    d["bench"],
                    len(abs_rel),
                    _quantile(abs_rel, 0.5),
                    _quantile(abs_rel, 0.9),
                    _quantile(abs_rel, 0.99),
                    (abs_rel[-1] if abs_rel else None),
                ]
            )


def plot_abs_rel_boxplot(per_bench: list[dict], out_dir: str):
    labels = [d["bench"] for d in per_bench]
    data = [np.abs(np.array(d["rel_runtime"], dtype=float)) for d in per_bench]

    fig, ax = plt.subplots(figsize=(11, 4.5))
    ax.boxplot(data, tick_labels=labels, showfliers=False)
    ax.set_yscale("log")
    ax.set_ylabel("abs(rel) (log scale)")
    ax.set_title("abs(rel) distribution per benchmark")
    ax.grid(True, axis="y", linestyle="-", alpha=0.12)
    fig.tight_layout()

    out_path = os.path.join(out_dir, "abs_rel_boxplot.png")
    fig.savefig(out_path, dpi=200)
    plt.close(fig)


def plot_abs_rel_survival_loglog(per_bench: list[dict], out_dir: str):
    fig, ax = plt.subplots(figsize=(7, 5))
    for d in per_bench:
        vals = np.abs(np.array(d["rel_runtime"], dtype=float))
        vals = vals[np.isfinite(vals)]
        if vals.size == 0:
            continue
        vals = np.sort(vals)
        y = 1.0 - (np.arange(vals.size) / float(vals.size))
        ax.plot(vals, y, label=d["bench"], linewidth=1.5)

    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("abs(rel)")
    ax.set_ylabel("survival P(abs(rel) >= x)")
    ax.set_title("abs(rel) survival (log-log)")
    ax.grid(True, which="both", linestyle="-", alpha=0.12)
    ax.legend(fontsize=11)
    fig.tight_layout()

    out_path = os.path.join(out_dir, "abs_rel_survival_loglog.png")
    fig.savefig(out_path, dpi=200)
    plt.close(fig)


def plot_top_pass_frequency(per_bench: list[dict], out_dir: str, top_k_per_bench: int = 200):
    mir_counter: Counter[str] = Counter()
    llvm_counter: Counter[str] = Counter()

    for d in per_bench:
        rel_by_cfg_scn = d["rel_runtime_by_cfg_scn"]
        cfg_pass = d["cfg_pass"]

        items = sorted(rel_by_cfg_scn.items(), key=lambda kv: kv[1])
        for (cfg, _scn), _rel in items[:top_k_per_bench]:
            mir, llvm = cfg_pass.get(cfg, ("N/A", "None"))
            mir_counter[mir] += 1
            llvm_counter[llvm] += 1

    top_mir = mir_counter.most_common(15)
    top_llvm = llvm_counter.most_common(15)

    fig, axes = plt.subplots(nrows=1, ncols=2, figsize=(12, 4.5))

    if top_mir:
        names = [n for n, _ in reversed(top_mir)]
        vals = [v for _, v in reversed(top_mir)]
        axes[0].barh(names, vals, color="#4C72B0", alpha=0.9)
    axes[0].set_title(f"Top MIR passes (best {top_k_per_bench} per bench)")
    axes[0].set_xlabel("frequency")
    axes[0].grid(True, axis="x", linestyle="-", alpha=0.12)

    if top_llvm:
        names = [n for n, _ in reversed(top_llvm)]
        vals = [v for _, v in reversed(top_llvm)]
        axes[1].barh(names, vals, color="#55A868", alpha=0.9)
    axes[1].set_title(f"Top LLVM passes (best {top_k_per_bench} per bench)")
    axes[1].set_xlabel("frequency")
    axes[1].grid(True, axis="x", linestyle="-", alpha=0.12)

    fig.tight_layout()
    out_path = os.path.join(out_dir, "top_pass_frequency.png")
    fig.savefig(out_path, dpi=200)
    plt.close(fig)


def plot_case_studies_normalized(per_bench: list[dict], out_dir: str):
    fig, axes = plt.subplots(nrows=3, ncols=2, figsize=(12, 7))
    axes = np.array(axes).reshape(-1)

    for i, d in enumerate(per_bench):
        ax = axes[i]
        bench = d["bench"]
        baseline = d["baseline"]
        rels = d["rel_runtime_by_cfg_scn"]
        cfg_pass = d["cfg_pass"]

        if not rels:
            ax.set_title(bench)
            ax.axis("off")
            continue

        best_key, best_rel = min(rels.items(), key=lambda kv: kv[1])
        best_cfg, best_scn = best_key
        mir, llvm = cfg_pass.get(best_cfg, ("N/A", "None"))

        ax.bar(["runtime(rel)"], [best_rel], color="#C44E52", alpha=0.9)
        ax.axhline(0.0, color="black", linewidth=1)
        ax.set_title(bench)
        ax.set_ylabel("rel (sym)")
        ax.set_ylim(-2.0, 2.0)
        ax.grid(True, axis="y", linestyle="-", alpha=0.12)
        ax.text(
            0.02,
            0.95,
            f"{best_cfg}\n{mir} + {llvm}\n{(d['scenario_field'] or 'scenario')}={best_scn}\nbase={baseline}",
            transform=ax.transAxes,
            va="top",
            fontsize=11,
        )

    for j in range(len(per_bench), len(axes)):
        axes[j].axis("off")

    fig.suptitle("case studies (best config per benchmark, normalized as symmetric rel)")
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    out_path = os.path.join(out_dir, "case_studies_normalized.png")
    fig.savefig(out_path, dpi=200)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="micro_results directory")
    ap.add_argument(
        "--output",
        default="/mnt/fjx/Compiler_Experiment/micro_results/figures_cross_layer/new",
        help="figures_cross_layer output directory",
    )
    ap.add_argument("--topk", type=int, default=200)
    args = ap.parse_args()

    micro_results_dir = os.path.abspath(args.input)
    out_dir = os.path.abspath(args.output)
    os.makedirs(out_dir, exist_ok=True)

    benches = list_benchmarks(micro_results_dir)
    want = [
        "aggregate_scalarization_bench",
        "async_state_machine_bench",
        "branch_cfg_bench",
        "iterator_pipeline_bench",
        "loop_hoisting_bench",
        "trait_monomorphization_bench",
    ]
    by_name = {b.name: b for b in benches}
    ordered = [by_name[n] for n in want if n in by_name]
    for b in benches:
        if b.name not in by_name:
            by_name[b.name] = b
    for b in benches:
        if b.name not in want:
            ordered.append(b)

    per_bench = [compute_rel_per_bench(micro_results_dir, b) for b in ordered]

    plot_rel_histograms_clipped(per_bench, out_dir)
    plot_rel_histograms_unclipped_logy_symlogx(per_bench, out_dir)
    write_abs_rel_quantiles(per_bench, out_dir)
    plot_abs_rel_boxplot(per_bench, out_dir)
    plot_abs_rel_survival_loglog(per_bench, out_dir)
    plot_top_pass_frequency(per_bench, out_dir, top_k_per_bench=args.topk)
    plot_case_studies_normalized(per_bench, out_dir)


if __name__ == "__main__":
    main()
