import pandas as pd
import numpy as np
import os
import glob
import scipy.stats as stats
import matplotlib.pyplot as plt
import seaborn as sns
from statsmodels.stats.multitest import multipletests

# Configuration
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "..", "data"))
OUTPUT_DIR = BASE_DIR
os.makedirs(OUTPUT_DIR, exist_ok=True)

def load_data():
    all_files = glob.glob(os.path.join(DATA_DIR, "*.csv"))
    df_list = []
    for filename in all_files:
        try:
            df = pd.read_csv(filename)
            df_list.append(df)
        except Exception as e:
            print(f"Error reading {filename}: {e}")
    
    if not df_list:
        raise ValueError("No CSV files found in data directory")
        
    full_df = pd.concat(df_list, ignore_index=True)
    
    # Filter out failed runs
    # Check for Status column if exists, or check for runtime > 0
    if 'Status' in full_df.columns:
        full_df = full_df[full_df['Status'] == 'Success']
    
    # Also ensure runtime is positive
    full_df = full_df[full_df['TotalRuntime(s)'] > 0]
    
    return full_df

def normalize_pass_names(df):
    # Normalize 'None', 'baseline', NaN to 'None'
    # These columns represent the "Targeted Pass for Disabling"
    # So 'None' means "No pass disabled" (i.e., All ON)
    
    def clean_name(name):
        if pd.isna(name):
            return "None"
        s = str(name).strip()
        if s.lower() in ["none", "baseline", "nan", ""]:
            return "None"
        return s

    df['LLVM_Pass'] = df['LLVM_Pass'].apply(clean_name)
    df['MIR_Pass'] = df['MIR_Pass'].apply(clean_name)
    return df

def analyze_interactions(df):
    # Identify all unique MIR passes and LLVM passes that were ablated
    # Exclude 'None' and 'All'
    mir_passes = [p for p in df['MIR_Pass'].unique() if p not in ['None', 'All']]
    llvm_passes = [p for p in df['LLVM_Pass'].unique() if p not in ['None', 'All']]
    
    print(f"Found {len(mir_passes)} MIR passes and {len(llvm_passes)} LLVM passes.")
    
    results = []
    
    # Baseline data (y00): MIR='None', LLVM='None'
    base_df = df[(df['MIR_Pass'] == 'None') & (df['LLVM_Pass'] == 'None')]
    if base_df.empty:
        print("WARNING: No baseline (y00) data found! Cannot calculate double differences.")
        return None
    
    # We use TotalRuntime(s) as the metric
    metric = 'TotalRuntime(s)'
    
    # Log transform
    base_df = base_df.copy()
    base_df['log_y'] = np.log(base_df[metric])
    z00 = base_df['log_y'].values
    
    print(f"Baseline (y00) samples: {len(z00)}")

    for m in mir_passes:
        for l in llvm_passes:
            # y10: MIR=m, LLVM='None'
            y10_df = df[(df['MIR_Pass'] == m) & (df['LLVM_Pass'] == 'None')]
            
            # y01: MIR='None', LLVM=l
            y01_df = df[(df['MIR_Pass'] == 'None') & (df['LLVM_Pass'] == l)]
            
            # y11: MIR=m, LLVM=l
            y11_df = df[(df['MIR_Pass'] == m) & (df['LLVM_Pass'] == l)]
            
            # Check completeness
            if y10_df.empty or y01_df.empty or y11_df.empty:
                # print(f"Skipping ({m}, {l}): Incomplete data")
                continue
                
            # Log transform
            z10 = np.log(y10_df[metric].values)
            z01 = np.log(y01_df[metric].values)
            z11 = np.log(y11_df[metric].values)
            
            # Calculate means
            mean_z00 = np.mean(z00)
            mean_z10 = np.mean(z10)
            mean_z01 = np.mean(z01)
            mean_z11 = np.mean(z11)
            
            # Interaction Delta = (z01 - z11) - (z00 - z10)
            # = (Effect of dropping MIR given LLVM is OFF) - (Effect of dropping MIR given LLVM is ON)
            # Or symmetric: (Effect of dropping LLVM given MIR is OFF) - (Effect of dropping LLVM given MIR is ON)
            delta = (mean_z01 - mean_z11) - (mean_z00 - mean_z10)
            
            # Bootstrap for CI and p-value
            # Resample from the runs for this specific (m,l) combination
            n_boot = 1000
            boot_deltas = []
            for _ in range(n_boot):
                s00 = np.random.choice(z00, size=len(z00), replace=True).mean()
                s10 = np.random.choice(z10, size=len(z10), replace=True).mean()
                s01 = np.random.choice(z01, size=len(z01), replace=True).mean()
                s11 = np.random.choice(z11, size=len(z11), replace=True).mean()
                boot_deltas.append((s01 - s11) - (s00 - s10))
            
            boot_deltas = np.array(boot_deltas)
            ci_low = np.percentile(boot_deltas, 2.5)
            ci_high = np.percentile(boot_deltas, 97.5)
            
            # P-value (approximate from bootstrap distribution or t-test)
            # Null hypothesis: Delta = 0
            # Simple bootstrap p-value: 2 * min(P(d>0), P(d<0))
            p_val = 2 * min(np.mean(boot_deltas > 0), np.mean(boot_deltas < 0))
            
            results.append({
                'mir_pass': m,
                'llvm_pass': l,
                'y00_mean': np.exp(mean_z00),
                'y10_mean': np.exp(mean_z10),
                'y01_mean': np.exp(mean_z01),
                'y11_mean': np.exp(mean_z11),
                'delta': delta,
                'ci_low': ci_low,
                'ci_high': ci_high,
                'p_value': p_val
            })
            
    return pd.DataFrame(results)

