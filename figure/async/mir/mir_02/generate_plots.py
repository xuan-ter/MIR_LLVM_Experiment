import csv
import matplotlib.pyplot as plt
import os
import sys
import numpy as np

# Configuration
CSV_PATH = "/mnt/fjx/Compiler_Experiment/serde_test/results/MIR/20260203_152054/experiment_results.csv"
OUTPUT_DIR = "/mnt/fjx/Compiler_Experiment/serde_test/results/MIR/20260203_152054/plots"
# Extract experiment name from directory path (parent of plots)
EXP_NAME = os.path.basename(os.path.dirname(OUTPUT_DIR))

def load_data(csv_path):
    grouped_data = {}
    if not os.path.exists(csv_path):
        print(f"Error: CSV file not found at {csv_path}")
        return []

    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row['Status'] != 'Success':
                continue
            
            config_name = row['ConfigName']
            if config_name not in grouped_data:
                grouped_data[config_name] = {
                    'sizes': [],
                    'times': [],
                    'compile_times': [],
                    'mir_pass': row['MIR_Pass'],
                    'llvm_pass': row.get('LLVM_Pass', None)
                }
            
            try:
                grouped_data[config_name]['sizes'].append(float(row['BinarySize(Bytes)']))
                grouped_data[config_name]['times'].append(float(row['TotalRuntime(s)']))
                grouped_data[config_name]['compile_times'].append(float(row['CompileTime(s)']))
            except ValueError:
                continue

    data = []
    for config_name, values in grouped_data.items():
        if not values['sizes']:
            continue
            
        # Calculate averages
        avg_size_bytes = sum(values['sizes']) / len(values['sizes'])
        avg_time = sum(values['times']) / len(values['times'])
        avg_compile_time = sum(values['compile_times']) / len(values['compile_times'])
        
        # Use MIR_Pass as name if available, otherwise ConfigName
        name = values['mir_pass']
        if name == 'N/A' or name == 'None':
            name = config_name
        
        # Disambiguate based on ConfigName
        if config_name.startswith('EXP_ISO_'):
            name = f"Only {name}"
        elif config_name == 'EXP_001_ALL_ON':
            name = "All Passes On"
        elif config_name == 'EXP_002_ALL_OFF':
            name = "All Passes Off"
        elif config_name == 'EXP_000_DEFAULT':
            name = "Default"
        
        # Convert Bytes to MB
        size_mb = avg_size_bytes / (1024 * 1024)
        
        item = {
            'name': name,
            'size': size_mb,
            'time': avg_time,
            'compile_time': avg_compile_time
        }
        data.append(item)
    return data

