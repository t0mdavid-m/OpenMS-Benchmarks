#!/usr/bin/env bash
set -euo pipefail

# ProSE (native OpenMS engine). ProSE is integrated: it reuses the shared DECOY_ decoys
# (-Search:decoys auto) and computes its OWN 1% PSM-level q-value FDR (-Search:FDR:PSM 0.01),
# so its output is already FDR-filtered with a 'q-value' main score.
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

# Override common.sh's default ID-prep: IDPosteriorErrorProbability does NOT support ProSE,
# so (per the chosen methodology) we relabel ProSE's own q-value as the 'Posterior Error
# Probability' score ProteomicsLFQ requires. Two IDScoreSwitcher passes: (1) move the q-value
# main score aside into a meta, promoting hyperscore; (2) promote that stashed q-value back to
# the main score, typed as 'Posterior Error Probability'. Values are unchanged.
prepare_ids() {
  local raw="$1" out="$2" b="${1%.idXML}"
  PeptideIndexer -in "$raw" -fasta "$DB_FASTA" -out "${b}.idx.idXML" \
    -decoy_string DECOY_ -decoy_string_position prefix -missing_decoy_action warn
  IDScoreSwitcher -in "${b}.idx.idXML" -out "${b}.s1.idXML" \
    -new_score "ln(hyperscore)_score" -new_score_orientation higher_better \
    -new_score_type hyperscore -old_score "ProSE_qvalue"
  IDScoreSwitcher -in "${b}.s1.idXML" -out "$out" \
    -new_score "ProSE_qvalue" -new_score_orientation lower_better \
    -new_score_type "Posterior Error Probability" -old_score "hyperscore"
}

# shellcheck source=/dev/null
source "$(dirname "$0")/../common.sh"