def main():
    print("Loading data...")
    df = load_data()
    print(f"Loaded {len(df)} rows.")
    
    print("Normalizing data...")
    df = normalize_pass_names(df)
    
    print("Analyzing interactions...")
    results_df = analyze_interactions(df)
    
    if results_df is None or results_df.empty:
        print("No interactions calculated.")
        return

    # FDR Correction
    reject, pvals_corrected, _, _ = multipletests(results_df['p_value'], alpha=0.05, method='fdr_bh')
    results_df['p_adj'] = pvals_corrected
    results_df['significant'] = reject
    
    # Save results
    results_csv = os.path.join(OUTPUT_DIR, "interaction_results.csv")
    results_df.sort_values('p_adj').to_csv(results_csv, index=False)
    print(f"Saved results to {results_csv}")
    
    # Visualizations
    
    # 1. Heatmap of Delta
    pivot_delta = results_df.pivot(index='mir_pass', columns='llvm_pass', values='delta')
    plt.figure(figsize=(12, 10))
    sns.heatmap(pivot_delta, cmap="RdBu_r", center=0, annot=False)
    plt.title("Interaction Effect (Delta) Heatmap")
    plt.tight_layout()
    plt.savefig(os.path.join(OUTPUT_DIR, "interaction_heatmap.png"), bbox_inches="tight")
    plt.savefig(os.path.join(OUTPUT_DIR, "interaction_heatmap.pdf"), bbox_inches="tight")
    
    # 2. Heatmap of Significance (P-adj)
    # Mask non-significant ones?
    pivot_sig = results_df.pivot(index='mir_pass', columns='llvm_pass', values='significant')
    
    # 3. Top-K Forest Plot
    top_k = (
        results_df[results_df["significant"]]
        .sort_values("delta", key=abs, ascending=False)
        .head(50)
        .copy()
    )
    if not top_k.empty:
        top_k["label"] = top_k["mir_pass"] + " + " + top_k["llvm_pass"]
        fig_h = max(10.0, 0.38 * len(top_k) + 2.0)
        plt.figure(figsize=(12, fig_h))

        plt.errorbar(
            x=top_k["delta"],
            y=range(len(top_k)),
            xerr=[top_k["delta"] - top_k["ci_low"], top_k["ci_high"] - top_k["delta"]],
            fmt="o",
            capsize=4,
            markersize=4,
            elinewidth=1.2,
        )
        plt.yticks(range(len(top_k)), top_k["label"], fontsize=8)
        plt.axvline(x=0, color="r", linestyle="--", linewidth=1.2)
        plt.xlabel("Interaction Effect (Delta)")
        plt.title("Top Significant Interactions (Top 50)")
        plt.tight_layout()
        out_png = os.path.join(OUTPUT_DIR, "top_interactions_forest.png")
        out_pdf = os.path.join(OUTPUT_DIR, "top_interactions_forest.pdf")
        plt.savefig(out_png, bbox_inches="tight")
        plt.savefig(out_pdf, bbox_inches="tight")
        plt.close()
    
    # 4. Save the 2x2 mean table for the top 1 result (as example)
    if not results_df.empty:
        top_row = results_df.sort_values('p_adj').iloc[0]
        print("\nTop Interaction Example:")
        print(f"MIR: {top_row['mir_pass']}, LLVM: {top_row['llvm_pass']}")
        print(f"y00 (Base): {top_row['y00_mean']:.4f}")
        print(f"y10 (No MIR): {top_row['y10_mean']:.4f}")
        print(f"y01 (No LLVM): {top_row['y01_mean']:.4f}")
        print(f"y11 (Neither): {top_row['y11_mean']:.4f}")
        print(f"Delta: {top_row['delta']:.4f}, p_adj: {top_row['p_adj']:.4e}")

if __name__ == "__main__":
    main()
