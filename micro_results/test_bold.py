import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

fig, ax = plt.subplots()
ax.plot([1, 2, 3], [1, 2, 3])
ax.xaxis.set_major_formatter(ticker.FuncFormatter(lambda x, pos: f"{x:g}"))
for label in ax.get_xticklabels():
    label.set_fontweight("bold")
fig.savefig("test_bold.png")
