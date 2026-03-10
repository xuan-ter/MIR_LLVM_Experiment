"""
功能：Lasso 回归分析与交互特征筛选
输入：experiment_expanded_llvm_mir.py 产出的 aggregated_results.csv
输出：lasso_edges.csv（筛选出的强交互边及其系数）
描述：
    对随机采样的 (MIR, LLVM) 联合配置数据进行 Lasso 回归建模。
    构建主效应与交互效应特征，利用 L1 正则化筛选出稀疏的显著交互对。
    执行 Bootstrap 稳定性选择以提高结果可靠性。
"""
import os
import csv
import math
import random
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Lasso, LassoCV

base = Path("/mnt/fjx/Compiler_Experiment/serde_test")
res_base = base / "results_expanded"
dirs = [d for d in res_base.iterdir() if d.is_dir() and d.name.startswith("random_configs_")]
if not dirs:
    raise SystemExit("no results dir")
res_dir = sorted(dirs)[-1]
agg_csv = res_dir / "aggregated_results.csv"
if not agg_csv.exists():
    raise SystemExit("missing aggregated_results.csv")
df = pd.read_csv(agg_csv)
df = df[df["Status"] == "Success"].copy()
df["y"] = np.log(df["TotalRuntime(s)"].astype(float) + 1e-9)
mir_lists = df["mir_disabled_list"].fillna("").astype(str).apply(lambda s: [x for x in s.split(";") if x])
llvm_lists = df["llvm_disabled_list"].fillna("").astype(str).apply(lambda s: [x for x in s.split(";") if x])
mir_set = sorted({p for lst in mir_lists for p in lst})
llvm_set = sorted({p for lst in llvm_lists for p in lst})
inter_pairs = [(m, l) for m in mir_set for l in llvm_set]
feat_cols = [f"M_{m}" for m in mir_set] + [f"L_{l}" for l in llvm_set] + [f"I_{m}__{l}" for m, l in inter_pairs]
rows = []
for ms, ls in zip(mir_lists, llvm_lists):
    d = {}
    ms_set = set(ms)
    ls_set = set(ls)
    for m in mir_set:
        d[f"M_{m}"] = 1 if m in ms_set else 0
    for l in llvm_set:
        d[f"L_{l}"] = 1 if l in ls_set else 0
    for m, l in inter_pairs:
        d[f"I_{m}__{l}"] = 1 if (m in ms_set and l in ls_set) else 0
    rows.append(d)
x = pd.DataFrame(rows, columns=feat_cols).astype(float).values
y = df["y"].values
scaler = StandardScaler(with_mean=True, with_std=True)
x_s = scaler.fit_transform(x)
cv = LassoCV(cv=5, n_alphas=100, random_state=0)
cv.fit(x_s, y)
alpha = float(cv.alpha_)
model = Lasso(alpha=alpha)
model.fit(x_s, y)
coef = model.coef_.astype(float)
coef_map = dict(zip(feat_cols, coef))
inter_coefs = []
for m, l in inter_pairs:
    key = f"I_{m}__{l}"
    inter_coefs.append((m, l, coef_map.get(key, 0.0)))
main_coefs = []
for m in mir_set:
    key = f"M_{m}"
    main_coefs.append(("MIR", m, coef_map.get(key, 0.0)))
for l in llvm_set:
    key = f"L_{l}"
    main_coefs.append(("LLVM", l, coef_map.get(key, 0.0)))
boot_n = 100
sel_freq = {f"I_{m}__{l}": 0 for m, l in inter_pairs}
coef_sum = {f"I_{m}__{l}": 0.0 for m, l in inter_pairs}
rng = np.random.default_rng(0)
for b in range(boot_n):
    idx = rng.choice(len(y), size=int(0.8 * len(y)), replace=False)
    xb = x_s[idx]
    yb = y[idx]
    mb = Lasso(alpha=alpha)
    mb.fit(xb, yb)
    cb = mb.coef_.astype(float)
    for i, col in enumerate(feat_cols):
        if col.startswith("I_"):
            if abs(cb[i]) > 1e-8:
                sel_freq[col] += 1
            coef_sum[col] += cb[i]
edges = []
for m, l in inter_pairs:
    key = f"I_{m}__{l}"
    freq = sel_freq[key] / boot_n
    mean_c = coef_sum[key] / boot_n
    edges.append((m, l, mean_c, freq))
edges.sort(key=lambda t: (-t[3], -abs(t[2])))
edges_csv = res_dir / "lasso_edges.csv"
with open(edges_csv, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["MIR_Pass", "LLVM_Pass", "coef_mean", "selected_freq"])
    for m, l, c, fr in edges:
        w.writerow([m, l, f"{c:.6g}", f"{fr:.6g}"])
main_csv = res_dir / "lasso_main_effects.csv"
with open(main_csv, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["Type", "Pass", "coef"])
    for t, p, c in sorted(main_coefs, key=lambda tpc: -abs(tpc[2])):
        w.writerow([t, p, f"{c:.6g}"])
print(str(edges_csv))
print(str(main_csv))
