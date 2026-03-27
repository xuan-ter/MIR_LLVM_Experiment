import sys

with open("generate_figures_cross_layer.py", "r") as f:
    content = f.read()

content = content.replace('fontsize=float(plt.rcParams["axes.titlesize"]) * 0.95', 'fontsize=float(plt.rcParams["axes.titlesize"]) * 0.9')

with open("generate_figures_cross_layer.py", "w") as f:
    f.write(content)