def plot_scatter(data):
    sizes = [d['size'] for d in data]
    times = [d['time'] for d in data]
    
    # Calculate stats
    avg_size = sum(sizes) / len(sizes)
    avg_time = sum(times) / len(times)

    # 1. Standard Scatter (Zoomed in)
    plt.figure(figsize=(12, 8))
    
    # Color points based on time deviation from average
    # Green (Fast) -> Red (Slow)
    colors = [(t - min(times))/(max(times) - min(times)) if max(times) != min(times) else 0.5 for t in times]
    
    scatter = plt.scatter(sizes, times, c=times, cmap='RdYlGn_r', s=100, alpha=0.8, edgecolors='black')
    plt.colorbar(scatter, label='Execution Time (s)')
    
    # Dynamic axis limits with padding to show differences
    size_span = max(sizes) - min(sizes)
    time_span = max(times) - min(times)
    
    # Handle case where size is constant
    if size_span == 0: size_span = 0.001
    if time_span == 0: time_span = 0.001
    
    plt.xlim(min(sizes) - size_span*0.2, max(sizes) + size_span*0.2)
    plt.ylim(min(times) - time_span*0.2, max(times) + time_span*0.2)

    # Annotate significant points
    sorted_by_time = sorted(data, key=lambda x: x['time'])
    
    # Label top 3 fastest and slowest
    labels_to_show = set()
    for i in range(min(3, len(sorted_by_time))):
        labels_to_show.add(sorted_by_time[i]['name'])
        labels_to_show.add(sorted_by_time[-(i+1)]['name'])
    
    # Label outliers in size
    sorted_by_size = sorted(data, key=lambda x: x['size'])
    labels_to_show.add(sorted_by_size[0]['name'])
    labels_to_show.add(sorted_by_size[-1]['name'])

    # Label points near the center (balanced trade-off)
    # Normalize data to calculate distance from average
    min_size, max_size = min(sizes), max(sizes)
    min_time, max_time = min(times), max(times)
    
    # Avoid division by zero
    size_range = max_size - min_size if max_size != min_size else 1.0
    time_range = max_time - min_time if max_time != min_time else 1.0
    
    # Calculate distance to average for each point
    data_with_dist = []
    for d in data:
        norm_size_diff = (d['size'] - avg_size) / size_range
        norm_time_diff = (d['time'] - avg_time) / time_range
        dist = (norm_size_diff ** 2 + norm_time_diff ** 2) ** 0.5
        data_with_dist.append((dist, d))
    
    # Sort by distance and take top 3 closest to center
    data_with_dist.sort(key=lambda x: x[0])
    for i in range(min(3, len(data_with_dist))):
        labels_to_show.add(data_with_dist[i][1]['name'])

    # Smart label placement to avoid overlap
    texts_to_draw = []
    for d in data:
        if d['name'] in labels_to_show:
            texts_to_draw.append(d)
    
    # Sort by x coordinate to process left-to-right
    texts_to_draw.sort(key=lambda x: x['size'])
    
    # Simple collision avoidance
    placed_labels = [] # List of (x_text, y_text)
    
    # Heuristic: convert time/size to normalized units for distance check
    # 1 unit approx = 10% of axis range
    x_unit = (max(sizes) - min(sizes)) * 0.1 if max(sizes) != min(sizes) else 1.0
    y_unit = (max(times) - min(times)) * 0.1 if max(times) != min(times) else 1.0
    
    # Define candidate offsets (in data units)
    offsets = [
        (0, 1), (0, -1),   # Top, Bottom
        (1, 0), (-1, 0),   # Right, Left
        (0.7, 0.7), (-0.7, 0.7), # TopRight, TopLeft
        (0.7, -0.7), (-0.7, -0.7), # BottomRight, BottomLeft
        (0, 2), (0, -2),   # Further Top, Bottom
    ]
    
    for d in texts_to_draw:
        best_pos = None
        min_cost = float('inf')
        
        # Scale offsets by units
        candidates = []
        for dx_m, dy_m in offsets:
            # Add some randomness to avoid perfect overlaps
            candidates.append((d['size'] + dx_m * x_unit * 0.5, d['time'] + dy_m * y_unit * 0.5))
            
        # Select best candidate
        for cx, cy in candidates:
            cost = 0
            # Distance from data point (prefer closer)
            dist_sq = ((cx - d['size'])/x_unit)**2 + ((cy - d['time'])/y_unit)**2
            cost += dist_sq * 0.1
            
            # Overlap with placed labels
            for px, py in placed_labels:
                # Calculate normalized distance
                p_dist_sq = ((cx - px)/x_unit)**2 + ((cy - py)/y_unit)**2
                # If too close, high cost
                if p_dist_sq < 0.25: # Radius 0.5
                    cost += 1000 / (p_dist_sq + 0.001)
            
            if cost < min_cost:
                min_cost = cost
                best_pos = (cx, cy)
        
        # If best_pos is found, use it
        if best_pos:
            placed_labels.append(best_pos)
            
            # Determine alignment based on relative position
            ha = 'center'
            if best_pos[0] > d['size'] + x_unit*0.1: ha = 'left'
            if best_pos[0] < d['size'] - x_unit*0.1: ha = 'right'
            
            va = 'center'
            if best_pos[1] > d['time'] + y_unit*0.1: va = 'bottom'
            if best_pos[1] < d['time'] - y_unit*0.1: va = 'top'
            
            plt.annotate(d['name'].replace('only_llvm_', ''), 
                        (d['size'], d['time']), 
                        xytext=best_pos, 
                        textcoords='data', # Use data coordinates
                        ha=ha, va=va,
                        fontsize=8,
                        fontweight='bold',
                        arrowprops=dict(arrowstyle='->', color='black', alpha=0.5),
                        bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="gray", alpha=0.8))

    plt.axvline(x=avg_size, color='gray', linestyle='--', alpha=0.5, label=f'Avg Size: {avg_size:.4f} MB')
    plt.axhline(y=avg_time, color='gray', linestyle='--', alpha=0.5, label=f'Avg Time: {avg_time:.4f} s')

    plt.title('Async Project - MIR Pass Impact: Binary Size vs Time (Zoomed & Color Coded)')
    plt.xlabel('Binary Size (MB)')
    plt.ylabel('Execution Time (s)')
    plt.grid(True, linestyle=':', alpha=0.6)
    plt.legend()
    
    output_path = os.path.join(OUTPUT_DIR, f'{EXP_NAME}_ablation_scatter_zoomed.png')
    plt.savefig(output_path, dpi=300)
    print(f"Zoomed scatter plot saved to: {output_path}")
    plt.close()

