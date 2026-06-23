"""Parse /input/spec.yaml -> OpenMS design.tsv and shell exports.
Runs in-container (python3 /work/lib/spec.py ...) and is host-unit-tested."""
import sys

import yaml


def load_spec(path):
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def design_tsv(spec) -> str:
    header = ("Fraction_Group\tFraction\tSpectra_Filepath\tLabel\t"
              "Sample\tMSstats_Condition\tMSstats_BioReplicate")
    rows = [header]
    i = 0
    conditions = spec["design"]["conditions"]
    for cond, reps in conditions.items():
        for rep, files in reps.items():
            for fname in files:
                i += 1
                path = f"/input/{fname}"
                rows.append(f"{i}\t1\t{path}\t1\t{i}\t{cond}\t{cond}_{rep}")
    return "\n".join(rows) + "\n"


def shell_exports(spec) -> str:
    tol = spec["tolerances"]
    lines = [
        f"export PREC_TOL_PPM={tol['precursor_ppm']}",
        f"export FRAG_TOL_DA={tol['fragment_da']}",
        f"export FASTA=/input/{spec['fasta']}",
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    mode, path = sys.argv[1], sys.argv[2]
    spec = load_spec(path)
    if mode == "--design":
        sys.stdout.write(design_tsv(spec))
    elif mode == "--shell":
        sys.stdout.write(shell_exports(spec))
    else:
        sys.exit(f"unknown mode {mode!r}")
