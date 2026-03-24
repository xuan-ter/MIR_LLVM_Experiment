import os
import glob
import pandas as pd
import numpy as np
import seaborn as sns
import matplotlib.pyplot as plt

DATA_DIR = "/mnt/fjx/Compiler_Experiment/analysis/data"
OUTPUT_DIR = "/mnt/fjx/Compiler_Experiment/analysis/lasso/results"
os.makedirs(OUTPUT_DIR, exist_ok=True)

def load_data():
    files = glob.glob(os.path.join(DATA_DIR, "*.csv"))
    dfs = []
    for f in files:
        try:
            df = pd.read_csv(f)
            if "Status" in df.columns:
                df = df[df["Status"] == "Success"]
            df["TotalRuntime(s)"] = pd.to_numeric(df["TotalRuntime(s)"], errors="coerce")
            df = df[df["TotalRuntime(s)"] > 0]
            dfs.append(df)
        except Exception:
            pass
    if not dfs:
        raise RuntimeError("no valid csv")
    return pd.concat(dfs, ignore_index=True)

def clean_name(x):
    if pd.isna(x):
        return None
    s = str(x).strip().lower()
    if s in ["none", "baseline", "nan", "", "all"]:
        return None
    return str(x).strip()

def compute_coverage(df):
    df = df.copy()
    df["MIR_Pass"] = df["MIR_Pass"].apply(clean_name)
    df["LLVM_Pass"] = df["LLVM_Pass"].apply(clean_name)
    mir = sorted([str(p) for p in df["MIR_Pass"].unique() if p is not None])
    llvm = sorted([str(p) for p in df["LLVM_Pass"].unique() if p is not None])
    mir_cov = df[df["MIR_Pass"].isin(mir)].groupby("MIR_Pass").size().reindex(mir, fill_value=0)
    llvm_cov = df[df["LLVM_Pass"].isin(llvm)].groupby("LLVM_Pass").size().reindex(llvm, fill_value=0)
    co = df.groupby(["MIR_Pass", "LLVM_Pass"]).size().reset_index(name="count")
    co["MIR_Pass"] = co["MIR_Pass"].apply(lambda x: str(x) if x is not None else x)
    co["LLVM_Pass"] = co["LLVM_Pass"].apply(lambda x: str(x) if x is not None else x)
    co = co[co["MIR_Pass"].isin(mir) & co["LLVM_Pass"].isin(llvm)]
    mat = co.pivot(index="MIR_Pass", columns="LLVM_Pass", values="count").reindex(index=mir, columns=llvm).fillna(0).astype(int)
    return mir_cov, llvm_cov, mat

def save_outputs(mir_cov, llvm_cov, mat):
    mir_cov.rename("count").to_csv(os.path.join(OUTPUT_DIR, "mir_coverage.csv"), index=True)
    llvm_cov.rename("count").to_csv(os.path.join(OUTPUT_DIR, "llvm_coverage.csv"), index=True)
    mat.to_csv(os.path.join(OUTPUT_DIR, "cooccurrence_matrix.csv"))
    plt.figure(figsize=(24, 16))
    sns.heatmap(mat, cmap="viridis")
    plt.title("MIR×LLVM 双禁用共现次数热力图")
    plt.xlabel("LLVM Pass")
    plt.ylabel("MIR Pass")
    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, "cooccurrence_heatmap.png"), dpi=220)
    plt.savefig(os.path.join(OUTPUT_DIR, "cooccurrence_heatmap.pdf"))

def main():
    df = load_data()
    mir_cov, llvm_cov, mat = compute_coverage(df)
    save_outputs(mir_cov, llvm_cov, mat)
    print("done")

if __name__ == "__main__":
    main()
