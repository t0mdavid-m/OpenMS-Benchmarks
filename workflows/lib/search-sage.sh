#!/usr/bin/env bash
# Engine search step: Sage. Sourced by lfq-sage and lfq-sage-perc.
# Shared logical params: Trypsin, 2 missed cleavages, Carbamidomethyl(C) fixed,
# Oxidation(M) variable. Tolerances come from the dataset (PREC_TOL_PPM/FRAG_TOL_DA).
run_search() {
  local mzml="$1" db="$2" out_id="$3"
  SageAdapter \
    -in "$mzml" -database "$db" -out "$out_id" \
    -enzyme Trypsin -missed_cleavages 2 \
    -fixed_modifications "Carbamidomethyl (C)" \
    -variable_modifications "Oxidation (M)" \
    -precursor_tol_left "-${PREC_TOL_PPM}" -precursor_tol_right "${PREC_TOL_PPM}" \
    -precursor_tol_unit ppm \
    -fragment_tol_left "-${FRAG_TOL_DA}" -fragment_tol_right "${FRAG_TOL_DA}" \
    -fragment_tol_unit Da \
    -threads "$THREADS"
}
