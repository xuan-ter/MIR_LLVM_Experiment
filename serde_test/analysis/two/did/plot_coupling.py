import os
import csv
import numpy as np
import matplotlib.pyplot as plt

try:
    import pandas as pd
    HAVE_PANDAS = True
except Exception:
    HAVE_PANDAS = False

try:
    import seaborn as sns
    HAVE_SEABORN = True
except Exception:
    HAVE_SEABORN = False

try:
    import networkx as nx
    HAVE_NETWORKX = True
except Exception:
    HAVE_NETWORKX = False

# Configuration
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_CSV = os.path.join(BASE_DIR, "interaction_results.csv")
OUTPUT_DIR = os.path.join(BASE_DIR, "coupling_plots")
os.makedirs(OUTPUT_DIR, exist_ok=True)

def plot_filtered_heatmap(data, output_path):
    """
    Plots a heatmap showing ONLY significant interactions.
    Non-significant cells are masked (white).
    Rows/Cols with NO significant interactions are removed to reduce clutter.
    """
    if HAVE_PANDAS and HAVE_SEABORN:
        df = data
        sig_df = df[df['significant'] == True]
        if sig_df.empty:
            print("No significant interactions found for heatmap.")
            return

        relevant_mir = sig_df['mir_pass'].unique()
        relevant_llvm = sig_df['llvm_pass'].unique()

        pivot_delta = df.pivot(index='mir_pass', columns='llvm_pass', values='delta')
        pivot_sig = df.pivot(index='mir_pass', columns='llvm_pass', values='significant')

        pivot_delta = pivot_delta.loc[relevant_mir, relevant_llvm]
        pivot_sig = pivot_sig.loc[relevant_mir, relevant_llvm]

        mask = ~pivot_sig.fillna(False).astype(bool)

        fig, ax = plt.subplots(figsize=(20, 15))
        sns.heatmap(
            pivot_delta,
            mask=mask,
            center=0,
            cmap='RdBu_r',
            annot=False,
            cbar_kws={
                'label': 'Interaction Delta (Significant Only)',
                'orientation': 'horizontal',
                'pad': 0.08,
                'shrink': 0.8,
            },
            square=True,
            linewidths=.5,
            linecolor='gray',
            ax=ax,
        )
        ax.set_title('Filtered Interaction Heatmap (Non-Significant Masked)')
        cbar = ax.collections[0].colorbar
        cbar.ax.xaxis.set_label_position('bottom')
        cbar.ax.xaxis.set_ticks_position('bottom')
        fig.tight_layout()
        fig.savefig(output_path)
        plt.close()
        print(f"Saved filtered heatmap to {output_path}")
        return

    def fbool(x):
        return str(x).strip().lower() == "true"

    def ffloat(x):
        try:
            return float(str(x).strip())
        except Exception:
            return float("nan")

    rows = data
    mir_order = {}
    llvm_order = {}
    for r in rows:
        if not fbool(r.get("significant")):
            continue
        m = str(r.get("mir_pass", "")).strip()
        l = str(r.get("llvm_pass", "")).strip()
        if m and m not in mir_order:
            mir_order[m] = len(mir_order)
        if l and l not in llvm_order:
            llvm_order[l] = len(llvm_order)

    mir_list = list(mir_order.keys())
    llvm_list = list(llvm_order.keys())
    if not mir_list or not llvm_list:
        print("No significant interactions found for heatmap.")
        return

    m = len(mir_list)
    n = len(llvm_list)
    mat = np.full((m, n), np.nan, dtype=float)
    for r in rows:
        if not fbool(r.get("significant")):
            continue
        mir = str(r.get("mir_pass", "")).strip()
        llvm = str(r.get("llvm_pass", "")).strip()
        if mir not in mir_order or llvm not in llvm_order:
            continue
        d = ffloat(r.get("delta"))
        if d != d:
            continue
        mat[mir_order[mir], llvm_order[llvm]] = d

    max_abs = float(np.nanmax(np.abs(mat)))
    if not (max_abs > 0):
        print("No valid deltas found for heatmap.")
        return

    from matplotlib.colors import TwoSlopeNorm

    masked = np.ma.array(mat, mask=np.isnan(mat))
    cmap = plt.get_cmap("RdBu_r").copy()
    cmap.set_bad(color="white")
    norm = TwoSlopeNorm(vmin=-max_abs, vcenter=0.0, vmax=max_abs)

    fig, ax = plt.subplots(figsize=(20, 15))
    im = ax.imshow(masked, cmap=cmap, norm=norm, aspect="equal", interpolation="nearest")
    ax.set_title("Filtered Interaction Heatmap (Non-Significant Masked)")

    ax.set_xticks(range(n))
    ax.set_yticks(range(m))
    ax.set_xticklabels(llvm_list, rotation=90, fontsize=6)
    ax.set_yticklabels(mir_list, fontsize=6)

    ax.set_xticks(np.arange(-.5, n, 1), minor=True)
    ax.set_yticks(np.arange(-.5, m, 1), minor=True)
    ax.grid(which="minor", color="gray", linestyle="-", linewidth=0.3)
    ax.tick_params(which="minor", bottom=False, left=False)

    cbar = fig.colorbar(im, ax=ax, orientation="horizontal", pad=0.08, shrink=0.8)
    cbar.set_label("Interaction Delta (Significant Only)")
    cbar.ax.xaxis.set_label_position("bottom")
    cbar.ax.xaxis.set_ticks_position("bottom")

    fig.tight_layout()
    fig.savefig(output_path)
    plt.close()
    print(f"Saved filtered heatmap to {output_path}")

