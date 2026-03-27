import csv
import math
import os


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EXPERIMENT_RESULTS_CSV = "/mnt/fjx/Compiler_Experiment/regex/mir_llvm_hybrid_py/20260310_224816/experiment_results.csv"
OUTPUT_CSV = os.path.join(BASE_DIR, "interaction_results.csv")
ALPHA = 0.05


def _clean_pass_name(value, *, is_mir):
    if value is None:
        return "None"
    s = str(value).strip()
    if s == "" or s.lower() in {"none", "baseline", "nan"}:
        return "None"
    if is_mir and s == "N/A":
        return "None"
    return s


def _mean(xs):
    if not xs:
        return math.nan
    return sum(xs) / len(xs)


def _var(xs, mean_x):
    n = len(xs)
    if n < 2:
        return 0.0
    s2 = sum((x - mean_x) ** 2 for x in xs) / (n - 1)
    if s2 != s2:
        return 0.0
    return max(0.0, s2)


def _norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _two_sided_p_from_z(z):
    az = abs(z)
    return max(0.0, min(1.0, 2.0 * (1.0 - _norm_cdf(az))))


def _bh_fdr(p_values):
    m = len(p_values)
    if m == 0:
        return []
    order = sorted(range(m), key=lambda i: (p_values[i], i))
    adj = [1.0] * m
    prev = 1.0
    for rank, idx in enumerate(reversed(order), start=1):
        i = order[-rank]
        p = p_values[i]
        k = m - rank + 1
        val = (p * m) / k if k > 0 else 1.0
        if val > prev:
            val = prev
        prev = val
        adj[i] = min(1.0, max(0.0, val))
    return adj


def _trend(r, eps):
    if r != r:
        return "unknown"
    if r < 1.0 - eps:
        return "better"
    if r > 1.0 + eps:
        return "worse"
    return "neutral"


def _classify_pattern(*, y00, y10, y01, y11, delta, significant):
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


def main():
    if not os.path.exists(EXPERIMENT_RESULTS_CSV):
        raise FileNotFoundError(EXPERIMENT_RESULTS_CSV)

    groups = {}
    mir_passes = set()
    llvm_passes = set()

    with open(EXPERIMENT_RESULTS_CSV, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            status = str(r.get("Status", "")).strip()
            if status and status != "Success":
                continue
            try:
                rt = float(str(r.get("TotalRuntime(s)", "")).strip())
            except Exception:
                continue
            if not (rt > 0.0):
                continue

            llvm_p = _clean_pass_name(r.get("LLVM_Pass"), is_mir=False)
            mir_p = _clean_pass_name(r.get("MIR_Pass"), is_mir=True)

            llvm_passes.add(llvm_p)
            mir_passes.add(mir_p)

            key = (mir_p, llvm_p)
            groups.setdefault(key, []).append(math.log(rt))

    mir_list = sorted(p for p in mir_passes if p not in {"None", "All"})
    llvm_list = sorted(p for p in llvm_passes if p not in {"None", "All"})

    z00 = groups.get(("None", "None"), [])
    if not z00:
        raise RuntimeError("baseline group (MIR=None, LLVM=None) not found")

    base_mean = _mean(z00)
    base_var = _var(z00, base_mean)
    base_n = len(z00)

    out_rows = []
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
                    "delta": delta,
                    "ci_low": ci_low,
                    "ci_high": ci_high,
                    "p_value": p,
                }
            )

    pvals = [r["p_value"] for r in out_rows]
    padj = _bh_fdr(pvals)
    for r, a in zip(out_rows, padj):
        r["p_adj"] = a
        r["significant"] = a <= ALPHA
        y00 = float(r["y00_mean"])
        y10 = float(r["y10_mean"])
        y01 = float(r["y01_mean"])
        y11 = float(r["y11_mean"])
        y_pred = (y10 * y01 / y00) if y00 > 0 else math.nan
        r["y_pred_mean"] = y_pred
        r["ratio_y11_over_pred"] = (y11 / y_pred) if (y_pred == y_pred and y_pred > 0) else math.nan
        r["ratio_y11_over_base"] = (y11 / y00) if y00 > 0 else math.nan
        r["ratio_pred_over_base"] = (y_pred / y00) if (y00 > 0 and y_pred == y_pred) else math.nan
        pat, pat_cn = _classify_pattern(y00=y00, y10=y10, y01=y01, y11=y11, delta=float(r["delta"]), significant=bool(r["significant"]))
        r["pattern"] = pat
        r["pattern_cn"] = pat_cn

    out_rows.sort(key=lambda r: (r["p_adj"], -abs(r["delta"])))

    os.makedirs(BASE_DIR, exist_ok=True)
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
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
        for r in out_rows:
            w.writerow(r)

    print(f"Saved results to {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
