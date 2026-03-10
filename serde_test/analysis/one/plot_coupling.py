import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt
import networkx as nx
import os
import numpy as np

# Configuration
INPUT_CSV = "/mnt/fjx/Compiler_Experiment/analysis/one/interaction_results.csv"
OUTPUT_DIR = "/mnt/fjx/Compiler_Experiment/analysis/one/coupling_plots"

def plot_filtered_heatmap(df, output_path):
    """
    Plots a heatmap showing ONLY significant interactions.
    Non-significant cells are masked (white).
    Rows/Cols with NO significant interactions are removed to reduce clutter.
    """
    # Filter only significant rows/cols first
    sig_df = df[df['significant'] == True]
    if sig_df.empty:
        print("No significant interactions found for heatmap.")
        return

    relevant_mir = sig_df['mir_pass'].unique()
    relevant_llvm = sig_df['llvm_pass'].unique()

    # Pivot full data but only for relevant items
    pivot_delta = df.pivot(index='mir_pass', columns='llvm_pass', values='delta')
    pivot_sig = df.pivot(index='mir_pass', columns='llvm_pass', values='significant')

    # Subset to relevant items
    pivot_delta = pivot_delta.loc[relevant_mir, relevant_llvm]
    pivot_sig = pivot_sig.loc[relevant_mir, relevant_llvm]

    # Mask: True means data will be hidden
    # We hide where significant is False or NaN
    mask = ~pivot_sig.fillna(False).astype(bool)

    plt.figure(figsize=(20, 15))
    sns.heatmap(pivot_delta, mask=mask, center=0, cmap='RdBu_r', annot=False, 
                cbar_kws={'label': 'Interaction Delta (Significant Only)'},
                square=True, linewidths=.5, linecolor='gray')
    plt.title('Filtered Interaction Heatmap (Non-Significant Masked)')
    plt.tight_layout()
    plt.savefig(output_path)
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
    try:
        df = pd.read_csv(INPUT_CSV)
    except FileNotFoundError:
        print("Error: Input CSV file not found.")
        return

    # 1. Filtered Heatmap
    plot_filtered_heatmap(df, os.path.join(OUTPUT_DIR, "filtered_heatmap.png"))

    # 2. Clustermap
    plot_clustermap(df, os.path.join(OUTPUT_DIR, "clustered_heatmap.png"))

    # 3. Bipartite Network (Top 50)
    plot_bipartite_network(df, os.path.join(OUTPUT_DIR, "coupling_network_top50.png"), top_n=50)

if __name__ == "__main__":
    main()
