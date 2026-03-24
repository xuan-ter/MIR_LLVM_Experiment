"""
功能：构建 Pareto 搜索所需的耦合模块定义
输入：Lasso 回归分析产出的边列表（lasso_edges.csv）
输出：模块定义文件（modules.json）
描述：
    读取 Lasso 筛选出的跨层强交互边，基于连通分量（或社区发现）将 Pass 划分为独立的耦合模块。
    为每个模块分配包含的 MIR/LLVM Passes 和内部交互边（带权重、方向）。
"""
import json
from pathlib import Path
import csv
import networkx as nx

base = Path("/mnt/fjx/Compiler_Experiment/serde_test")
res = sorted((base / "results_expanded").glob("random_configs_*"))
if not res:
    raise SystemExit("no random_configs_* results")
res_dir = res[-1]
edges_csv = res_dir / "lasso_edges.csv"
out_dir = base / "pareto_search"
out_dir.mkdir(parents=True, exist_ok=True)
out_json = out_dir / "modules.json"
rows = []
with edges_csv.open(newline="", encoding="utf-8") as f:
    r = csv.DictReader(f)
    for row in r:
        m = row["MIR_Pass"].strip()
        l = row["LLVM_Pass"].strip()
        c = float(row["coef_mean"])
        fr = float(row["selected_freq"])
        if fr >= 0.6 and abs(c) > 0:
            rows.append((m, l, c, fr))
G = nx.Graph()
for m, l, c, fr in rows:
    G.add_node("M:" + m, layer="MIR", label=m)
    G.add_node("L:" + l, layer="LLVM", label=l)
    G.add_edge("M:" + m, "L:" + l, w=abs(c), sign=1 if c > 0 else -1, freq=fr)
mods = []
for i, comp in enumerate(nx.connected_components(G), 1):
    nodes = sorted(comp)
    mir = [G.nodes[n]["label"] for n in nodes if G.nodes[n]["layer"] == "MIR"]
    llvm = [G.nodes[n]["label"] for n in nodes if G.nodes[n]["layer"] == "LLVM"]
    es = []
    for u, v in G.subgraph(nodes).edges:
        d = G.edges[u, v]
        mu = G.nodes[u]["label"]
        lv = G.nodes[v]["label"]
        if u.startswith("M:"):
            mpass, lpass = mu, lv
        else:
            mpass, lpass = lv, mu
        es.append({"mir": mpass, "llvm": lpass, "w": d["w"], "sign": d["sign"], "freq": d["freq"]})
    mods.append({"id": i, "mir": mir, "llvm": llvm, "edges": es})
out_json.write_text(json.dumps({"source": str(edges_csv), "modules": mods}, indent=2), encoding="utf-8")
print(out_json)
