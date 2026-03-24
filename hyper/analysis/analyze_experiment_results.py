import os


HYPER_EXPERIMENT_CSV = r"d:\MIR_LLVM\mir_-llvm\hyper\mir_llvm_hybrid_py\20260319_180449\experiment_results.csv"


def _load_shared_analyzer() -> dict:
    here = os.path.dirname(os.path.abspath(__file__))
    shared = os.path.abspath(os.path.join(here, "..", "..", "ripgrep", "analysis", "analyze_experiment_results.py"))
    g = {"__name__": "_shared_analyze_experiment_results", "__file__": os.path.abspath(__file__)}
    with open(shared, "r", encoding="utf-8") as f:
        code = f.read()
    exec(compile(code, shared, "exec"), g)
    return g


def main() -> int:
    g = _load_shared_analyzer()
    shared_main = g.get("main")
    if not callable(shared_main):
        raise RuntimeError("shared analyze_experiment_results.py does not define main()")
    return int(
        shared_main(
            [
                "--input",
                HYPER_EXPERIMENT_CSV,
            ]
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
