import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

fig, ax = plt.subplots()
ax.plot([1, 2, 3], [1, 2, 3])
ax.xaxis.set_major_formatter(ticker.FuncFormatter(lambda x, pos: f"{x:g}"))
for label in ax.get_xticklabels():
    label.set_fontweight("bold")
fig.canvas.draw()
print("Without draw first:", [l.get_fontweight() for l in ax.get_xticklabels()])

fig2, ax2 = plt.subplots()
ax2.plot([1, 2, 3], [1, 2, 3])
ax2.xaxis.set_major_formatter(ticker.FuncFormatter(lambda x, pos: f"{x:g}"))
fig2.canvas.draw()
for label in ax2.get_xticklabels():
    label.set_fontweight("bold")
print("With draw first:", [l.get_fontweight() for l in ax2.get_xticklabels()])
