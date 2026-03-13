import argparse
import csv
import json
import os
import re
import shutil
import subprocess
import time
from datetime import datetime


SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(SCRIPT_DIR)

PROJECT_ROOT = SCRIPT_DIR
DEFAULT_JSON_PATH = "/mnt/MIR_LLVM_Experiment/table/table_json/combined_experiment_matrix.json"
if not os.path.exists(DEFAULT_JSON_PATH):
    DEFAULT_JSON_PATH = os.path.join(REPO_ROOT, "table", "table_json", "combined_experiment_matrix.json")

DEFAULT_BENCH_NAME = "iterator_pipeline"
DEFAULT_BENCH_FILTERS = ["easy_case", "mir_dependent_case"]
DEFAULT_KERNELS = {
    "easy_case": "kernel_easy",
    "mir_dependent_case": "kernel_mir_dependent",
}

DEFAULT_BIN_NAME = "iterator_pipeline_bench"


def get_combinations(json_path):
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("combinations", [])


def get_core4_combinations():
    return [
        {
            "name": "CORE_BASELINE",
            "group": "Baseline",
            "llvm": {"pass": "baseline", "switches": [], "parameters": {}},
            "mir": None,
        },
        {
            "name": "CORE_NO_MIR_LOWERING",
            "group": "No-MIR-Lowering",
            "llvm": {"pass": "baseline", "switches": [], "parameters": {}},
            "mir": {"pass": "Inline", "switches": ["-Inline"], "parameters": {}},
        },
        {
            "name": "CORE_NO_LLVM_VECTORIZE",
            "group": "No-LLVM-Vectorize",
            "llvm": {
                "pass": "vectorize",
                "switches": ["-vectorize-loops=false", "-vectorize-slp=false"],
                "parameters": {},
            },
            "mir": None,
        },
        {
            "name": "CORE_DUAL_DISABLE",
            "group": "Dual-disable",
            "llvm": {
                "pass": "vectorize",
                "switches": ["-vectorize-loops=false", "-vectorize-slp=false"],
                "parameters": {},
            },
            "mir": {"pass": "Inline", "switches": ["-Inline"], "parameters": {}},
        },
    ]


def clean_project(env=None):
    target_dir = os.path.join(PROJECT_ROOT, "target")
    if os.path.exists(target_dir):
        try:
            shutil.rmtree(target_dir)
        except Exception:
            if env is None:
                env = os.environ.copy()
            subprocess.run(
                ["cargo", "clean"],
                cwd=PROJECT_ROOT,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )


def compose_rustflags_from_combo(combo):
    parts = ["-C opt-level=3"]
    if combo.get("mir") and isinstance(combo["mir"], dict) and combo["mir"].get("switches"):
        switches = ",".join(combo["mir"]["switches"])
        parts.append(f"-Z mir-enable-passes={switches}")
    if combo.get("llvm") and isinstance(combo["llvm"], dict) and combo["llvm"].get("switches"):
        for switch in combo["llvm"]["switches"]:
            parts.append(f"-C llvm-args={switch}")
    if "RUSTFLAGS" in combo and combo["RUSTFLAGS"]:
        parts.append(combo["RUSTFLAGS"])
    return " ".join(parts)


def build_bench(env, bench_name, logf, retries=2):
    backoff = 0.5
    last_err = ""
    cmd = [
        "cargo",
        "+nightly",
        "bench",
        "--bench",
        bench_name,
        "--no-run",
        "--quiet",
    ]
    for _ in range(retries + 1):
        r = subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if r.returncode == 0:
            return True, "Success", "", r.stdout or "", r.stderr or ""
        err = r.stderr or ""
        last_err = err
        logf.write(err + "\n")
        logf.flush()
        if ("Text file busy (os error 26)" in err) or ("never executed" in err):
            time.sleep(backoff)
            backoff = min(backoff * 2, 4.0)
            continue
        return False, "BuildFailed", err.strip(), r.stdout or "", r.stderr or ""
    if ("Text file busy (os error 26)" in last_err) or ("never executed" in last_err) or ("failed to run custom build command" in last_err):
        return False, "Skipped", last_err.strip(), "", last_err
    return False, "BuildFailed", last_err.strip(), "", last_err


def build_release_bin(env, logf, retries=2):
    backoff = 0.5
    last_err = ""
    cmd = [
        "cargo",
        "+nightly",
        "build",
        "--release",
        "--quiet",
    ]
    for _ in range(retries + 1):
        r = subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if r.returncode == 0:
            return True, "Success", "", r.stdout or "", r.stderr or ""
        err = r.stderr or ""
        last_err = err
        logf.write(err + "\n")
        logf.flush()
        if ("Text file busy (os error 26)" in err) or ("never executed" in err):
            time.sleep(backoff)
            backoff = min(backoff * 2, 4.0)
            continue
        return False, "BuildFailed", err.strip(), r.stdout or "", r.stderr or ""
    if ("Text file busy (os error 26)" in last_err) or ("never executed" in last_err) or ("failed to run custom build command" in last_err):
        return False, "Skipped", last_err.strip(), "", last_err
    return False, "BuildFailed", last_err.strip(), "", last_err


