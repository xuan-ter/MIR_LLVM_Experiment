import sys

with open("generate_figures_cross_layer.py", "r") as f:
    content = f.read()

content = content.replace('figsize=(12, 12.5)', 'figsize=(12, 13.75)')
content = content.replace('figsize=(3.2 * ncols, 6.4)', 'figsize=(3.2 * ncols, 7.04)')

with open("generate_figures_cross_layer.py", "w") as f:
    f.write(content)
