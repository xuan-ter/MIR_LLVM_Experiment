import argparse
import csv
import math
import os
from collections import defaultdict
from datetime import datetime
from statistics import median


PROJECT_ROOT = "/mnt/fjx/Compiler_Experiment/loop_test"


def safe_dir_name(s):
    s = str(s).strip().replace(" ", "_")
    import re

    s = re.sub(r"[^A-Za-z0-9._-]+", "_", s)
    return s[:180] if len(s) > 180 else s


def _to_float(v, default=None):
    try:
        x = float(v)
        if math.isfinite(x):
            return x
        return default
    except Exception:
        return default


def _read_csv_rows(path):
    with open(path, "r", encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        return [row for row in r]


def _write_csv_rows(path, fieldnames, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)


def _pareto_nondominated(rows, keys):
    pts = []
    for r in rows:
        p = []
        ok = True
        for k in keys:
            v = _to_float(r.get(k), None)
            if v is None:
                ok = False
                break
            p.append(v)
        if ok:
            pts.append((r, tuple(p)))

    keep = []
    for i, (ri, pi) in enumerate(pts):
        dominated = False
        for j, (rj, pj) in enumerate(pts):
            if i == j:
                continue
            le_all = all(a <= b for a, b in zip(pj, pi))
            lt_any = any(a < b for a, b in zip(pj, pi))
            if le_all and lt_any:
                dominated = True
                break
        if not dominated:
            keep.append(ri)
    return keep


def _pearson(xs, ys):
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    mx = sum(xs) / len(xs)
    my = sum(ys) / len(ys)
    vx = sum((x - mx) ** 2 for x in xs)
    vy = sum((y - my) ** 2 for y in ys)
    if vx <= 0 or vy <= 0:
        return None
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return cov / math.sqrt(vx * vy)


def analyze_results_csv(input_csv, analysis_out, topk=20):
    in_path = str(input_csv).strip()
    if in_path.startswith("\\") and not in_path.startswith("/"):
        in_path = in_path.replace("\\", "/")
    in_path = os.path.abspath(in_path)
    if not os.path.exists(in_path):
        raise FileNotFoundError(in_path)

    root = str(analysis_out).strip()
    if root:
        if root.startswith("\\") and not root.startswith("/"):
            root = root.replace("\\", "/")
        root = os.path.abspath(root)
    else:
        root = os.path.join(PROJECT_ROOT, "analysis")
    os.makedirs(root, exist_ok=True)

    base = os.path.basename(os.path.dirname(in_path)) or "analysis"
    out_dir = os.path.join(root, safe_dir_name(base) + "_explain")
    if os.path.exists(out_dir) and os.listdir(out_dir):
        out_dir = out_dir + "_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs(out_dir, exist_ok=True)

    rows = _read_csv_rows(in_path)
    ok_rows = [r for r in rows if str(r.get("Status", "")).strip() == "Success"]

    baseline_rows = [r for r in ok_rows if str(r.get("ConfigName", "")).strip() == "EXP_000_ALL_OFF"]
    evidence_fields = [
        "MIR_BB_Last",
        "MIR_TermBlocks_Last",
        "MIR_Goto_Last",
        "MIR_SwitchInt_Last",
        "MIR_Locals_Last",
        "LLVM_BB",
        "LLVM_br",
        "LLVM_switch",
        "LICM_Remarks_Passed",
        "LICM_Remarks_Missed",
        "HotLoop_SCCSize",
        "HotLoop_Loads",
        "FactorConst_InHotLoop",
        "FactorConst_OutHotLoop",
        "FactorConst_Total",
        "FactorConst_Hoisted",
    ]

    baseline = {}
    by_mode = defaultdict(list)
    for r in baseline_rows:
        mode = str(r.get("Mode", "")).strip()
        rt = _to_float(r.get("TotalRuntime(s)"), None)
        ct = _to_float(r.get("CompileTime(s)"), None)
        sz = _to_float(r.get("BinarySize(Bytes)"), None)
        if not mode or rt is None or ct is None or sz is None:
            continue
        ev = {k: _to_float(r.get(k), None) for k in evidence_fields}
        by_mode[mode].append((rt, ct, sz, ev))
    for mode, pts in by_mode.items():
        baseline[mode] = {
            "runtime_med": median([p[0] for p in pts]),
            "compile_med": median([p[1] for p in pts]),
            "size_med": median([p[2] for p in pts]),
        }
        for k in evidence_fields:
            vals = [p[3].get(k) for p in pts if p[3].get(k) is not None]
            baseline[mode][k] = median(vals) if vals else None

    groups = defaultdict(list)
    for r in ok_rows:
        key = (
            str(r.get("ConfigName", "")).strip(),
            str(r.get("Mode", "")).strip(),
            str(r.get("LLVM_Pass", "")).strip(),
            str(r.get("MIR_Pass", "")).strip(),
        )
        groups[key].append(r)

    summary = []
    for (cfg, mode, llvm_p, mir_p), rs in groups.items():
        rts = [_to_float(r.get("TotalRuntime(s)"), None) for r in rs]
        cts = [_to_float(r.get("CompileTime(s)"), None) for r in rs]
        szs = [_to_float(r.get("BinarySize(Bytes)"), None) for r in rs]
        rts = [x for x in rts if x is not None]
        cts = [x for x in cts if x is not None]
        szs = [x for x in szs if x is not None]
        if not rts or not cts or not szs:
            continue

        out = {
            "ConfigName": cfg,
            "Mode": mode,
            "LLVM_Pass": llvm_p,
            "MIR_Pass": mir_p,
            "n": len(rs),
            "runtime_med": median(rts),
            "compile_med": median(cts),
            "size_med": median(szs),
        }

        b = baseline.get(mode, None)
        if b and b.get("runtime_med"):
            out["runtime_delta_pct"] = (out["runtime_med"] / b["runtime_med"] - 1.0) * 100.0
        else:
            out["runtime_delta_pct"] = None
        if b and b.get("compile_med"):
            out["compile_delta_pct"] = (out["compile_med"] / b["compile_med"] - 1.0) * 100.0
        else:
            out["compile_delta_pct"] = None
        if b and b.get("size_med"):
            out["size_delta_pct"] = (out["size_med"] / b["size_med"] - 1.0) * 100.0
        else:
            out["size_delta_pct"] = None

        for k in evidence_fields:
            vals = [_to_float(r.get(k), None) for r in rs]
            vals = [v for v in vals if v is not None]
            out[k] = median(vals) if vals else None
            if b and b.get(k) is not None and out[k] is not None:
                out[k + "_delta"] = out[k] - b[k]
            else:
                out[k + "_delta"] = None

        denom = (out.get("LICM_Remarks_Passed") or 0.0) + (out.get("LICM_Remarks_Missed") or 0.0)
        out["licm_pass_rate"] = (out.get("LICM_Remarks_Passed") or 0.0) / denom if denom > 0 else None
        denom2 = out.get("FactorConst_Total") or 0.0
        out["factor_hoist_rate"] = (out.get("FactorConst_Hoisted") or 0.0) / denom2 if denom2 > 0 else None

        summary.append(out)

    summary.sort(key=lambda r: (str(r.get("Mode", "")), _to_float(r.get("runtime_med"), 0.0)))

    _write_csv_rows(
        os.path.join(out_dir, "baseline_by_mode.csv"),
        ["Mode"]
        + ["runtime_med", "compile_med", "size_med"]
        + evidence_fields,
        [{"Mode": m, **b} for m, b in sorted(baseline.items())],
    )

    fieldnames = [
        "ConfigName",
        "Mode",
        "LLVM_Pass",
        "MIR_Pass",
        "n",
        "runtime_med",
        "compile_med",
        "size_med",
        "runtime_delta_pct",
        "compile_delta_pct",
        "size_delta_pct",
    ]
    for k in evidence_fields:
        fieldnames.append(k)
        fieldnames.append(k + "_delta")
    fieldnames += ["licm_pass_rate", "factor_hoist_rate"]

    _write_csv_rows(os.path.join(out_dir, "summary_by_config_mode.csv"), fieldnames, summary)

    modes = sorted({str(r.get("Mode", "")).strip() for r in summary if str(r.get("Mode", "")).strip()})
    for mode in modes:
        rs = [r for r in summary if str(r.get("Mode", "")).strip() == mode]
        pareto = _pareto_nondominated(rs, ("runtime_med", "compile_med", "size_med"))
        pareto.sort(key=lambda r: (_to_float(r.get("runtime_med"), 0.0), _to_float(r.get("size_med"), 0.0)))
        _write_csv_rows(
            os.path.join(out_dir, f"pareto_front_{safe_dir_name(mode)}.csv"),
            fieldnames,
            pareto,
        )

        rs2 = [(r, _to_float(r.get("runtime_delta_pct"), None)) for r in rs]
        rs2 = [(r, v) for r, v in rs2 if v is not None]
        rs2.sort(key=lambda x: x[1])
        top = [r for r, _ in rs2[: max(1, int(topk))]]
        _write_csv_rows(os.path.join(out_dir, f"top{topk}_runtime_{safe_dir_name(mode)}.csv"), fieldnames, top)

    try:
        import matplotlib.pyplot as plt

        def _scatter(mode, x_key, y_key, xlab, ylab, fname):
            rs = [r for r in summary if str(r.get("Mode", "")).strip() == mode]
            xs = []
            ys = []
            for r in rs:
                x = _to_float(r.get(x_key), None)
                y = _to_float(r.get(y_key), None)
                if x is None or y is None:
                    continue
                xs.append(x)
                ys.append(y)
            if len(xs) < 5:
                return
            corr = _pearson(xs, ys)
            plt.figure(figsize=(7.5, 6))
            plt.scatter(xs, ys, s=16, alpha=0.35, color="#4C78A8")
            if corr is not None:
                plt.title(f"{mode}: {ylab} vs {xlab} (r={corr:.3f})")
            else:
                plt.title(f"{mode}: {ylab} vs {xlab}")
            plt.xlabel(xlab)
            plt.ylabel(ylab)
            plt.tight_layout()
            out_png = os.path.join(out_dir, fname + ".png")
            out_pdf = os.path.join(out_dir, fname + ".pdf")
            plt.savefig(out_png, dpi=200)
            plt.savefig(out_pdf)
            plt.close()

        for mode in modes:
            _scatter(mode, "FactorConst_Hoisted_delta", "runtime_delta_pct", "Δ hoisted consts", "Runtime Δ% vs baseline", f"{safe_dir_name(mode)}_rt_delta_vs_hoisted_delta")
            _scatter(mode, "HotLoop_Loads_delta", "runtime_delta_pct", "Δ hot-loop loads", "Runtime Δ% vs baseline", f"{safe_dir_name(mode)}_rt_delta_vs_hotloads_delta")
            _scatter(mode, "LICM_Remarks_Passed_delta", "runtime_delta_pct", "Δ LICM passed", "Runtime Δ% vs baseline", f"{safe_dir_name(mode)}_rt_delta_vs_licm_passed_delta")
            _scatter(mode, "MIR_BB_Last_delta", "runtime_delta_pct", "Δ MIR basic blocks", "Runtime Δ% vs baseline", f"{safe_dir_name(mode)}_rt_delta_vs_mir_bb_delta")
    except Exception:
        pass

    try:
        combine_six_panels_pdf(
            out_dir,
            [
                "easy_rt_delta_vs_mir_bb_delta.pdf",
                "easy_rt_delta_vs_licm_passed_delta.pdf",
                "easy_rt_delta_vs_hotloads_delta.pdf",
                "mir-dependent_rt_delta_vs_mir_bb_delta.pdf",
                "mir-dependent_rt_delta_vs_licm_passed_delta.pdf",
                "mir-dependent_rt_delta_vs_hotloads_delta.pdf",
            ],
            os.path.join(out_dir, "rt_delta_explain_2x3.pdf"),
            rows=2,
            cols=3,
        )
    except Exception:
        pass

    return out_dir


def combine_six_panels_pdf(out_dir, pdf_names, out_pdf, rows=2, cols=3):
    from pypdf import PdfReader, PdfWriter, Transformation

    if len(pdf_names) != rows * cols:
        raise ValueError("pdf_names length mismatch")

    pages = []
    for name in pdf_names:
        p = os.path.join(out_dir, name)
        if not os.path.exists(p):
            raise FileNotFoundError(p)
        r = PdfReader(p)
        if not r.pages:
            raise RuntimeError(p)
        pages.append(r.pages[0])

    pad = 18.0
    col_widths = []
    row_heights = []
    for c in range(cols):
        ws = []
        for r in range(rows):
            pg = pages[r * cols + c]
            ws.append(float(pg.mediabox.width))
        col_widths.append(max(ws))
    for r in range(rows):
        hs = []
        for c in range(cols):
            pg = pages[r * cols + c]
            hs.append(float(pg.mediabox.height))
        row_heights.append(max(hs))

    total_w = sum(col_widths) + pad * (cols + 1)
    total_h = sum(row_heights) + pad * (rows + 1)

    writer = PdfWriter()
    dst = writer.add_blank_page(width=total_w, height=total_h)

    y = total_h - pad
    for r in range(rows):
        y -= row_heights[r]
        x = pad
        for c in range(cols):
            pg = pages[r * cols + c]
            w = float(pg.mediabox.width)
            h = float(pg.mediabox.height)
            cw = col_widths[c]
            ch = row_heights[r]
            s = min(cw / w if w else 1.0, ch / h if h else 1.0)
            sw = w * s
            sh = h * s
            dx = x + (cw - sw) / 2.0
            dy = y + (ch - sh) / 2.0
            dst.merge_transformed_page(pg, Transformation().scale(s).translate(dx, dy))
            x += cw + pad
        y -= pad

    with open(out_pdf, "wb") as f:
        writer.write(f)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input-csv", required=True)
    ap.add_argument("--out-root", default=os.path.join(PROJECT_ROOT, "analysis"))
    ap.add_argument("--topk", type=int, default=20)
    args = ap.parse_args()
    out_dir = analyze_results_csv(args.input_csv, args.out_root, topk=args.topk)
    print(f"[Analysis] Input: {os.path.abspath(args.input_csv)}")
    print(f"[Analysis] Output dir: {out_dir}")


if __name__ == "__main__":
    main()