def find_bench_exe(bench_name):
    deps_dir = os.path.join(PROJECT_ROOT, "target", "release", "deps")
    if not os.path.isdir(deps_dir):
        return None
    prefix = f"{bench_name}-"
    candidates = []
    for name in os.listdir(deps_dir):
        if not name.startswith(prefix):
            continue
        if name.endswith(".d"):
            continue
        path = os.path.join(deps_dir, name)
        if not os.path.isfile(path):
            continue
        if not os.access(path, os.X_OK):
            continue
        try:
            mtime = os.path.getmtime(path)
        except Exception:
            mtime = 0
        candidates.append((mtime, path))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def find_release_bin(bin_name):
    path = os.path.join(PROJECT_ROOT, "target", "release", bin_name)
    if os.path.isfile(path) and os.access(path, os.X_OK):
        return path
    return ""


def run_benchmark(exe_path, bench_filter, repeat):
    total_wall = 0.0
    last_out = ""
    last_err = ""
    ns_per_iter = ""
    mbps = ""

    def extract_numeric_before(text, suffix):
        pos = text.lower().rfind(suffix.lower())
        if pos < 0:
            return ""
        i = pos - 1
        while i >= 0 and text[i].isspace():
            i -= 1
        j = i
        while j >= 0 and (text[j].isdigit() or text[j] in ",."):
            j -= 1
        if j == i:
            return ""
        return text[j + 1 : i + 1].replace(",", "")
    for _ in range(repeat):
        t0 = time.perf_counter()
        p = subprocess.run(
            [exe_path, "--bench", bench_filter, "--exact", "--test-threads", "1", "-q"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        t1 = time.perf_counter()
        if p.returncode != 0:
            last_err = (p.stdout or "").strip()
            return None, "", "", last_err
        last_out = p.stdout or ""
        total_wall += (t1 - t0)

        m_ns = re.search(r"bench:\\s*([0-9][0-9,]*(?:\\.[0-9]+)?)\\s*ns/iter", last_out)
        if not m_ns:
            m_ns = re.search(r"([0-9][0-9,]*(?:\\.[0-9]+)?)\\s*ns/iter", last_out)
        if m_ns:
            ns_per_iter = m_ns.group(1).replace(",", "")
        elif not ns_per_iter:
            ns_per_iter = extract_numeric_before(last_out, "ns/iter")
        m_mbps = re.search(r"=\\s*([0-9][0-9,]*(?:\\.[0-9]+)?)\\s*MB/s", last_out)
        if not m_mbps:
            m_mbps = re.search(r"([0-9][0-9,]*(?:\\.[0-9]+)?)\\s*MB/s", last_out)
        if m_mbps:
            mbps = m_mbps.group(1).replace(",", "")
        elif not mbps:
            mbps = extract_numeric_before(last_out, "MB/s")

    if not ns_per_iter:
        last_err = last_out.strip()
        return None, "", "", last_err

    return total_wall, ns_per_iter, mbps, last_err


def run_bin_case(exe_path, mode, length, iters, seed, repeat):
    total_wall = 0.0
    last_out = ""
    last_err = ""
    ns_per_iter = ""
    mbps = ""

    for _ in range(repeat):
        t0 = time.perf_counter()
        p = subprocess.run(
            [
                exe_path,
                "--mode",
                mode,
                "--len",
                str(length),
                "--iters",
                str(iters),
                "--seed",
                str(seed),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        t1 = time.perf_counter()
        if p.returncode != 0:
            last_err = (p.stdout or "").strip()
            return None, "", "", last_err
        last_out = p.stdout or ""
        total_wall += (t1 - t0)

        m_ns = re.search(r"ns_per_iter=([0-9]+(?:\\.[0-9]+)?)", last_out)
        if m_ns:
            ns_per_iter = m_ns.group(1)
        m_mbps = re.search(r"mbps=([0-9]+(?:\\.[0-9]+)?)", last_out)
        if m_mbps:
            mbps = m_mbps.group(1)

    if not ns_per_iter:
        last_err = last_out.strip()
        return None, "", "", last_err

    return total_wall, ns_per_iter, mbps, last_err


def choose_iters_for_target(ns_per_iter, base_iters, target_seconds):
    try:
        ns = float(ns_per_iter)
    except Exception:
        return base_iters
    if ns <= 0.0:
        return base_iters
    if target_seconds <= 0.0:
        return base_iters

    target_ns_total = target_seconds * 1e9
    target_iters = int((target_ns_total / ns) + 0.999999)
    if target_iters < 1:
        target_iters = 1
    if target_iters > 0xFFFF_FFFF:
        target_iters = 0xFFFF_FFFF
    if target_iters < base_iters:
        return base_iters
    return target_iters


def extract_ir_blocks(raw_text, wanted_substrings):
    blocks = []
    current = []
    keep = False
    for line in raw_text.splitlines(True):
        if line.startswith("; *** IR Dump After "):
            if current and keep:
                blocks.append("".join(current))
            current = [line]
            keep = any(s in line for s in wanted_substrings)
            continue
        if current:
            current.append(line)
    if current and keep:
        blocks.append("".join(current))
    return "".join(blocks)


def dump_ir_sample(combo, bench_name, base_out, logf, ir_passes):
    name = combo.get("name") or combo.get("Experiment_ID") or "Unknown"
    group = combo.get("group") or "Matrix"
    ir_dir = os.path.join(base_out, "ir_samples")
    os.makedirs(ir_dir, exist_ok=True)

    env = os.environ.copy()
    cargo_bin = os.path.expanduser("~/.cargo/bin")
    if cargo_bin and cargo_bin not in env.get("PATH", ""):
        env["PATH"] = f"{cargo_bin}:{env.get('PATH', '')}"

    extra = [
        "-Z unstable-options",
        "-C symbol-mangling-version=legacy",
        "-C llvm-args=-pass-remarks=loop-vectorize",
        "-C llvm-args=-pass-remarks-missed=loop-vectorize",
    ]
    for p in ir_passes:
        extra.append(f"-C llvm-args=-print-after={p}")

    rustflags = compose_rustflags_from_combo(combo) + " " + " ".join(extra)
    env["RUSTFLAGS"] = rustflags

    msg = f"[IRSample] {name} ({group}) passes={','.join(ir_passes)}"
    print(msg)
    logf.write(msg + "\n")
    logf.flush()

    clean_project(env)
    cmd = ["cargo", "+nightly", "bench", "--bench", bench_name, "--no-run"]
    r = subprocess.run(
        cmd,
        cwd=PROJECT_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    raw_path = os.path.join(ir_dir, f"{name}__{group}__raw_ir_dump.txt")
    with open(raw_path, "w", encoding="utf-8") as f:
        f.write((r.stdout or "") + "\n")
        f.write(r.stderr or "")

    if r.returncode != 0:
        logf.write(f"[IRSampleError] rustc failed for {name} ({group})\n")
        logf.write((r.stderr or "").strip() + "\n")
        logf.flush()
        return False, "", 0, False

    wanted = ["iterator_pipeline_bench", "kernel_", "step_", "zip", "fold", "sum"]
    filtered = extract_ir_blocks(r.stderr or "", wanted)
    filtered_path = os.path.join(ir_dir, f"{name}__{group}__filtered_ir_dump.txt")
    with open(filtered_path, "w", encoding="utf-8") as f:
        f.write(filtered)

    remarks = "\n".join([ln for ln in (r.stderr or "").splitlines() if ln.startswith("remark:")])
    remarks_path = os.path.join(ir_dir, f"{name}__{group}__vectorize_remarks.txt")
    with open(remarks_path, "w", encoding="utf-8") as f:
        f.write(remarks + ("\n" if remarks else ""))

    remark_count = 0
    vectorized = False
    if remarks:
        remark_count = remarks.count("\n") + 1
        vectorized = "vectorized loop" in remarks

    logf.write(f"[IRSampleSaved] raw={raw_path} filtered={filtered_path} remarks={remarks_path}\n")
    logf.flush()
    return True, remarks_path, remark_count, vectorized


def analyze_mir_text(text):
    bb_count = 0
    locals_seen = set()

    for ln in text.splitlines():
        s = ln.strip()
        if s.startswith("fn ") and "->" in s:
            for m in re.finditer(r"(_[0-9]+):", s):
                locals_seen.add(m.group(1))
        m_let = re.search(r"\blet(?:\s+mut)?\s+(_[0-9]+):", s)
        if m_let:
            locals_seen.add(m_let.group(1))

        if re.match(r"^bb[0-9]+:", s):
            bb_count += 1

    return bb_count, len(locals_seen)


def find_ll_file_with_substring(needle):
    deps_dir = os.path.join(PROJECT_ROOT, "target", "release", "deps")
    if not os.path.isdir(deps_dir):
        return ""
    candidates = []
    for name in os.listdir(deps_dir):
        if not name.endswith(".ll"):
            continue
        if not (name.startswith("iterator_pipeline_bench-") or name.startswith("iterator_pipeline-")):
            continue
        path = os.path.join(deps_dir, name)
        if not os.path.isfile(path):
            continue
        try:
            mtime = os.path.getmtime(path)
        except Exception:
            mtime = 0
        candidates.append((mtime, path))
    if not candidates:
        return ""
    candidates.sort(reverse=True)
    for _, path in candidates:
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                chunk = f.read(512 * 1024)
            if needle in chunk:
                return path
        except Exception:
            continue
    return candidates[0][1]


def extract_llvm_function_blocks(ll_text, name_substring):
    blocks = []
    lines = ll_text.splitlines(True)
    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("define ") and name_substring in ln:
            cur = [ln]
            i += 1
            while i < len(lines):
                cur.append(lines[i])
                if lines[i].strip() == "}":
                    break
                i += 1
            blocks.append("".join(cur))
        i += 1
    return blocks


def analyze_llvm_ir_for_vectorization(ll_text, kernel_name):
    blocks = extract_llvm_function_blocks(ll_text, kernel_name)
    if not blocks:
        return {"LLVMIR_Vectorized": "", "LLVMIR_VectorWidth": 0}

    vectorized = False
    max_width = 0
    for b in blocks:
        if "vector.body" in b:
            vectorized = True
        for m in re.finditer(r"<\\s*([0-9]+)\\s+x\\s+i32\\s*>", b):
            try:
                w = int(m.group(1))
                if w > max_width:
                    max_width = w
            except Exception:
                pass
        for m in re.finditer(r"<\\s*([0-9]+)\\s+x\\s+i64\\s*>", b):
            try:
                w = int(m.group(1))
                if w > max_width:
                    max_width = w
            except Exception:
                pass
    return {"LLVMIR_Vectorized": "1" if vectorized else "0", "LLVMIR_VectorWidth": max_width}


def dump_llvm_ir_sample(combo, base_out, logf):
    name = combo.get("name") or combo.get("Experiment_ID") or "Unknown"
    group = combo.get("group") or "Matrix"

    out_dir = os.path.join(base_out, "llvm_ir_samples", f"{name}__{group}")
    os.makedirs(out_dir, exist_ok=True)

    env = os.environ.copy()
    cargo_bin = os.path.expanduser("~/.cargo/bin")
    if cargo_bin and cargo_bin not in env.get("PATH", ""):
        env["PATH"] = f"{cargo_bin}:{env.get('PATH', '')}"

    extra = [
        "-Z unstable-options",
        "-C symbol-mangling-version=legacy",
    ]
    rustflags = compose_rustflags_from_combo(combo) + " " + " ".join(extra)
    env["RUSTFLAGS"] = rustflags

    msg = f"[LLVMSample] {name} ({group})"
    print(msg)
    logf.write(msg + "\n")
    logf.flush()

    clean_project(env)
    r = subprocess.run(
        ["cargo", "+nightly", "rustc", "--release", "--lib", "--quiet", "--", "--emit=llvm-ir"],
        cwd=PROJECT_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    build_log_path = os.path.join(out_dir, "build_log.txt")
    with open(build_log_path, "w", encoding="utf-8") as f:
        f.write((r.stdout or "") + "\n")
        f.write(r.stderr or "")

    if r.returncode != 0:
        logf.write(f"[LLVMSampleError] build failed for {name} ({group})\n")
        logf.flush()
        return {}, ""

    ll_path = find_ll_file_with_substring("kernel_easy")
    if not ll_path:
        logf.write(f"[LLVMSampleError] no .ll produced for {name} ({group})\n")
        logf.flush()
        return {}, ""

    dst = os.path.join(out_dir, os.path.basename(ll_path))
    shutil.copy2(ll_path, dst)
    try:
        with open(dst, "r", encoding="utf-8", errors="replace") as f:
            ll_text = f.read()
    except Exception:
        return {}, dst

    metrics = {}
    for case, kernel in DEFAULT_KERNELS.items():
        metrics[case] = analyze_llvm_ir_for_vectorization(ll_text, kernel)

    metrics_path = os.path.join(out_dir, "llvm_ir_metrics.json")
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)

    logf.write(f"[LLVMSampleSaved] dir={out_dir}\n")
    logf.flush()
    return metrics, dst


def select_mir_file(mir_dir, kernel_name):
    if not os.path.isdir(mir_dir):
        return ""
    prefix = f"iterator_pipeline_bench.{kernel_name}."
    preferred_suffixes = [
        "3-3-000.runtime-optimized.after.mir",
        "runtime-optimized.after.mir",
        "PreCodegen.after.mir",
    ]

    names = [n for n in os.listdir(mir_dir) if n.startswith(prefix) and n.endswith(".mir")]
    if not names:
        return ""

    for suf in preferred_suffixes:
        matches = [n for n in names if n.endswith(suf)]
        if matches:
            matches.sort()
            return os.path.join(mir_dir, matches[-1])

    names.sort()
    return os.path.join(mir_dir, names[-1])


def dump_mir_sample(combo, bench_name, base_out, logf):
    name = combo.get("name") or combo.get("Experiment_ID") or "Unknown"
    group = combo.get("group") or "Matrix"

    base_dir = os.path.join(base_out, "mir_samples", f"{name}__{group}")
    os.makedirs(base_dir, exist_ok=True)
    tmp_dir = os.path.join(base_dir, "mir_dump")
    if os.path.exists(tmp_dir):
        shutil.rmtree(tmp_dir, ignore_errors=True)
    os.makedirs(tmp_dir, exist_ok=True)

    env = os.environ.copy()
    cargo_bin = os.path.expanduser("~/.cargo/bin")
    if cargo_bin and cargo_bin not in env.get("PATH", ""):
        env["PATH"] = f"{cargo_bin}:{env.get('PATH', '')}"

    extra = [
        "-Z dump-mir=all",
        f"-Z dump-mir-dir={tmp_dir}",
    ]
    rustflags = compose_rustflags_from_combo(combo) + " " + " ".join(extra)
    env["RUSTFLAGS"] = rustflags

    msg = f"[MIRSample] {name} ({group})"
    print(msg)
    logf.write(msg + "\n")
    logf.flush()

    clean_project(env)
    cmd = ["cargo", "+nightly", "bench", "--bench", bench_name, "--no-run", "--quiet"]
    r = subprocess.run(
        cmd,
        cwd=PROJECT_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    build_log_path = os.path.join(base_dir, "build_log.txt")
    with open(build_log_path, "w", encoding="utf-8") as f:
        f.write((r.stdout or "") + "\n")
        f.write(r.stderr or "")

    if r.returncode != 0:
        logf.write(f"[MIRSampleError] rustc failed for {name} ({group})\n")
        logf.flush()
        return {}

    metrics = {}
    for case, kernel in DEFAULT_KERNELS.items():
        src = select_mir_file(tmp_dir, kernel)
        if not src:
            metrics[case] = {"Kernel": kernel, "MIRPath": "", "MIR_BBCount": 0, "MIR_LocalCount": 0}
            continue

        dst = os.path.join(base_dir, os.path.basename(src))
        shutil.copy2(src, dst)
        try:
            with open(dst, "r", encoding="utf-8", errors="replace") as f:
                text = f.read()
            bb_count, local_count = analyze_mir_text(text)
        except Exception:
            bb_count, local_count = 0, 0

        metrics[case] = {"Kernel": kernel, "MIRPath": dst, "MIR_BBCount": bb_count, "MIR_LocalCount": local_count}

    metrics_path = os.path.join(base_dir, "mir_metrics.json")
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)

    logf.write(f"[MIRSampleSaved] dir={base_dir}\n")
    logf.flush()
    return metrics


def measure_combination(
    combo,
    runs,
    bench_name,
    bench_filters,
    bench_repeat,
    logf,
    remarks_by_name=None,
    mir_by_name_case=None,
    llvm_ir_by_name_case=None,
    runner="bin",
    bin_len=1048576,
    bin_iters=6000,
    bin_seed=0,
    target_runtime_s=0.0,
):
    name = combo.get("name") or combo.get("Experiment_ID") or "Unknown"
    group = combo.get("group") or "Matrix"

    mir_pass = "N/A"
    if combo.get("mir"):
        if isinstance(combo["mir"], dict):
            mir_pass = combo["mir"].get("pass", "N/A")
        else:
            mir_pass = str(combo["mir"])

    llvm_pass = "None"
    if combo.get("llvm"):
        if isinstance(combo["llvm"], dict):
            llvm_pass = combo["llvm"].get("pass", "None")
        else:
            llvm_pass = str(combo["llvm"])

    env = os.environ.copy()
    cargo_bin = os.path.expanduser("~/.cargo/bin")
    if cargo_bin and cargo_bin not in env.get("PATH", ""):
        env["PATH"] = f"{cargo_bin}:{env.get('PATH', '')}"

    rustflags = compose_rustflags_from_combo(combo)
    env["RUSTFLAGS"] = rustflags

    total_iters = runs + 1
    rows = []
    calibrated_iters = {}
    for n in range(total_iters):
        is_warmup = (n == 0)
        run_id = n

        msg1 = f"[Exp] {name} Warmup 1/1" if is_warmup else f"[Exp] {name} Iteration {run_id}/{runs}"
        msg2 = f"[Flags] {rustflags}"
        msg3 = f"[Bench] {bench_name}::{','.join(bench_filters)} x{bench_repeat}"
        print(msg1)
        print(msg2)
        print(msg3)
        logf.write(msg1 + "\n")
        logf.write(msg2 + "\n")
        logf.write(msg3 + "\n")
        logf.flush()

        clean_project(env)

        t0 = time.perf_counter()
        if runner == "bin":
            ok, status, build_err, _, _ = build_release_bin(env, logf)
        else:
            ok, status, build_err, _, _ = build_bench(env, bench_name, logf)
        t1 = time.perf_counter()
        compile_time = t1 - t0

        if not ok:
            if is_warmup:
                logf.write(f"[SkipConfig] Warmup build failed: {status}\n")
                if build_err:
                    logf.write("[BuildError] " + build_err + "\n")
                logf.flush()
                break

            for bench_filter in bench_filters:
                remark_info = (remarks_by_name or {}).get(name, {})
                mir_info = (mir_by_name_case or {}).get((name, bench_filter), {})
                rows.append(
                    {
                        "ConfigName": name,
                        "Group": group,
                        "Case": bench_filter,
                        "RunID": run_id,
                        "LLVM_Pass": llvm_pass,
                        "MIR_Pass": mir_pass,
                        "BinarySize(Bytes)": 0,
                        "NsPerIter": "",
                        "MBps": "",
                        "TotalRuntime(s)": 0,
                        "CompileTime(s)": f"{compile_time:.6f}",
                        "VectorizeRemarkCount": remark_info.get("VectorizeRemarkCount", 0),
                        "Vectorized": remark_info.get("Vectorized", ""),
                        "MIR_BBCount": mir_info.get("MIR_BBCount", 0),
                        "MIR_LocalCount": mir_info.get("MIR_LocalCount", 0),
                        "Status": status,
                    }
                )
            break

        if runner == "bin":
            exe_path = find_release_bin(DEFAULT_BIN_NAME)
        else:
            exe_path = find_bench_exe(bench_name)
        if not exe_path:
            if is_warmup:
                logf.write("[SkipConfig] Warmup produced no bench binary\n")
                logf.flush()
                break
            for bench_filter in bench_filters:
                remark_info = (remarks_by_name or {}).get(name, {})
                mir_info = (mir_by_name_case or {}).get((name, bench_filter), {})
                rows.append(
                    {
                        "ConfigName": name,
                        "Group": group,
                        "Case": bench_filter,
                        "RunID": run_id,
                        "LLVM_Pass": llvm_pass,
                        "MIR_Pass": mir_pass,
                        "BinarySize(Bytes)": 0,
                        "NsPerIter": "",
                        "MBps": "",
                        "TotalRuntime(s)": 0,
                        "CompileTime(s)": f"{compile_time:.6f}",
                        "VectorizeRemarkCount": remark_info.get("VectorizeRemarkCount", 0),
                        "Vectorized": remark_info.get("Vectorized", ""),
                        "MIR_BBCount": mir_info.get("MIR_BBCount", 0),
                        "MIR_LocalCount": mir_info.get("MIR_LocalCount", 0),
                        "Status": "NoBinary",
                    }
                )
            break

        try:
            size = os.path.getsize(exe_path)
        except Exception:
            size = 0

        for bench_filter in bench_filters:
            if runner == "bin":
                mode = "easy" if bench_filter == "easy_case" else "mir-dependent"
                iters_to_use = bin_iters
                if target_runtime_s and target_runtime_s > 0.0:
                    key = (name, bench_filter)
                    if key in calibrated_iters:
                        iters_to_use = calibrated_iters[key]
                    else:
                        probe_wall, probe_ns, _, probe_err = run_bin_case(
                            exe_path,
                            mode=mode,
                            length=bin_len,
                            iters=bin_iters,
                            seed=bin_seed,
                            repeat=1,
                        )
                        if probe_wall is None:
                            wall_time, ns_per_iter, mbps, run_err = (None, "", "", probe_err)
                            iters_to_use = bin_iters
                        else:
                            iters_to_use = choose_iters_for_target(probe_ns, bin_iters, target_runtime_s)
                            calibrated_iters[key] = iters_to_use
                wall_time, ns_per_iter, mbps, run_err = run_bin_case(
                    exe_path,
                    mode=mode,
                    length=bin_len,
                    iters=iters_to_use,
                    seed=bin_seed,
                    repeat=bench_repeat,
                )
            else:
                wall_time, ns_per_iter, mbps, run_err = run_benchmark(exe_path, bench_filter, bench_repeat)
            if wall_time is None:
                if run_err:
                    logf.write(f"[RunError:{bench_filter}] " + run_err + "\n")
                    logf.flush()
                if is_warmup:
                    logf.write(f"[SkipConfig] Warmup run failed for {bench_filter}\n")
                    logf.flush()
                    return rows
                remark_info = (remarks_by_name or {}).get(name, {})
                mir_info = (mir_by_name_case or {}).get((name, bench_filter), {})
                llvm_info = (llvm_ir_by_name_case or {}).get((name, bench_filter), {})
                rows.append(
                    {
                        "ConfigName": name,
                        "Group": group,
                        "Case": bench_filter,
                        "RunID": run_id,
                        "LLVM_Pass": llvm_pass,
                        "MIR_Pass": mir_pass,
                        "BinarySize(Bytes)": size,
                        "NsPerIter": "",
                        "MBps": "",
                        "TotalRuntime(s)": 0,
                        "CompileTime(s)": f"{compile_time:.6f}",
                        "VectorizeRemarkCount": remark_info.get("VectorizeRemarkCount", 0),
                        "Vectorized": remark_info.get("Vectorized", ""),
                        "MIR_BBCount": mir_info.get("MIR_BBCount", 0),
                        "MIR_LocalCount": mir_info.get("MIR_LocalCount", 0),
                        "LLVMIR_Vectorized": llvm_info.get("LLVMIR_Vectorized", ""),
                        "LLVMIR_VectorWidth": llvm_info.get("LLVMIR_VectorWidth", 0),
                        "Status": "RunFailed",
                    }
                )
                continue

            if is_warmup:
                print(
                    f"[WarmupResult:{bench_filter}] Size={size}B, Compile={compile_time:.6f}s, Wall={wall_time:.6f}s, NsPerIter={ns_per_iter}, MBps={mbps}"
                )
                continue

            print(
                f"[Result:{bench_filter}] Size={size}B, Compile={compile_time:.6f}s, Wall={wall_time:.6f}s, NsPerIter={ns_per_iter}, MBps={mbps}"
            )
            remark_info = (remarks_by_name or {}).get(name, {})
            mir_info = (mir_by_name_case or {}).get((name, bench_filter), {})
            llvm_info = (llvm_ir_by_name_case or {}).get((name, bench_filter), {})
            rows.append(
                {
                    "ConfigName": name,
                    "Group": group,
                    "Case": bench_filter,
                    "RunID": run_id,
                    "LLVM_Pass": llvm_pass,
                    "MIR_Pass": mir_pass,
                    "BinarySize(Bytes)": size,
                    "NsPerIter": ns_per_iter,
                    "MBps": mbps,
                    "TotalRuntime(s)": f"{wall_time:.6f}",
                    "CompileTime(s)": f"{compile_time:.6f}",
                    "VectorizeRemarkCount": remark_info.get("VectorizeRemarkCount", 0),
                    "Vectorized": remark_info.get("Vectorized", ""),
                    "MIR_BBCount": mir_info.get("MIR_BBCount", 0),
                    "MIR_LocalCount": mir_info.get("MIR_LocalCount", 0),
                    "LLVMIR_Vectorized": llvm_info.get("LLVMIR_Vectorized", ""),
                    "LLVMIR_VectorWidth": llvm_info.get("LLVMIR_VectorWidth", 0),
                    "Status": "Success",
                }
            )

    return rows


def write_interaction_summary(results_csv, out_path):
    wanted_groups = ["Baseline", "No-MIR-Lowering", "No-LLVM-Vectorize", "Dual-disable"]
    data = {}

    with open(results_csv, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("Status") != "Success":
                continue
            run_id = row.get("RunID", "")
            if str(run_id).strip() in {"0", ""}:
                continue
            group = row.get("Group", "")
            if group not in wanted_groups:
                continue
            case = row.get("Case", "")
            ns = row.get("NsPerIter", "")
            try:
                ns_f = float(ns)
            except Exception:
                continue
            data.setdefault((case, group), []).append(ns_f)

    def mean(xs):
        return sum(xs) / len(xs) if xs else None

    rows = []
    for case in sorted({k[0] for k in data.keys()}):
        t00 = mean(data.get((case, "Baseline"), []))
        t10 = mean(data.get((case, "No-MIR-Lowering"), []))
        t01 = mean(data.get((case, "No-LLVM-Vectorize"), []))
        t11 = mean(data.get((case, "Dual-disable"), []))
        if t00 is None or t10 is None or t01 is None or t11 is None:
            continue
        interaction = (t11 - t01) - (t10 - t00)
        rows.append(
            {
                "Case": case,
                "T00_Baseline(ns/iter)": f"{t00:.3f}",
                "T10_NoMIR(ns/iter)": f"{t10:.3f}",
                "T01_NoLLVMVec(ns/iter)": f"{t01:.3f}",
                "T11_Dual(ns/iter)": f"{t11:.3f}",
                "I(ns/iter)": f"{interaction:.3f}",
            }
        )

    if not rows:
        return False

    with open(out_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "Case",
                "T00_Baseline(ns/iter)",
                "T10_NoMIR(ns/iter)",
                "T01_NoLLVMVec(ns/iter)",
                "T11_Dual(ns/iter)",
                "I(ns/iter)",
            ],
        )
        writer.writeheader()
        for r in rows:
            writer.writerow(r)
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json-path", default=DEFAULT_JSON_PATH)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--bench-name", default=DEFAULT_BENCH_NAME)
    parser.add_argument("--bench-repeat", type=int, default=1)
    parser.add_argument("--runner", choices=["bench", "bin"], default="bin")
    parser.add_argument("--len", type=int, default=1048576)
    parser.add_argument("--iters", type=int, default=6000)
    parser.add_argument("--seed", type=int, default=305419896)
    parser.add_argument("--target-runtime-s", type=float, default=0.0)
    parser.add_argument("--core4", action="store_true")
    parser.add_argument("--ir-sample-count", type=int, default=-1)
    parser.add_argument("--ir-passes", default="loop-vectorize")
    parser.add_argument("--collect-remarks", action="store_true")
    parser.add_argument("--collect-mir", action="store_true")
    parser.add_argument("--collect-llvm-ir", action="store_true")
    args = parser.parse_args()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_out = args.output_dir or os.path.join(PROJECT_ROOT, "mir_llvm_hybrid_py", ts)
    os.makedirs(base_out, exist_ok=True)

    results_csv = os.path.join(base_out, "experiment_results.csv")
    exec_log = os.path.join(base_out, "experiment_execution.log")
    interaction_csv = os.path.join(base_out, "interaction_summary.csv")

    if args.core4:
        combos = get_core4_combinations()
    else:
        if not os.path.exists(args.json_path):
            print(f"Error: JSON path {args.json_path} does not exist.")
            return
        combos = get_combinations(args.json_path)
    if args.start > 0:
        combos = combos[args.start:]
    if args.limit and args.limit > 0:
        combos = combos[: args.limit]

    with open(exec_log, "w", encoding="utf-8") as logf:
        print(f"Total Rows: {len(combos)}")
        logf.write(f"Total Rows: {len(combos)}\n")
        logf.flush()

        if args.core4:
            if not args.collect_remarks:
                args.collect_remarks = True
            if not args.collect_mir:
                args.collect_mir = True
            if not args.collect_llvm_ir:
                args.collect_llvm_ir = True

        ir_passes = [p.strip() for p in args.ir_passes.split(",") if p.strip()]
        sample_count = args.ir_sample_count
        if sample_count < 0:
            sample_count = 4 if args.core4 else 0
        for combo in combos[:sample_count]:
            dump_ir_sample(combo, args.bench_name, base_out, logf, ir_passes)

        remarks_by_name = {}
        if args.collect_remarks:
            for combo in combos:
                name = combo.get("name") or combo.get("Experiment_ID") or "Unknown"
                if name in remarks_by_name:
                    continue
                ok, _, remark_count, vectorized = dump_ir_sample(combo, args.bench_name, base_out, logf, [])
                if ok:
                    remarks_by_name[name] = {
                        "VectorizeRemarkCount": remark_count,
                        "Vectorized": "1" if vectorized else "0",
                    }
                else:
                    remarks_by_name[name] = {"VectorizeRemarkCount": 0, "Vectorized": ""}

        mir_by_name_case = {}
        if args.collect_mir:
            for combo in combos:
                name = combo.get("name") or combo.get("Experiment_ID") or "Unknown"
                group = combo.get("group") or "Matrix"
                msg = f"[MIRMetrics] {name} ({group})"
                print(msg)
                logf.write(msg + "\n")
                logf.flush()
                metrics = dump_mir_sample(combo, args.bench_name, base_out, logf)
                for case, d in metrics.items():
                    mir_by_name_case[(name, case)] = {
                        "MIR_BBCount": d.get("MIR_BBCount", 0),
                        "MIR_LocalCount": d.get("MIR_LocalCount", 0),
                    }

        llvm_ir_by_name_case = {}
        if args.collect_llvm_ir:
            for combo in combos:
                name = combo.get("name") or combo.get("Experiment_ID") or "Unknown"
                group = combo.get("group") or "Matrix"
                msg = f"[LLVMIRMetrics] {name} ({group})"
                print(msg)
                logf.write(msg + "\n")
                logf.flush()
                metrics, _ = dump_llvm_ir_sample(combo, base_out, logf)
                for case, d in metrics.items():
                    llvm_ir_by_name_case[(name, case)] = {
                        "LLVMIR_Vectorized": d.get("LLVMIR_Vectorized", ""),
                        "LLVMIR_VectorWidth": d.get("LLVMIR_VectorWidth", 0),
                    }

        with open(results_csv, "w", encoding="utf-8", newline="") as outcsv:
            writer = csv.DictWriter(
                outcsv,
                fieldnames=[
                    "ConfigName",
                    "Group",
                    "Case",
                    "RunID",
                    "LLVM_Pass",
                    "MIR_Pass",
                    "BinarySize(Bytes)",
                    "NsPerIter",
                    "MBps",
                    "TotalRuntime(s)",
                    "CompileTime(s)",
                    "VectorizeRemarkCount",
                    "Vectorized",
                    "MIR_BBCount",
                    "MIR_LocalCount",
                    "LLVMIR_Vectorized",
                    "LLVMIR_VectorWidth",
                    "Status",
                ],
            )
            writer.writeheader()
            outcsv.flush()

            for combo in combos:
                rows = measure_combination(
                    combo,
                    args.runs,
                    args.bench_name,
                    DEFAULT_BENCH_FILTERS,
                    args.bench_repeat,
                    logf,
                    remarks_by_name=remarks_by_name,
                    mir_by_name_case=mir_by_name_case,
                    llvm_ir_by_name_case=llvm_ir_by_name_case,
                    runner=args.runner,
                    bin_len=args.len,
                    bin_iters=args.iters,
                    bin_seed=args.seed,
                    target_runtime_s=args.target_runtime_s,
                )
                for row in rows:
                    writer.writerow(row)
                outcsv.flush()

        if args.core4:
            ok = write_interaction_summary(results_csv, interaction_csv)
            if ok:
                print(f"[Interaction] saved: {interaction_csv}")
                logf.write(f"[Interaction] saved: {interaction_csv}\n")
                logf.flush()


if __name__ == "__main__":
    main()
