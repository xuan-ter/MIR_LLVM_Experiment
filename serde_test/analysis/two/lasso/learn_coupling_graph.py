import pandas as pd
import numpy as np
import os
import glob
from sklearn.linear_model import LassoCV, Lasso
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.model_selection import KFold
import matplotlib.pyplot as plt
import seaborn as sns
import networkx as nx
from matplotlib.lines import Line2D

# Configuration
DATA_DIR = "/mnt/fjx/Compiler_Experiment/analysis/data"
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
os.makedirs(OUTPUT_DIR, exist_ok=True)

def load_and_preprocess_data():
    """
    Loads raw CSV data and converts it into a feature matrix X and target vector y
    suitable for Lasso regression.
    
    X: Binary matrix where 1 means the Pass is DISABLED.
    y: Log-transformed runtime.
    """
    print("Loading data...")
    all_files = glob.glob(os.path.join(DATA_DIR, "*.csv"))
    df_list = []
    for filename in all_files:
        try:
            df = pd.read_csv(filename)
            # Filter failed runs
            if 'Status' in df.columns:
                df = df[df['Status'] == 'Success']
            
            # Ensure TotalRuntime(s) is numeric
            df['TotalRuntime(s)'] = pd.to_numeric(df['TotalRuntime(s)'], errors='coerce')
            df = df[df['TotalRuntime(s)'] > 0]
            df_list.append(df)
        except Exception as e:
            print(f"Error reading {filename}: {e}")
            import traceback
            traceback.print_exc()
    
    if not df_list:
        raise ValueError("No CSV files found")
        
    full_df = pd.concat(df_list, ignore_index=True)
    
    # Normalize pass names
    def clean_name(name):
        try:
            if pd.isna(name):
                return None
            s = str(name).strip()
            if s.lower() in ["none", "baseline", "nan", "", "all"]:
                return None
            return s
        except:
            return None

    full_df['MIR_Pass'] = full_df['MIR_Pass'].apply(clean_name)
    full_df['LLVM_Pass'] = full_df['LLVM_Pass'].apply(clean_name)
    
    # Identify all unique passes
    # Filter out None values before sorting
    mir_passes = [p for p in full_df['MIR_Pass'].unique() if p is not None]
    llvm_passes = [p for p in full_df['LLVM_Pass'].unique() if p is not None]
    
    # Sort them, ensuring all are strings
    mir_passes = sorted([str(p) for p in mir_passes])
    llvm_passes = sorted([str(p) for p in llvm_passes])
    
    all_passes = mir_passes + llvm_passes
    print(f"Features: {len(mir_passes)} MIR passes + {len(llvm_passes)} LLVM passes = {len(all_passes)} total features.")
    
    # Build Feature Matrix X
    # Each row is a run. 
    # Columns: [MIR_Pass_1, ..., MIR_Pass_N, LLVM_Pass_1, ..., LLVM_Pass_M]
    # Value 1 means Disabled, 0 means Enabled.
    
    X_rows = []
    y = []
    
    # Map pass name to column index
    pass_to_idx = {p: i for i, p in enumerate(all_passes)}
    
    for _, row in full_df.iterrows():
        x_vec = np.zeros(len(all_passes))
        
        m_pass = row['MIR_Pass']
        l_pass = row['LLVM_Pass']
        
        if m_pass is not None and m_pass in pass_to_idx:
            x_vec[pass_to_idx[m_pass]] = 1
        if l_pass is not None and l_pass in pass_to_idx:
            x_vec[pass_to_idx[l_pass]] = 1
            
        X_rows.append(x_vec)
        y.append(np.log(row['TotalRuntime(s)']))
        
    X = np.array(X_rows)
    y = np.array(y)
    
    # Generate Interaction Features (Cross-Level Only for efficiency)
    # We only care about MIR x LLVM interactions as per paper
    print("Generating interaction features...")
    interaction_features = []
    interaction_names = []
    
    for i, m_pass in enumerate(mir_passes):
        for j, l_pass in enumerate(llvm_passes):
            # Find indices in X
            idx_m = pass_to_idx[m_pass]
            idx_l = pass_to_idx[l_pass]
            
            # Interaction term: x_i * x_j (1 only if BOTH are disabled)
            interaction_col = X[:, idx_m] * X[:, idx_l]
            
            # Optimization: Only add if this interaction actually appears in data
            if np.sum(interaction_col) > 0:
                interaction_features.append(interaction_col)
                interaction_names.append(f"{m_pass}|{l_pass}")
    
    if interaction_features:
        X_inter = np.column_stack(interaction_features)
        X_full = np.hstack([X, X_inter])
        feature_names = all_passes + interaction_names
    else:
        X_full = X
        feature_names = all_passes
        
    print(f"Final Feature Matrix shape: {X_full.shape}")
    return X_full, y, feature_names, mir_passes, llvm_passes

