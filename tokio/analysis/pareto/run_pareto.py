import argparse
import csv
import math
import os
from datetime import datetime
from statistics import median
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import matplotlib.pyplot as plt


TOKIO_EXPERIMENT_CSV = r"d:\MIR_LLVM\mir_-llvm\tokio\mir_llvm_hybrid_py\20260315_201152\experiment_results.csv"
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
                "runtime_med": float(median(rts)),
                "compile_med": float(median(cts)),
                "size_med": float(median(szs)),
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
    ap.add_argument("--input", default=TOKIO_EXPERIMENT_CSV)
    args = ap.parse_args(argv)

    rows = _read_rows(args.input)
    agg = _aggregate(rows)
    if not agg:
        raise SystemExit("No valid rows after filtering Status/metrics.")

    baseline = _find_baseline(agg)
    front = pareto_front(agg)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(OUT_ROOT, ts)
    os.makedirs(out_dir, exist_ok=True)

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

    print(f"Wrote: {os.path.join(out_dir, 'pareto_front.csv')}")
    print(f"Wrote: {os.path.join(out_dir, 'pareto_scatter.pdf')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
