import argparse
import csv
import json
import math
import os
import random
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Iterable, List, Sequence, Set, Tuple
 
 
@dataclass(frozen=True)
class Candidate:
    disabled_mir: Tuple[str, ...]
    disabled_llvm: Tuple[str, ...]
 
    def key(self) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
        return (self.disabled_mir, self.disabled_llvm)
 
 
def read_csv_rows(path: str) -> List[Dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))
 
 
def write_csv(path: str, fieldnames: Sequence[str], rows: Sequence[Dict[str, object]]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(fieldnames))
        w.writeheader()
        w.writerows(rows)
 

def _read_float(row: Dict[str, str], key: str, default: float) -> float:
    try:
        v = row.get(key, "")
        if v is None:
            return default
        s = str(v).strip()
        if not s:
            return default
        return float(s)
    except Exception:
        return default


def _read_int(row: Dict[str, str], key: str, default: int) -> int:
    try:
        v = row.get(key, "")
        if v is None:
            return default
        s = str(v).strip()
        if not s:
            return default
        return int(float(s))
    except Exception:
        return default


def _svg_escape(s: str) -> str:
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _write_svg(path: str, svg: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(svg)


def _plot_hv_svg(
    out_path: str,
    series: Dict[str, List[Tuple[float, float]]],
    hv_ref: float,
    title: str,
) -> None:
    width = 1200
    height = 720
    pad_l, pad_r, pad_t, pad_b = 80, 30, 50, 70
    plot_w = width - pad_l - pad_r
    plot_h = height - pad_t - pad_b

    all_x: List[float] = []
    all_y: List[float] = []
    for pts in series.values():
        for x, y in pts:
            all_x.append(x)
            all_y.append(y)
    if not all_x:
        return

    x_min, x_max = min(all_x), max(all_x)
    y_min, y_max = 0.0, max([max(all_y), hv_ref, 1e-9])
    if x_max <= x_min:
        x_max = x_min + 1.0
    if y_max <= y_min:
        y_max = y_min + 1.0

    def tx(x: float) -> float:
        return pad_l + (x - x_min) / (x_max - x_min) * plot_w

    def ty(y: float) -> float:
        return pad_t + (1.0 - (y - y_min) / (y_max - y_min)) * plot_h

    palette = [
        "#1f77b4",
        "#ff7f0e",
        "#2ca02c",
        "#d62728",
        "#9467bd",
        "#8c564b",
        "#e377c2",
        "#7f7f7f",
        "#bcbd22",
        "#17becf",
    ]
    keys = sorted(series.keys())
    color = {k: palette[i % len(palette)] for i, k in enumerate(keys)}

    ticks = 5
    x_ticks = [x_min + (x_max - x_min) * i / ticks for i in range(ticks + 1)]
    y_ticks = [y_min + (y_max - y_min) * i / ticks for i in range(ticks + 1)]

    parts: List[str] = []
    parts.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">')
    parts.append('<rect x="0" y="0" width="100%" height="100%" fill="white"/>')
    parts.append(f'<text x="{width/2:.1f}" y="28" text-anchor="middle" font-size="18" font-family="Arial">{_svg_escape(title)}</text>')

    parts.append(f'<line x1="{pad_l}" y1="{pad_t}" x2="{pad_l}" y2="{pad_t+plot_h}" stroke="#000" stroke-width="1"/>')
    parts.append(f'<line x1="{pad_l}" y1="{pad_t+plot_h}" x2="{pad_l+plot_w}" y2="{pad_t+plot_h}" stroke="#000" stroke-width="1"/>')

    for xv in x_ticks:
        xpix = tx(xv)
        parts.append(f'<line x1="{xpix:.2f}" y1="{pad_t+plot_h}" x2="{xpix:.2f}" y2="{pad_t+plot_h+6}" stroke="#000" stroke-width="1"/>')
        parts.append(
            f'<text x="{xpix:.2f}" y="{pad_t+plot_h+24}" text-anchor="middle" font-size="12" font-family="Arial">{int(round(xv))}</text>'
        )
        parts.append(f'<line x1="{xpix:.2f}" y1="{pad_t}" x2="{xpix:.2f}" y2="{pad_t+plot_h}" stroke="#eee" stroke-width="1"/>')

    for yv in y_ticks:
        ypix = ty(yv)
        parts.append(f'<line x1="{pad_l-6}" y1="{ypix:.2f}" x2="{pad_l}" y2="{ypix:.2f}" stroke="#000" stroke-width="1"/>')
        parts.append(
            f'<text x="{pad_l-10}" y="{ypix+4:.2f}" text-anchor="end" font-size="12" font-family="Arial">{yv:.3f}</text>'
        )
        parts.append(f'<line x1="{pad_l}" y1="{ypix:.2f}" x2="{pad_l+plot_w}" y2="{ypix:.2f}" stroke="#eee" stroke-width="1"/>')

    if hv_ref > 0:
        yref = ty(hv_ref)
        parts.append(f'<line x1="{pad_l}" y1="{yref:.2f}" x2="{pad_l+plot_w}" y2="{yref:.2f}" stroke="#333" stroke-dasharray="6,4" stroke-width="1"/>')
        parts.append(
            f'<text x="{pad_l+plot_w-2}" y="{yref-6:.2f}" text-anchor="end" font-size="12" font-family="Arial">hv_ref={hv_ref:.3f}</text>'
        )
        y95 = ty(0.95 * hv_ref)
        parts.append(f'<line x1="{pad_l}" y1="{y95:.2f}" x2="{pad_l+plot_w}" y2="{y95:.2f}" stroke="#666" stroke-dasharray="3,4" stroke-width="1"/>')
        parts.append(
            f'<text x="{pad_l+plot_w-2}" y="{y95-6:.2f}" text-anchor="end" font-size="12" font-family="Arial">0.95·hv_ref</text>'
        )

    for k in keys:
        pts = series[k]
        if len(pts) < 2:
            continue
        d = " ".join([f"L {tx(x):.2f} {ty(y):.2f}" for x, y in pts[1:]])
        parts.append(f'<path d="M {tx(pts[0][0]):.2f} {ty(pts[0][1]):.2f} {d}" fill="none" stroke="{color[k]}" stroke-width="2"/>')

    legend_x = pad_l + 10
    legend_y = pad_t + 10
    for i, k in enumerate(keys):
        y = legend_y + i * 18
        parts.append(f'<rect x="{legend_x}" y="{y-10}" width="14" height="3" fill="{color[k]}"/>')
        parts.append(f'<text x="{legend_x+20}" y="{y-7}" font-size="12" font-family="Arial">{_svg_escape(k)}</text>')

    parts.append(f'<text x="{pad_l+plot_w/2:.1f}" y="{height-24}" text-anchor="middle" font-size="14" font-family="Arial">Samples</text>')
    parts.append(f'<text x="18" y="{pad_t+plot_h/2:.1f}" text-anchor="middle" font-size="14" font-family="Arial" transform="rotate(-90 18 {pad_t+plot_h/2:.1f})">Hypervolume</text>')

    parts.append("</svg>")
    _write_svg(out_path, "\n".join(parts))


def generate_plots_for_out_dir(out_dir: str) -> List[str]:
    out_paths: List[str] = []
    summary_path = os.path.join(out_dir, "summary.csv")
    ref_path = os.path.join(out_dir, "reference.csv")
    if not os.path.exists(summary_path):
        return out_paths

    summary_rows = read_csv_rows(summary_path)
    methods = [str(r.get("method", "")).strip() for r in summary_rows if str(r.get("method", "")).strip()]
    methods = [m for m in methods if os.path.exists(os.path.join(out_dir, f"{m}_evals.csv"))]
    if not methods:
        return out_paths

    hv_ref = 0.0
    if os.path.exists(ref_path):
        ref_rows = read_csv_rows(ref_path)
        if ref_rows:
            hv_ref = _read_float(ref_rows[0], "hv_ref", 0.0)

    series: Dict[str, List[Tuple[float, float]]] = {}
    for m in methods:
        rows = read_csv_rows(os.path.join(out_dir, f"{m}_evals.csv"))
        pts: List[Tuple[float, float]] = []
        for r in rows:
            t = _read_float(r, "t", 0.0)
            hv = _read_float(r, "hv", 0.0)
            if t <= 0:
                continue
            pts.append((t, hv))
        if pts:
            series[m] = pts

    if series:
        hv_svg = os.path.join(out_dir, "hv_curve.svg")
        _plot_hv_svg(hv_svg, series, hv_ref, "Pareto Search Convergence (HV)")
        out_paths.append(hv_svg)

    try:
        import matplotlib.pyplot as plt

        if series:
            plt.figure(figsize=(10, 6))
            for m, pts in series.items():
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                plt.plot(xs, ys, label=m, linewidth=2)
            if hv_ref > 0:
                plt.axhline(hv_ref, color="#333", linestyle="--", linewidth=1, label=f"hv_ref={hv_ref:.3f}")
                plt.axhline(0.95 * hv_ref, color="#666", linestyle=":", linewidth=1, label="0.95·hv_ref")
            plt.xlabel("Samples")
            plt.ylabel("Hypervolume")
            plt.title("Pareto Search Convergence (HV)")
            plt.legend(loc="lower right", fontsize=9)
            plt.tight_layout()
            hv_png = os.path.join(out_dir, "hv_curve.png")
            hv_pdf = os.path.join(out_dir, "hv_curve.pdf")
            plt.savefig(hv_png, dpi=200)
            plt.savefig(hv_pdf)
            plt.close()
            out_paths.append(hv_png)
            out_paths.append(hv_pdf)
    except Exception:
        pass

    return out_paths

 
def generate_aggregate_hv_plots_for_out_dir(out_dir: str) -> List[str]:
    out_paths: List[str] = []
    if not os.path.isdir(out_dir):
        return out_paths

    rep_dirs: List[str] = []
    for name in sorted(os.listdir(out_dir)):
        if not name.startswith("rep_"):
            continue
        p = os.path.join(out_dir, name)
        if os.path.isdir(p):
            rep_dirs.append(p)
    if not rep_dirs:
        return out_paths

    ref_path = os.path.join(out_dir, "reference.csv")
    hv_ref = 0.0
    if os.path.exists(ref_path):
        ref_rows = read_csv_rows(ref_path)
        if ref_rows:
            hv_ref = _read_float(ref_rows[0], "hv_ref", 0.0)

    summary_all = os.path.join(out_dir, "summary_all.csv")
    methods: List[str] = []
    if os.path.exists(summary_all):
        rows = read_csv_rows(summary_all)
        seen: Set[str] = set()
        for r in rows:
            m = str(r.get("method", "")).strip()
            if not m or m in seen:
                continue
            seen.add(m)
            methods.append(m)
    else:
        rep0_summary = os.path.join(rep_dirs[0], "summary.csv")
        if os.path.exists(rep0_summary):
            rows = read_csv_rows(rep0_summary)
            methods = [str(r.get("method", "")).strip() for r in rows if str(r.get("method", "")).strip()]

    methods = [m for m in methods if m]
    if not methods:
        return out_paths

    hv_by_method: Dict[str, List[List[float]]] = {}
    budget = None
    for m in methods:
        hv_by_method[m] = []
        for rep_dir in rep_dirs:
            evals_path = os.path.join(rep_dir, f"{m}_evals.csv")
            if not os.path.exists(evals_path):
                continue
            rows = read_csv_rows(evals_path)
            hv: List[float] = []
            last = 0.0
            for r in rows:
                t = _read_int(r, "t", 0)
                if t <= 0:
                    continue
                v = _read_float(r, "hv", last)
                last = v
                hv.append(v)
            if hv:
                hv_by_method[m].append(hv)
                budget = budget or len(hv)

    if not budget or budget <= 1:
        return out_paths

    def _mean_std(xs: List[float]) -> Tuple[float, float]:
        if not xs:
            return 0.0, 0.0
        mu = sum(xs) / len(xs)
        var = sum((x - mu) ** 2 for x in xs) / max(1, (len(xs) - 1))
        return mu, math.sqrt(max(0.0, var))

    try:
        import matplotlib.pyplot as plt

        plt.figure(figsize=(10, 11))
        for m in methods:
            reps = hv_by_method.get(m, [])
            if not reps:
                continue
            ys_mean: List[float] = []
            ys_std: List[float] = []
            for i in range(budget):
                vals: List[float] = []
                for rep in reps:
                    if i < len(rep):
                        vals.append(rep[i])
                    else:
                        vals.append(rep[-1])
                mu, sd = _mean_std(vals)
                ys_mean.append(mu)
                ys_std.append(sd)
            xs = list(range(1, budget + 1))
            (line,) = plt.plot(xs, ys_mean, label=m, linewidth=4)
            c = line.get_color()
            lower = [max(0.0, a - b) for a, b in zip(ys_mean, ys_std)]
            upper = [a + b for a, b in zip(ys_mean, ys_std)]
            plt.fill_between(xs, lower, upper, color=c, alpha=0.08)
        if hv_ref > 0:
            plt.axhline(hv_ref, color="#333", linestyle="--", linewidth=2, label=f"hv_ref={hv_ref:.3f}")
            plt.axhline(0.95 * hv_ref, color="#666", linestyle=":", linewidth=2, label="0.95·hv_ref")
        plt.xlabel("Samples", fontsize=24)
        plt.ylabel("Hypervolume", fontsize=24)
        plt.title("Pareto Search Convergence (HV, mean±std)", fontsize=28)
        plt.legend(loc="lower right", fontsize=18)
        plt.xticks(fontsize=18)
        plt.yticks(fontsize=18)
        plt.tight_layout()
        out_png = os.path.join(out_dir, "hv_curve_mean_std.png")
        out_pdf = os.path.join(out_dir, "hv_curve_mean_std.pdf")
        plt.savefig(out_png, dpi=200)
        plt.savefig(out_pdf)
        plt.close()
        out_paths.extend([out_png, out_pdf])
    except Exception:
        return out_paths

    return out_paths


def load_pass_list(csv_path: str, column: str) -> List[str]:
    vals: List[str] = []
    for row in read_csv_rows(csv_path):
        v = str(row.get(column, "")).strip()
        if not v or v.lower() == "nan":
            continue
        vals.append(v)
    seen: Set[str] = set()
    out: List[str] = []
    for v in vals:
        if v in seen:
            continue
        seen.add(v)
        out.append(v)
    return out
 
 
def load_baseline_metrics(baseline_csv: str) -> Dict[str, float]:
    runtime_sum = 0.0
    compile_sum = 0.0
    size_sum = 0.0
    n = 0
    for row in read_csv_rows(baseline_csv):
        if row.get("Status") != "Success":
            continue
        try:
            runtime = float(row.get("TotalRuntime(s)", "0") or 0)
            compile_time = float(row.get("CompileTime(s)", "0") or 0)
            size = float(row.get("BinarySize(Bytes)", "0") or 0)
        except ValueError:
            continue
        if runtime <= 0 or compile_time <= 0 or size <= 0:
            continue
        runtime_sum += runtime
        compile_sum += compile_time
        size_sum += size
        n += 1
    if n == 0:
        raise RuntimeError(f"No valid baseline rows found in {baseline_csv}")
    return {"runtime": runtime_sum / n, "compile_time": compile_sum / n, "size": size_sum / n}
 
 
def load_main_effects(
    results_csv: str,
    pass_column: str,
    baseline: Dict[str, float],
    allowed_passes: Set[str],
) -> Dict[str, Dict[str, float]]:
    sums: Dict[str, Dict[str, float]] = {}
    counts: Dict[str, int] = {}
    for row in read_csv_rows(results_csv):
        if row.get("Status") != "Success":
            continue
        pass_name = str(row.get(pass_column, "")).strip()
        if not pass_name or pass_name.lower() == "nan":
            continue
        if pass_name not in allowed_passes:
            continue
        try:
            runtime = float(row.get("TotalRuntime(s)", "0") or 0)
            compile_time = float(row.get("CompileTime(s)", "0") or 0)
            size = float(row.get("BinarySize(Bytes)", "0") or 0)
        except ValueError:
            continue
        if runtime <= 0 or compile_time <= 0 or size <= 0:
            continue
 
        if pass_name not in sums:
            sums[pass_name] = {"runtime": 0.0, "compile_time": 0.0, "size": 0.0}
            counts[pass_name] = 0
        sums[pass_name]["runtime"] += runtime
        sums[pass_name]["compile_time"] += compile_time
        sums[pass_name]["size"] += size
        counts[pass_name] += 1
 
    effects: Dict[str, Dict[str, float]] = {}
    for pass_name, c in counts.items():
        if c <= 0:
            continue
        r_mean = sums[pass_name]["runtime"] / c
        c_mean = sums[pass_name]["compile_time"] / c
        s_mean = sums[pass_name]["size"] / c
        effects[pass_name] = {
            "log_runtime": math.log(r_mean) - math.log(baseline["runtime"]),
            "log_compile_time": math.log(c_mean) - math.log(baseline["compile_time"]),
            "log_size": math.log(s_mean) - math.log(baseline["size"]),
        }
    return effects
 
 
def load_coupling_edges(
    edges_csv: str,
    mir_passes: Set[str],
    llvm_passes: Set[str],
    min_stability: float,
) -> List[Tuple[str, str, float, float]]:
    out: List[Tuple[str, str, float, float]] = []
    for row in read_csv_rows(edges_csv):
        src = str(row.get("Source", "")).strip()
        tgt = str(row.get("Target", "")).strip()
        try:
            w = float(row.get("Weight", "nan"))
            s = float(row.get("Stability", "nan"))
        except ValueError:
            continue
        if not src or not tgt:
            continue
        if s < min_stability:
            continue
        if src not in mir_passes:
            continue
        if tgt not in llvm_passes:
            continue
        out.append((src, tgt, w, s))
    return out
 
 
def evaluate_candidate(
    cand: Candidate,
    baseline: Dict[str, float],
    mir_effects: Dict[str, Dict[str, float]],
    llvm_effects: Dict[str, Dict[str, float]],
    coupling: Dict[Tuple[str, str], float],
) -> Dict[str, float]:
    log_runtime = math.log(baseline["runtime"])
    log_compile = math.log(baseline["compile_time"])
    log_size = math.log(baseline["size"])
 
    for p in cand.disabled_mir:
        eff = mir_effects.get(p)
        if eff is not None:
            log_runtime += eff["log_runtime"]
            log_compile += eff["log_compile_time"]
            log_size += eff["log_size"]
 
    for p in cand.disabled_llvm:
        eff = llvm_effects.get(p)
        if eff is not None:
            log_runtime += eff["log_runtime"]
            log_compile += eff["log_compile_time"]
            log_size += eff["log_size"]
 
    for m in cand.disabled_mir:
        for l in cand.disabled_llvm:
            w = coupling.get((m, l))
            if w is not None:
                log_runtime += w
 
    runtime = math.exp(log_runtime)
    compile_time = math.exp(log_compile)
    size = math.exp(log_size)
    return {
        "runtime": runtime,
        "compile_time": compile_time,
        "size": size,
        "runtime_n": runtime / baseline["runtime"],
        "compile_time_n": compile_time / baseline["compile_time"],
        "size_n": size / baseline["size"],
        "log_runtime": log_runtime,
        "log_compile_time": log_compile,
        "log_size": log_size,
    }
 
 
def dominates(a: Sequence[float], b: Sequence[float]) -> bool:
    return all(x <= y for x, y in zip(a, b)) and any(x < y for x, y in zip(a, b))
 
 
def pareto_filter(points: List[Tuple[float, float, float]]) -> List[Tuple[float, float, float]]:
    out: List[Tuple[float, float, float]] = []
    for i, p in enumerate(points):
        dom = False
        for j, q in enumerate(points):
            if i == j:
                continue
            if dominates(q, p):
                dom = True
                break
        if not dom:
            out.append(p)
    return out
 
 
def _skyline_add(y_list: List[float], z_list: List[float], y: float, z: float) -> None:
    i = bisect_left(y_list, y)
    if i > 0 and z_list[i - 1] <= z:
        return
    if i < len(y_list) and y_list[i] == y:
        if z_list[i] <= z:
            return
        z_list[i] = z
        j = i + 1
        while j < len(y_list) and z_list[j] >= z:
            del y_list[j]
            del z_list[j]
        return
    y_list.insert(i, y)
    z_list.insert(i, z)
    j = i + 1
    while j < len(y_list) and z_list[j] >= z:
        del y_list[j]
        del z_list[j]


def _skyline_dominates(y_list: List[float], z_list: List[float], y: float, z: float) -> bool:
    i = bisect_right(y_list, y) - 1
    return i >= 0 and z_list[i] <= z


def hypervolume_3d_mc(
    points: List[Tuple[float, float, float]],
    ref: Tuple[float, float, float],
    mc_points_sorted_by_x: List[Tuple[float, float, float]],
) -> float:
    pts = [p for p in points if p[0] < ref[0] and p[1] < ref[1] and p[2] < ref[2]]
    pts.sort(key=lambda p: (p[0], p[1], p[2]))
    if not pts or not mc_points_sorted_by_x:
        return 0.0

    y_list: List[float] = []
    z_list: List[float] = []
    e = 0
    dominated = 0
    for xq, yq, zq in mc_points_sorted_by_x:
        while e < len(pts) and pts[e][0] <= xq:
            _, y, z = pts[e]
            _skyline_add(y_list, z_list, y, z)
            e += 1
        if _skyline_dominates(y_list, z_list, yq, zq):
            dominated += 1

    vol = ref[0] * ref[1] * ref[2]
    return (dominated / len(mc_points_sorted_by_x)) * vol


def hv_2d(points: List[Tuple[float, float]], ref: Tuple[float, float]) -> float:
    pts = list(points)
    pts.sort(key=lambda x: (x[0], x[1]))
    nd: List[Tuple[float, float]] = []
    best_y = float("inf")
    for x, y in pts:
        if x >= ref[0] or y >= ref[1]:
            continue
        if y < best_y:
            best_y = y
            nd.append((x, y))
    area = 0.0
    cur_y = ref[1]
    for x, y in nd:
        if y >= cur_y:
            continue
        area += (ref[0] - x) * (cur_y - y)
        cur_y = y
    return max(0.0, area)
 
 
def hypervolume_3d(points: List[Tuple[float, float, float]], ref: Tuple[float, float, float]) -> float:
    pts = [p for p in points if p[0] < ref[0] and p[1] < ref[1] and p[2] < ref[2]]
    pts = pareto_filter(pts)
    pts.sort(key=lambda p: (p[0], p[1], p[2]))
    if not pts:
        return 0.0
    hv = 0.0
    for i, p in enumerate(pts):
        x0 = p[0]
        x1 = pts[i + 1][0] if i + 1 < len(pts) else ref[0]
        if x1 <= x0:
            continue
        yz = [(q[1], q[2]) for q in pts[: i + 1]]
        a = hv_2d(yz, (ref[1], ref[2]))
        hv += (x1 - x0) * a
    return max(0.0, hv)
 
 
def graph_centrality(
    edges: Sequence[Tuple[str, str, float, float]],
    mir_passes: Sequence[str],
    llvm_passes: Sequence[str],
) -> Tuple[Dict[str, float], Dict[str, Set[str]]]:
    adj: Dict[str, Set[str]] = {p: set() for p in list(mir_passes) + list(llvm_passes)}
    score: Dict[str, float] = {p: 0.0 for p in adj}
    for m, l, w, s in edges:
        weight = abs(w) * max(0.0, min(1.0, s))
        score[m] = score.get(m, 0.0) + weight
        score[l] = score.get(l, 0.0) + weight
        if m in adj:
            adj[m].add(l)
        if l in adj:
            adj[l].add(m)
    return score, adj
 
 
def pick_hubs(score: Dict[str, float], k: int) -> List[str]:
    items = [(p, v) for p, v in score.items() if v > 0]
    items.sort(key=lambda x: (-x[1], x[0]))
    return [p for p, _ in items[: max(0, k)]]
 

def _pick_hubs_by_degree(adj: Dict[str, Set[str]], k: int) -> List[str]:
    items = [(p, len(nbs)) for p, nbs in adj.items() if nbs]
    items.sort(key=lambda x: (-x[1], x[0]))
    return [p for p, _ in items[: max(0, k)]]


def _pagerank(adj: Dict[str, Set[str]], iters: int = 60, damping: float = 0.85) -> Dict[str, float]:
    nodes = list(adj.keys())
    n = len(nodes)
    if n == 0:
        return {}
    idx = {p: i for i, p in enumerate(nodes)}
    outdeg = [len(adj[p]) for p in nodes]
    pr = [1.0 / n] * n
    base = (1.0 - damping) / n
    for _ in range(max(1, iters)):
        nxt = [base] * n
        for u, p in enumerate(nodes):
            if outdeg[u] <= 0:
                share = damping * pr[u] / n
                for v in range(n):
                    nxt[v] += share
                continue
            share = damping * pr[u] / outdeg[u]
            for q in adj[p]:
                v = idx.get(q)
                if v is not None:
                    nxt[v] += share
        pr = nxt
    return {nodes[i]: pr[i] for i in range(n)}


def _pick_hubs_by_pagerank(adj: Dict[str, Set[str]], k: int) -> List[str]:
    pr = _pagerank(adj)
    items = [(p, pr.get(p, 0.0)) for p in adj.keys() if pr.get(p, 0.0) > 0.0]
    items.sort(key=lambda x: (-x[1], x[0]))
    return [p for p, _ in items[: max(0, k)]]


def _betweenness(adj: Dict[str, Set[str]]) -> Dict[str, float]:
    nodes = list(adj.keys())
    c = {v: 0.0 for v in nodes}
    for s in nodes:
        stack: List[str] = []
        pred: Dict[str, List[str]] = {v: [] for v in nodes}
        sigma = {v: 0.0 for v in nodes}
        sigma[s] = 1.0
        dist = {v: -1 for v in nodes}
        dist[s] = 0
        q: List[str] = [s]
        qi = 0
        while qi < len(q):
            v = q[qi]
            qi += 1
            stack.append(v)
            for w in adj.get(v, set()):
                if dist[w] < 0:
                    q.append(w)
                    dist[w] = dist[v] + 1
                if dist[w] == dist[v] + 1:
                    sigma[w] += sigma[v]
                    pred[w].append(v)
        delta = {v: 0.0 for v in nodes}
        while stack:
            w = stack.pop()
            for v in pred[w]:
                if sigma[w] > 0:
                    delta[v] += (sigma[v] / sigma[w]) * (1.0 + delta[w])
            if w != s:
                c[w] += delta[w]
    return c


def _pick_hubs_by_betweenness(adj: Dict[str, Set[str]], k: int) -> List[str]:
    bc = _betweenness(adj)
    items = [(p, bc.get(p, 0.0)) for p in adj.keys() if bc.get(p, 0.0) > 0.0]
    items.sort(key=lambda x: (-x[1], x[0]))
    return [p for p, _ in items[: max(0, k)]]


def select_hubs(
    metric: str,
    score: Dict[str, float],
    adj: Dict[str, Set[str]],
    k: int,
) -> List[str]:
    m = str(metric or "weighted_degree").strip().lower()
    if m in ("weighted_degree", "weighted-degree", "wdeg"):
        return pick_hubs(score, k)
    if m in ("degree",):
        return _pick_hubs_by_degree(adj, k)
    if m in ("pagerank", "page_rank"):
        return _pick_hubs_by_pagerank(adj, k)
    if m in ("betweenness", "btw"):
        return _pick_hubs_by_betweenness(adj, k)
    raise ValueError(f"Unknown hub metric: {metric}")
 
def candidate_from_bits(
    bits_mir: Sequence[int],
    bits_llvm: Sequence[int],
    mir_passes: Sequence[str],
    llvm_passes: Sequence[str],
) -> Candidate:
    dm = tuple(sorted([mir_passes[i] for i, b in enumerate(bits_mir) if b]))
    dl = tuple(sorted([llvm_passes[i] for i, b in enumerate(bits_llvm) if b]))
    return Candidate(dm, dl)
 
 
def bits_from_candidate(
    cand: Candidate,
    mir_index: Dict[str, int],
    llvm_index: Dict[str, int],
    n_mir: int,
    n_llvm: int,
) -> Tuple[List[int], List[int]]:
    bm = [0] * n_mir
    bl = [0] * n_llvm
    for p in cand.disabled_mir:
        i = mir_index.get(p)
        if i is not None:
            bm[i] = 1
    for p in cand.disabled_llvm:
        i = llvm_index.get(p)
        if i is not None:
            bl[i] = 1
    return bm, bl
 
 
def random_bits(rng: random.Random, n: int, p: float) -> List[int]:
    return [1 if rng.random() < p else 0 for _ in range(n)]
 
 
def mutate_bits(rng: random.Random, bits: List[int], p_flip: float) -> None:
    for i in range(len(bits)):
        if rng.random() < p_flip:
            bits[i] = 0 if bits[i] else 1
 
 
def crossover(rng: random.Random, a: List[int], b: List[int]) -> Tuple[List[int], List[int]]:
    if len(a) != len(b):
        raise ValueError("bit length mismatch")
    c1 = a[:]
    c2 = b[:]
    for i in range(len(a)):
        if rng.random() < 0.5:
            c1[i], c2[i] = c2[i], c1[i]
    return c1, c2
 
 
def fast_nondominated_sort(objs: List[Tuple[float, float, float]]) -> List[List[int]]:
    n = len(objs)
    s: List[List[int]] = [[] for _ in range(n)]
    n_dom = [0] * n
    fronts: List[List[int]] = [[]]
    for p in range(n):
        for q in range(n):
            if p == q:
                continue
            if dominates(objs[p], objs[q]):
                s[p].append(q)
            elif dominates(objs[q], objs[p]):
                n_dom[p] += 1
        if n_dom[p] == 0:
            fronts[0].append(p)
    i = 0
    while i < len(fronts) and fronts[i]:
        nxt: List[int] = []
        for p in fronts[i]:
            for q in s[p]:
                n_dom[q] -= 1
                if n_dom[q] == 0:
                    nxt.append(q)
        i += 1
        if nxt:
            fronts.append(nxt)
    return fronts
 
 
def crowding_distance(front: List[int], objs: List[Tuple[float, float, float]]) -> Dict[int, float]:
    dist: Dict[int, float] = {i: 0.0 for i in front}
    if len(front) <= 2:
        for i in front:
            dist[i] = float("inf")
        return dist
    m = 3
    for k in range(m):
        front_sorted = sorted(front, key=lambda i: objs[i][k])
        dist[front_sorted[0]] = float("inf")
        dist[front_sorted[-1]] = float("inf")
        min_v = objs[front_sorted[0]][k]
        max_v = objs[front_sorted[-1]][k]
        if max_v <= min_v:
            continue
        for t in range(1, len(front_sorted) - 1):
            i = front_sorted[t]
            prev_v = objs[front_sorted[t - 1]][k]
            next_v = objs[front_sorted[t + 1]][k]
            dist[i] += (next_v - prev_v) / (max_v - min_v)
    return dist
 
 
def nsga2(
    rng: random.Random,
    n_eval: int,
    pop_size: int,
    n_mir: int,
    n_llvm: int,
    eval_fn,
    init_p: float,
    canonicalize_fn=None,
) -> List[Tuple[Candidate, Dict[str, float]]]:
    if n_eval <= 0:
        return []
    pop_size = max(2, pop_size)
    p_flip_mir = 1.0 / max(1, n_mir)
    p_flip_llvm = 1.0 / max(1, n_llvm)

    seen: Set[Tuple[Tuple[int, ...], Tuple[int, ...]]] = set()
    history: List[Tuple[Candidate, Dict[str, float]]] = []

    def sample_unique_bits() -> Tuple[List[int], List[int]]:
        for _ in range(2000):
            bm = random_bits(rng, n_mir, init_p)
            bl = random_bits(rng, n_llvm, init_p)
            if canonicalize_fn is not None:
                canonicalize_fn(bm, bl)
            key = (tuple(bm), tuple(bl))
            if key in seen:
                continue
            seen.add(key)
            return bm, bl
        bm = random_bits(rng, n_mir, init_p)
        bl = random_bits(rng, n_llvm, init_p)
        if canonicalize_fn is not None:
            canonicalize_fn(bm, bl)
        seen.add((tuple(bm), tuple(bl)))
        return bm, bl

    def evaluate_bits(bm: List[int], bl: List[int]) -> Tuple[Candidate, Dict[str, float]]:
        cand, met = eval_fn(bm, bl)
        history.append((cand, met))
        return cand, met

    pop_bits: List[Tuple[List[int], List[int]]] = []
    pop_mets: List[Dict[str, float]] = []
    while len(pop_bits) < pop_size and len(history) < n_eval:
        bm, bl = sample_unique_bits()
        _, met = evaluate_bits(bm, bl)
        pop_bits.append((bm, bl))
        pop_mets.append(met)

    while len(history) < n_eval:
        objs = [(m["runtime_n"], m["compile_time_n"], m["size_n"]) for m in pop_mets]
        fronts = fast_nondominated_sort(objs)
        ranks: Dict[int, int] = {}
        crowd: Dict[int, float] = {}
        for r, f in enumerate(fronts):
            for i in f:
                ranks[i] = r
            crowd.update(crowding_distance(f, objs))

        def tournament() -> int:
            a = rng.randrange(len(pop_bits))
            b = rng.randrange(len(pop_bits))
            ra = ranks.get(a, 10**9)
            rb = ranks.get(b, 10**9)
            if ra < rb:
                return a
            if rb < ra:
                return b
            ca = crowd.get(a, 0.0)
            cb = crowd.get(b, 0.0)
            if ca > cb:
                return a
            if cb > ca:
                return b
            return a if rng.random() < 0.5 else b

        children_bits: List[Tuple[List[int], List[int]]] = []
        while len(children_bits) < pop_size and len(history) < n_eval:
            p1 = pop_bits[tournament()]
            p2 = pop_bits[tournament()]
            c1m, c2m = crossover(rng, p1[0], p2[0])
            c1l, c2l = crossover(rng, p1[1], p2[1])
            mutate_bits(rng, c1m, p_flip_mir)
            mutate_bits(rng, c1l, p_flip_llvm)
            mutate_bits(rng, c2m, p_flip_mir)
            mutate_bits(rng, c2l, p_flip_llvm)
            if canonicalize_fn is not None:
                canonicalize_fn(c1m, c1l)
                canonicalize_fn(c2m, c2l)
            for bm, bl in ((c1m, c1l), (c2m, c2l)):
                if len(children_bits) >= pop_size or len(history) >= n_eval:
                    break
                key = (tuple(bm), tuple(bl))
                if key in seen:
                    continue
                seen.add(key)
                children_bits.append((bm, bl))

        children_mets: List[Dict[str, float]] = []
        for bm, bl in children_bits:
            _, met = evaluate_bits(bm, bl)
            children_mets.append(met)
            if len(history) >= n_eval:
                break

        combined_bits = pop_bits + children_bits
        combined_mets = pop_mets + children_mets
        combined_objs = [(m["runtime_n"], m["compile_time_n"], m["size_n"]) for m in combined_mets]
        combined_fronts = fast_nondominated_sort(combined_objs)

        next_idx: List[int] = []
        for f in combined_fronts:
            if len(next_idx) + len(f) <= pop_size:
                next_idx.extend(f)
                continue
            dist = crowding_distance(f, combined_objs)
            f_sorted = sorted(f, key=lambda i: dist.get(i, 0.0), reverse=True)
            next_idx.extend(f_sorted[: max(0, pop_size - len(next_idx))])
            break

        pop_bits = [combined_bits[i] for i in next_idx]
        pop_mets = [combined_mets[i] for i in next_idx]

    return history[:n_eval]
 
 
def bayes_linear_thompson(
    rng: random.Random,
    n_eval: int,
    n_mir: int,
    n_llvm: int,
    eval_fn,
    init_p: float,
    pool_size: int,
    canonicalize_fn=None,
) -> List[Tuple[Candidate, Dict[str, float]]]:
    if n_eval <= 0:
        return []
    d = n_mir + n_llvm
    alpha = 1.0
    beta = 10.0
    warmup = min(n_eval, max(40, d // 2))

    seen: Set[Tuple[Tuple[int, ...], Tuple[int, ...]]] = set()
    history: List[Tuple[Candidate, Dict[str, float]]] = []
    x_active: List[List[int]] = []
    o_list: List[Tuple[float, float, float]] = []

    def sample_unique_bits() -> Tuple[List[int], List[int]]:
        for _ in range(2000):
            bm = random_bits(rng, n_mir, init_p)
            bl = random_bits(rng, n_llvm, init_p)
            if canonicalize_fn is not None:
                canonicalize_fn(bm, bl)
            key = (tuple(bm), tuple(bl))
            if key in seen:
                continue
            seen.add(key)
            return bm, bl
        bm = random_bits(rng, n_mir, init_p)
        bl = random_bits(rng, n_llvm, init_p)
        if canonicalize_fn is not None:
            canonicalize_fn(bm, bl)
        seen.add((tuple(bm), tuple(bl)))
        return bm, bl

    def active_idx(bm: List[int], bl: List[int]) -> List[int]:
        out: List[int] = []
        for i, b in enumerate(bm):
            if b:
                out.append(i)
        off = n_mir
        for i, b in enumerate(bl):
            if b:
                out.append(off + i)
        return out

    for _ in range(warmup):
        bm, bl = sample_unique_bits()
        cand, met = eval_fn(bm, bl)
        history.append((cand, met))
        x_active.append(active_idx(bm, bl))
        o_list.append((met["runtime_n"], met["compile_time_n"], met["size_n"]))
        if len(history) >= n_eval:
            return history[:n_eval]

    while len(history) < n_eval:
        w = [rng.expovariate(1.0) for _ in range(3)]
        s_w = sum(w) or 1.0
        w = [x / s_w for x in w]
        y_list = [w[0] * math.log(o[0]) + w[1] * math.log(o[1]) + w[2] * math.log(o[2]) for o in o_list]

        sum_x2 = [0.0] * d
        sum_xy = [0.0] * d
        for act, y in zip(x_active, y_list):
            for j in act:
                sum_x2[j] += 1.0
                sum_xy[j] += y

        theta = [0.0] * d
        for j in range(d):
            prec = alpha + beta * sum_x2[j]
            var = 1.0 / prec
            mean = (beta * sum_xy[j]) / prec
            theta[j] = rng.gauss(mean, math.sqrt(var))

        best_bits: Tuple[List[int], List[int]] | None = None
        best_score = float("inf")
        for _ in range(pool_size):
            bm, bl = sample_unique_bits()
            act = active_idx(bm, bl)
            score = sum(theta[j] for j in act)
            if score < best_score:
                best_score = score
                best_bits = (bm, bl)
        bm, bl = best_bits if best_bits is not None else sample_unique_bits()
        cand, met = eval_fn(bm, bl)
        history.append((cand, met))
        x_active.append(active_idx(bm, bl))
        o_list.append((met["runtime_n"], met["compile_time_n"], met["size_n"]))

    return history[:n_eval]
 
 
class Evaluator:
    def __init__(
        self,
        baseline: Dict[str, float],
        mir_passes: Sequence[str],
        llvm_passes: Sequence[str],
        mir_effects: Dict[str, Dict[str, float]],
        llvm_effects: Dict[str, Dict[str, float]],
        coupling: Dict[Tuple[str, str], float],
        allowed_mir: Set[str],
        allowed_llvm: Set[str],
    ) -> None:
        self.baseline = baseline
        self.mir_passes = list(mir_passes)
        self.llvm_passes = list(llvm_passes)
        self.mir_index = {p: i for i, p in enumerate(self.mir_passes)}
        self.llvm_index = {p: i for i, p in enumerate(self.llvm_passes)}
        self.mir_effects = mir_effects
        self.llvm_effects = llvm_effects
        self.coupling = coupling
        self.allowed_mir = set(allowed_mir)
        self.allowed_llvm = set(allowed_llvm)
    def eval_bits(self, bm: List[int], bl: List[int]) -> Tuple[Candidate, Dict[str, float]]:
        dm = [self.mir_passes[i] for i, b in enumerate(bm) if b and self.mir_passes[i] in self.allowed_mir]
        dl = [self.llvm_passes[i] for i, b in enumerate(bl) if b and self.llvm_passes[i] in self.allowed_llvm]
        cand = Candidate(tuple(sorted(dm)), tuple(sorted(dl)))
        return cand, evaluate_candidate(cand, self.baseline, self.mir_effects, self.llvm_effects, self.coupling)
 
 
def run_method(
    method: str,
    rng: random.Random,
    evaluator: Evaluator,
    budget: int,
    hub_mir: Set[str],
    hub_llvm: Set[str],
    neighbor_mir: Set[str],
    neighbor_llvm: Set[str],
    hub_budget_ratio: float,
    pop_size: int,
    node_score: Dict[str, float],
    adj: Dict[str, Set[str]],
) -> List[Tuple[Candidate, Dict[str, float]]]:
    n_mir = len(evaluator.mir_passes)
    n_llvm = len(evaluator.llvm_passes)
    init_p = 0.1
 
    def canonicalize(bm: List[int], bl: List[int]) -> None:
        for i, p in enumerate(evaluator.mir_passes):
            if p not in evaluator.allowed_mir:
                bm[i] = 0
        for i, p in enumerate(evaluator.llvm_passes):
            if p not in evaluator.allowed_llvm:
                bl[i] = 0
 
    if method == "random":
        out: List[Tuple[Candidate, Dict[str, float]]] = []
        for _ in range(budget):
            bm = random_bits(rng, n_mir, init_p)
            bl = random_bits(rng, n_llvm, init_p)
            canonicalize(bm, bl)
            out.append(evaluator.eval_bits(bm, bl))
        return out
 
    if method == "ga":
        return nsga2(
            rng=rng,
            n_eval=budget,
            pop_size=pop_size,
            n_mir=n_mir,
            n_llvm=n_llvm,
            eval_fn=evaluator.eval_bits,
            init_p=init_p,
            canonicalize_fn=canonicalize,
        )
 
    if method == "bo":
        return bayes_linear_thompson(
            rng=rng,
            n_eval=budget,
            n_mir=n_mir,
            n_llvm=n_llvm,
            eval_fn=evaluator.eval_bits,
            init_p=init_p,
            pool_size=max(200, pop_size * 10),
            canonicalize_fn=canonicalize,
        )
 
    if method == "ggps_neighbor_only":
        base_allowed_mir = evaluator.allowed_mir
        base_allowed_llvm = evaluator.allowed_llvm
        evaluator.allowed_mir = set(neighbor_mir)
        evaluator.allowed_llvm = set(neighbor_llvm)
        out = nsga2(
            rng=rng,
            n_eval=budget,
            pop_size=max(10, min(pop_size, budget)),
            n_mir=n_mir,
            n_llvm=n_llvm,
            eval_fn=evaluator.eval_bits,
            init_p=0.08,
            canonicalize_fn=canonicalize,
        )
        evaluator.allowed_mir = set(base_allowed_mir)
        evaluator.allowed_llvm = set(base_allowed_llvm)
        return out[:budget]

    if method in (
        "ggps",
        "ggps_random_subspace",
        "ggps_nonhub_subspace",
        "ggps_no_centrality",
        "ggps_hub_only",
    ):
        if method == "ggps_hub_only":
            step2_budget = max(1, int(budget))
            step3_budget = 0
        else:
            step2_budget = max(1, int(budget * hub_budget_ratio))
            step3_budget = max(0, budget - step2_budget)
 
        if method == "ggps_random_subspace":
            all_mir = list(evaluator.allowed_mir)
            all_llvm = list(evaluator.allowed_llvm)
            rng.shuffle(all_mir)
            rng.shuffle(all_llvm)
            hub_mir = set(all_mir[: len(hub_mir)])
            hub_llvm = set(all_llvm[: len(hub_llvm)])
        elif method == "ggps_nonhub_subspace":
            all_nodes = sorted(list(evaluator.allowed_mir | evaluator.allowed_llvm), key=lambda p: (node_score.get(p, 0.0), p))
            hub_mir = set([p for p in all_nodes if p in evaluator.allowed_mir][: len(hub_mir)])
            hub_llvm = set([p for p in all_nodes if p in evaluator.allowed_llvm][: len(hub_llvm)])
        elif method == "ggps_no_centrality":
            mir_candidates = [p for p in evaluator.allowed_mir if adj.get(p)]
            llvm_candidates = [p for p in evaluator.allowed_llvm if adj.get(p)]
            rng.shuffle(mir_candidates)
            rng.shuffle(llvm_candidates)
            hub_mir = set(mir_candidates[: len(hub_mir)])
            hub_llvm = set(llvm_candidates[: len(hub_llvm)])
 
        base_allowed_mir = evaluator.allowed_mir
        base_allowed_llvm = evaluator.allowed_llvm
 
        evaluator.allowed_mir = set(hub_mir)
        evaluator.allowed_llvm = set(hub_llvm)
        step2 = nsga2(
            rng=rng,
            n_eval=step2_budget,
            pop_size=max(10, min(pop_size, step2_budget)),
            n_mir=n_mir,
            n_llvm=n_llvm,
            eval_fn=evaluator.eval_bits,
            init_p=0.08,
            canonicalize_fn=canonicalize,
        )
 
        fronts = pareto_filter([(m["runtime_n"], m["compile_time_n"], m["size_n"]) for _, m in step2])
        elite: List[Tuple[Candidate, Dict[str, float]]] = []
        for cand, met in step2:
            o = (met["runtime_n"], met["compile_time_n"], met["size_n"])
            if o in fronts:
                elite.append((cand, met))
        if not elite:
            elite = step2[- min(len(step2), 5) :]
 
        evaluator.allowed_mir = set(base_allowed_mir)
        evaluator.allowed_llvm = set(base_allowed_llvm)
 
        out = list(step2)
        if step3_budget <= 0:
            return out[:budget]
 
        neighbor_mir = set(neighbor_mir) | set(hub_mir)
        neighbor_llvm = set(neighbor_llvm) | set(hub_llvm)
 
        elites = elite[: min(len(elite), max(5, pop_size // 2))]
        for _ in range(step3_budget):
            base_cand, _ = rng.choice(elites)
            bm, bl = bits_from_candidate(base_cand, evaluator.mir_index, evaluator.llvm_index, n_mir, n_llvm)
            for i in range(n_mir):
                p = evaluator.mir_passes[i]
                if p not in neighbor_mir:
                    bm[i] = 1 if p in base_cand.disabled_mir else 0
            for i in range(n_llvm):
                p = evaluator.llvm_passes[i]
                if p not in neighbor_llvm:
                    bl[i] = 1 if p in base_cand.disabled_llvm else 0
            for _ in range(rng.randint(1, 4)):
                if rng.random() < 0.5 and neighbor_mir:
                    p = rng.choice(list(neighbor_mir))
                    i = evaluator.mir_index.get(p)
                    if i is not None:
                        bm[i] = 0 if bm[i] else 1
                elif neighbor_llvm:
                    p = rng.choice(list(neighbor_llvm))
                    i = evaluator.llvm_index.get(p)
                    if i is not None:
                        bl[i] = 0 if bl[i] else 1
            canonicalize(bm, bl)
            out.append(evaluator.eval_bits(bm, bl))
        return out[:budget]
 
    raise ValueError(f"Unknown method: {method}")
 
 
def compute_hv_curve(
    evals: List[Tuple[Candidate, Dict[str, float]]],
    ref: Tuple[float, float, float],
    mc_points_sorted_by_x: List[Tuple[float, float, float]],
    stride: int,
) -> List[float]:
    pts: List[Tuple[float, float, float]] = []
    curve: List[float] = []
    stride = max(1, int(stride))
    last_hv = 0.0
    for t, (_, m) in enumerate(evals, 1):
        pts.append((m["runtime_n"], m["compile_time_n"], m["size_n"]))
        if (t % stride) == 0 or t == len(evals):
            last_hv = hypervolume_3d_mc(pts, ref, mc_points_sorted_by_x)
        curve.append(last_hv)
    return curve
 
 
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--analysis-root", default="/mnt/fjx/Compiler_Experiment/serde_test/analysis")
    ap.add_argument("--out-root", default="/mnt/fjx/Compiler_Experiment/serde_test/analysis/pareto/out")
    ap.add_argument("--plot-only", default="")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--budget", type=int, default=1200)
    ap.add_argument("--ref-budget", type=int, default=12000)
    ap.add_argument("--min-stability", type=float, default=0.4)
    ap.add_argument("--topk", type=int, default=12)
    ap.add_argument("--hub-metric", default="weighted_degree")
    ap.add_argument("--hub-budget-ratio", type=float, default=0.55)
    ap.add_argument("--pop-size", type=int, default=48)
    ap.add_argument(
        "--methods",
        default="ggps,ggps_hub_only,ggps_neighbor_only,ggps_no_centrality,random,bo,ga,ggps_random_subspace,ggps_nonhub_subspace",
    )
    ap.add_argument("--hv-mc", type=int, default=8000)
    ap.add_argument("--hv-stride", type=int, default=20)
    args = ap.parse_args()
 
    if str(args.plot_only).strip():
        out_dir = str(args.plot_only).strip()
        if out_dir.startswith("\\") and not out_dir.startswith("/"):
            out_dir = out_dir.replace("\\", "/")
        out_dir = os.path.abspath(out_dir)
        _ = generate_plots_for_out_dir(out_dir)
        _ = generate_aggregate_hv_plots_for_out_dir(out_dir)
        for name in sorted(os.listdir(out_dir)) if os.path.isdir(out_dir) else []:
            if not name.startswith("rep_"):
                continue
            p = os.path.join(out_dir, name)
            if os.path.isdir(p):
                _ = generate_plots_for_out_dir(p)
        return

    baseline_csv = os.path.join(args.analysis_root, "data", "baseline.csv")
    mir_results_csv = os.path.join(args.analysis_root, "data", "experiment_results_mir.csv")
    llvm_results_csv = os.path.join(args.analysis_root, "data", "experiment_results_llvm.csv")
    edges_csv_candidates = [
        os.path.join(args.analysis_root, "coupling_graph", "coupling_edges.csv"),
        os.path.join(args.analysis_root, "two", "lasso", "coupling_edges.csv"),
    ]
    edges_csv = next((p for p in edges_csv_candidates if os.path.exists(p)), edges_csv_candidates[0])
    mir_coverage_csv = os.path.join(args.analysis_root, "lasso", "results", "mir_coverage.csv")
    llvm_coverage_csv = os.path.join(args.analysis_root, "lasso", "results", "llvm_coverage.csv")
 
    mir_passes = load_pass_list(mir_coverage_csv, "MIR_Pass")
    llvm_passes = load_pass_list(llvm_coverage_csv, "LLVM_Pass")
    mir_set = set(mir_passes)
    llvm_set = set(llvm_passes)
 
    baseline = load_baseline_metrics(baseline_csv)
    mir_effects = load_main_effects(mir_results_csv, "MIR_Pass", baseline, mir_set)
    llvm_effects = load_main_effects(llvm_results_csv, "LLVM_Pass", baseline, llvm_set)
 
    edges = load_coupling_edges(edges_csv, mir_set, llvm_set, args.min_stability)
    coupling: Dict[Tuple[str, str], float] = {(m, l): w for (m, l, w, _) in edges}
 
    score, adj = graph_centrality(edges, mir_passes, llvm_passes)
    hubs = select_hubs(args.hub_metric, score, adj, args.topk)
    hub_mir = set([p for p in hubs if p in mir_set])
    hub_llvm = set([p for p in hubs if p in llvm_set])
    neighbor_mir: Set[str] = set()
    neighbor_llvm: Set[str] = set()
    for p in hubs:
        for nb in adj.get(p, set()):
            if nb in mir_set:
                neighbor_mir.add(nb)
            if nb in llvm_set:
                neighbor_llvm.add(nb)
 
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.out_root, run_id)
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "config.json"), "w", encoding="utf-8") as f:
        json.dump(vars(args), f, ensure_ascii=False, indent=2)
 
    n_edges = len(edges)
    density = n_edges / max(1, (len(mir_passes) * len(llvm_passes)))
    deg_vals = sorted([len(adj.get(p, set())) for p in list(mir_set | llvm_set)], reverse=True)
    top10_share = sum(deg_vals[:10]) / max(1, sum(deg_vals)) if deg_vals else 0.0
    write_csv(
        os.path.join(out_dir, "graph_stats.csv"),
        ["n_mir", "n_llvm", "n_edges", "density", "top10_degree_share"],
        [
            {
                "n_mir": len(mir_passes),
                "n_llvm": len(llvm_passes),
                "n_edges": n_edges,
                "density": density,
                "top10_degree_share": top10_share,
            }
        ],
    )
    hub_rows = []
    for p in hubs:
        hub_rows.append(
            {
                "pass": p,
                "side": "MIR" if p in mir_set else "LLVM",
                "weighted_degree": score.get(p, 0.0),
                "degree": len(adj.get(p, set())),
            }
        )
    write_csv(os.path.join(out_dir, "hubs.csv"), ["pass", "side", "weighted_degree", "degree"], hub_rows)
 
    ref_point = (2.0, 2.0, 2.0)
    rng_mc = random.Random(args.seed + 424242)
    mc = [
        (
            rng_mc.random() * ref_point[0],
            rng_mc.random() * ref_point[1],
            rng_mc.random() * ref_point[2],
        )
        for _ in range(max(1, int(args.hv_mc)))
    ]
    mc.sort(key=lambda p: (p[0], p[1], p[2]))
    rng_ref = random.Random(args.seed + 9991)
    ref_eval = Evaluator(
        baseline=baseline,
        mir_passes=mir_passes,
        llvm_passes=llvm_passes,
        mir_effects=mir_effects,
        llvm_effects=llvm_effects,
        coupling=coupling,
        allowed_mir=mir_set,
        allowed_llvm=llvm_set,
    )
    ref_evals = run_method(
        method="random",
        rng=rng_ref,
        evaluator=ref_eval,
        budget=args.ref_budget,
        hub_mir=hub_mir,
        hub_llvm=hub_llvm,
        neighbor_mir=neighbor_mir,
        neighbor_llvm=neighbor_llvm,
        hub_budget_ratio=args.hub_budget_ratio,
        pop_size=args.pop_size,
        node_score=score,
        adj=adj,
    )
    ref_pts = [(m["runtime_n"], m["compile_time_n"], m["size_n"]) for _, m in ref_evals]
    hv_ref = hypervolume_3d_mc(ref_pts, ref_point, mc)
    write_csv(
        os.path.join(out_dir, "reference.csv"),
        [
            "ref_point_runtime_n",
            "ref_point_compile_time_n",
            "ref_point_size_n",
            "ref_budget",
            "hv_ref",
            "hv_mc",
        ],
        [
            {
                "ref_point_runtime_n": ref_point[0],
                "ref_point_compile_time_n": ref_point[1],
                "ref_point_size_n": ref_point[2],
                "ref_budget": args.ref_budget,
                "hv_ref": hv_ref,
                "hv_mc": int(args.hv_mc),
            }
        ],
    )
 
    methods = [m.strip() for m in str(args.methods).split(",") if m.strip()]
    repeats = max(1, int(args.repeats))
    per_rep_summary_rows: List[Dict[str, object]] = []
    per_method_hv_final: Dict[str, List[float]] = {m: [] for m in methods}
    per_method_t95: Dict[str, List[int]] = {m: [] for m in methods}
    per_method_success: Dict[str, int] = {m: 0 for m in methods}
    hv_curves_last: Dict[str, List[float]] = {}

    for rep in range(repeats):
        rep_dir = out_dir if repeats == 1 else os.path.join(out_dir, f"rep_{rep:02d}")
        os.makedirs(rep_dir, exist_ok=True)
        hv_curves: Dict[str, List[float]] = {}

        for method in methods:
            print(
                f"rep={rep} method={method} budget={args.budget} topk={args.topk} hub_metric={args.hub_metric} min_stability={args.min_stability}",
                flush=True,
            )
            rng = random.Random(args.seed + rep * 10007 + (abs(hash(method)) % 100000))
            evaluator = Evaluator(
                baseline=baseline,
                mir_passes=mir_passes,
                llvm_passes=llvm_passes,
                mir_effects=mir_effects,
                llvm_effects=llvm_effects,
                coupling=coupling,
                allowed_mir=mir_set,
                allowed_llvm=llvm_set,
            )
            evals = run_method(
                method=method,
                rng=rng,
                evaluator=evaluator,
                budget=args.budget,
                hub_mir=hub_mir,
                hub_llvm=hub_llvm,
                neighbor_mir=neighbor_mir,
                neighbor_llvm=neighbor_llvm,
                hub_budget_ratio=args.hub_budget_ratio,
                pop_size=args.pop_size,
                node_score=score,
                adj=adj,
            )
            curve = compute_hv_curve(evals, ref_point, mc, args.hv_stride)
            hv_curves[method] = curve

            t95 = None
            if hv_ref > 0:
                target = 0.95 * hv_ref
                for i, hv in enumerate(curve, 1):
                    if hv >= target:
                        t95 = i
                        break

            hv_final = float(curve[-1] if curve else 0.0)
            per_rep_summary_rows.append(
                {
                    "rep": rep,
                    "method": method,
                    "budget": args.budget,
                    "hv_final": hv_final,
                    "hv_ref": hv_ref,
                    "t95": t95 if t95 is not None else "",
                }
            )
            per_method_hv_final[method].append(hv_final)
            if t95 is not None:
                per_method_t95[method].append(int(t95))
                per_method_success[method] += 1

            rows = []
            for i, (cand, met) in enumerate(evals, 1):
                rows.append(
                    {
                        "t": i,
                        "disabled_mir": ";".join(cand.disabled_mir),
                        "disabled_llvm": ";".join(cand.disabled_llvm),
                        "runtime_n": met["runtime_n"],
                        "compile_time_n": met["compile_time_n"],
                        "size_n": met["size_n"],
                        "hv": curve[i - 1],
                    }
                )
            write_csv(
                os.path.join(rep_dir, f"{method}_evals.csv"),
                ["t", "disabled_mir", "disabled_llvm", "runtime_n", "compile_time_n", "size_n", "hv"],
                rows,
            )

            front_pts = pareto_filter([(m["runtime_n"], m["compile_time_n"], m["size_n"]) for _, m in evals])
            front_rows = [{"runtime_n": p[0], "compile_time_n": p[1], "size_n": p[2]} for p in sorted(front_pts)]
            write_csv(os.path.join(rep_dir, f"{method}_front.csv"), ["runtime_n", "compile_time_n", "size_n"], front_rows)

        hv_curves_last = hv_curves

        write_csv(
            os.path.join(rep_dir, "summary.csv"),
            ["rep", "method", "budget", "hv_final", "hv_ref", "t95"],
            [r for r in per_rep_summary_rows if int(r.get("rep", -1)) == rep],
        )

        try:
            import matplotlib.pyplot as plt

            plt.figure(figsize=(10, 6))
            for method, curve in hv_curves.items():
                xs = list(range(1, len(curve) + 1))
                plt.plot(xs, curve, label=method, linewidth=2)
            plt.xlabel("Samples")
            plt.ylabel("Hypervolume")
            plt.title("Pareto Search Convergence (HV)")
            plt.legend(loc="lower right", fontsize=9)
            plt.tight_layout()
            plt.savefig(os.path.join(rep_dir, "hv_curve.png"), dpi=200)
            plt.savefig(os.path.join(rep_dir, "hv_curve.pdf"))
            plt.close()
        except Exception:
            pass

        _ = generate_plots_for_out_dir(rep_dir)

    write_csv(
        os.path.join(out_dir, "summary_all.csv"),
        ["rep", "method", "budget", "hv_final", "hv_ref", "t95"],
        per_rep_summary_rows,
    )

    def _mean_std(xs: List[float]) -> Tuple[float, float]:
        if not xs:
            return 0.0, 0.0
        mu = sum(xs) / len(xs)
        var = sum((x - mu) ** 2 for x in xs) / max(1, (len(xs) - 1))
        return mu, math.sqrt(max(0.0, var))

    agg_rows: List[Dict[str, object]] = []
    for method in methods:
        hv_mu, hv_std = _mean_std([float(x) for x in per_method_hv_final.get(method, [])])
        t_list = [float(x) for x in per_method_t95.get(method, [])]
        t_mu, t_std = _mean_std(t_list) if t_list else (0.0, 0.0)
        agg_rows.append(
            {
                "method": method,
                "repeats": repeats,
                "hv_final_mean": hv_mu,
                "hv_final_std": hv_std,
                "t95_mean": t_mu if t_list else "",
                "t95_std": t_std if t_list else "",
                "t95_success_rate": (per_method_success.get(method, 0) / repeats) if repeats > 0 else 0.0,
                "hv_ref": hv_ref,
            }
        )
    write_csv(
        os.path.join(out_dir, "summary_agg.csv"),
        ["method", "repeats", "hv_final_mean", "hv_final_std", "t95_mean", "t95_std", "t95_success_rate", "hv_ref"],
        agg_rows,
    )
    if repeats > 1:
        _ = generate_aggregate_hv_plots_for_out_dir(out_dir)
 
    if repeats == 1 and hv_curves_last:
        try:
            import matplotlib.pyplot as plt

            plt.figure(figsize=(10, 6))
            for method, curve in hv_curves_last.items():
                xs = list(range(1, len(curve) + 1))
                plt.plot(xs, curve, label=method, linewidth=2)
            plt.xlabel("Samples")
            plt.ylabel("Hypervolume")
            plt.title("Pareto Search Convergence (HV)")
            plt.legend(loc="lower right", fontsize=9)
            plt.tight_layout()
            plt.savefig(os.path.join(out_dir, "hv_curve.png"), dpi=200)
            plt.savefig(os.path.join(out_dir, "hv_curve.pdf"))
            plt.close()
        except Exception:
            pass

        _ = generate_plots_for_out_dir(out_dir)
 
 
if __name__ == "__main__":
    main()