def plot_clustermap(df, output_path):
    """
    Plots a clustermap to group similar interaction patterns.
    Uses 0 for non-significant interactions during clustering.
    """
    sig_df = df[df['significant'] == True]
    if sig_df.empty:
        return

    relevant_mir = sig_df['mir_pass'].unique()
    relevant_llvm = sig_df['llvm_pass'].unique()

    # Create matrix where non-significant = 0
    pivot_delta = df.pivot(index='mir_pass', columns='llvm_pass', values='delta')
    pivot_sig = df.pivot(index='mir_pass', columns='llvm_pass', values='significant').fillna(False)
    
    # Filter relevant
    pivot_delta = pivot_delta.loc[relevant_mir, relevant_llvm]
    pivot_sig = pivot_sig.loc[relevant_mir, relevant_llvm]

    # Apply mask (set non-sig to 0)
    data_for_clustering = pivot_delta.copy()
    data_for_clustering[~pivot_sig] = 0
    
    # Fill NaNs with 0
    data_for_clustering = data_for_clustering.fillna(0)

    g = sns.clustermap(data_for_clustering, center=0, cmap='RdBu_r', 
                       figsize=(20, 20), method='ward',
                       cbar_kws={'label': 'Interaction Delta'})
    g.fig.suptitle('Clustered Interaction Map (Significant Only)', y=1.02)
    plt.savefig(output_path)
    plt.close()
    print(f"Saved clustermap to {output_path}")

