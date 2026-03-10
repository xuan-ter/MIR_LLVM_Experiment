"""
功能：模块内多目标 Pareto 搜索示范（带真实编译计时）
输入：耦合图模块定义（modules.json）
输出：module_results.csv（所有候选评估结果）、module_pareto.csv（非支配前沿）
描述：
    在指定的模块（MIR/LLVM Pass 子集）内执行多目标优化搜索。
    生成包含单点/双点翻转（交互感知）的候选配置，实际测量运行时、编译时和二进制大小。
    输出该模块的局部 Pareto 前沿，作为全局组合的候选池。
"""
import os
import csv
import json
import re
import subprocess
from pathlib import Path
from datetime import datetime
import random
import time
import shutil

BASE = Path("/mnt/fjx/Compiler_Experiment/serde_test")
MODULES_JSON = BASE / "pareto_search" / "modules.json"
TARGET_BIN = BASE / "target" / "release" / "serde_test"
ITER = "3000"

def parse_time(stdout):
    ser = 0.0
    de = 0.0
    m1 = re.search(r"Serialize Time:\s+([0-9\.]+)\s*s", stdout)
    if m1:
        ser = float(m1.group(1))
    m2 = re.search(r"Deserialize Time:\s+([0-9\.]+)\s*s", stdout)
    if m2:
        de = float(m2.group(1))
    return ser + de, ser, de

