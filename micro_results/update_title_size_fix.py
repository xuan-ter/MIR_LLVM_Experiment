import sys

with open("generate_figures_cross_layer.py", "r") as f:
    content = f.read()

# We need to make sure the fontsize for the PDF is correctly picking up the scaled pdf_rc titlesize.
old_str_1 = """            if d["bench"] == "trait_monomorphization_bench":
                ax.set_title(d["bench"], pad=title_pad, fontweight="bold", fontsize=plt.rcParams["axes.titlesize"] * 0.95)
            else:
                ax.set_title(d["bench"], pad=title_pad, fontweight="bold")"""

new_str_1 = """            if d["bench"] == "trait_monomorphization_bench":
                ax.set_title(d["bench"], pad=title_pad, fontweight="bold", fontsize=float(plt.rcParams["axes.titlesize"]) * 0.95)
            else:
                ax.set_title(d["bench"], pad=title_pad, fontweight="bold")"""

content = content.replace(old_str_1, new_str_1)

with open("generate_figures_cross_layer.py", "w") as f:
    f.write(content)
