import os
import csv
import math
from PIL import Image, ImageDraw, ImageFont

try:
    import pandas as pd
    import numpy as np
    import matplotlib.pyplot as plt
    import seaborn as sns
    HAVE_MPL = True
except Exception:
    HAVE_MPL = False

# Configuration
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_CSV = os.path.join(BASE_DIR, "interaction_results.csv")
OUTPUT_BASE = os.path.join(BASE_DIR, "classified_results")

# Paths
NEG_DIR = os.path.join(OUTPUT_BASE, "negative_interaction")
POS_DIR = os.path.join(OUTPUT_BASE, "positive_interaction")
IND_DIR = os.path.join(OUTPUT_BASE, "independent")
os.makedirs(NEG_DIR, exist_ok=True)
os.makedirs(POS_DIR, exist_ok=True)
os.makedirs(IND_DIR, exist_ok=True)

def plot_interaction_detail(row, output_path, title_prefix):
    """
    Plots a 2x2 interaction plot for a single (MIR, LLVM) pair.
    """
    # Data preparation
    data = {
        'LLVM Status': ['ON', 'OFF', 'ON', 'OFF'],
        'MIR Status': ['ON', 'ON', 'OFF', 'OFF'],
        'Runtime (s)': [row['y00_mean'], row['y01_mean'], row['y10_mean'], row['y11_mean']]
    }
    df_plot = pd.DataFrame(data)
    
    plt.figure(figsize=(8, 6))
    sns.lineplot(data=df_plot, x='LLVM Status', y='Runtime (s)', hue='MIR Status', 
                 markers=True, dashes=False, style='MIR Status', markersize=10)
    
    plt.title(f"{title_prefix}\nMIR: {row['mir_pass']} vs LLVM: {row['llvm_pass']}\nDelta = {row['delta']:.4f}")
    plt.grid(True, linestyle='--', alpha=0.7)
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()

def plot_top_forest(df, output_path, title, color):
    """
    Plots a forest plot for the top K interactions in the dataframe.
    """
    if df.empty:
        return

    top_k = df.sort_values('delta', key=abs, ascending=False).head(20)
    
    plt.figure(figsize=(10, 8))
    # Create label
    top_k = top_k.copy()
    top_k['label'] = top_k['mir_pass'] + " + " + top_k['llvm_pass']
    
    plt.errorbar(x=top_k['delta'], y=range(len(top_k)), 
                 xerr=[top_k['delta'] - top_k['ci_low'], top_k['ci_high'] - top_k['delta']], 
                 fmt='o', capsize=5, color=color, ecolor='gray')
    plt.yticks(range(len(top_k)), top_k['label'])
    plt.axvline(x=0, color='black', linestyle='--', linewidth=1)
    plt.xlabel("Interaction Effect (Delta)")
    plt.title(title)
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()

def _hist_counts(values, bins, min_x, max_x):
    if bins <= 0:
        raise ValueError("bins must be positive")
    if max_x <= min_x:
        raise ValueError("max_x must be greater than min_x")
    w = (max_x - min_x) / bins
    counts = [0] * bins
    for v in values:
        if v is None or v != v:
            continue
        if v < min_x or v > max_x:
            continue
        idx = int((v - min_x) / w)
        if idx >= bins:
            idx = bins - 1
        if idx < 0:
            idx = 0
        counts[idx] += 1
    return counts

def _load_font(size, bold=False):
    candidates = []
    if bold:
        candidates.extend([
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        ])
    candidates.extend([
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ])
    for p in candidates:
        try:
            return ImageFont.truetype(p, size=size)
        except Exception:
            continue
    return ImageFont.load_default()

def _kde_gaussian(values, xs):
    vals = [v for v in values if v is not None and v == v]
    n = len(vals)
    if n < 2:
        return [0.0 for _ in xs]
    mean = sum(vals) / n
    var = sum((v - mean) ** 2 for v in vals) / (n - 1)
    sd = math.sqrt(var) if var > 0 else 0.0
    if sd == 0.0:
        return [0.0 for _ in xs]
    h = 1.06 * sd * (n ** (-1 / 5))
    if h <= 0:
        return [0.0 for _ in xs]
    inv_nh = 1.0 / (n * h)
    inv_sqrt_2pi = 1.0 / math.sqrt(2.0 * math.pi)
    out = []
    for x in xs:
        s = 0.0
        for v in vals:
            z = (x - v) / h
            s += math.exp(-0.5 * z * z)
        out.append(inv_nh * inv_sqrt_2pi * s)
    return out

def _nice_tick_step(max_abs):
    if max_abs <= 0:
        return 0.01
    exp10 = 10 ** math.floor(math.log10(max_abs))
    frac = max_abs / exp10
    if frac <= 1.5:
        step = 0.2 * exp10
    elif frac <= 3:
        step = 0.5 * exp10
    elif frac <= 7:
        step = 1.0 * exp10
    else:
        step = 2.0 * exp10
    return step

