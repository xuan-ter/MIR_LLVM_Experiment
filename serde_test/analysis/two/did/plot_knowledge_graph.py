import pandas as pd
import networkx as nx
import matplotlib.pyplot as plt
import os
import numpy as np

# Configuration
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_CSV = os.path.join(BASE_DIR, "interaction_results.csv")
OUTPUT_DIR = os.path.join(BASE_DIR, "coupling_plots")
os.makedirs(OUTPUT_DIR, exist_ok=True)

def plot_knowledge_graph(df, output_path, top_n=None):
    """
    Plots a Knowledge Graph style network (Force-Directed Layout).
    - MIR Passes: Square nodes (Source)
    - LLVM Passes: Circular nodes (Target)
    - Edge Color: Blue (Negative/Redundant), Red (Positive/Interference)
    - Node Size: Proportional to total interaction strength (Degree Centrality)
    - Layout: Spring layout to naturally cluster coupled nodes
    """
    # Filter significant interactions
    sig_df = df[df['significant'] == True].copy()
    if sig_df.empty:
        print("No significant interactions found.")
        return

    # Use all significant interactions if top_n is None
    if top_n is not None:
        sig_df['abs_delta'] = sig_df['delta'].abs()
        top_interactions = sig_df.sort_values('abs_delta', ascending=False).head(top_n)
    else:
        top_interactions = sig_df
        top_interactions['abs_delta'] = top_interactions['delta'].abs()

    # Create Graph
    G = nx.Graph()
    
    # Track node types and total strength
    mir_nodes = set()
    llvm_nodes = set()
    node_strength = {}

    for _, row in top_interactions.iterrows():
        mir = row['mir_pass']
        llvm = row['llvm_pass']
        weight = row['delta']
        abs_weight = abs(weight)
        
        mir_nodes.add(mir)
        llvm_nodes.add(llvm)
        
        G.add_edge(mir, llvm, weight=weight, abs_weight=abs_weight)
        
        # Accumulate strength for node sizing
        node_strength[mir] = node_strength.get(mir, 0) + abs_weight
        node_strength[llvm] = node_strength.get(llvm, 0) + abs_weight

    # Define Layout (Spring/Force-Directed)
    # k parameter controls node spacing (larger = more spread out)
    pos = nx.spring_layout(G, k=0.5, iterations=100, seed=42)

    plt.figure(figsize=(16, 16))
    
    # Draw Edges
    edges = G.edges(data=True)
    neg_edges = [(u, v) for u, v, d in edges if d['weight'] < 0]
    pos_edges = [(u, v) for u, v, d in edges if d['weight'] > 0]
    
    # Edge widths
    width_scale = 15
    weights_neg = [G[u][v]['abs_weight'] * width_scale for u, v in neg_edges]
    weights_pos = [G[u][v]['abs_weight'] * width_scale for u, v in pos_edges]

    nx.draw_networkx_edges(G, pos, edgelist=neg_edges, edge_color='royalblue', alpha=0.6, width=weights_neg)
    nx.draw_networkx_edges(G, pos, edgelist=pos_edges, edge_color='crimson', alpha=0.6, width=weights_pos)

    # Draw Nodes
    # Size nodes by their total interaction strength
    base_size = 300
    size_scale = 3000
    
    mir_sizes = [base_size + node_strength[n] * size_scale for n in mir_nodes if n in G]
    llvm_sizes = [base_size + node_strength[n] * size_scale for n in llvm_nodes if n in G]
    
    # Draw MIR Nodes (Squares)
    nx.draw_networkx_nodes(G, pos, nodelist=list(mir_nodes), node_shape='s', 
                           node_color='#87CEEB', # SkyBlue
                           node_size=mir_sizes, 
                           label='MIR Pass (Source)')
    
    # Draw LLVM Nodes (Circles)
    nx.draw_networkx_nodes(G, pos, nodelist=list(llvm_nodes), node_shape='o', 
                           node_color='#98FB98', # PaleGreen
                           node_size=llvm_sizes, 
                           label='LLVM Pass (Target)')

    # Draw Labels
    # Use a slightly smaller font for less clutter
    nx.draw_networkx_labels(G, pos, font_size=9, font_family='sans-serif', font_weight='bold')

    plt.title(f'Optimization Coupling Knowledge Graph (Force-Directed)\nTop {top_n} Interactions', fontsize=16)
    plt.axis('off')

    # Legend
    from matplotlib.lines import Line2D
    legend_elements = [
        Line2D([0], [0], color='royalblue', lw=3, label='Negative Coupling (Redundancy)'),
        Line2D([0], [0], color='crimson', lw=3, label='Positive Coupling (Interference)'),
        Line2D([0], [0], marker='s', color='w', markerfacecolor='#87CEEB', markersize=15, label='MIR Pass (Hubs)'),
        Line2D([0], [0], marker='o', color='w', markerfacecolor='#98FB98', markersize=15, label='LLVM Pass (Leaves)')
    ]
    plt.legend(handles=legend_elements, loc='lower right', fontsize=12)

    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()
    print(f"Saved knowledge graph to {output_path}")

def main():
    print(f"Reading data from {INPUT_CSV}...")
    try:
        df = pd.read_csv(INPUT_CSV)
    except FileNotFoundError:
        print("Error: Input CSV file not found.")
        return

    plot_knowledge_graph(df, os.path.join(OUTPUT_DIR, "coupling_knowledge_graph.pdf"), top_n=None)

if __name__ == "__main__":
    main()