def plot_bipartite_network(df, output_path, top_n=50):
    """
    Plots a bipartite network graph for the top N strongest interactions.
    """
    # Get top N strongest significant interactions
    sig_df = df[df['significant'] == True].copy()
    if sig_df.empty:
        return

    sig_df['abs_delta'] = sig_df['delta'].abs()
    top_interactions = sig_df.sort_values('abs_delta', ascending=False).head(top_n)

    B = nx.Graph()
    mir_nodes = top_interactions['mir_pass'].unique()
    llvm_nodes = top_interactions['llvm_pass'].unique()

    B.add_nodes_from(mir_nodes, bipartite=0)
    B.add_nodes_from(llvm_nodes, bipartite=1)

    # Add edges
    for _, row in top_interactions.iterrows():
        B.add_edge(row['mir_pass'], row['llvm_pass'], weight=row['delta'])

    # Position nodes in two vertical layers
    pos = {}
    # Sort nodes alphabetically for consistent layout
    mir_nodes_sorted = sorted(mir_nodes)
    llvm_nodes_sorted = sorted(llvm_nodes)

    # Left layer (MIR)
    for i, node in enumerate(mir_nodes_sorted):
        y = 1.0 - (i / (len(mir_nodes_sorted) - 1)) if len(mir_nodes_sorted) > 1 else 0.5
        pos[node] = (0.2, y) # x=0.2
    
    # Right layer (LLVM)
    for i, node in enumerate(llvm_nodes_sorted):
        y = 1.0 - (i / (len(llvm_nodes_sorted) - 1)) if len(llvm_nodes_sorted) > 1 else 0.5
        pos[node] = (0.8, y) # x=0.8

    plt.figure(figsize=(12, 12))
    
    # Draw Nodes
    nx.draw_networkx_nodes(B, pos, nodelist=mir_nodes, node_color='lightblue', node_shape='s', node_size=500, label='MIR')
    nx.draw_networkx_nodes(B, pos, nodelist=llvm_nodes, node_color='lightgreen', node_shape='o', node_size=500, label='LLVM')

    # Draw Edges (Red for positive, Blue for negative)
    edges = B.edges(data=True)
    neg_edges = [(u, v) for u, v, d in edges if d['weight'] < 0]
    pos_edges = [(u, v) for u, v, d in edges if d['weight'] > 0]

    # Width scaling
    width_scale = 30
    weights_neg = [abs(B[u][v]['weight']) * width_scale for u, v in neg_edges]
    weights_pos = [abs(B[u][v]['weight']) * width_scale for u, v in pos_edges]

    nx.draw_networkx_edges(B, pos, edgelist=neg_edges, edge_color='blue', width=weights_neg, alpha=0.6)
    nx.draw_networkx_edges(B, pos, edgelist=pos_edges, edge_color='red', width=weights_pos, alpha=0.6)

    # Labels
    # Offset labels slightly to avoid overlap with nodes
    # For MIR (Left), align right of node? No, align left.
    # For LLVM (Right), align right.
    
    # Simple labels for now
    nx.draw_networkx_labels(B, pos, font_size=8, font_family='sans-serif')

    plt.title(f'Top {top_n} Strongest Cross-Layer Couplings (Bipartite Graph)\nBlue=Negative (Redundant), Red=Positive (Interference)')
    plt.axis('off')
    
    # Legend
    from matplotlib.lines import Line2D
    legend_elements = [
        Line2D([0], [0], color='blue', lw=2, label='Negative Interaction (Redundancy)'),
        Line2D([0], [0], color='red', lw=2, label='Positive Interaction (Interference)'),
        Line2D([0], [0], marker='s', color='w', markerfacecolor='lightblue', markersize=10, label='MIR Pass'),
        Line2D([0], [0], marker='o', color='w', markerfacecolor='lightgreen', markersize=10, label='LLVM Pass')
    ]
    plt.legend(handles=legend_elements, loc='upper center', bbox_to_anchor=(0.5, -0.05), ncol=2)

    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()
    print(f"Saved bipartite network to {output_path}")

def main():
    print(f"Reading data from {INPUT_CSV}...")
    if HAVE_PANDAS:
        try:
            df = pd.read_csv(INPUT_CSV)
        except FileNotFoundError:
            print("Error: Input CSV file not found.")
            return
        plot_filtered_heatmap(df, os.path.join(OUTPUT_DIR, "filtered_heatmap.pdf"))
        if HAVE_SEABORN:
            plot_clustermap(df, os.path.join(OUTPUT_DIR, "clustered_heatmap.pdf"))
        if HAVE_NETWORKX:
            plot_bipartite_network(df, os.path.join(OUTPUT_DIR, "coupling_network_top50.pdf"), top_n=50)
        return

    if not os.path.exists(INPUT_CSV):
        print("Error: Input CSV file not found.")
        return

    rows = []
    with open(INPUT_CSV, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows.append(r)

    plot_filtered_heatmap(rows, os.path.join(OUTPUT_DIR, "filtered_heatmap.pdf"))

if __name__ == "__main__":
    main()