def plot_top_interactions_forest_pil(rows, output_png_path, top_n=50):
    def fbool(x):
        return str(x).strip().lower() == "true"

    def ffloat(x):
        x = str(x).strip()
        if x == "" or x.lower() == "nan":
            return math.nan
        return float(x)

    sig = []
    for r in rows:
        d = ffloat(r.get("delta"))
        if not (d == d):
            continue
        if not fbool(r.get("significant")):
            continue
        lo = ffloat(r.get("ci_low"))
        hi = ffloat(r.get("ci_high"))
        if not (lo == lo):
            lo = d
        if not (hi == hi):
            hi = d
        sig.append(
            {
                "mir": str(r.get("mir_pass", "")).strip(),
                "llvm": str(r.get("llvm_pass", "")).strip(),
                "delta": d,
                "ci_low": lo,
                "ci_high": hi,
            }
        )

    sig.sort(key=lambda x: abs(x["delta"]), reverse=True)
    top = sig[: max(0, int(top_n))]
    if not top:
        return

    min_x = min(r["ci_low"] for r in top)
    max_x = max(r["ci_high"] for r in top)
    if min_x == max_x:
        min_x -= 1.0
        max_x += 1.0
    pad = (max_x - min_x) * 0.06
    min_x -= pad
    max_x += pad
    if min_x > 0:
        min_x = -pad
    if max_x < 0:
        max_x = pad

    n = len(top)
    row_h = 26
    width = 3000
    height = 260 + n * row_h + 140
    img = Image.new("RGBA", (width, height), (255, 255, 255, 255))
    draw = ImageDraw.Draw(img)

    font_title = _load_font(40, bold=True)
    font_subtitle = _load_font(22, bold=False)
    font_label = _load_font(22, bold=True)
    font_tick = _load_font(18, bold=False)
    font_axis = _load_font(22, bold=False)

    draw.text((90, 38), "Top Significant Interactions (Forest Plot)", fill=(0, 0, 0), font=font_title)
    draw.text((90, 92), f"Top {n} by |Δ| among significant pairs", fill=(70, 70, 70), font=font_subtitle)

    left = 1180
    right = 120
    top_m = 170
    bottom = 140
    x0 = left
    x1 = width - right
    y0 = top_m
    y1 = height - bottom

    draw.rectangle([x0, y0, x1, y1], fill=(250, 250, 250, 255), outline=None)

    def x_to_px(x):
        return x0 + int((x - min_x) / (max_x - min_x) * (x1 - x0))

    def draw_dashed_vline(x_px, y_start, y_end, dash=10, gap_px=8, color=(220, 0, 0, 255)):
        y = y_start
        while y < y_end:
            y_end2 = min(y + dash, y_end)
            draw.line([(x_px, y), (x_px, y_end2)], fill=color, width=2)
            y = y_end2 + gap_px

    max_abs = max(abs(min_x), abs(max_x))
    step = _nice_tick_step(max_abs)
    tmax = math.ceil(max_abs / step) * step
    x_ticks = [-tmax, -tmax / 2.0, 0.0, tmax / 2.0, tmax]
    for xt in x_ticks:
        x = x_to_px(xt)
        draw.line([(x, y0), (x, y1)], fill=(235, 235, 235, 255), width=2)

    zero_x = x_to_px(0.0)
    draw_dashed_vline(zero_x, y0, y1, color=(220, 0, 0, 255))

    color = (31, 119, 180)
    axis_color = (0, 0, 0, 255)
    y_start = y0 + 24
    for i, r in enumerate(top):
        y = y_start + i * row_h + row_h // 2
        label = f"{r['mir']} + {r['llvm']}"
        try:
            tb = draw.textbbox((0, 0), label, font=font_tick)
            tw = tb[2] - tb[0]
        except Exception:
            tw = 10 * len(label)
        draw.text((left - 20 - tw, y - 10), label, fill=(0, 0, 0), font=font_tick)

        x_lo = x_to_px(r["ci_low"])
        x_hi = x_to_px(r["ci_high"])
        x_pt = x_to_px(r["delta"])
        draw.line([(x_lo, y), (x_hi, y)], fill=(*color, 255), width=3)
        cap = 7
        draw.line([(x_lo, y - cap), (x_lo, y + cap)], fill=(*color, 255), width=3)
        draw.line([(x_hi, y - cap), (x_hi, y + cap)], fill=(*color, 255), width=3)
        rad = 5
        draw.ellipse([x_pt - rad, y - rad, x_pt + rad, y + rad], fill=(*color, 255), outline=(0, 0, 0, 80))

    draw.line([(x0, y1), (x1, y1)], fill=axis_color, width=2)
    for xt in x_ticks:
        x = x_to_px(xt)
        draw.line([(x, y1), (x, y1 + 10)], fill=axis_color, width=2)
        draw.text((x - 26, y1 + 14), f"{xt:.2f}", fill=(0, 0, 0), font=font_tick)

    draw.text((x0 - 190, y0 - 34), "Interaction", fill=(0, 0, 0), font=font_label)
    draw.text((x0 + (x1 - x0) // 2 - 210, y1 + 54), "Interaction effect  Δ  (log scale)", fill=(0, 0, 0), font=font_axis)

    img.convert("RGB").save(output_png_path)
    pdf_path = os.path.splitext(output_png_path)[0] + ".pdf"
    img.convert("RGB").save(pdf_path, "PDF", resolution=300.0)

def plot_delta_distributions_three_types(neg_deltas, pos_deltas, ind_deltas, output_png_path, bins=50):
    deltas_all = [d for d in (neg_deltas + pos_deltas + ind_deltas) if d is not None and d == d]
    if not deltas_all:
        return

    min_d = min(deltas_all)
    max_d = max(deltas_all)
    max_abs = max(abs(min_d), abs(max_d))
    pad = max_abs * 0.05
    min_x = -(max_abs + pad)
    max_x = +(max_abs + pad)

    width, height = 2400, 1500
    img = Image.new("RGBA", (width, height), (255, 255, 255, 255))
    draw = ImageDraw.Draw(img)
    font_title = _load_font(40, bold=True)
    font_subtitle = _load_font(22, bold=False)
    font_label = _load_font(24, bold=True)
    font_tick = _load_font(20, bold=False)
    font_axis = _load_font(22, bold=False)
    font_bar = _load_font(16, bold=False)

    title = "Distribution of Interaction Effects (Δ) by Type"
    subtitle = "Histogram count with KDE overlay; Negative: significant & Δ<0   Positive: significant & Δ>0   Linear: not significant"
    draw.text((90, 38), title, fill=(0, 0, 0), font=font_title)
    draw.text((90, 92), subtitle, fill=(70, 70, 70), font=font_subtitle)

    panels = [
        ("Negative interaction", neg_deltas, (31, 119, 180)),
        ("Positive interaction", pos_deltas, (214, 39, 40)),
        ("Linear", ind_deltas, (70, 70, 70)),
    ]
    n_neg = sum(1 for v in neg_deltas if v is not None and v == v)
    n_pos = sum(1 for v in pos_deltas if v is not None and v == v)
    n_ind = sum(1 for v in ind_deltas if v is not None and v == v)

    legend_font = _load_font(22, bold=False)
    legend_items = [
        ("Negative (n={})".format(n_neg), panels[0][2]),
        ("Positive (n={})".format(n_pos), panels[1][2]),
        ("Linear (n={})".format(n_ind), panels[2][2]),
    ]
    lx, ly = width - 900, 40
    sw, sh = 30, 18
    for i, (txt, col) in enumerate(legend_items):
        x = lx + i * 290
        draw.rectangle([x, ly + 12, x + sw, ly + 12 + sh], fill=(*col, 255), outline=(0, 0, 0, 255), width=1)
        draw.text((x + sw + 10, ly + 6), txt, fill=(0, 0, 0), font=legend_font)

    top = 170
    left = 170
    right = 80
    bottom = 120
    gap = 54
    panel_h = (height - top - bottom - gap * (len(panels) - 1)) // len(panels)
    panel_w = width - left - right

    def x_to_px(x):
        return left + int((x - min_x) / (max_x - min_x) * panel_w)

    def y_to_px(y, y_max, base_y, usable_h):
        if y_max <= 0:
            return base_y
        return base_y - int(y / y_max * usable_h)

    def draw_dashed_vline(x_px, y0, y1, dash=10, gap_px=8, color=(0, 0, 0)):
        y = y0
        while y < y1:
            y_end = min(y + dash, y1)
            draw.line([(x_px, y), (x_px, y_end)], fill=color, width=2)
            y = y_end + gap_px

    grids = 5
    xs_kde = [min_x + (max_x - min_x) * i / 400 for i in range(401)]
    bin_w = (max_x - min_x) / bins

    hist_counts = []
    panel_ns = []
    kde_lines_scaled = []
    y_max_per_panel = []
    for _, values, _ in panels:
        counts = _hist_counts(values, bins=bins, min_x=min_x, max_x=max_x)
        n = sum(1 for v in values if v is not None and v == v)
        kde_density = _kde_gaussian(values, xs_kde)
        kde_scaled = [y * n * bin_w for y in kde_density] if n > 0 else [0.0 for _ in kde_density]
        hist_counts.append(counts)
        panel_ns.append(n)
        kde_lines_scaled.append(kde_scaled)
        y_max_panel = 0.0
        if counts:
            y_max_panel = max(y_max_panel, max(counts))
        if kde_scaled:
            y_max_panel = max(y_max_panel, max(kde_scaled))
        y_max_panel = max(1.0, y_max_panel * 1.10)
        y_max_per_panel.append(y_max_panel)
    step = _nice_tick_step(max_abs + pad)
    tmax = math.ceil((max_abs + pad) / step) * step
    x_ticks = [-tmax, -tmax / 2.0, 0.0, tmax / 2.0, tmax]

    for i, (label, values, color) in enumerate(panels):
        y0 = top + i * (panel_h + gap)
        y1 = y0 + panel_h
        base_y = y1 - 56
        usable_h = panel_h - 98

        draw.rectangle([left, y0, left + panel_w, y1], fill=(250, 250, 250, 255), outline=None)

        for g in range(1, grids + 1):
            gy = y0 + 30 + int(usable_h * g / (grids + 1))
            draw.line([(left, gy), (left + panel_w, gy)], fill=(230, 230, 230, 255), width=2)

        for xt in x_ticks:
            x = x_to_px(xt)
            draw.line([(x, y0 + 24), (x, base_y)], fill=(235, 235, 235, 255), width=2)

        y_max = y_max_per_panel[i]
        y_top = int(math.ceil(y_max))
        y_mid = int(round(y_top * 0.5))
        y_ticks = [0, y_mid, y_top]
        for t in y_ticks:
            yy = y_to_px(t, y_max, base_y, usable_h)
            draw.line([(left - 10, yy), (left, yy)], fill=(0, 0, 0, 255), width=2)
            draw.text((left - 130, yy - 12), f"{int(t)}", fill=(0, 0, 0), font=font_tick)

        counts = hist_counts[i]
        n = panel_ns[i]
        bar_labels = []
        for b, c in enumerate(counts):
            if c <= 0:
                continue
            x0 = left + int(b * (panel_w / bins))
            x1 = left + int((b + 1) * (panel_w / bins)) - 2
            y_bar = y_to_px(c, y_max, base_y, usable_h)
            alpha = 200 if i != 2 else 240
            outline = (max(0, int(color[0] * 0.60)), max(0, int(color[1] * 0.60)), max(0, int(color[2] * 0.60)), 255)
            draw.rectangle([x0, y_bar, x1, base_y], fill=(*color, alpha), outline=outline, width=1)
            txt = str(int(c))
            try:
                tb = draw.textbbox((0, 0), txt, font=font_bar)
                tw = tb[2] - tb[0]
                th = tb[3] - tb[1]
            except Exception:
                tw, th = (10 * len(txt), 16)
            x_txt = (x0 + x1) // 2 - tw // 2
            y_txt = y_bar - th - 4 - (b % 2) * (th + 2)
            y_min = y0 + 26
            if y_txt < y_min:
                y_txt = y_min
            x_min = left + 2
            x_max = left + panel_w - tw - 2
            if x_txt < x_min:
                x_txt = x_min
            if x_txt > x_max:
                x_txt = x_max
            y_max_txt = base_y - th - 2
            if y_txt > y_max_txt:
                y_txt = y_max_txt
            bar_labels.append((x_txt, y_txt, tw, th, txt))

        kde = kde_lines_scaled[i]
        pts = []
        for x, y in zip(xs_kde, kde):
            pts.append((x_to_px(x), y_to_px(y, y_max, base_y, usable_h)))
        if len(pts) >= 2:
            draw.line(pts, fill=(0, 0, 0, 110), width=9)
            draw.line(pts, fill=(*color, 255), width=6)

        zero_x = x_to_px(0.0)
        draw_dashed_vline(zero_x, y0 + 24, base_y, color=(0, 0, 0, 255))

        for x_txt, y_txt, tw, th, txt in bar_labels:
            pad_x, pad_y = 4, 2
            draw.rectangle([x_txt - pad_x, y_txt - pad_y, x_txt + tw + pad_x, y_txt + th + pad_y], fill=(255, 255, 255, 235))
            draw.text((x_txt, y_txt), txt, fill=(0, 0, 0, 235), font=font_bar)

        panel_tag = ["(a)", "(b)", "(c)"][i]
        draw.text((left + 14, y0 + 10), f"{panel_tag} {label}  (n={n})", fill=(0, 0, 0), font=font_label)
        draw.text((left - 140, y0 + 10), "Count", fill=(0, 0, 0), font=font_tick)

        axis_color = (0, 0, 0, 255)
        draw.line([(left, base_y), (left + panel_w, base_y)], fill=axis_color, width=2)
        for xt in x_ticks:
            x = x_to_px(xt)
            draw.line([(x, base_y), (x, base_y + 10)], fill=axis_color, width=2)
            draw.text((x - 24, base_y + 14), f"{xt:.2f}", fill=(0, 0, 0), font=font_tick)
        draw.text((left + panel_w // 2 - 190, base_y + 44), "Interaction effect  Δ  (log scale)", fill=(0, 0, 0), font=font_axis)

    img.convert("RGB").save(output_png_path)
    pdf_path = os.path.splitext(output_png_path)[0] + ".pdf"
    img.convert("RGB").save(pdf_path, "PDF", resolution=300.0)

def plot_kde_overlay_three_types(neg_deltas, pos_deltas, ind_deltas, output_png_path):
    deltas_all = [d for d in (neg_deltas + pos_deltas + ind_deltas) if d is not None and d == d]
    if not deltas_all:
        return

    min_d = min(deltas_all)
    max_d = max(deltas_all)
    max_abs = max(abs(min_d), abs(max_d))
    pad = max_abs * 0.05
    min_x = -(max_abs + pad)
    max_x = +(max_abs + pad)

    width, height = 2400, 1100
    img = Image.new("RGBA", (width, height), (255, 255, 255, 255))
    draw = ImageDraw.Draw(img)

    font_title = _load_font(40, bold=True)
    font_subtitle = _load_font(22, bold=False)
    font_tick = _load_font(20, bold=False)
    font_axis = _load_font(22, bold=False)
    font_legend = _load_font(22, bold=False)

    title = "Interaction Effect Density (KDE) by Type"
    subtitle = "Kernel density estimate of Δ (log scale); dashed line indicates Δ=0"
    draw.text((90, 38), title, fill=(0, 0, 0), font=font_title)
    draw.text((90, 92), subtitle, fill=(70, 70, 70), font=font_subtitle)

    colors = {
        "Negative": (31, 119, 180),
        "Positive": (214, 39, 40),
        "Linear": (70, 70, 70),
    }

    n_neg = sum(1 for v in neg_deltas if v is not None and v == v)
    n_pos = sum(1 for v in pos_deltas if v is not None and v == v)
    n_lin = sum(1 for v in ind_deltas if v is not None and v == v)

    left = 170
    right = 80
    top = 170
    bottom = 140
    plot_w = width - left - right
    plot_h = height - top - bottom
    x0 = left
    y0 = top
    x1 = left + plot_w
    y1 = top + plot_h
    base_y = y1

    def x_to_px(x):
        return x0 + int((x - min_x) / (max_x - min_x) * plot_w)

    def y_to_px(y, y_max):
        if y_max <= 0:
            return base_y
        return base_y - int(y / y_max * plot_h)

    def draw_dashed_vline(x_px, y_start, y_end, dash=10, gap_px=8, color=(0, 0, 0, 255)):
        y = y_start
        while y < y_end:
            y_end2 = min(y + dash, y_end)
            draw.line([(x_px, y), (x_px, y_end2)], fill=color, width=2)
            y = y_end2 + gap_px

    step = _nice_tick_step(max_abs + pad)
    tmax = math.ceil((max_abs + pad) / step) * step
    x_ticks = [-tmax, -tmax / 2.0, 0.0, tmax / 2.0, tmax]

    for xt in x_ticks:
        x = x_to_px(xt)
        draw.line([(x, y0), (x, y1)], fill=(235, 235, 235, 255), width=2)

    grids = 4
    for g in range(1, grids + 1):
        gy = y0 + int(plot_h * g / (grids + 1))
        draw.line([(x0, gy), (x1, gy)], fill=(230, 230, 230, 255), width=2)

    xs = [min_x + (max_x - min_x) * i / 600 for i in range(601)]
    kde_neg = _kde_gaussian(neg_deltas, xs)
    kde_pos = _kde_gaussian(pos_deltas, xs)
    kde_lin = _kde_gaussian(ind_deltas, xs)
    y_max = max(max(kde_neg or [0.0]), max(kde_pos or [0.0]), max(kde_lin or [0.0])) * 1.10
    y_ticks = [0.0, y_max * 0.5, y_max]

    for t in y_ticks:
        yy = y_to_px(t, y_max)
        draw.line([(x0 - 10, yy), (x0, yy)], fill=(0, 0, 0, 255), width=2)
        draw.text((x0 - 130, yy - 12), f"{t:.2f}", fill=(0, 0, 0), font=font_tick)

    def draw_curve(kde, color):
        pts = [(x_to_px(x), y_to_px(y, y_max)) for x, y in zip(xs, kde)]
        if len(pts) >= 2:
            draw.line(pts, fill=(0, 0, 0, 90), width=10)
            draw.line(pts, fill=(*color, 255), width=7)

    draw_curve(kde_neg, colors["Negative"])
    draw_curve(kde_pos, colors["Positive"])
    draw_curve(kde_lin, colors["Linear"])

    zero_x = x_to_px(0.0)
    draw_dashed_vline(zero_x, y0, y1, color=(0, 0, 0, 255))

    axis_color = (0, 0, 0, 255)
    draw.line([(x0, y1), (x1, y1)], fill=axis_color, width=2)
    for xt in x_ticks:
        x = x_to_px(xt)
        draw.line([(x, y1), (x, y1 + 10)], fill=axis_color, width=2)
        draw.text((x - 24, y1 + 14), f"{xt:.2f}", fill=(0, 0, 0), font=font_tick)
    draw.text((x0 + plot_w // 2 - 190, y1 + 54), "Interaction effect  Δ  (log scale)", fill=(0, 0, 0), font=font_axis)
    draw.text((x0 - 140, y0 + 10), "Density", fill=(0, 0, 0), font=font_tick)

    legend = [
        ("Negative (n={})".format(n_neg), colors["Negative"]),
        ("Positive (n={})".format(n_pos), colors["Positive"]),
        ("Linear (n={})".format(n_lin), colors["Linear"]),
    ]
    lx, ly = width - 900, 40
    sw, sh = 30, 18
    for i, (txt, col) in enumerate(legend):
        x = lx + i * 290
        draw.rectangle([x, ly + 12, x + sw, ly + 12 + sh], fill=(*col, 255), outline=(0, 0, 0, 255), width=1)
        draw.text((x + sw + 10, ly + 6), txt, fill=(0, 0, 0), font=font_legend)

    img.convert("RGB").save(output_png_path)
    pdf_path = os.path.splitext(output_png_path)[0] + ".pdf"
    img.convert("RGB").save(pdf_path, "PDF", resolution=300.0)

def plot_kde_panels_three_types(neg_deltas, pos_deltas, ind_deltas, output_png_path):
    deltas_all = [d for d in (neg_deltas + pos_deltas + ind_deltas) if d is not None and d == d]
    if not deltas_all:
        return

    min_d = min(deltas_all)
    max_d = max(deltas_all)
    max_abs = max(abs(min_d), abs(max_d))
    pad = max_abs * 0.05
    min_x = -(max_abs + pad)
    max_x = +(max_abs + pad)

    width, height = 2400, 1500
    img = Image.new("RGBA", (width, height), (255, 255, 255, 255))
    draw = ImageDraw.Draw(img)

    font_title = _load_font(40, bold=True)
    font_subtitle = _load_font(22, bold=False)
    font_label = _load_font(24, bold=True)
    font_tick = _load_font(20, bold=False)
    font_axis = _load_font(22, bold=False)

    title = "Interaction Effect Density (KDE) by Type"
    subtitle = "Three-panel KDE of Δ (log scale); dashed line indicates Δ=0"
    draw.text((90, 38), title, fill=(0, 0, 0), font=font_title)
    draw.text((90, 92), subtitle, fill=(70, 70, 70), font=font_subtitle)

    panels = [
        ("Negative interaction", neg_deltas, (31, 119, 180)),
        ("Positive interaction", pos_deltas, (214, 39, 40)),
        ("Linear", ind_deltas, (70, 70, 70)),
    ]

    top = 170
    left = 170
    right = 80
    bottom = 120
    gap = 54
    panel_h = (height - top - bottom - gap * (len(panels) - 1)) // len(panels)
    panel_w = width - left - right

    def x_to_px(x):
        return left + int((x - min_x) / (max_x - min_x) * panel_w)

    def y_to_px(y, y_max, base_y, usable_h):
        if y_max <= 0:
            return base_y
        return base_y - int(y / y_max * usable_h)

    def draw_dashed_vline(x_px, y0, y1, dash=10, gap_px=8, color=(0, 0, 0, 255)):
        y = y0
        while y < y1:
            y_end = min(y + dash, y1)
            draw.line([(x_px, y), (x_px, y_end)], fill=color, width=2)
            y = y_end + gap_px

    grids = 5
    xs_kde = [min_x + (max_x - min_x) * i / 500 for i in range(501)]
    kde_lines = []
    y_max = 0.0
    for _, values, _ in panels:
        kde = _kde_gaussian(values, xs_kde)
        kde_lines.append(kde)
        if kde:
            y_max = max(y_max, max(kde))
    y_max *= 1.10
    y_ticks = [0.0, y_max * 0.5, y_max]
    step = _nice_tick_step(max_abs + pad)
    tmax = math.ceil((max_abs + pad) / step) * step
    x_ticks = [-tmax, -tmax / 2.0, 0.0, tmax / 2.0, tmax]

    for i, (label, values, color) in enumerate(panels):
        y0 = top + i * (panel_h + gap)
        y1 = y0 + panel_h
        base_y = y1 - 56
        usable_h = panel_h - 98

        draw.rectangle([left, y0, left + panel_w, y1], fill=(250, 250, 250, 255), outline=None)

        for g in range(1, grids + 1):
            gy = y0 + 30 + int(usable_h * g / (grids + 1))
            draw.line([(left, gy), (left + panel_w, gy)], fill=(230, 230, 230, 255), width=2)

        for xt in x_ticks:
            x = x_to_px(xt)
            draw.line([(x, y0 + 24), (x, base_y)], fill=(235, 235, 235, 255), width=2)

        for t in y_ticks:
            yy = y_to_px(t, y_max, base_y, usable_h)
            draw.line([(left - 10, yy), (left, yy)], fill=(0, 0, 0, 255), width=2)
            draw.text((left - 130, yy - 12), f"{t:.2f}", fill=(0, 0, 0), font=font_tick)

        kde = kde_lines[i]
        pts = [(x_to_px(x), y_to_px(y, y_max, base_y, usable_h)) for x, y in zip(xs_kde, kde)]
        if len(pts) >= 2:
            draw.line(pts, fill=(0, 0, 0, 110), width=9)
            draw.line(pts, fill=(*color, 255), width=6)

        zero_x = x_to_px(0.0)
        draw_dashed_vline(zero_x, y0 + 24, base_y, color=(0, 0, 0, 255))

        n = sum(1 for v in values if v is not None and v == v)
        panel_tag = ["(a)", "(b)", "(c)"][i]
        draw.text((left + 14, y0 + 10), f"{panel_tag} {label}  (n={n})", fill=(0, 0, 0), font=font_label)
        draw.text((left - 140, y0 + 10), "Density", fill=(0, 0, 0), font=font_tick)

        axis_color = (0, 0, 0, 255)
        draw.line([(left, base_y), (left + panel_w, base_y)], fill=axis_color, width=2)
        for xt in x_ticks:
            x = x_to_px(xt)
            draw.line([(x, base_y), (x, base_y + 10)], fill=axis_color, width=2)
            draw.text((x - 24, base_y + 14), f"{xt:.2f}", fill=(0, 0, 0), font=font_tick)
        draw.text((left + panel_w // 2 - 190, base_y + 44), "Interaction effect  Δ  (log scale)", fill=(0, 0, 0), font=font_axis)

    img.convert("RGB").save(output_png_path)
    pdf_path = os.path.splitext(output_png_path)[0] + ".pdf"
    img.convert("RGB").save(pdf_path, "PDF", resolution=300.0)

def main():
    print(f"Reading data from {INPUT_CSV}...")
    if HAVE_MPL:
        try:
            df = pd.read_csv(INPUT_CSV)
        except FileNotFoundError:
            print("Error: Input CSV file not found.")
            return
    else:
        if not os.path.exists(INPUT_CSV):
            print("Error: Input CSV file not found.")
            return
        rows = []
        with open(INPUT_CSV, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                rows.append(r)

    # Classification Logic
    # 1. Negative Interaction: Significant = True AND Delta < 0
    if HAVE_MPL:
        neg_df = df[(df['significant'] == True) & (df['delta'] < 0)].copy()
    else:
        neg_df = []
    
    # 2. Positive Interaction: Significant = True AND Delta > 0
    if HAVE_MPL:
        pos_df = df[(df['significant'] == True) & (df['delta'] > 0)].copy()
    else:
        pos_df = []
    
    # 3. Independent: Significant = False
    if HAVE_MPL:
        ind_df = df[df['significant'] == False].copy()
    else:
        ind_df = []
    
    if HAVE_MPL:
        print(f"Found {len(neg_df)} negative interactions.")
        print(f"Found {len(pos_df)} positive interactions.")
        print(f"Found {len(ind_df)} independent pairs.")
    else:
        def fbool(x):
            return str(x).strip().lower() == "true"
        def ffloat(x):
            x = str(x).strip()
            if x == "" or x.lower() == "nan":
                return math.nan
            return float(x)
        neg_deltas = []
        pos_deltas = []
        ind_deltas = []
        for r in rows:
            d = ffloat(r.get("delta"))
            sig = fbool(r.get("significant"))
            if sig and d < 0:
                neg_deltas.append(d)
            elif sig and d > 0:
                pos_deltas.append(d)
            elif not sig:
                ind_deltas.append(d)
        print(f"Found {len(neg_deltas)} negative interactions.")
        print(f"Found {len(pos_deltas)} positive interactions.")
        print(f"Found {len(ind_deltas)} independent pairs.")
        out_path = os.path.join(OUTPUT_BASE, "interaction_delta_dist_by_type.png")
        plot_delta_distributions_three_types(
            neg_deltas=neg_deltas,
            pos_deltas=pos_deltas,
            ind_deltas=ind_deltas,
            output_png_path=out_path,
            bins=50,
        )
        print(f"Saved distribution plot to {out_path}")
        print(f"Saved distribution plot to {os.path.splitext(out_path)[0] + '.pdf'}")
        kde_overlay_out = os.path.join(OUTPUT_BASE, "interaction_delta_kde_overlay.png")
        plot_kde_overlay_three_types(
            neg_deltas=neg_deltas,
            pos_deltas=pos_deltas,
            ind_deltas=ind_deltas,
            output_png_path=kde_overlay_out,
        )
        print(f"Saved KDE overlay plot to {kde_overlay_out}")
        print(f"Saved KDE overlay plot to {os.path.splitext(kde_overlay_out)[0] + '.pdf'}")
        kde_panels_out = os.path.join(OUTPUT_BASE, "interaction_delta_kde_panels_by_type.png")
        plot_kde_panels_three_types(
            neg_deltas=neg_deltas,
            pos_deltas=pos_deltas,
            ind_deltas=ind_deltas,
            output_png_path=kde_panels_out,
        )
        print(f"Saved 3-panel KDE plot to {kde_panels_out}")
        print(f"Saved 3-panel KDE plot to {os.path.splitext(kde_panels_out)[0] + '.pdf'}")
        forest_out = os.path.join(BASE_DIR, "top_interactions_forest.png")
        plot_top_interactions_forest_pil(rows, forest_out, top_n=50)
        print(f"Saved top-50 forest plot to {forest_out}")
        print(f"Saved top-50 forest plot to {os.path.splitext(forest_out)[0] + '.pdf'}")
        return

    # Save CSVs
    neg_csv = os.path.join(NEG_DIR, "negative_interactions.csv")
    neg_df.sort_values('delta', ascending=True).to_csv(neg_csv, index=False)
    
    pos_csv = os.path.join(POS_DIR, "positive_interactions.csv")
    pos_df.sort_values('delta', ascending=False).to_csv(pos_csv, index=False)
    
    ind_csv = os.path.join(IND_DIR, "independent_pairs.csv")
    ind_df.sort_values('p_value', ascending=True).to_csv(ind_csv, index=False)
    
    print("CSVs saved.")

    # Generate Plots
    
    # 1. Negative Interactions
    if not neg_df.empty:
        # Forest Plot
        plot_top_forest(neg_df, os.path.join(NEG_DIR, "negative_forest_plot.png"), 
                        "Top Negative Interactions (Redundancy/Backup)", "blue")
        
        # Detail Plots for Top 5
        top_neg = neg_df.sort_values('delta', ascending=True).head(5)
        for idx, row in top_neg.iterrows():
            filename = f"interaction_{row['mir_pass']}_{row['llvm_pass']}.png".replace(" ", "_")
            plot_interaction_detail(row, os.path.join(NEG_DIR, filename), "Negative Interaction")

    # 2. Positive Interactions
    if not pos_df.empty:
        # Forest Plot
        plot_top_forest(pos_df, os.path.join(POS_DIR, "positive_forest_plot.png"), 
                        "Top Positive Interactions (Interference/Conflict)", "red")
        
        # Detail Plots for Top 5
        top_pos = pos_df.sort_values('delta', ascending=False).head(5)
        for idx, row in top_pos.iterrows():
            filename = f"interaction_{row['mir_pass']}_{row['llvm_pass']}.png".replace(" ", "_")
            plot_interaction_detail(row, os.path.join(POS_DIR, filename), "Positive Interaction")

    # 3. Independent (Just a histogram of Deltas maybe?)
    if not ind_df.empty:
        plt.figure(figsize=(10, 6))
        sns.histplot(ind_df['delta'], bins=50, kde=True, color='gray')
        plt.title("Distribution of Interaction Effects (Delta) for Independent Pairs")
        plt.xlabel("Delta")
        plt.axvline(x=0, color='black', linestyle='--')
        plt.tight_layout()
        plt.savefig(os.path.join(IND_DIR, "independent_delta_dist.png"))
        plt.close()

    dist_out = os.path.join(OUTPUT_BASE, "interaction_delta_dist_by_type.png")
    neg_deltas = neg_df["delta"].dropna().astype(float).tolist()
    pos_deltas = pos_df["delta"].dropna().astype(float).tolist()
    ind_deltas = ind_df["delta"].dropna().astype(float).tolist()
    plot_delta_distributions_three_types(
        neg_deltas=neg_deltas,
        pos_deltas=pos_deltas,
        ind_deltas=ind_deltas,
        output_png_path=dist_out,
        bins=50,
    )

    kde_overlay_out = os.path.join(OUTPUT_BASE, "interaction_delta_kde_overlay.png")
    plot_kde_overlay_three_types(
        neg_deltas=neg_deltas,
        pos_deltas=pos_deltas,
        ind_deltas=ind_deltas,
        output_png_path=kde_overlay_out,
    )

    kde_panels_out = os.path.join(OUTPUT_BASE, "interaction_delta_kde_panels_by_type.png")
    plot_kde_panels_three_types(
        neg_deltas=neg_deltas,
        pos_deltas=pos_deltas,
        ind_deltas=ind_deltas,
        output_png_path=kde_panels_out,
    )

    print("Plots generated.")

if __name__ == "__main__":
    main()
