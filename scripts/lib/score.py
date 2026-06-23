"""Self-scoring for the OpenMS family. Reads quant.tsv + spec.yaml, prints
`metric<TAB>value<TAB>unit` rows. Ported verbatim from bench/species.py and
bench/scoring/lfq_quant.py. Runs in-container; host-unit-tested."""
import csv
import math
import re
import statistics
import sys
from collections import defaultdict

import yaml


def assign_species(protein_header, exclude_regex, suffix_map):
    if exclude_regex and re.search(exclude_regex, protein_header):
        return None
    catch_all = None
    for suffix, species in suffix_map.items():
        if suffix == "":
            catch_all = species
            continue
        if protein_header.endswith(suffix):
            return species
    return catch_all


def score_quant(quant_rows, species_rule, expected_log2):
    exclude_regex = species_rule.get("exclude_regex", "")
    suffix_map = species_rule["suffix_map"]
    inten = defaultdict(lambda: defaultdict(list))
    prec_species = defaultdict(set)
    prec_proteins = defaultdict(set)

    for row in quant_rows:
        try:
            intensity = float(row["intensity"])
        except (ValueError, KeyError):
            continue
        if intensity <= 0 or math.isnan(intensity):
            continue
        sp = assign_species(row["protein"], exclude_regex, suffix_map)
        if sp is None:
            continue
        key = (row["precursor"], row["charge"])
        prec_species[key].add(sp)
        inten[key][row["condition"]].append(intensity)
        prec_proteins[key].add(row["protein"])

    per_species_log2 = defaultdict(list)
    cv_values = []
    n_quant = 0
    quantified_proteins = set()

    for key, conds in inten.items():
        species = prec_species[key]
        if len(species) != 1:
            continue
        sp = next(iter(species))
        a = conds.get("A", [])
        b = conds.get("B", [])
        if not a or not b:
            continue
        n_quant += 1
        quantified_proteins |= prec_proteins[key]
        per_species_log2[sp].append(math.log2(statistics.fmean(a) / statistics.fmean(b)))
        for reps in (a, b):
            if len(reps) >= 2:
                m = statistics.fmean(reps)
                if m > 0:
                    cv_values.append(statistics.pstdev(reps) / m)

    metrics = [
        ("num_precursors_quantified", float(n_quant), "count"),
        ("num_proteins", float(len(quantified_proteins)), "count"),
    ]
    all_errors = []
    for sp, observed in sorted(per_species_log2.items()):
        expected = float(expected_log2.get(sp, 0.0))
        errors = [abs(o - expected) for o in observed]
        all_errors.extend(errors)
        metrics.append((f"median_log2_ratio_{sp}", statistics.median(observed), "log2"))
        metrics.append((f"mean_abs_error_{sp}", statistics.fmean(errors), "log2"))
    metrics.append(("mean_abs_error_overall",
                    statistics.fmean(all_errors) if all_errors else 0.0, "log2"))
    metrics.append(("median_intra_condition_cv",
                    statistics.median(cv_values) if cv_values else 0.0, "ratio"))
    return metrics


if __name__ == "__main__":
    quant_tsv, spec_yaml = sys.argv[1], sys.argv[2]
    with open(spec_yaml, encoding="utf-8") as fh:
        spec = yaml.safe_load(fh)
    with open(quant_tsv, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh, delimiter="\t"))
    for name, value, unit in score_quant(rows, spec["species_rule"],
                                         spec["expected_log2_ratio"]):
        sys.stdout.write(f"{name}\t{value:g}\t{unit}\n")
