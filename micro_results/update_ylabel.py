import sys

with open("generate_figures_cross_layer.py", "r") as f:
    content = f.read()

old_str_1 = """    for ax in axes[: len(per_bench)]:
        ax.set_ylabel("count (log)")
        ax.set_xlabel("rel (symlog x)")"""

new_str_1 = """    for i, ax in enumerate(axes[: len(per_bench)]):
        if i == 0:
            ax.set_ylabel("count (log)")
        ax.set_xlabel("rel (symlog x)")"""

old_str_2 = """        for ax in axes[: min(len(per_bench), nrows_pdf * ncols_pdf)]:
            ax.set_ylabel("count (log)")
            ax.set_xlabel("rel (symlog x)")"""

new_str_2 = """        for i, ax in enumerate(axes[: min(len(per_bench), nrows_pdf * ncols_pdf)]):
            if i % ncols_pdf == 0:
                ax.set_ylabel("count (log)")
            ax.set_xlabel("rel (symlog x)")"""

content = content.replace(old_str_1, new_str_1)
content = content.replace(old_str_2, new_str_2)

with open("generate_figures_cross_layer.py", "w") as f:
    f.write(content)
