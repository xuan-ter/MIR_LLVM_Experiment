import sys

with open("generate_figures_cross_layer.py", "r") as f:
    content = f.read()

old_str = """        for label in ax.get_xticklabels():
            label.set_fontweight("bold")
        ax.grid(True, which="both", axis="y", linestyle="-", alpha=0.12)"""

new_str = """        for label in ax.get_xticklabels():
            label.set_fontweight("bold")
        for label in ax.get_yticklabels():
            label.set_fontweight("bold")
        ax.grid(True, which="both", axis="y", linestyle="-", alpha=0.12)"""

content = content.replace(old_str, new_str)

old_str_1 = """            for label in ax.get_xticklabels():
                label.set_fontweight("bold")
            ax.grid(True, which="both", axis="y", linestyle="-", alpha=0.12)"""

new_str_1 = """            for label in ax.get_xticklabels():
                label.set_fontweight("bold")
            for label in ax.get_yticklabels():
                label.set_fontweight("bold")
            ax.grid(True, which="both", axis="y", linestyle="-", alpha=0.12)"""

content = content.replace(old_str_1, new_str_1)

with open("generate_figures_cross_layer.py", "w") as f:
    f.write(content)
