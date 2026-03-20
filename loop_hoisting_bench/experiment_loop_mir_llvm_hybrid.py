import argparse
import csv
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import time
from datetime import datetime
import math
from collections import defaultdict
from statistics import median


PROJECT_ROOT = "/mnt/fjx/Compiler_Experiment/loop_test"
DEFAULT_JSON_PATH = "/mnt/fjx/Compiler_Experiment/table/table_json/combined_experiment_matrix.json"
CSV_COLS = 41


def get_combinations(json_path):
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("combinations", [])


def safe_dir_name(s):
    s = str(s).strip().replace(" ", "_")
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", s)
    return s[:180] if len(s) > 180 else s


def labels_from_combo(combo):
    mir_pass_label = "N/A"
    if combo.get("mir"):
        if isinstance(combo["mir"], dict):
            mir_pass_label = combo["mir"].get("pass", "N/A")
        else:
            mir_pass_label = str(combo["mir"])

    llvm_pass_label = "None"
    if combo.get("llvm"):
        if isinstance(combo["llvm"], dict):
            llvm_pass_label = combo["llvm"].get("pass", "None")
        else:
            llvm_pass_label = str(combo["llvm"])

    return llvm_pass_label, mir_pass_label


def compose_rustflags_from_combo(combo):
    flags = ["-C opt-level=3"]

    if combo.get("mir") and isinstance(combo["mir"], dict) and combo["mir"].get("switches"):
        switches = ",".join(combo["mir"]["switches"])
        flags.append(f"-Z mir-enable-passes={switches}")

    if combo.get("llvm") and isinstance(combo["llvm"], dict) and combo["llvm"].get("switches"):
        for switch in combo["llvm"]["switches"]:
            flags.append(f"-C llvm-args={switch}")

    if combo.get("RUSTFLAGS"):
        flags.append(str(combo["RUSTFLAGS"]))

    return " ".join(flags)