def run_lasso_stability_selection(X, y, feature_names, n_bootstrap=100):
    """
    Runs Lasso with stability selection (Bootstrap).
    """
    print(f"Running Stability Selection with {n_bootstrap} bootstraps...")
    
    n_samples, n_features = X.shape
    stability_scores = np.zeros(n_features)
    
    # Use LassoCV to automatically find alpha for each bootstrap? 
    # Or fix alpha based on a pilot run? LassoCV is safer but slower.
    # To speed up, we use a fixed alpha estimated from the whole dataset, or a small LassoCV per run.
    # Let's use LassoCV on full data first to get a sense of alpha.
    
    print("Tuning hyperparameters on full dataset...")
    # Standardize features? 
    # Our features are 0/1, but standardization is usually good for Lasso.
    # However, interaction terms (product of binary) are also 0/1.
    # Let's just fit intercept.
    
    model_cv = LassoCV(cv=5, random_state=42, n_jobs=-1, max_iter=10000)
    model_cv.fit(X, y)
    best_alpha = model_cv.alpha_
    print(f"Best alpha found: {best_alpha}")
    
    # Now run bootstrap with this alpha (or slightly randomized)
    coeffs_list = []
    
    for i in range(n_bootstrap):
        if i % 10 == 0:
            print(f"Bootstrap {i}/{n_bootstrap}")
            
        # Resample
        indices = np.random.choice(n_samples, n_samples, replace=True)
        X_res = X[indices]
        y_res = y[indices]
        
        # Fit Lasso
        # We use a slightly randomized alpha to encourage stability exploration? 
        # Or just fixed alpha. Standard Stability Selection uses RandomizedLasso, 
        # but here we just do Bootstrap + Lasso.
        lasso = Lasso(alpha=best_alpha, max_iter=10000)
        lasso.fit(X_res, y_res)
        
        # Record non-zero coefficients
        nonzero = np.abs(lasso.coef_) > 1e-5
        stability_scores[nonzero] += 1
        coeffs_list.append(lasso.coef_)
        
    stability_scores /= n_bootstrap
    avg_coeffs = np.mean(coeffs_list, axis=0)
    
    return stability_scores, avg_coeffs

def save_coupling_graph(stability_scores, avg_coeffs, feature_names, threshold=0.5):
    """
    Extracts significant interactions and saves them.
    """
    print("Extracting significant interactions...")
    edges = []
    
    for i, score in enumerate(stability_scores):
        name = feature_names[i]
        
        # Check if it's an interaction feature (contains '|')
        if '|' in name:
            if score >= threshold:
                parts = name.split('|')
                mir = parts[0]
                llvm = parts[1]
                weight = avg_coeffs[i]
                
                edges.append({
                    'Source': mir,
                    'Target': llvm,
                    'Type': 'Interaction',
                    'Weight': weight,
                    'Stability': score
                })
                
    df_edges = pd.DataFrame(edges)
    output_path = os.path.join(OUTPUT_DIR, 'coupling_edges.csv')
    df_edges.to_csv(output_path, index=False)
    print(f"Saved {len(df_edges)} significant edges to {output_path}")
    return df_edges