def eval_config(dis_mir, dis_llvm, clean_build=False):
    llvm_args = [f"-C llvm-args=-disable-{p}" for p in sorted(dis_llvm)]
    mir_args = [f"-Z mir-enable-passes=-{p}" for p in sorted(dis_mir)]
    rustflags = " ".join(["-C opt-level=3"] + llvm_args + mir_args)
    env = os.environ.copy()
    env["RUSTFLAGS"] = rustflags
    env.setdefault("CARGO_INCREMENTAL", "0")
    p = os.path.expanduser("~/.cargo/bin")
    if p not in env["PATH"]:
        env["PATH"] = f"{p}:{env['PATH']}"
    if clean_build:
        target_dir = BASE / "target"
        if target_dir.exists():
            shutil.rmtree(target_dir, ignore_errors=True)
    t0 = time.perf_counter()
    b1 = subprocess.run(
        "cargo build --release --quiet",
        cwd=str(BASE),
        env=env,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    compile_s = time.perf_counter() - t0
    if b1.returncode != 0:
        return 0, 0.0, compile_s, "BuildFailed"
    if not TARGET_BIN.exists():
        return 0, 0.0, compile_s, "BuildFailed"
    size = TARGET_BIN.stat().st_size
    r = subprocess.run(f"{TARGET_BIN} {ITER}", cwd=str(BASE), env=env, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if r.returncode != 0:
        return size, 0.0, compile_s, "RunFailed"
    tot, ser, de = parse_time(r.stdout)
    return size, tot, compile_s, "Success"

def penalty(dis_mir, dis_llvm, edges):
    s = 0.0
    for e in edges:
        i = e["mir"] in dis_mir
        j = e["llvm"] in dis_llvm
        if e["sign"] > 0 and i and j:
            s += e["freq"] * e["w"]
    return s

def nondominated(rows):
    res = []
    for i, a in enumerate(rows):
        dominated = False
        for j, b in enumerate(rows):
            if i == j:
                continue
            if (b["TotalRuntime(s)"] <= a["TotalRuntime(s)"] and
                b["CompileTime(s)"] <= a["CompileTime(s)"] and
                b["BinarySize(Bytes)"] <= a["BinarySize(Bytes)"] and
                (b["TotalRuntime(s)"] < a["TotalRuntime(s)"] or
                 b["CompileTime(s)"] < a["CompileTime(s)"] or
                 b["BinarySize(Bytes)"] < a["BinarySize(Bytes)"])):
                dominated = True
                break
        if not dominated:
            res.append(a)
    return res

def gen_candidates(mod, budget):
    edges = mod["edges"]
    seen = set()
    uniq = []
    def add(dm, dl):
        key = (";".join(sorted(dm)), ";".join(sorted(dl)))
        if key in seen:
            return False
        seen.add(key)
        uniq.append((dm, dl))
        return True

    add(set(), set())

    neg_edges = [e for e in edges if e.get("sign", 0) < 0]
    pos_edges = [e for e in edges if e.get("sign", 0) > 0]

    for e in neg_edges:
        m = e["mir"]
        l = e["llvm"]
        add({m}, set())
        add(set(), {l})
        add({m}, {l})

    for e in pos_edges:
        m = e["mir"]
        l = e["llvm"]
        add({m}, set())
        add(set(), {l})

    weighted = []
    weights = []
    for e in edges:
        w = float(e.get("freq", 0.0)) * float(e.get("w", 0.0))
        if w <= 0:
            continue
        weighted.append(e)
        weights.append(w)

    def add_from_edge(dm, dl, e):
        m = e["mir"]
        l = e["llvm"]
        if e.get("sign", 0) < 0:
            r = random.random()
            if r < 0.65:
                dm.add(m)
                dl.add(l)
            elif r < 0.825:
                dm.add(m)
            else:
                dl.add(l)
        else:
            r = random.random()
            if r < 0.85:
                (dm.add(m) if random.random() < 0.5 else dl.add(l))
            elif r < 0.95:
                dm.add(m)
                dl.add(l)
            else:
                pass

    attempts = 0
    max_attempts = max(200, budget * 50)
    while len(uniq) < budget and attempts < max_attempts:
        attempts += 1
        dm = set()
        dl = set()
        if weighted:
            k = min(len(weighted), random.randint(1, 4))
            for e in random.choices(weighted, weights=weights, k=k):
                add_from_edge(dm, dl, e)
        add(dm, dl)

    return uniq[:budget]

def run_module(mod, out_dir, budget):
    clean_build = os.environ.get("CLEAN_BUILD", "0") == "1"
    seed = int(os.environ.get("SEED", "0"))
    random.seed(seed)
    cand = gen_candidates(mod, budget)
    res_csv = out_dir / "module_results.csv"
    fieldnames = [
        "idx",
        "MIR_Disabled",
        "LLVM_Disabled",
        "BinarySize(Bytes)",
        "TotalRuntime(s)",
        "CompileTime(s)",
        "Penalty",
        "Status",
    ]
    rows = []
    with res_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for idx, (dm, dl) in enumerate(cand, 1):
            size, tot, comp, status = eval_config(dm, dl, clean_build=clean_build)
            pen = penalty(dm, dl, mod["edges"])
            row = {
                "idx": idx,
                "MIR_Disabled": ";".join(sorted(dm)),
                "LLVM_Disabled": ";".join(sorted(dl)),
                "BinarySize(Bytes)": size,
                "TotalRuntime(s)": tot,
                "CompileTime(s)": comp,
                "Penalty": pen,
                "Status": status,
            }
            rows.append(row)
            w.writerow(row)
            f.flush()
            print(f"module={mod['id']} {idx}/{len(cand)} status={status} rt={tot:.6g}s ct={comp:.6g}s size={size} pen={pen:.6g}", flush=True)
    ok = [r for r in rows if r["Status"] == "Success"]
    pareto = nondominated(ok)
    pareto_csv = out_dir / "module_pareto.csv"
    with pareto_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(pareto)
    return res_csv, pareto_csv

def main():
    out_root = BASE / "pareto_search" / ("demo_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    out_root.mkdir(parents=True, exist_ok=True)
    data = json.loads(MODULES_JSON.read_text(encoding="utf-8"))
    mods = data["modules"]
    budget = int(os.environ.get("MODULE_BUDGET", "60"))
    module_limit = int(os.environ.get("MODULE_LIMIT", "1"))
    done = []
    for i, mod in enumerate(mods[:module_limit], 1):
        mdir = out_root / f"module_{mod['id']}"
        mdir.mkdir(parents=True, exist_ok=True)
        r, p = run_module(mod, mdir, budget)
        done.append((r, p))
    print(str(out_root))
    for r, p in done:
        print(str(r))
        print(str(p))

if __name__ == "__main__":
    main()
