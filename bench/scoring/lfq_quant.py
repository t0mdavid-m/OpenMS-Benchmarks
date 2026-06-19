import csv
import math
import statistics
from collections import defaultdict
from pathlib import Path

from bench.datasets import Dataset
from bench.species import assign_species

Metric = tuple[str, float, str]


def score(out_dir: Path, dataset: Dataset) -> list[Metric]:
    gt = dataset.ground_truth
    # precursor key -> condition -> list of intensities (one per replicate)
    inten: dict[tuple[str, str], dict[str, list[float]]] = defaultdict(
        lambda: defaultdict(list))
    # precursor key -> set of species (to drop cross-species)
    prec_species: dict[tuple[str, str], set[str]] = defaultdict(set)
    proteins_seen: set[str] = set()

    with (Path(out_dir) / "quant.tsv").open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            try:
                intensity = float(row["intensity"])
            except (ValueError, KeyError):
                continue
            if intensity <= 0 or math.isnan(intensity):
                continue
            sp = assign_species(row["protein"], gt.exclude_regex, gt.suffix_map)
            if sp is None:
                continue
            key = (row["precursor"], row["charge"])
            prec_species[key].add(sp)
            inten[key][row["condition"]].append(intensity)
            proteins_seen.add(row["protein"])

    per_species_log2: dict[str, list[float]] = defaultdict(list)
    cv_values: list[float] = []
    n_quant = 0

    for key, conds in inten.items():
        species = prec_species[key]
        if len(species) != 1:
            continue  # cross-species, drop
        sp = next(iter(species))
        a = conds.get("A", [])
        b = conds.get("B", [])
        if not a or not b:
            continue  # require quant in both conditions
        n_quant += 1
        mean_a = statistics.fmean(a)
        mean_b = statistics.fmean(b)
        per_species_log2[sp].append(math.log2(mean_a / mean_b))
        for reps in (a, b):
            if len(reps) >= 2:
                m = statistics.fmean(reps)
                if m > 0:
                    cv_values.append(statistics.pstdev(reps) / m)

    metrics: list[Metric] = [
        ("num_precursors_quantified", float(n_quant), "count"),
        ("num_proteins", float(len(proteins_seen)), "count"),
    ]
    all_errors: list[float] = []
    for sp, observed in sorted(per_species_log2.items()):
        expected = gt.expected_log2.get(sp, 0.0)
        errors = [abs(o - expected) for o in observed]
        all_errors.extend(errors)
        metrics.append((f"median_log2_ratio_{sp}",
                        statistics.median(observed), "log2"))
        metrics.append((f"mean_abs_error_{sp}",
                        statistics.fmean(errors), "log2"))
    metrics.append(("mean_abs_error_overall",
                    statistics.fmean(all_errors) if all_errors else 0.0, "log2"))
    metrics.append(("median_intra_condition_cv",
                    statistics.median(cv_values) if cv_values else 0.0, "ratio"))
    return metrics