def plot_relative_impact(data):
    # Calculate relative change from average
    sizes = [d['size'] for d in data]
    times = [d['time'] for d in data]
    avg_size = sum(sizes) / len(sizes)
    avg_time = sum(times) / len(times)
    
    rel_data = []
    for d in data:
        rel_data.append({
            'name': d['name'],
            'size_pct': (d['size'] - avg_size) / avg_size * 100,
            'time_pct': (d['time'] - avg_time) / avg_time * 100
        })
        
    plt.figure(figsize=(14, 10))
    
    # Quadrant plot
    x = [d['size_pct'] for d in rel_data]
    y = [d['time_pct'] for d in rel_data]
    
    plt.scatter(x, y, color='purple', alpha=0.7, s=80)
    
    # Draw quadrant lines
    plt.axhline(0, color='black', linewidth=1)
    plt.axvline(0, color='black', linewidth=1)
    
    # Add quadrant labels
    xlim = plt.xlim()
    ylim = plt.ylim()
    
    # Annotate points with significant deviation (> 1% change)
    texts_to_draw = []
    for d in rel_data:
        if abs(d['time_pct']) > 1.0 or abs(d['size_pct']) > 0.1:
            texts_to_draw.append(d)
    
    # Sort by size_pct for processing
    texts_to_draw.sort(key=lambda x: x['size_pct'])
    
    # Smart label placement to avoid overlap (Similar to scatter plot)
    placed_labels = [] 
    
    # Heuristic units for distance check in percentage space
    # x_range is typically small (size changes are small), y_range is larger
    x_span = max([abs(d['size_pct']) for d in rel_data]) * 2 if rel_data else 1.0
    y_span = max([abs(d['time_pct']) for d in rel_data]) * 2 if rel_data else 1.0
    
    if x_span == 0: x_span = 0.1
    if y_span == 0: y_span = 0.1
    
    x_unit = x_span * 0.1
    y_unit = y_span * 0.1
    
    # Define candidate offsets (in data units)
    offsets = [
        (0, 1), (0, -1),   # Top, Bottom
        (1, 0), (-1, 0),   # Right, Left
        (0.7, 0.7), (-0.7, 0.7), # TopRight, TopLeft
        (0.7, -0.7), (-0.7, -0.7), # BottomRight, BottomLeft
        (0, 2), (0, -2), (2, 0), (-2, 0) # Further out
    ]
    
    for d in texts_to_draw:
        best_pos = None
        min_cost = float('inf')
        
        # Scale offsets by units
        candidates = []
        for dx_m, dy_m in offsets:
            candidates.append((d['size_pct'] + dx_m * x_unit * 0.5, d['time_pct'] + dy_m * y_unit * 0.5))
            
        # Select best candidate
        for cx, cy in candidates:
            cost = 0
            # Distance from data point
            dist_sq = ((cx - d['size_pct'])/x_unit)**2 + ((cy - d['time_pct'])/y_unit)**2
            cost += dist_sq * 0.1
            
            # Overlap with placed labels
            for px, py in placed_labels:
                p_dist_sq = ((cx - px)/x_unit)**2 + ((cy - py)/y_unit)**2
                if p_dist_sq < 0.25: 
                    cost += 1000 / (p_dist_sq + 0.001)
            
            if cost < min_cost:
                min_cost = cost
                best_pos = (cx, cy)
        
        if best_pos:
            placed_labels.append(best_pos)
            
            # Determine alignment
            ha = 'center'
            if best_pos[0] > d['size_pct'] + x_unit*0.1: ha = 'left'
            if best_pos[0] < d['size_pct'] - x_unit*0.1: ha = 'right'
            
            va = 'center'
            if best_pos[1] > d['time_pct'] + y_unit*0.1: va = 'bottom'
            if best_pos[1] < d['time_pct'] - y_unit*0.1: va = 'top'

            plt.annotate(d['name'].replace('only_llvm_', ''), 
                        (d['size_pct'], d['time_pct']),
                        xytext=best_pos, textcoords='data',
                        ha=ha, va=va,
                        fontsize=8,
                        arrowprops=dict(arrowstyle='->', color='black', alpha=0.5),
                        bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="gray", alpha=0.8))
            
    plt.title('Async Project - Relative Impact: % Change from Average (MIR Pass Config)')
    plt.xlabel('Binary Size Change (%)')
    plt.ylabel('Execution Time Change (%)')
    plt.grid(True, linestyle='--', alpha=0.3)
    
    output_path = os.path.join(OUTPUT_DIR, f'{EXP_NAME}_ablation_relative.png')
    plt.savefig(output_path, dpi=300)
    print(f"Relative plot saved to: {output_path}")
    plt.close()