def plot_coupling_graph(df_edges, mir_passes, llvm_passes):
    if df_edges.empty:
        print("No significant edges to plot.")
        return

    plt.figure(figsize=(22, 18))
    G = nx.Graph()
    
    # Identify node types
    mir_set = set(mir_passes)
    llvm_set = set(llvm_passes)
    
    # Add nodes and edges
    nodes_in_graph = set()
    for _, row in df_edges.iterrows():
        u, v = row['Source'], row['Target']
        G.add_edge(u, v, weight=abs(row['Weight']), color='red' if row['Weight'] > 0 else 'blue')
        nodes_in_graph.add(u)
        nodes_in_graph.add(v)
        
    pos = nx.spring_layout(G, k=0.6, iterations=200, seed=42)
    
    # Split nodes for drawing
    mir_nodes = [n for n in nodes_in_graph if n in mir_set]
    llvm_nodes = [n for n in nodes_in_graph if n in llvm_set]
    # Handle nodes not in either set (fallback)
    other_nodes = [n for n in nodes_in_graph if n not in mir_set and n not in llvm_set]
    
    # Draw MIR nodes (Square 's', Yellow)
    nx.draw_networkx_nodes(G, pos, nodelist=mir_nodes, node_shape='s', 
                           node_color='yellow', node_size=1100, alpha=0.7, label='MIR Pass')
                           
    # Draw LLVM nodes (Circle 'o', LightBlue)
    nx.draw_networkx_nodes(G, pos, nodelist=llvm_nodes, node_shape='o', 
                           node_color='lightblue', node_size=1100, alpha=0.7, label='LLVM Pass')
                           
    if other_nodes:
        nx.draw_networkx_nodes(G, pos, nodelist=other_nodes, node_shape='o', 
                               node_color='lightgrey', node_size=900, alpha=0.5)

    # Draw edges
    edges = G.edges()
    colors = [G[u][v]['color'] for u,v in edges]
    weights = [max(0.2, min(G[u][v]['weight'] * 40, 6.0)) for u,v in edges]
    
    nx.draw_networkx_edges(G, pos, edge_color=colors, width=weights, alpha=0.55)
    
    # Draw labels
    nx.draw_networkx_labels(G, pos, font_size=8, font_family='sans-serif')
    
    # Create custom legend handles to avoid overlap and ensure clarity
    legend_elements = [
        Line2D([0], [0], marker='s', color='w', label='MIR Pass',
               markerfacecolor='yellow', markersize=15, alpha=0.7),
        Line2D([0], [0], marker='o', color='w', label='LLVM Pass',
               markerfacecolor='lightblue', markersize=15, alpha=0.7),
        Line2D([0], [0], color='red', lw=2, label='Conflict (+)', alpha=0.55),
        Line2D([0], [0], color='blue', lw=2, label='Synergy (-)', alpha=0.55)
    ]
    
    # Place legend outside the plot area
    plt.legend(handles=legend_elements, loc='upper left', bbox_to_anchor=(1, 1), 
               title="Node/Edge Types", fontsize=10, title_fontsize=12)
    
    plt.title("Cross-Level Coupling Graph (Lasso Recovered)\nSquare=MIR, Circle=LLVM | Red=Conflict(+), Blue=Synergy(-)")
    plt.axis('off')
    plt.savefig(os.path.join(OUTPUT_DIR, "lasso_coupling_graph.png"), dpi=220, bbox_inches="tight")
    plt.savefig(os.path.join(OUTPUT_DIR, "lasso_coupling_graph.pdf"), bbox_inches="tight")
    print("Graph plot saved.")

if __name__ == "__main__":
    try:
        X, y, feature_names, mir_passes, llvm_passes = load_and_preprocess_data()
        
        # Run Lasso
        stability, coeffs = run_lasso_stability_selection(X, y, feature_names, n_bootstrap=50)
        
        # Save and Plot
        df_edges = save_coupling_graph(stability, coeffs, feature_names, threshold=0.4) # Threshold 40%
        plot_coupling_graph(df_edges, mir_passes, llvm_passes)
        
        print("\n=== Top Recovered Interactions ===")
        if not df_edges.empty:
            print(df_edges.sort_values('Stability', ascending=False).head(10))
        
    except Exception as e:
        print(f"An error occurred: {e}")
