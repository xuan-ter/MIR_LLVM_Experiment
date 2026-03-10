import argparse
import csv
import json
import math
import os
import random
from dataclasses import dataclass
from typing import Dict, Iterable, List, Sequence, Set, Tuple


@dataclass(frozen=True)
class Candidate:
    disabled_mir: Tuple[str, ...]
    disabled_llvm: Tuple[str, ...]

    def key(self) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
        return (self.disabled_mir, self.disabled_llvm)


def load_pass_list(csv_path: str, column: str) -> List[str]:
    vals: List[str] = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            v = str(row.get(column, "")).strip()
            if not v or v.lower() == "nan":
                continue
            vals.append(v)
    seen: Set[str] = set()
    out: List[str] = []
    for v in vals:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def load_baseline_metrics(baseline_csv: str) -> Dict[str, float]:
    runtime_sum = 0.0
    compile_sum = 0.0
    size_sum = 0.0
    n = 0
    with open(baseline_csv, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            if row.get("Status") != "Success":
                continue
            try:
                runtime = float(row.get("TotalRuntime(s)", "0") or 0)
                compile_time = float(row.get("CompileTime(s)", "0") or 0)
                size = float(row.get("BinarySize(Bytes)", "0") or 0)
            except ValueError:
                continue
            if runtime <= 0 or compile_time <= 0 or size <= 0:
                continue
            runtime_sum += runtime
            compile_sum += compile_time
            size_sum += size
            n += 1
    if n == 0:
        raise RuntimeError(f"No valid baseline rows found in {baseline_csv}")
    runtime = runtime_sum / n
    compile_time = compile_sum / n
    size = size_sum / n
    return {"runtime": runtime, "compile_time": compile_time, "size": size}


def load_main_effects(
    results_csv: str,
    pass_column: str,
    baseline: Dict[str, float],
    allowed_passes: Set[str],
) -> Dict[str, Dict[str, float]]:
    sums: Dict[str, Dict[str, float]] = {}
    counts: Dict[str, int] = {}
    with open(results_csv, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            if row.get("Status") != "Success":
                continue
            pass_name = str(row.get(pass_column, "")).strip()
            if not pass_name or pass_name.lower() == "nan":
                continue
            if pass_name not in allowed_passes:
                continue
            try:
                runtime = float(row.get("TotalRuntime(s)", "0") or 0)
                compile_time = float(row.get("CompileTime(s)", "0") or 0)
                size = float(row.get("BinarySize(Bytes)", "0") or 0)
            except ValueError:
                continue
            if runtime <= 0 or compile_time <= 0 or size <= 0:
                continue

            if pass_name not in sums:
                sums[pass_name] = {"runtime": 0.0, "compile_time": 0.0, "size": 0.0}
                counts[pass_name] = 0
            sums[pass_name]["runtime"] += runtime
            sums[pass_name]["compile_time"] += compile_time
            sums[pass_name]["size"] += size
            counts[pass_name] += 1

    effects: Dict[str, Dict[str, float]] = {}
    for pass_name, c in counts.items():
        if c <= 0:
            continue
        r_mean = sums[pass_name]["runtime"] / c
        c_mean = sums[pass_name]["compile_time"] / c
        s_mean = sums[pass_name]["size"] / c
        effects[pass_name] = {
            "log_runtime": math.log(r_mean) - math.log(baseline["runtime"]),
            "log_compile_time": math.log(c_mean) - math.log(baseline["compile_time"]),
            "log_size": math.log(s_mean) - math.log(baseline["size"]),
        }
    return effects


def load_coupling_edges(
    edges_csv: str,
    mir_passes: Set[str],
    llvm_passes: Set[str],
    min_stability: float,
) -> List[Tuple[str, str, float, float]]:
    out: List[Tuple[str, str, float, float]] = []
    with open(edges_csv, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            src = str(row.get("Source", "")).strip()
            tgt = str(row.get("Target", "")).strip()
            try:
                w = float(row.get("Weight", "nan"))
                s = float(row.get("Stability", "nan"))
            except ValueError:
                continue
            if not src or not tgt:
                continue
            if s < min_stability:
                continue
            if src not in mir_passes:
                continue
            if tgt not in llvm_passes:
                continue
            out.append((src, tgt, w, s))
    return out


def connected_components(nodes: Iterable[str], edges: Iterable[Tuple[str, str]]) -> List[Set[str]]:
    adj: Dict[str, Set[str]] = {n: set() for n in nodes}
    for a, b in edges:
        if a not in adj or b not in adj:
            continue
        adj[a].add(b)
        adj[b].add(a)

    seen: Set[str] = set()
    comps: List[Set[str]] = []
    for n in adj:
        if n in seen:
            continue
        stack = [n]
        comp: Set[str] = set()
        seen.add(n)
        while stack:
            cur = stack.pop()
            comp.add(cur)
            for nb in adj[cur]:
                if nb not in seen:
                    seen.add(nb)
                    stack.append(nb)
        comps.append(comp)
    comps.sort(key=lambda c: (-len(c), sorted(c)[0] if c else ""))
    return comps


def sample_candidate(
    rng: random.Random,
    mir_passes: Sequence[str],
    llvm_passes: Sequence[str],
    edges: Sequence[Tuple[str, str, float, float]],
    edge_weights: Sequence[float],
    max_pairs: int,
    extra_single_flips: int,
) -> Candidate:
    disabled_mir: Set[str] = set()
    disabled_llvm: Set[str] = set()

    n_pairs = rng.randint(0, max_pairs)
    for _ in range(n_pairs):
        src, tgt, _, _ = rng.choices(edges, weights=edge_weights, k=1)[0]
        if rng.random() < 0.5:
            disabled_mir.add(src)
        if rng.random() < 0.5:
            disabled_llvm.add(tgt)
        if rng.random() < 0.35:
            disabled_mir.add(src)
            disabled_llvm.add(tgt)

    for _ in range(extra_single_flips):
        if rng.random() < 0.5 and mir_passes:
            disabled_mir.add(rng.choice(mir_passes))
        elif llvm_passes:
            disabled_llvm.add(rng.choice(llvm_passes))

    return Candidate(
        disabled_mir=tuple(sorted(disabled_mir)),
        disabled_llvm=tuple(sorted(disabled_llvm)),
    )


def evaluate_candidate(
    cand: Candidate,
    baseline: Dict[str, float],
    mir_effects: Dict[str, Dict[str, float]],
    llvm_effects: Dict[str, Dict[str, float]],
    coupling: Dict[Tuple[str, str], float],
) -> Dict[str, float]:
    log_runtime = math.log(baseline["runtime"])
    log_compile = math.log(baseline["compile_time"])
    log_size = math.log(baseline["size"])

    for p in cand.disabled_mir:
        eff = mir_effects.get(p)
        if eff is not None:
            log_runtime += eff["log_runtime"]
            log_compile += eff["log_compile_time"]
            log_size += eff["log_size"]

    for p in cand.disabled_llvm:
        eff = llvm_effects.get(p)
        if eff is not None:
            log_runtime += eff["log_runtime"]
            log_compile += eff["log_compile_time"]
            log_size += eff["log_size"]

    for m in cand.disabled_mir:
        for l in cand.disabled_llvm:
            w = coupling.get((m, l))
            if w is not None:
                log_runtime += w

    return {
        "log_runtime": log_runtime,
        "log_compile_time": log_compile,
        "log_size": log_size,
        "runtime": math.exp(log_runtime),
        "compile_time": math.exp(log_compile),
        "size": math.exp(log_size),
    }


def pareto_front(rows: List[Dict[str, float]], objectives: Sequence[str]) -> List[int]:
    idxs = list(range(len(rows)))
    front: List[int] = []
    for i in idxs:
        ri = rows[i]
        dominated = False
        for j in idxs:
            if i == j:
                continue
            rj = rows[j]
            if all(rj[o] <= ri[o] for o in objectives) and any(rj[o] < ri[o] for o in objectives):
                dominated = True
                break
        if not dominated:
            front.append(i)
    return front


def write_csv(path: str, fieldnames: List[str], rows: List[Dict[str, object]]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def write_modules_json(
    out_path: str,
    edges_csv: str,
    mir_set: Set[str],
    llvm_set: Set[str],
    edges: Sequence[Tuple[str, str, float, float]],
) -> None:
    nodes_from_edges: Set[str] = set()
    undirected_edges: List[Tuple[str, str]] = []
    for m, l, _, _ in edges:
        nodes_from_edges.add(m)
        nodes_from_edges.add(l)
        undirected_edges.append((m, l))

    comps = connected_components(nodes_from_edges, undirected_edges)
    modules: List[Dict[str, object]] = []
    for i, comp in enumerate(comps, 1):
        mir_in = sorted([p for p in comp if p in mir_set])
        llvm_in = sorted([p for p in comp if p in llvm_set])
        es: List[Dict[str, object]] = []
        comp_set = set(comp)
        for m, l, w, s in edges:
            if m in comp_set and l in comp_set:
                es.append(
                    {
                        "mir": m,
                        "llvm": l,
                        "w": abs(w),
                        "sign": 1 if w > 0 else -1,
                        "freq": s,
                    }
                )
        modules.append({"id": i, "mir": mir_in, "llvm": llvm_in, "edges": es})

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"source": edges_csv, "modules": modules}, f, ensure_ascii=False, indent=2)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--analysis-root", default="/mnt/fjx/Compiler_Experiment/analysis")
    ap.add_argument("--out-dir", default="/mnt/fjx/Compiler_Experiment/analysis/pareto_coupling_search/out")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--budget", type=int, default=6000)
    ap.add_argument("--min-stability", type=float, default=0.4)
    ap.add_argument("--max-pairs", type=int, default=10)
    ap.add_argument("--extra-single-flips", type=int, default=6)
    args = ap.parse_args()

    baseline_csv = os.path.join(args.analysis_root, "data", "baseline.csv")
    mir_results_csv = os.path.join(args.analysis_root, "data", "experiment_results_mir.csv")
    llvm_results_csv = os.path.join(args.analysis_root, "data", "experiment_results_llvm.csv")
    edges_csv_candidates = [
        os.path.join(args.analysis_root, "coupling_graph", "coupling_edges.csv"),
        os.path.join(args.analysis_root, "two", "lasso", "coupling_edges.csv"),
    ]
    edges_csv = next((p for p in edges_csv_candidates if os.path.exists(p)), edges_csv_candidates[0])

    mir_coverage_csv = os.path.join(args.analysis_root, "lasso", "results", "mir_coverage.csv")
    llvm_coverage_csv = os.path.join(args.analysis_root, "lasso", "results", "llvm_coverage.csv")

    mir_passes = load_pass_list(mir_coverage_csv, "MIR_Pass")
    llvm_passes = load_pass_list(llvm_coverage_csv, "LLVM_Pass")
    mir_set = set(mir_passes)
    llvm_set = set(llvm_passes)

    baseline = load_baseline_metrics(baseline_csv)
    mir_effects = load_main_effects(mir_results_csv, "MIR_Pass", baseline, mir_set)
    llvm_effects = load_main_effects(llvm_results_csv, "LLVM_Pass", baseline, llvm_set)

    edges = load_coupling_edges(edges_csv, mir_set, llvm_set, args.min_stability)
    coupling: Dict[Tuple[str, str], float] = {(m, l): w for (m, l, w, _) in edges}

    write_modules_json(
        out_path=os.path.join(args.out_dir, "modules.json"),
        edges_csv=edges_csv,
        mir_set=mir_set,
        llvm_set=llvm_set,
        edges=edges,
    )

    node_set: Set[str] = set(mir_passes) | set(llvm_passes)
    undirected_edges = [(m, l) for (m, l, _, _) in edges]
    comps = connected_components(node_set, undirected_edges)

    modules_rows: List[Dict[str, object]] = []
    for k, comp in enumerate(comps):
        mir_in = sorted([p for p in comp if p in mir_set])
        llvm_in = sorted([p for p in comp if p in llvm_set])
        modules_rows.append(
            {
                "module_id": k,
                "n_total": len(comp),
                "n_mir": len(mir_in),
                "n_llvm": len(llvm_in),
                "mir_passes": ";".join(mir_in),
                "llvm_passes": ";".join(llvm_in),
            }
        )
    write_csv(
        os.path.join(args.out_dir, "modules.csv"),
        ["module_id", "n_total", "n_mir", "n_llvm", "mir_passes", "llvm_passes"],
        modules_rows,
    )

    rng = random.Random(args.seed)
    edge_weights = [abs(w) * s for (_, _, w, s) in edges] if edges else [1.0]
    if not edge_weights:
        edge_weights = [1.0]

    seen: Set[Tuple[Tuple[str, ...], Tuple[str, ...]]] = set()
    candidates: List[Candidate] = [Candidate((), ())]
    seen.add(candidates[0].key())

    while len(candidates) < args.budget and edges:
        c = sample_candidate(
            rng=rng,
            mir_passes=mir_passes,
            llvm_passes=llvm_passes,
            edges=edges,
            edge_weights=edge_weights,
            max_pairs=args.max_pairs,
            extra_single_flips=args.extra_single_flips,
        )
        if c.key() in seen:
            continue
        seen.add(c.key())
        candidates.append(c)

    while len(candidates) < args.budget:
        disabled_mir = tuple(sorted([p for p in mir_passes if rng.random() < 0.1]))
        disabled_llvm = tuple(sorted([p for p in llvm_passes if rng.random() < 0.1]))
        c = Candidate(disabled_mir, disabled_llvm)
        if c.key() in seen:
            continue
        seen.add(c.key())
        candidates.append(c)

    rows: List[Dict[str, object]] = []
    metric_rows: List[Dict[str, float]] = []
    for cand in candidates:
        metrics = evaluate_candidate(cand, baseline, mir_effects, llvm_effects, coupling)
        metric_rows.append(metrics)
        rows.append(
            {
                "disabled_mir_count": len(cand.disabled_mir),
                "disabled_llvm_count": len(cand.disabled_llvm),
                "disabled_mir": ";".join(cand.disabled_mir),
                "disabled_llvm": ";".join(cand.disabled_llvm),
                **metrics,
            }
        )

    objectives = ["log_runtime", "log_compile_time", "log_size"]
    front_idxs = pareto_front(metric_rows, objectives)

    all_fields = [
        "disabled_mir_count",
        "disabled_llvm_count",
        "disabled_mir",
        "disabled_llvm",
        "runtime",
        "compile_time",
        "size",
        "log_runtime",
        "log_compile_time",
        "log_size",
    ]
    write_csv(os.path.join(args.out_dir, "candidates.csv"), all_fields, rows)

    front_rows = [rows[i] for i in front_idxs]
    front_rows.sort(key=lambda r: (float(r["runtime"]), float(r["compile_time"]), float(r["size"])))
    write_csv(os.path.join(args.out_dir, "pareto_front.csv"), all_fields, front_rows)

    meta = {
        "analysis_root": args.analysis_root,
        "edges_csv": edges_csv,
        "baseline_runtime": baseline["runtime"],
        "baseline_compile_time": baseline["compile_time"],
        "baseline_size": baseline["size"],
        "n_mir_passes": len(mir_passes),
        "n_llvm_passes": len(llvm_passes),
        "n_edges": len(edges),
        "min_stability": args.min_stability,
        "budget": len(candidates),
        "seed": args.seed,
        "max_pairs": args.max_pairs,
        "extra_single_flips": args.extra_single_flips,
        "n_front": len(front_rows),
    }
    write_csv(os.path.join(args.out_dir, "meta.csv"), list(meta.keys()), [meta])


if __name__ == "__main__":
    main()