def plot_bar_time(data):
    # Sort by time
    sorted_data = sorted(data, key=lambda x: x['time'])
    
    names = [d['name'] for d in sorted_data]
    times = [d['time'] for d in sorted_data]
    
    # Calculate bounds for zooming
    min_time = min(times)
    max_time = max(times)
    time_span = max_time - min_time
    
    # Set x-axis limit to focus on the variation
    # Start slightly below the minimum value
    x_min = max(0, min_time - time_span * 0.2)
    x_max = max_time + time_span * 0.1
    
    plt.figure(figsize=(12, 24)) # Taller figure
    y_pos = range(len(names))
    
    # Create horizontal bars
    bars = plt.barh(y_pos, times, align='center', alpha=0.8, color='steelblue')
    
    # Highlight bars that deviate significantly from average
    avg_time = sum(times) / len(times)
    for i, bar in enumerate(bars):
        name = names[i]
        if name == "Default":
            bar.set_color('black')
        elif name == "All Passes On":
            bar.set_color('darkblue')
        elif name == "All Passes Off":
            bar.set_color('darkorange')
        elif times[i] > avg_time * 1.01: # 1% slower
            bar.set_color('indianred')
        elif times[i] < avg_time * 0.99: # 1% faster
            bar.set_color('mediumseagreen')

    plt.yticks(y_pos, names, fontsize=9)
    plt.xlabel('Execution Time (s)')
    plt.title('Async Project - Impact of MIR Pass Config on Execution Time (Zoomed View)')
    
    # Set the zoomed x-axis
    plt.xlim(x_min, x_max)
    
    plt.grid(axis='x', linestyle='--', alpha=0.7, which='both')
    plt.minorticks_on()
    
    # Add value labels to the end of bars
    for i, v in enumerate(times):
        plt.text(v, i, f' {v:.4f}s', va='center', fontsize=8)
    
    plt.axvline(x=avg_time, color='r', linestyle='--', label=f'Average: {avg_time:.4f}s')
    plt.legend(loc='lower right')
    
    plt.tight_layout()
    output_path = os.path.join(OUTPUT_DIR, f'{EXP_NAME}_ablation_time_bar.png')
    plt.savefig(output_path, dpi=300)
    print(f"Time bar chart saved to: {output_path}")
    plt.close()

