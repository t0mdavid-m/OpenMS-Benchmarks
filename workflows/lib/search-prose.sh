#!/usr/bin/env bash
# Engine search step: ProSE (native OpenMS engine). Sourced by lfq-prose and
# lfq-prose-perc. ProSE reuses the shared DECOY_ decoys (-Search:decoys auto).
# It computes its own 1% PSM q-value FDR (-Search:FDR:PSM 0.01); lfq-prose's
# prepare_ids override relabels that q-value as PEP for ProteomicsLFQ. (ProSE has
# no Percolator variant: it does internal target-decoy competition and reports
# only winners, so it never exposes the decoy population rescorers need.)
run_search() {
  local mzml="$1" db="$2" out_id="$3"
  ProSE \
    -in "$mzml" -database "$db" -out_idxml "$out_id" \
    -Search:enzyme Trypsin \
    -Search:peptide:missed_cleavages 2 \
    -Search:modifications:fixed "Carbamidomethyl (C)" \
    -Search:modifications:variable "Oxidation (M)" \
    -Search:precursor:mass_tolerance_lower "${PREC_TOL_PPM}" \
    -Search:precursor:mass_tolerance_upper "${PREC_TOL_PPM}" \
    -Search:precursor:mass_tolerance_unit ppm \
    -Search:fragment:mass_tolerance "${FRAG_TOL_DA}" \
    -Search:fragment:mass_tolerance_unit Da \
    -Search:decoys auto -Search:decoy_prefix DECOY_ \
    -Search:FDR:PSM 0.01 \
    -threads "$THREADS"
}
