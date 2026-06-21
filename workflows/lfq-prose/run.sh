#!/usr/bin/env bash
set -euo pipefail

# shellcheck source=/dev/null
source "$(dirname "$0")/../lib/search-prose.sh"   # defines run_search()

# Override common.sh's default ID-prep: IDPosteriorErrorProbability does NOT support ProSE,
# so (per the chosen methodology) we relabel ProSE's own q-value as the 'Posterior Error
# Probability' score ProteomicsLFQ requires. Two IDScoreSwitcher passes: (1) move the q-value
# main score aside into a meta, promoting hyperscore; (2) promote that stashed q-value back to
# the main score, typed as 'Posterior Error Probability'. Values are unchanged.
# (The lfq-prose-perc variant skips this and re-scores via PercolatorAdapter instead.)
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