def plot_bar_size(data):
    # Sort by size
    sorted_data = sorted(data, key=lambda x: x['size'])
    
    names = [d['name'] for d in sorted_data]
    sizes = [d['size'] for d in sorted_data]
    
    # Calculate bounds for zooming
    min_size = min(sizes)
    max_size = max(sizes)
    size_span = max_size - min_size
    
    # Set x-axis limit to focus on the variation
    if size_span == 0:
        x_min = 0
        x_max = max_size * 1.1
    else:
        x_min = max(0, min_size - size_span * 0.2)
        x_max = max_size + size_span * 0.1
    
    plt.figure(figsize=(12, 24)) # Taller figure
    y_pos = range(len(names))
    
    # Create horizontal bars
    bars = plt.barh(y_pos, sizes, align='center', alpha=0.8, color='steelblue')
    
    # Highlight bars that deviate significantly from average
    avg_size = sum(sizes) / len(sizes)
    for i, bar in enumerate(bars):
        name = names[i]
        if name == "Default":
            bar.set_color('black')
        elif name == "All Passes On":
            bar.set_color('darkblue')
        elif name == "All Passes Off":
            bar.set_color('darkorange')
        elif sizes[i] > avg_size: # Larger than average
            bar.set_color('indianred')
        elif sizes[i] < avg_size: # Smaller than average
            bar.set_color('mediumseagreen')

    plt.yticks(y_pos, names, fontsize=9)
    plt.xlabel('Binary Size (MB)')
    plt.title('Async Project - Impact of MIR Pass Config on Binary Size (Zoomed View)')
    
    # Set x-axis limits
    plt.xlim(x_min, x_max)
    
    # Add value labels to end of bars
    for i, v in enumerate(sizes):
        plt.text(v, i, f' {v:.4f}MB', va='center', fontsize=8)
        
    # Add average line
    plt.axvline(avg_size, color='red', linestyle='--', label=f'Average: {avg_size:.4f}MB')
    plt.legend()
    
    # Add grid lines for x-axis
    plt.grid(axis='x', linestyle='--', alpha=0.3, which='both')
    plt.minorticks_on()
    
    plt.tight_layout()
    
    output_path = os.path.join(OUTPUT_DIR, f'{EXP_NAME}_ablation_size_bar.png')
    plt.savefig(output_path, dpi=300)
    print(f"Size bar chart saved to: {output_path}")
    plt.close()

def plot_correlation_heatmap(data):
    # Prepare data for correlation
    # Metrics: Binary Size, Runtime, Compile Time
    
    binary_sizes = [d['size'] for d in data]
    runtimes = [d['time'] for d in data]
    compile_times = [d['compile_time'] for d in data]
    
    matrix_data = np.array([binary_sizes, compile_times, runtimes])
    correlation_matrix = np.corrcoef(matrix_data)
    
    labels = ['BinarySize(MB)', 'CompileTime(s)', 'Runtime(s)']
    
    plt.figure(figsize=(8, 6))
    
    # Create heatmap using imshow
    plt.imshow(correlation_matrix, cmap='RdYlBu_r', vmin=-1, vmax=1)
    
    # Add colorbar
    plt.colorbar(label='Pearson Correlation Coefficient')
    
    # Add labels
    plt.xticks(range(len(labels)), labels)
    plt.yticks(range(len(labels)), labels)
    plt.title('Correlation Matrix Heatmap')
    
    # Add text annotations
    for i in range(len(labels)):
        for j in range(len(labels)):
            text = f"{correlation_matrix[i, j]:.2f}"
            plt.text(j, i, text, ha='center', va='center', color='black', fontsize=12, fontweight='bold')
            
    plt.tight_layout()
    output_path = os.path.join(OUTPUT_DIR, f'{EXP_NAME}_correlation_heatmap.png')
    plt.savefig(output_path, dpi=300)
    print(f"Correlation heatmap saved to: {output_path}")
    plt.close()

def main():
    if not os.path.exists(OUTPUT_DIR):
        try:
            os.makedirs(OUTPUT_DIR, exist_ok=True)
        except Exception as e:
            print(f"Warning: Could not create directory {OUTPUT_DIR}: {e}")
        
    print(f"Loading data from {CSV_PATH}...")
    
    data = load_data(CSV_PATH)
    print(f"Loaded {len(data)} records.")
    
    if not data:
        print("No data found!")
        return

    print("Generating plots...")
    plot_scatter(data)
    plot_relative_impact(data)
    plot_bar_time(data)
    plot_bar_size(data)
    plot_correlation_heatmap(data)
    print("Done.")

if __name__ == "__main__":
    main()
