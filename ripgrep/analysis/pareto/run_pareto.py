import argparse
import csv
import json
import os
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple

import matplotlib.pyplot as plt


RIPGREP_EXPERIMENT_CSV = r"d:\MIR_LLVM\mir_-llvm\ripgrep\results\experiment_results.csv"
RIPGREP_LASSO_EDGES_CSV = r"d:\MIR_LLVM\mir_-llvm\ripgrep\analysis\lasso\coupling_edges.csv"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_ROOT = os.path.join(BASE_DIR, "out")


def _clean_pass(x: object) -> str:
    if x is None:
        return "None"
    s = str(x).strip()
    if not s:
        return "None"
    lo = s.lower()
    if lo in {"none", "baseline", "nan", "n/a", "na", "all"}:
        return "None"
    return s


def _to_float(x: object) -> float:
    try:
        s = str(x).strip()
        if not s:
            return float("nan")
        return float(s)
    except Exception:
        return float("nan")


def _to_int(x: object) -> int:
    try:
        s = str(x).strip()
        if not s:
            return 0
        return int(float(s))
    except Exception:
        return 0


def _is_success(status: object) -> bool:
    return str(status or "").strip().lower() == "success"


def _read_rows(path: str) -> List[Dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _group_key(r: Dict[str, str]) -> Tuple[str, str, str]:
    cfg = str(r.get("ConfigName", "")).strip()
    mir = _clean_pass(r.get("MIR_Pass"))
    llvm = _clean_pass(r.get("LLVM_Pass"))
    return (cfg, mir, llvm)


def _aggregate(rows: Sequence[Dict[str, str]]) -> List[Dict[str, object]]:
    grouped: Dict[Tuple[str, str, str], List[Dict[str, str]]] = {}
    for r in rows:
        if not _is_success(r.get("Status")):
            continue
        rt = _to_float(r.get("TotalRuntime(s)"))
        ct = _to_float(r.get("CompileTime(s)"))
        sz = _to_int(r.get("BinarySize(Bytes)"))
        if not (rt > 0):
            continue
        if not (ct > 0):
            continue
        if sz <= 0:
            continue
        grouped.setdefault(_group_key(r), []).append(r)

    out: List[Dict[str, object]] = []
    for (cfg, mir, llvm), rs in grouped.items():
        rts = [_to_float(r.get("TotalRuntime(s)")) for r in rs]
        cts = [_to_float(r.get("CompileTime(s)")) for r in rs]
        szs = [_to_int(r.get("BinarySize(Bytes)")) for r in rs]
        rts = [x for x in rts if x > 0]
        cts = [x for x in cts if x > 0]
        szs = [x for x in szs if x > 0]
        if not rts or not cts or not szs:
            continue
        out.append(
            {
                "ConfigName": cfg,
                "MIR_Pass": mir,
                "LLVM_Pass": llvm,
                "n": int(len(rs)),
                "runtime_med": float(sorted(rts)[len(rts) // 2]),
                "compile_med": float(sorted(cts)[len(cts) // 2]),
                "size_med": float(sorted(szs)[len(szs) // 2]),
            }
        )
    return out


def _dominates(a: Dict[str, object], b: Dict[str, object]) -> bool:
    ar = float(a["runtime_med"])
    ac = float(a["compile_med"])
    asz = float(a["size_med"])
    br = float(b["runtime_med"])
    bc = float(b["compile_med"])
    bsz = float(b["size_med"])
    return (ar <= br and ac <= bc and asz <= bsz) and (ar < br or ac < bc or asz < bsz)


def pareto_front(items: Sequence[Dict[str, object]]) -> List[Dict[str, object]]:
    front: List[Dict[str, object]] = []
    for i in items:
        dominated = False
        for j in items:
            if i is j:
                continue
            if _dominates(j, i):
                dominated = True
                break
        if not dominated:
            front.append(i)
    front.sort(key=lambda r: (float(r["runtime_med"]), float(r["size_med"]), float(r["compile_med"])))
    return front


def _write_csv(path: str, fieldnames: Sequence[str], rows: Sequence[Dict[str, object]]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(fieldnames))
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})


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


def _plot_hv_svg(out_path: str, series: Dict[str, List[Tuple[float, float]]], hv_ref: float, title: str) -> None:
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
        parts.append(f'<text x="{xpix:.2f}" y="{pad_t+plot_h+24}" text-anchor="middle" font-size="12" font-family="Arial">{int(round(xv))}</text>')
        parts.append(f'<line x1="{xpix:.2f}" y1="{pad_t}" x2="{xpix:.2f}" y2="{pad_t+plot_h}" stroke="#eee" stroke-width="1"/>')

    for yv in y_ticks:
        ypix = ty(yv)
        parts.append(f'<line x1="{pad_l-6}" y1="{ypix:.2f}" x2="{pad_l}" y2="{ypix:.2f}" stroke="#000" stroke-width="1"/>')
        parts.append(f'<text x="{pad_l-10}" y="{ypix+4:.2f}" text-anchor="end" font-size="12" font-family="Arial">{yv:.3f}</text>')
        parts.append(f'<line x1="{pad_l}" y1="{ypix:.2f}" x2="{pad_l+plot_w}" y2="{ypix:.2f}" stroke="#eee" stroke-width="1"/>')

    if hv_ref > 0:
        yref = ty(hv_ref)
        parts.append(f'<line x1="{pad_l}" y1="{yref:.2f}" x2="{pad_l+plot_w}" y2="{yref:.2f}" stroke="#333" stroke-dasharray="6,4" stroke-width="1"/>')
        parts.append(f'<text x="{pad_l+plot_w-2}" y="{yref-6:.2f}" text-anchor="end" font-size="12" font-family="Arial">hv_ref={hv_ref:.3f}</text>')
        y95 = ty(0.95 * hv_ref)
        parts.append(f'<line x1="{pad_l}" y1="{y95:.2f}" x2="{pad_l+plot_w}" y2="{y95:.2f}" stroke="#666" stroke-dasharray="3,4" stroke-width="1"/>')
        parts.append(f'<text x="{pad_l+plot_w-2}" y="{y95-6:.2f}" text-anchor="end" font-size="12" font-family="Arial">0.95·hv_ref</text>')

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


def _nondominated_2d(points: Sequence[Tuple[float, float]]) -> List[Tuple[float, float]]:
    pts = sorted(points, key=lambda p: (p[0], p[1]))
    out: List[Tuple[float, float]] = []
    best_z = float("inf")
    for y, z in pts:
        if z < best_z:
            out.append((float(y), float(z)))
            best_z = float(z)
    return out


def _hv_2d(points: Sequence[Tuple[float, float]], ref_y: float, ref_z: float) -> float:
    pts = [(y, z) for (y, z) in points if y <= ref_y and z <= ref_z]
    if not pts:
        return 0.0
    nd = _nondominated_2d(pts)
    hv = 0.0
    for i, (y, z) in enumerate(nd):
        y_next = nd[i + 1][0] if i + 1 < len(nd) else ref_y
        hv += max(0.0, float(y_next) - float(y)) * max(0.0, float(ref_z) - float(z))
    return float(hv)


def _nondominated_3d(points: Sequence[Tuple[float, float, float]]) -> List[Tuple[float, float, float]]:
    pts = list(points)
    out: List[Tuple[float, float, float]] = []
    for i, a in enumerate(pts):
        dominated = False
        for j, b in enumerate(pts):
            if i == j:
                continue
            if (b[0] <= a[0] and b[1] <= a[1] and b[2] <= a[2]) and (b[0] < a[0] or b[1] < a[1] or b[2] < a[2]):
                dominated = True
                break
        if not dominated:
            out.append(a)
    return out


def _hv_3d(points: Sequence[Tuple[float, float, float]], ref: Tuple[float, float, float]) -> float:
    rx, ry, rz = ref
    pts = [(x, y, z) for (x, y, z) in points if x <= rx and y <= ry and z <= rz]
    if not pts:
        return 0.0
    nd = _nondominated_3d(pts)
    nd.sort(key=lambda p: p[0], reverse=True)
    hv = 0.0
    prev_x = rx
    yz: List[Tuple[float, float]] = []
    for x, y, z in nd:
        dx = max(0.0, float(prev_x) - float(x))
        yz.append((float(y), float(z)))
        hv2 = _hv_2d(yz, ry, rz)
        hv += dx * hv2
        prev_x = float(x)
    return float(hv)


def _read_edges(path: str) -> List[Dict[str, object]]:
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out: List[Dict[str, object]] = []
    for r in rows:
        s = str(r.get("Source", "")).strip()
        t = str(r.get("Target", "")).strip()
        if not s or not t:
            continue
        try:
            w = float(r.get("Weight", 0.0))
        except Exception:
            w = 0.0
        out.append({"Source": s, "Target": t, "Weight": float(w)})
    return out


def _write_graph_stats(out_dir: str) -> None:
    edges = _read_edges(RIPGREP_LASSO_EDGES_CSV)
    if not edges:
        return
    mir_nodes = sorted({str(e["Source"]) for e in edges})
    llvm_nodes = sorted({str(e["Target"]) for e in edges})
    n_mir = len(mir_nodes)
    n_llvm = len(llvm_nodes)
    n_edges = len(edges)
    denom = float(n_mir * n_llvm) if n_mir > 0 and n_llvm > 0 else 0.0
    density = float(n_edges / denom) if denom > 0 else 0.0

    degree: Dict[str, int] = {}
    weighted: Dict[str, float] = {}
    for e in edges:
        s = str(e["Source"])
        t = str(e["Target"])
        w = abs(float(e["Weight"]))
        degree[s] = degree.get(s, 0) + 1
        degree[t] = degree.get(t, 0) + 1
        weighted[s] = weighted.get(s, 0.0) + w
        weighted[t] = weighted.get(t, 0.0) + w

    total_degree = float(sum(degree.values())) if degree else 0.0
    top10 = sorted(degree.items(), key=lambda kv: kv[1], reverse=True)[:10]
    top10_share = float(sum(d for _, d in top10) / total_degree) if total_degree > 0 else 0.0

    _write_csv(
        os.path.join(out_dir, "graph_stats.csv"),
        ["n_mir", "n_llvm", "n_edges", "density", "top10_degree_share"],
        [
            {
                "n_mir": n_mir,
                "n_llvm": n_llvm,
                "n_edges": n_edges,
                "density": density,
                "top10_degree_share": top10_share,
            }
        ],
    )

    hubs: List[Dict[str, object]] = []
    mir_set = set(mir_nodes)
    for p, deg in degree.items():
        side = "MIR" if p in mir_set else "LLVM"
        hubs.append({"pass": p, "side": side, "weighted_degree": float(weighted.get(p, 0.0)), "degree": int(deg)})
    hubs.sort(key=lambda r: (float(r["weighted_degree"]), float(r["degree"])), reverse=True)
    _write_csv(os.path.join(out_dir, "hubs.csv"), ["pass", "side", "weighted_degree", "degree"], hubs[:50])


def _find_baseline(agg: Sequence[Dict[str, object]]) -> Optional[Dict[str, object]]:
    for r in agg:
        if str(r.get("MIR_Pass")) == "None" and str(r.get("LLVM_Pass")) == "None":
            return r
    for r in agg:
        if str(r.get("ConfigName", "")).strip().upper().endswith("BASELINE"):
            return r
    return None


def _add_deltas(rows: List[Dict[str, object]], baseline: Optional[Dict[str, object]]) -> None:
    if baseline is None:
        for r in rows:
            r["runtime_delta_pct"] = ""
            r["compile_delta_pct"] = ""
            r["size_delta_pct"] = ""
        return

    br = float(baseline["runtime_med"])
    bc = float(baseline["compile_med"])
    bs = float(baseline["size_med"])
    for r in rows:
        rr = float(r["runtime_med"])
        rc = float(r["compile_med"])
        rs = float(r["size_med"])
        r["runtime_delta_pct"] = float((rr - br) / br * 100.0) if br > 0 else ""
        r["compile_delta_pct"] = float((rc - bc) / bc * 100.0) if bc > 0 else ""
        r["size_delta_pct"] = float((rs - bs) / bs * 100.0) if bs > 0 else ""


def _plot_scatter(agg: Sequence[Dict[str, object]], front: Sequence[Dict[str, object]], out_png: str, out_pdf: str) -> None:
    xs = [float(r["size_med"]) for r in agg]
    ys = [float(r["runtime_med"]) for r in agg]
    cs = [float(r["compile_med"]) for r in agg]

    fx = [float(r["size_med"]) for r in front]
    fy = [float(r["runtime_med"]) for r in front]

    plt.figure(figsize=(12, 8))
    sc = plt.scatter(xs, ys, c=cs, cmap="viridis", alpha=0.7, s=30, edgecolors="none")
    plt.colorbar(sc, label="CompileTime(s) (median)")
    if fx:
        plt.scatter(fx, fy, c="red", alpha=0.95, s=60, edgecolors="black", linewidths=0.5, label=f"Pareto front ({len(front)})")
        order = sorted(range(len(front)), key=lambda i: (fx[i], fy[i]))
        px = [fx[i] for i in order]
        py = [fy[i] for i in order]
        plt.plot(px, py, color="red", linewidth=1.5, alpha=0.8)
        plt.legend(loc="upper right")

    plt.xlabel("BinarySize(Bytes) (median)")
    plt.ylabel("TotalRuntime(s) (median)")
    plt.title("Pareto Front (min runtime, min size, min compile)")
    plt.tight_layout()
    plt.savefig(out_png, dpi=220, bbox_inches="tight")
    plt.savefig(out_pdf, bbox_inches="tight")
    plt.close()


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=RIPGREP_EXPERIMENT_CSV)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--budget", type=int, default=1000)
    ap.add_argument("--ref-budget", type=int, default=8000)
    args = ap.parse_args(argv)

    rows = _read_rows(args.input)
    agg = _aggregate(rows)
    if not agg:
        raise SystemExit("No valid rows after filtering Status/metrics.")

    baseline = _find_baseline(agg)
    if baseline is None:
        raise SystemExit("Baseline (MIR=None, LLVM=None) not found.")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(OUT_ROOT, ts)
    os.makedirs(out_dir, exist_ok=True)

    config = {
        "analysis_root": os.path.abspath(os.path.join(BASE_DIR, "..")),
        "out_root": os.path.abspath(OUT_ROOT),
        "seed": int(args.seed),
        "budget": int(args.budget),
        "ref_budget": int(args.ref_budget),
        "methods": "random",
    }
    with open(os.path.join(out_dir, "config.json"), "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

    br = float(baseline["runtime_med"])
    bc = float(baseline["compile_med"])
    bs = float(baseline["size_med"])
    if not (br > 0 and bc > 0 and bs > 0):
        raise SystemExit("Invalid baseline metrics.")

    candidates: List[Dict[str, object]] = []
    for r in agg:
        mir = str(r.get("MIR_Pass", "None"))
        llvm = str(r.get("LLVM_Pass", "None"))
        rt = float(r["runtime_med"])
        ct = float(r["compile_med"])
        sz = float(r["size_med"])
        candidates.append(
            {
                "disabled_mir": "" if mir == "None" else mir,
                "disabled_llvm": "" if llvm == "None" else llvm,
                "runtime_n": float(rt / br),
                "compile_time_n": float(ct / bc),
                "size_n": float(sz / bs),
            }
        )

    budget = int(min(max(1, int(args.budget)), len(candidates)))
    ref_budget = int(min(max(1, int(args.ref_budget)), len(candidates)))
    ref_point = (2.0, 2.0, 2.0)

    rng = __import__("random").Random(int(args.seed))
    ref_sample = rng.sample(candidates, k=ref_budget)
    hv_ref = _hv_3d([(c["runtime_n"], c["compile_time_n"], c["size_n"]) for c in ref_sample], ref_point)
    _write_csv(
        os.path.join(out_dir, "reference.csv"),
        ["ref_point_runtime_n", "ref_point_compile_time_n", "ref_point_size_n", "ref_budget", "hv_ref"],
        [
            {
                "ref_point_runtime_n": ref_point[0],
                "ref_point_compile_time_n": ref_point[1],
                "ref_point_size_n": ref_point[2],
                "ref_budget": ref_budget,
                "hv_ref": hv_ref,
            }
        ],
    )

    eval_sample = rng.sample(candidates, k=budget)
    seen: List[Tuple[float, float, float]] = []
    eval_rows: List[Dict[str, object]] = []
    hv_series: List[Tuple[float, float]] = []
    for i, c in enumerate(eval_sample, start=1):
        p = (float(c["runtime_n"]), float(c["compile_time_n"]), float(c["size_n"]))
        seen.append(p)
        hv = _hv_3d(seen, ref_point)
        eval_rows.append(
            {
                "t": i,
                "disabled_mir": str(c["disabled_mir"]),
                "disabled_llvm": str(c["disabled_llvm"]),
                "runtime_n": p[0],
                "compile_time_n": p[1],
                "size_n": p[2],
                "hv": hv,
            }
        )
        hv_series.append((float(i), float(hv)))

    _write_csv(
        os.path.join(out_dir, "random_evals.csv"),
        ["t", "disabled_mir", "disabled_llvm", "runtime_n", "compile_time_n", "size_n", "hv"],
        eval_rows,
    )

    front_pts = _nondominated_3d(seen)
    front_rows = [{"runtime_n": p[0], "compile_time_n": p[1], "size_n": p[2]} for p in sorted(front_pts)]
    _write_csv(os.path.join(out_dir, "random_front.csv"), ["runtime_n", "compile_time_n", "size_n"], front_rows)

    hv_final = float(hv_series[-1][1]) if hv_series else 0.0
    t95 = ""
    if hv_ref > 0:
        target = 0.95 * hv_ref
        for t, hv in hv_series:
            if hv >= target:
                t95 = int(t)
                break
    _write_csv(
        os.path.join(out_dir, "summary.csv"),
        ["method", "budget", "hv_final", "hv_ref", "t95"],
        [{"method": "random", "budget": budget, "hv_final": hv_final, "hv_ref": hv_ref, "t95": t95}],
    )

    series = {"random": hv_series}
    hv_svg = os.path.join(out_dir, "hv_curve.svg")
    _plot_hv_svg(hv_svg, series, hv_ref, "Pareto Search Convergence (HV)")

    plt.figure(figsize=(10, 6))
    plt.plot([t for t, _ in hv_series], [hv for _, hv in hv_series], label="random", linewidth=2)
    if hv_ref > 0:
        plt.axhline(hv_ref, color="#333", linestyle="--", linewidth=1, label=f"hv_ref={hv_ref:.3f}")
        plt.axhline(0.95 * hv_ref, color="#666", linestyle=":", linewidth=1, label="0.95·hv_ref")
    plt.xlabel("Samples")
    plt.ylabel("Hypervolume")
    plt.title("Pareto Search Convergence (HV)")
    plt.legend(loc="lower right", fontsize=9)
    plt.tight_layout()
    plt.savefig(os.path.join(out_dir, "hv_curve.png"), dpi=200)
    plt.savefig(os.path.join(out_dir, "hv_curve.pdf"))
    plt.close()

    _write_graph_stats(out_dir)

    front = pareto_front(agg)
    _add_deltas(agg, baseline)
    _add_deltas(front, baseline)

    fields = [
        "ConfigName",
        "MIR_Pass",
        "LLVM_Pass",
        "n",
        "runtime_med",
        "compile_med",
        "size_med",
        "runtime_delta_pct",
        "compile_delta_pct",
        "size_delta_pct",
    ]
    _write_csv(os.path.join(out_dir, "all_agg.csv"), fields, agg)
    _write_csv(os.path.join(out_dir, "pareto_front.csv"), fields, front)
    _plot_scatter(agg, front, os.path.join(out_dir, "pareto_scatter.png"), os.path.join(out_dir, "pareto_scatter.pdf"))

    print(f"Wrote: {os.path.join(out_dir, 'summary.csv')}")
    print(f"Wrote: {os.path.join(out_dir, 'pareto_front.csv')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