def clean_project(env):
    target_dir = os.path.join(PROJECT_ROOT, "target")
    if os.path.exists(target_dir):
        try:
            shutil.rmtree(target_dir)
            return True
        except Exception:
            pass
    p = subprocess.run(["cargo", "clean"], cwd=PROJECT_ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return p.returncode == 0


def run_capture(cmd, env, logf):
    logf.write(f"[EXEC] {cmd}\n")
    logf.flush()
    p = subprocess.run(
        cmd,
        cwd=PROJECT_ROOT,
        env=env,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if p.stdout:
        logf.write(f"[STDOUT] {p.stdout}\n")
    if p.stderr:
        logf.write(f"[STDERR] {p.stderr}\n")
    logf.flush()
    return p


def write_csv_row(csv_path, row):
    if len(row) < CSV_COLS:
        row = row + [""] * (CSV_COLS - len(row))
    elif len(row) > CSV_COLS:
        row = row[:CSV_COLS]
    with open(csv_path, "a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(row)


def build_project(env, logf, retries=3):
    cmd = "cargo build --release --quiet"
    last_err = ""
    backoff = 0.5
    for _ in range(max(retries, 1)):
        t0 = time.perf_counter()
        p = run_capture(cmd, env, logf)
        t1 = time.perf_counter()
        if p.returncode == 0:
            return True, (t1 - t0), (p.stderr or "")
        last_err = (p.stderr or "") + "\n" + (p.stdout or "")
        if "Text file busy (os error 26)" in last_err:
            time.sleep(backoff)
            backoff = min(backoff * 2, 4.0)
            continue
        break
    return False, 0.0, last_err


def extract_licm_remarks(stderr_text):
    if not stderr_text:
        return ""
    out = []
    for ln in stderr_text.splitlines():
        if not ln.startswith("remark:"):
            continue
        if "remark:" in ln:
            out.append(ln)
    return "\n".join(out) + ("\n" if out else "")


def get_exe_path():
    exe_path = os.path.join(PROJECT_ROOT, "target", "release", "loop_test")
    return exe_path if os.path.exists(exe_path) else None


def run_benchmark(exe_path, run_args, pin_cpu=-1):
    cmd = [exe_path] + run_args
    if pin_cpu is not None and pin_cpu >= 0 and shutil.which("taskset"):
        cmd = ["taskset", "-c", str(pin_cpu)] + cmd
    p = subprocess.run(cmd, cwd=PROJECT_ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        return None
    m = re.search(r"Total Time:\s+([\d\.]+)\s+s", p.stdout)
    if not m:
        return None
    return float(m.group(1))


def list_files_by_mtime(root_dir, suffixes):
    results = []
    for dirpath, _, filenames in os.walk(root_dir):
        for fn in filenames:
            if any(fn.endswith(suf) for suf in suffixes):
                fp = os.path.join(dirpath, fn)
                try:
                    st = os.stat(fp)
                except OSError:
                    continue
                results.append((st.st_mtime, fp))
    results.sort(key=lambda x: x[0])
    return [fp for _, fp in results]


def parse_mir_counts(mir_text):
    bb = 0
    for line in mir_text.splitlines():
        if re.match(r"^\s*bb\d+:", line):
            bb += 1
    goto = len(re.findall(r"\bgoto\b", mir_text))
    switch_int = len(re.findall(r"\bswitchInt\b", mir_text))
    terminator = len(re.findall(r"^\s*(goto|switchInt|return|resume|unreachable)\b", mir_text, flags=re.MULTILINE))
    locals_cnt = len(re.findall(r"^\s*let(\s+mut)?\s+_\d+:", mir_text, flags=re.MULTILINE))
    return {
        "bb": bb,
        "goto": goto,
        "switchInt": switch_int,
        "terminatorBlocks": terminator,
        "locals": locals_cnt,
    }


def collect_mir_evidence(mir_dump_dir):
    mir_files = list_files_by_mtime(mir_dump_dir, (".mir",))
    if not mir_files:
        return None

    built_after = None
    runtime_opt_after = None
    for fp in mir_files:
        base = os.path.basename(fp)
        if base.endswith(".built.after.mir"):
            built_after = fp
        elif base.endswith(".runtime-optimized.after.mir"):
            runtime_opt_after = fp

    first_fp = built_after or mir_files[0]
    last_fp = runtime_opt_after or mir_files[-1]

    try:
        with open(first_fp, "r", encoding="utf-8", errors="replace") as f:
            first_text = f.read()
        with open(last_fp, "r", encoding="utf-8", errors="replace") as f:
            last_text = f.read()
    except OSError:
        return None

    first = parse_mir_counts(first_text)
    last = parse_mir_counts(last_text)
    return {
        "mir_first_file": os.path.basename(first_fp),
        "mir_last_file": os.path.basename(last_fp),
        "mir_first_path": first_fp,
        "mir_last_path": last_fp,
        "mir_bb_first": first["bb"],
        "mir_bb_last": last["bb"],
        "mir_term_blocks_first": first["terminatorBlocks"],
        "mir_term_blocks_last": last["terminatorBlocks"],
        "mir_goto_first": first["goto"],
        "mir_goto_last": last["goto"],
        "mir_switch_first": first["switchInt"],
        "mir_switch_last": last["switchInt"],
        "mir_locals_first": first["locals"],
        "mir_locals_last": last["locals"],
    }


def collect_recent_emit_files(modified_after):
    exts = (".ll", ".s")
    root = os.path.join(PROJECT_ROOT, "target", "release", "deps")
    found = []
    if not os.path.isdir(root):
        return []
    for dirpath, _, filenames in os.walk(root):
        for fn in filenames:
            if not fn.endswith(exts):
                continue
            if "loop_test" not in fn:
                continue
            fp = os.path.join(dirpath, fn)
            try:
                st = os.stat(fp)
            except OSError:
                continue
            if st.st_mtime >= modified_after:
                found.append((st.st_mtime, fp))
    found.sort(key=lambda x: x[0])
    return [fp for _, fp in found]


def parse_llvm_function_block(ir_text, func_name):
    m = re.search(rf"^define\b.*@{re.escape(func_name)}\b.*\{{\s*$", ir_text, flags=re.MULTILINE)
    if not m:
        return None
    start = m.end()
    end = ir_text.find("\n}\n", start)
    if end == -1:
        end = ir_text.find("\n}", start)
        if end == -1:
            return None
    return ir_text[start:end]


def parse_llvm_counts(ir_text, func_name):
    body = parse_llvm_function_block(ir_text, func_name)
    if body is None:
        return None
    bb = 0
    br = 0
    switch = 0
    for line in body.splitlines():
        if re.match(r"^[A-Za-z$._][A-Za-z0-9$._-]*:\s*(;.*)?$", line):
            bb += 1
        if re.search(r"^\s*br\s", line):
            br += 1
        if re.search(r"^\s*switch\s", line):
            switch += 1
    return {"llvm_bb": bb, "llvm_br": br, "llvm_switch": switch}


def extract_function_def_line(ir_text, func_name):
    m = re.search(rf"^define\b.*@{re.escape(func_name)}\b.*\{{\s*$", ir_text, flags=re.MULTILINE)
    if not m:
        return ""
    line_start = ir_text.rfind("\n", 0, m.start())
    if line_start == -1:
        line_start = 0
    else:
        line_start += 1
    line_end = ir_text.find("\n", m.start())
    if line_end == -1:
        line_end = m.start()
    return ir_text[line_start:line_end]


def split_llvm_blocks(func_body):
    blocks = {}
    order = []
    current = None
    for raw in func_body.splitlines():
        line = raw.rstrip("\n")
        m = re.match(r"^([A-Za-z$._][A-Za-z0-9$._-]*):\s*(;.*)?$", line)
        if m:
            current = m.group(1)
            order.append(current)
            blocks[current] = []
            continue
        if current is None:
            current = "entry"
            order.append(current)
            blocks[current] = []
        blocks[current].append(line)
    return order, blocks


def llvm_successors(block_lines):
    succ = []
    for line in reversed(block_lines[-6:]):
        if re.search(r"^\s*br\s", line):
            targets = re.findall(r"label\s+%([A-Za-z$._][A-Za-z0-9$._-]*)", line)
            succ.extend(targets)
            return succ
        if re.search(r"^\s*switch\s", line):
            targets = re.findall(r"label\s+%([A-Za-z$._][A-Za-z0-9$._-]*)", line)
            succ.extend(targets)
            return succ
    return succ


def scc_tarjan(nodes, edges):
    index = 0
    stack = []
    onstack = set()
    idx = {}
    low = {}
    comps = []

    def strongconnect(v):
        nonlocal index
        idx[v] = index
        low[v] = index
        index += 1
        stack.append(v)
        onstack.add(v)

        for w in edges.get(v, []):
            if w not in idx:
                strongconnect(w)
                low[v] = min(low[v], low[w])
            elif w in onstack:
                low[v] = min(low[v], idx[w])

        if low[v] == idx[v]:
            comp = []
            while True:
                w = stack.pop()
                onstack.remove(w)
                comp.append(w)
                if w == v:
                    break
            comps.append(comp)

    for v in nodes:
        if v not in idx:
            strongconnect(v)

    return comps


def analyze_factor_hoisting(ll_text, func_name, mode):
    body = parse_llvm_function_block(ll_text, func_name)
    if body is None:
        return None

    order, blocks = split_llvm_blocks(body)
    edges = {b: llvm_successors(blocks.get(b, [])) for b in order}

    comps = scc_tarjan(order, edges)
    loop_comps = []
    for comp in comps:
        if len(comp) > 1:
            loop_comps.append(comp)
            continue
        b = comp[0]
        if b in edges and b in edges[b]:
            loop_comps.append(comp)

    if not loop_comps:
        return {
            "hot_scc_size": 0,
            "hot_loads": 0,
            "factor_in_hot": 0,
            "factor_out_hot": 0,
            "factor_total": 0,
            "factor_hoisted": 0,
        }

    def load_count(comp):
        n = 0
        for b in comp:
            for ln in blocks.get(b, []):
                if re.search(r"\bload\b", ln):
                    n += 1
        return n

    loop_comps.sort(key=lambda c: (load_count(c), len(c)), reverse=True)
    hot = loop_comps[0]
    hot_set = set(hot)
    hot_loads = load_count(hot)

    def_line = extract_function_def_line(ll_text, func_name)
    arg_names = re.findall(r"%[A-Za-z$._][A-Za-z0-9$._-]*", def_line)
    tainted = set(arg_names)

    consts = {7, 3} if mode == "easy" else {13, 7, 3, 5}
    const_pat = re.compile(r"\b(" + "|".join(str(c) for c in sorted(consts)) + r")\b")
    def_pat = re.compile(r"^\s*(%[A-Za-z$._][A-Za-z0-9$._-]*)\s*=\s*([A-Za-z]+)\b")

    insn_by_block = []
    for b in order:
        for ln in blocks.get(b, []):
            insn_by_block.append((b, ln))

    changed = True
    while changed:
        changed = False
        for _, ln in insn_by_block:
            m = def_pat.match(ln)
            if not m:
                continue
            dst = m.group(1)
            if dst in tainted:
                continue
            ops = re.findall(r"%[A-Za-z$._][A-Za-z0-9$._-]*", ln)
            if any(op in tainted for op in ops):
                tainted.add(dst)
                changed = True

    factor_in_hot = 0
    factor_out_hot = 0
    factor_total = 0
    for b, ln in insn_by_block:
        m = def_pat.match(ln)
        if not m:
            continue
        dst = m.group(1)
        if dst not in tainted:
            continue
        if not const_pat.search(ln):
            continue
        op = m.group(2).lower()
        if op not in {"add", "mul", "xor", "shl", "lshr", "ashr", "or", "and", "sub"}:
            continue
        factor_total += 1
        if b in hot_set:
            factor_in_hot += 1
        else:
            factor_out_hot += 1

    factor_hoisted = 1 if (factor_total > 0 and factor_in_hot == 0 and factor_out_hot > 0) else 0
    return {
        "hot_scc_size": len(hot_set),
        "hot_loads": hot_loads,
        "factor_in_hot": factor_in_hot,
        "factor_out_hot": factor_out_hot,
        "factor_total": factor_total,
        "factor_hoisted": factor_hoisted,
    }


def parse_licm_remarks(path):
    if not path or (not os.path.isfile(path)):
        return {"licm_passed": 0, "licm_missed": 0}
    try:
        text = open(path, "r", encoding="utf-8", errors="replace").read()
    except OSError:
        return {"licm_passed": 0, "licm_missed": 0}
    lines = [ln for ln in text.splitlines() if ln.strip()]
    passed = 0
    missed = 0
    for ln in lines:
        if "remark:" not in ln:
            continue
        low = ln.lower()
        if "failed to" in low:
            missed += 1
        else:
            passed += 1
    return {"licm_passed": passed, "licm_missed": missed}


def already_done(csv_path, name, mode, runs_needed):
    if not os.path.exists(csv_path):
        return False
    count = 0
    prefix = f"{name},{mode},"
    with open(csv_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.startswith(prefix):
                count += 1
                if count >= runs_needed:
                    return True
    return False


def parse_run_args(mode, length, iters, seed):
    return [
        "--mode",
        mode,
        "--len",
        str(length),
        "--iters",
        str(iters),
        "--seed",
        str(seed),
    ]


def measure_combination_mode(
    combo,
    mode,
    runs,
    skip_clean,
    length,
    iters,
    seed,
    warmup_iters,
    pin_cpu,
    csv_path,
    logf,
    evidence,
    keep_ir,
    base_out,
):
    name = combo.get("name") or combo.get("Experiment_ID") or "Unknown"
    llvm_pass_label, mir_pass_label = labels_from_combo(combo)

    if already_done(csv_path, name, mode, runs):
        msg = f"[Skip] {name} mode={mode} (Already done)"
        print(msg)
        logf.write(msg + "\n")
        logf.flush()
        return

    env = os.environ.copy()
    cargo_bin = os.path.expanduser("~/.cargo/bin")
    if cargo_bin and cargo_bin not in env.get("PATH", ""):
        env["PATH"] = f"{cargo_bin}:{env.get('PATH', '')}"

    env["CARGO_INCREMENTAL"] = "0"

    if combo.get("force_rustflags"):
        rustflags_base = str(combo.get("force_rustflags"))
    else:
        rustflags_base = compose_rustflags_from_combo(combo)
    run_args = parse_run_args(mode, length, iters, seed)
    warmup_run_args = parse_run_args(mode, length, warmup_iters, seed) if warmup_iters and warmup_iters > 0 else None
    dump_item = "loop_easy" if mode == "easy" else "loop_mir_dependent"

    for run_id in range(1, runs + 1):
        evidence_dir = os.path.join(base_out, "evidence", safe_dir_name(name), mode, f"run_{run_id}")
        mir_dump_dir = os.path.join(evidence_dir, "mir_dump")
        licm_remarks_path = os.path.join(evidence_dir, "licm_remarks.yaml")

        if evidence:
            os.makedirs(mir_dump_dir, exist_ok=True)
            os.makedirs(evidence_dir, exist_ok=True)
            env_rustflags_run = (
                rustflags_base
                + " --emit=llvm-ir,asm,link"
                + f" -Z dump-mir={dump_item}"
                + f" -Z dump-mir-dir={mir_dump_dir}"
                + " -Z dump-mir-exclude-pass-number=yes"
                + " -Z dump-mir-exclude-alloc-bytes=yes"
                + " -C llvm-args=-pass-remarks=licm"
                + " -C llvm-args=-pass-remarks-missed=licm"
            )
        else:
            env_rustflags_run = rustflags_base

        env["RUSTFLAGS"] = env_rustflags_run

        msg1 = f"[Exp] {name} mode={mode} Iteration {run_id}/{runs}"
        msg2 = f"[Flags] {env_rustflags_run}"
        msg3 = f"[Run] args={' '.join(run_args)}"
        print(msg1)
        print(msg2)
        print(msg3)
        logf.write(msg1 + "\n")
        logf.write(msg2 + "\n")
        logf.write(msg3 + "\n")
        logf.flush()

        if not skip_clean:
            clean_ok = clean_project(env)
            if not clean_ok:
                write_csv_row(csv_path, [name, mode, length, iters, seed, warmup_iters, pin_cpu, run_id, llvm_pass_label, mir_pass_label, 0, "", 0, 0, "CleanFailed"])
                continue

        build_start_ts = time.time()
        ok, compile_time, build_stderr = build_project(env, logf)
        exe_path = get_exe_path()
        if (not ok) or (not exe_path):
            write_csv_row(csv_path, [name, mode, length, iters, seed, warmup_iters, pin_cpu, run_id, llvm_pass_label, mir_pass_label, 0, "", 0, f"{compile_time:.6f}", "BuildFailed"])
            continue

        size_bytes = os.path.getsize(exe_path)
        try:
            with open(exe_path, "rb") as bf:
                binary_sha256 = hashlib.sha256(bf.read()).hexdigest()
        except OSError:
            binary_sha256 = ""

        mir_ev = None
        llvm_ev = None
        ll_file = ""
        s_file = ""
        licm_passed = ""
        licm_missed = ""
        ll_analysis = None
        if evidence:
            mir_ev = collect_mir_evidence(mir_dump_dir)

            recent = collect_recent_emit_files(build_start_ts - 1.0)
            ll_candidates = [p for p in recent if p.endswith(".ll")]
            s_candidates = [p for p in recent if p.endswith(".s")]
            ll_fp = ll_candidates[-1] if ll_candidates else ""
            s_fp = s_candidates[-1] if s_candidates else ""
            ll_file = os.path.basename(ll_fp) if ll_fp else ""
            s_file = os.path.basename(s_fp) if s_fp else ""

            if ll_fp:
                try:
                    ll_text = open(ll_fp, "r", encoding="utf-8", errors="replace").read()
                    func = "loop_easy" if mode == "easy" else "loop_mir_dependent"
                    llvm_ev = parse_llvm_counts(ll_text, func)
                    ll_analysis = analyze_factor_hoisting(ll_text, func, mode)
                except OSError:
                    llvm_ev = None

            licm_text = extract_licm_remarks(build_stderr)
            try:
                with open(licm_remarks_path, "w", encoding="utf-8") as f:
                    f.write(licm_text)
            except OSError:
                pass

            licm_stats = parse_licm_remarks(licm_remarks_path)
            licm_passed = licm_stats.get("licm_passed", 0)
            licm_missed = licm_stats.get("licm_missed", 0)

            if mir_ev and (not keep_ir):
                keep = {mir_ev.get("mir_first_path"), mir_ev.get("mir_last_path")}
                for dirpath, _, filenames in os.walk(mir_dump_dir):
                    for fn in filenames:
                        fp = os.path.join(dirpath, fn)
                        if fp in keep:
                            continue
                        try:
                            os.remove(fp)
                        except OSError:
                            pass

            if not keep_ir:
                for fp in [ll_fp, s_fp]:
                    if fp and os.path.isfile(fp):
                        try:
                            os.remove(fp)
                        except OSError:
                            pass
                ll_file = ""
                s_file = ""

        if warmup_run_args:
            _ = run_benchmark(exe_path, warmup_run_args, pin_cpu=pin_cpu)
        runtime_s = run_benchmark(exe_path, run_args, pin_cpu=pin_cpu)
        if runtime_s is None:
            write_csv_row(csv_path, [name, mode, length, iters, seed, warmup_iters, pin_cpu, run_id, llvm_pass_label, mir_pass_label, size_bytes, binary_sha256, 0, f"{compile_time:.6f}", "RunFailed"])
            continue

        mir_first_file = mir_ev["mir_first_file"] if mir_ev else ""
        mir_last_file = mir_ev["mir_last_file"] if mir_ev else ""
        mir_bb_first = mir_ev["mir_bb_first"] if mir_ev else ""
        mir_bb_last = mir_ev["mir_bb_last"] if mir_ev else ""
        mir_term_first = mir_ev["mir_term_blocks_first"] if mir_ev else ""
        mir_term_last = mir_ev["mir_term_blocks_last"] if mir_ev else ""
        mir_goto_first = mir_ev["mir_goto_first"] if mir_ev else ""
        mir_goto_last = mir_ev["mir_goto_last"] if mir_ev else ""
        mir_switch_first = mir_ev["mir_switch_first"] if mir_ev else ""
        mir_switch_last = mir_ev["mir_switch_last"] if mir_ev else ""
        mir_locals_first = mir_ev["mir_locals_first"] if mir_ev else ""
        mir_locals_last = mir_ev["mir_locals_last"] if mir_ev else ""

        llvm_bb = llvm_ev["llvm_bb"] if llvm_ev else ""
        llvm_br = llvm_ev["llvm_br"] if llvm_ev else ""
        llvm_switch = llvm_ev["llvm_switch"] if llvm_ev else ""
        hot_scc_size = ll_analysis["hot_scc_size"] if ll_analysis else ""
        hot_loads = ll_analysis["hot_loads"] if ll_analysis else ""
        factor_in_hot = ll_analysis["factor_in_hot"] if ll_analysis else ""
        factor_out_hot = ll_analysis["factor_out_hot"] if ll_analysis else ""
        factor_total = ll_analysis["factor_total"] if ll_analysis else ""
        factor_hoisted = ll_analysis["factor_hoisted"] if ll_analysis else ""

        write_csv_row(
            csv_path,
            [
                name,
                mode,
                length,
                iters,
                seed,
                warmup_iters,
                pin_cpu,
                run_id,
                llvm_pass_label,
                mir_pass_label,
                size_bytes,
                binary_sha256,
                f"{runtime_s:.6f}",
                f"{compile_time:.6f}",
                "Success",
                mir_first_file,
                mir_last_file,
                mir_bb_first,
                mir_bb_last,
                mir_term_first,
                mir_term_last,
                mir_goto_first,
                mir_goto_last,
                mir_switch_first,
                mir_switch_last,
                mir_locals_first,
                mir_locals_last,
                ll_file,
                llvm_bb,
                llvm_br,
                llvm_switch,
                s_file,
                licm_passed,
                licm_missed,
                os.path.basename(licm_remarks_path) if evidence else "",
                hot_scc_size,
                hot_loads,
                factor_in_hot,
                factor_out_hot,
                factor_total,
                factor_hoisted,
            ],
        )

        msg4 = f"[Result] Size={size_bytes}B, Compile={compile_time:.6f}s, Run={runtime_s:.6f}s, LICM(Passed/Missed)={licm_passed}/{licm_missed}"
        print(msg4)
        logf.write(msg4 + "\n")
        logf.flush()


def _to_float(v, default=None):
    try:
        x = float(v)
        if math.isfinite(x):
            return x
        return default
    except Exception:
        return default


def _read_csv_rows(path):
    with open(path, "r", encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        return [row for row in r]


def _write_csv_rows(path, fieldnames, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            w.writerow(row)


def _pareto_nondominated(rows, keys):
    pts = []
    for r in rows:
        p = []
        ok = True
        for k in keys:
            v = _to_float(r.get(k), None)
            if v is None:
                ok = False
                break
            p.append(v)
        if ok:
            pts.append((r, tuple(p)))

    keep = []
    for i, (ri, pi) in enumerate(pts):
        dominated = False
        for j, (rj, pj) in enumerate(pts):
            if i == j:
                continue
            le_all = all(a <= b for a, b in zip(pj, pi))
            lt_any = any(a < b for a, b in zip(pj, pi))
            if le_all and lt_any:
                dominated = True
                break
        if not dominated:
            keep.append(ri)
    return keep


def analyze_results_csv(input_csv, analysis_out):
    in_path = str(input_csv).strip()
    if in_path.startswith("\\") and not in_path.startswith("/"):
        in_path = in_path.replace("\\", "/")
    in_path = os.path.abspath(in_path)
    if not os.path.exists(in_path):
        raise FileNotFoundError(in_path)

    root = str(analysis_out).strip()
    if root:
        if root.startswith("\\") and not root.startswith("/"):
            root = root.replace("\\", "/")
        root = os.path.abspath(root)
    else:
        root = os.path.join(PROJECT_ROOT, "analysis")
    os.makedirs(root, exist_ok=True)

    base = os.path.basename(os.path.dirname(in_path)) or "analysis"
    out_dir = os.path.join(root, safe_dir_name(base))
    if os.path.exists(out_dir) and os.listdir(out_dir):
        out_dir = out_dir + "_" + datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs(out_dir, exist_ok=True)

    rows = _read_csv_rows(in_path)
    n_total = len(rows)
    ok_rows = [r for r in rows if str(r.get("Status", "")).strip() == "Success"]
    n_ok = len(ok_rows)

    baseline = {}
    baseline_rows = [r for r in ok_rows if str(r.get("ConfigName", "")).strip() == "EXP_000_ALL_OFF"]
    by_mode = defaultdict(list)
    for r in baseline_rows:
        mode = str(r.get("Mode", "")).strip()
        rt = _to_float(r.get("TotalRuntime(s)"), None)
        ct = _to_float(r.get("CompileTime(s)"), None)
        sz = _to_float(r.get("BinarySize(Bytes)"), None)
        if not mode or rt is None or ct is None or sz is None:
            continue
        by_mode[mode].append((rt, ct, sz))
    for mode, pts in by_mode.items():
        baseline[mode] = {
            "runtime_med": median([p[0] for p in pts]),
            "compile_med": median([p[1] for p in pts]),
            "size_med": median([p[2] for p in pts]),
        }

    groups = defaultdict(list)
    for r in ok_rows:
        key = (
            str(r.get("ConfigName", "")).strip(),
            str(r.get("Mode", "")).strip(),
            str(r.get("LLVM_Pass", "")).strip(),
            str(r.get("MIR_Pass", "")).strip(),
        )
        groups[key].append(r)

    summary = []
    for (cfg, mode, llvm_p, mir_p), rs in groups.items():
        rts = [_to_float(r.get("TotalRuntime(s)"), None) for r in rs]
        cts = [_to_float(r.get("CompileTime(s)"), None) for r in rs]
        szs = [_to_float(r.get("BinarySize(Bytes)"), None) for r in rs]
        rts = [x for x in rts if x is not None]
        cts = [x for x in cts if x is not None]
        szs = [x for x in szs if x is not None]
        if not rts or not cts or not szs:
            continue

        rt_med = median(rts)
        ct_med = median(cts)
        sz_med = median(szs)
        b = baseline.get(mode, None)
        if b:
            rt_delta = (rt_med / b["runtime_med"] - 1.0) * 100.0 if b["runtime_med"] else None
            ct_delta = (ct_med / b["compile_med"] - 1.0) * 100.0 if b["compile_med"] else None
            sz_delta = (sz_med / b["size_med"] - 1.0) * 100.0 if b["size_med"] else None
        else:
            rt_delta = None
            ct_delta = None
            sz_delta = None

        summary.append(
            {
                "ConfigName": cfg,
                "Mode": mode,
                "LLVM_Pass": llvm_p,
                "MIR_Pass": mir_p,
                "n": len(rs),
                "runtime_med": rt_med,
                "compile_med": ct_med,
                "size_med": sz_med,
                "runtime_delta_pct": rt_delta,
                "compile_delta_pct": ct_delta,
                "size_delta_pct": sz_delta,
            }
        )

    summary.sort(key=lambda r: (str(r.get("Mode", "")), _to_float(r.get("runtime_med"), 0.0)))

    baseline_rows_out = []
    for mode, b in sorted(baseline.items()):
        baseline_rows_out.append(
            {
                "Mode": mode,
                "runtime_med": b["runtime_med"],
                "compile_med": b["compile_med"],
                "size_med": b["size_med"],
                "n_total": n_total,
                "n_success": n_ok,
            }
        )
    _write_csv_rows(
        os.path.join(out_dir, "baseline_by_mode.csv"),
        ["Mode", "runtime_med", "compile_med", "size_med", "n_total", "n_success"],
        baseline_rows_out,
    )
    _write_csv_rows(
        os.path.join(out_dir, "summary_by_config_mode.csv"),
        [
            "ConfigName",
            "Mode",
            "LLVM_Pass",
            "MIR_Pass",
            "n",
            "runtime_med",
            "compile_med",
            "size_med",
            "runtime_delta_pct",
            "compile_delta_pct",
            "size_delta_pct",
        ],
        summary,
    )

    modes = sorted({str(r.get("Mode", "")).strip() for r in summary if str(r.get("Mode", "")).strip()})
    for mode in modes:
        rs = [r for r in summary if str(r.get("Mode", "")).strip() == mode]
        pareto = _pareto_nondominated(rs, ("runtime_med", "compile_med", "size_med"))
        pareto.sort(key=lambda r: (_to_float(r.get("runtime_med"), 0.0), _to_float(r.get("size_med"), 0.0)))
        _write_csv_rows(
            os.path.join(out_dir, f"pareto_front_{safe_dir_name(mode)}.csv"),
            [
                "ConfigName",
                "Mode",
                "LLVM_Pass",
                "MIR_Pass",
                "n",
                "runtime_med",
                "compile_med",
                "size_med",
                "runtime_delta_pct",
                "compile_delta_pct",
                "size_delta_pct",
            ],
            pareto,
        )

    try:
        import matplotlib.pyplot as plt

        def _label(r):
            x = str(r.get("MIR_Pass", "")).strip() or str(r.get("ConfigName", "")).strip()
            return x[:48] + ("…" if len(x) > 48 else "")

        for mode in modes:
            rs = [r for r in summary if str(r.get("Mode", "")).strip() == mode]
            for metric, title in (
                ("runtime_delta_pct", "Runtime Δ% vs baseline (median)"),
                ("compile_delta_pct", "Compile time Δ% vs baseline (median)"),
                ("size_delta_pct", "Binary size Δ% vs baseline (median)"),
            ):
                rs2 = [(r, _to_float(r.get(metric), None)) for r in rs]
                rs2 = [(r, v) for r, v in rs2 if v is not None]
                if not rs2:
                    continue
                rs2.sort(key=lambda x: x[1])
                top = rs2[:20]
                labels = [_label(r) for r, _ in top]
                vals = [v for _, v in top]
                plt.figure(figsize=(10, 6))
                plt.barh(list(range(len(vals))), vals, color="#4C78A8")
                plt.yticks(list(range(len(vals))), labels, fontsize=9)
                plt.gca().invert_yaxis()
                plt.axvline(0, color="#333", linewidth=1)
                plt.xlabel("Δ%")
                plt.title(f"{mode}: {title} (top 20)")
                plt.tight_layout()
                out_png = os.path.join(out_dir, f"{safe_dir_name(mode)}_{metric}_top20.png")
                out_pdf = os.path.join(out_dir, f"{safe_dir_name(mode)}_{metric}_top20.pdf")
                plt.savefig(out_png, dpi=200)
                plt.savefig(out_pdf)
                plt.close()

            pareto = _pareto_nondominated(rs, ("runtime_med", "compile_med", "size_med"))
            if pareto:
                plt.figure(figsize=(8, 6))
                plt.scatter(
                    [_to_float(r.get("runtime_med"), 0.0) for r in rs],
                    [_to_float(r.get("size_med"), 0.0) for r in rs],
                    s=18,
                    alpha=0.25,
                    color="#999999",
                )
                plt.scatter(
                    [_to_float(r.get("runtime_med"), 0.0) for r in pareto],
                    [_to_float(r.get("size_med"), 0.0) for r in pareto],
                    s=28,
                    alpha=0.9,
                    color="#E45756",
                    label="Pareto front",
                )
                plt.xlabel("Runtime (s), median")
                plt.ylabel("Binary size (bytes), median")
                plt.title(f"{mode}: Runtime vs Size (median), Pareto highlighted")
                plt.legend(loc="best", fontsize=9)
                plt.tight_layout()
                out_png = os.path.join(out_dir, f"{safe_dir_name(mode)}_runtime_vs_size_pareto.png")
                out_pdf = os.path.join(out_dir, f"{safe_dir_name(mode)}_runtime_vs_size_pareto.pdf")
                plt.savefig(out_png, dpi=200)
                plt.savefig(out_pdf)
                plt.close()
    except Exception:
        pass

    print(f"[Analysis] Input: {in_path}")
    print(f"[Analysis] Output dir: {out_dir}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--analyze-csv", default="")
    parser.add_argument("--analysis-out", default="")
    parser.add_argument("--json-path", default=DEFAULT_JSON_PATH)
    parser.add_argument("--opt3-only", action="store_true")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--skip-clean", action="store_true")
    parser.add_argument("--modes", default="easy,mir-dependent")
    parser.add_argument("--len", type=int, default=8_388_608)
    parser.add_argument("--iters", type=int, default=1200)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--warmup-iters", type=int, default=0)
    parser.add_argument("--pin-cpu", type=int, default=-1)
    parser.add_argument("--shuffle", action="store_true")
    parser.add_argument("--shuffle-seed", type=int, default=1)
    parser.add_argument("--no-evidence", action="store_true")
    parser.add_argument("--keep-ir", action="store_true")
    args = parser.parse_args()

    if str(args.analyze_csv).strip():
        analyze_results_csv(str(args.analyze_csv).strip(), str(args.analysis_out).strip())
        return

    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    modes = ["mir-dependent" if m in ("mir_dependent", "mir", "dependent") else m for m in modes]

    if args.opt3_only:
        combos = [
            {
                "name": "OPT3_ONLY",
                "Experiment_ID": "OPT3_ONLY",
                "force_rustflags": "-C opt-level=3",
            }
        ]
        args.no_evidence = True
        args.keep_ir = False
    else:
        combos = get_combinations(args.json_path)
    if args.start > 0:
        combos = combos[args.start:]
    if args.limit and args.limit > 0:
        combos = combos[: args.limit]
    if args.shuffle:
        rng = random.Random(args.shuffle_seed)
        rng.shuffle(combos)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_out = args.output_dir or os.path.join(PROJECT_ROOT, "mir_llvm_hybrid_py", ts)
    os.makedirs(base_out, exist_ok=True)
    results_csv = os.path.join(base_out, "experiment_results.csv")
    exec_log = os.path.join(base_out, "experiment_execution.log")

    if not os.path.exists(results_csv):
        with open(results_csv, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(
                [
                    "ConfigName",
                    "Mode",
                    "Len",
                    "Iters",
                    "Seed",
                    "WarmupIters",
                    "PinCPU",
                    "RunID",
                    "LLVM_Pass",
                    "MIR_Pass",
                    "BinarySize(Bytes)",
                    "BinarySHA256",
                    "TotalRuntime(s)",
                    "CompileTime(s)",
                    "Status",
                    "MIR_First_File",
                    "MIR_Last_File",
                    "MIR_BB_First",
                    "MIR_BB_Last",
                    "MIR_TermBlocks_First",
                    "MIR_TermBlocks_Last",
                    "MIR_Goto_First",
                    "MIR_Goto_Last",
                    "MIR_SwitchInt_First",
                    "MIR_SwitchInt_Last",
                    "MIR_Locals_First",
                    "MIR_Locals_Last",
                    "LLVM_LL_File",
                    "LLVM_BB",
                    "LLVM_br",
                    "LLVM_switch",
                    "ASM_S_File",
                    "LICM_Remarks_Passed",
                    "LICM_Remarks_Missed",
                    "LICM_Remarks_File",
                    "HotLoop_SCCSize",
                    "HotLoop_Loads",
                    "FactorConst_InHotLoop",
                    "FactorConst_OutHotLoop",
                    "FactorConst_Total",
                    "FactorConst_Hoisted",
                ]
            )

    with open(exec_log, "w", encoding="utf-8") as logf:
        logf.write(f"Total Rows: {len(combos)}\n")
        try:
            rustc_vv = subprocess.run(["rustc", "-Vv"], cwd=PROJECT_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True).stdout
        except Exception:
            rustc_vv = ""
        try:
            cargo_v = subprocess.run(["cargo", "-V"], cwd=PROJECT_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True).stdout
        except Exception:
            cargo_v = ""
        try:
            uname_a = subprocess.run(["uname", "-a"], cwd=PROJECT_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True).stdout
        except Exception:
            uname_a = ""
        logf.write("Toolchain:\n")
        if rustc_vv:
            logf.write(rustc_vv + ("\n" if not rustc_vv.endswith("\n") else ""))
        if cargo_v:
            logf.write(cargo_v + ("\n" if not cargo_v.endswith("\n") else ""))
        if uname_a:
            logf.write(uname_a + ("\n" if not uname_a.endswith("\n") else ""))
        logf.flush()
        print(f"Total Rows: {len(combos)}")
        if args.warmup_iters and args.warmup_iters > 0:
            warmup_iters = args.warmup_iters
        else:
            warmup_iters = max(1, min(200, args.iters // 50))
        for combo in combos:
            for mode in modes:
                measure_combination_mode(
                    combo=combo,
                    mode=mode,
                    runs=args.runs,
                    skip_clean=args.skip_clean,
                    length=args.len,
                    iters=args.iters,
                    seed=args.seed,
                    warmup_iters=warmup_iters,
                    pin_cpu=args.pin_cpu,
                    csv_path=results_csv,
                    logf=logf,
                    evidence=(not args.no_evidence),
                    keep_ir=args.keep_ir,
                    base_out=base_out,
                )


if __name__ == "__main__":
    main()
