import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import os

# Configuration
INPUT_CSV = "/mnt/fjx/Compiler_Experiment/analysis/one/interaction_results.csv"
OUTPUT_BASE = "/mnt/fjx/Compiler_Experiment/analysis/one/classified_results"

# Paths
NEG_DIR = os.path.join(OUTPUT_BASE, "negative_interaction")
POS_DIR = os.path.join(OUTPUT_BASE, "positive_interaction")
IND_DIR = os.path.join(OUTPUT_BASE, "independent")

def plot_interaction_detail(row, output_path, title_prefix):
    """
    Plots a 2x2 interaction plot for a single (MIR, LLVM) pair.
    """
    # Data preparation
    data = {
        'LLVM Status': ['ON', 'OFF', 'ON', 'OFF'],
        'MIR Status': ['ON', 'ON', 'OFF', 'OFF'],
        'Runtime (s)': [row['y00_mean'], row['y01_mean'], row['y10_mean'], row['y11_mean']]
    }
    df_plot = pd.DataFrame(data)
    
    plt.figure(figsize=(8, 6))
    sns.lineplot(data=df_plot, x='LLVM Status', y='Runtime (s)', hue='MIR Status', 
                 markers=True, dashes=False, style='MIR Status', markersize=10)
    
    plt.title(f"{title_prefix}\nMIR: {row['mir_pass']} vs LLVM: {row['llvm_pass']}\nDelta = {row['delta']:.4f}")
    plt.grid(True, linestyle='--', alpha=0.7)
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()

def plot_top_forest(df, output_path, title, color):
    """
    Plots a forest plot for the top K interactions in the dataframe.
    """
    if df.empty:
        return

    top_k = df.sort_values('delta', key=abs, ascending=False).head(20)
    
    plt.figure(figsize=(10, 8))
    # Create label
    top_k = top_k.copy()
    top_k['label'] = top_k['mir_pass'] + " + " + top_k['llvm_pass']
    
    plt.errorbar(x=top_k['delta'], y=range(len(top_k)), 
                 xerr=[top_k['delta'] - top_k['ci_low'], top_k['ci_high'] - top_k['delta']], 
                 fmt='o', capsize=5, color=color, ecolor='gray')
    plt.yticks(range(len(top_k)), top_k['label'])
    plt.axvline(x=0, color='black', linestyle='--', linewidth=1)
    plt.xlabel("Interaction Effect (Delta)")
    plt.title(title)
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()

def main():
    print(f"Reading data from {INPUT_CSV}...")
    try:
        df = pd.read_csv(INPUT_CSV)
    except FileNotFoundError:
        print("Error: Input CSV file not found.")
        return

    # Classification Logic
    # 1. Negative Interaction: Significant = True AND Delta < 0
    neg_df = df[(df['significant'] == True) & (df['delta'] < 0)].copy()
    
    # 2. Positive Interaction: Significant = True AND Delta > 0
    pos_df = df[(df['significant'] == True) & (df['delta'] > 0)].copy()
    
    # 3. Independent: Significant = False
    ind_df = df[df['significant'] == False].copy()
    
    print(f"Found {len(neg_df)} negative interactions.")
    print(f"Found {len(pos_df)} positive interactions.")
    print(f"Found {len(ind_df)} independent pairs.")

    # Save CSVs
    neg_csv = os.path.join(NEG_DIR, "negative_interactions.csv")
    neg_df.sort_values('delta', ascending=True).to_csv(neg_csv, index=False)
    
    pos_csv = os.path.join(POS_DIR, "positive_interactions.csv")
    pos_df.sort_values('delta', ascending=False).to_csv(pos_csv, index=False)
    
    ind_csv = os.path.join(IND_DIR, "independent_pairs.csv")
    ind_df.sort_values('p_value', ascending=True).to_csv(ind_csv, index=False)
    
    print("CSVs saved.")

    # Generate Plots
    
    # 1. Negative Interactions
    if not neg_df.empty:
        # Forest Plot
        plot_top_forest(neg_df, os.path.join(NEG_DIR, "negative_forest_plot.png"), 
                        "Top Negative Interactions (Redundancy/Backup)", "blue")
        
        # Detail Plots for Top 5
        top_neg = neg_df.sort_values('delta', ascending=True).head(5)
        for idx, row in top_neg.iterrows():
            filename = f"interaction_{row['mir_pass']}_{row['llvm_pass']}.png".replace(" ", "_")
            plot_interaction_detail(row, os.path.join(NEG_DIR, filename), "Negative Interaction")

    # 2. Positive Interactions
    if not pos_df.empty:
        # Forest Plot
        plot_top_forest(pos_df, os.path.join(POS_DIR, "positive_forest_plot.png"), 
                        "Top Positive Interactions (Interference/Conflict)", "red")
        
        # Detail Plots for Top 5
        top_pos = pos_df.sort_values('delta', ascending=False).head(5)
        for idx, row in top_pos.iterrows():
            filename = f"interaction_{row['mir_pass']}_{row['llvm_pass']}.png".replace(" ", "_")
            plot_interaction_detail(row, os.path.join(POS_DIR, filename), "Positive Interaction")

    # 3. Independent (Just a histogram of Deltas maybe?)
    if not ind_df.empty:
        plt.figure(figsize=(10, 6))
        sns.histplot(ind_df['delta'], bins=50, kde=True, color='gray')
        plt.title("Distribution of Interaction Effects (Delta) for Independent Pairs")
        plt.xlabel("Delta")
        plt.axvline(x=0, color='black', linestyle='--')
        plt.tight_layout()
        plt.savefig(os.path.join(IND_DIR, "independent_delta_dist.png"))
        plt.close()

    print("Plots generated.")

if __name__ == "__main__":
    main()
