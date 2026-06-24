#!/usr/bin/env bash
set -euo pipefail
source "${WORK}/lib/search-prose.sh"

# Override common.sh's default ID-prep for ProSE.
#
# On current OpenMS develop, ProSE with -Search:FDR:PSM > 0 runs FalseDiscoveryRate
# internally (add_decoy_peptides=true): it OVERWRITES each PSM's hyperscore with its
# q-value (main score type becomes "q-value", lower-better) and filters to q<=0.01,
# but RETAINS decoys (categorical decoy removal only happens at protein-FDR
# finalization, which we don't trigger -- FDR:protein defaults to 0).
#
# ProteomicsLFQ needs a target-only set whose main score TYPE is "Posterior Error
# Probability". IDPosteriorErrorProbability cannot model ProSE scores, so (per the
# chosen methodology) we reuse ProSE's own q-value AS the PEP: index to the shared
# decoy DB, drop decoy PSMs, then relabel the "q-value" score type as "Posterior
# Error Probability" (values + lower-better orientation unchanged). The relabel is a
# targeted sed on the PeptideIdentification score_type attribute -- robust to ProSE's
# evolving meta-value names, and mirrors the percolator path's idXML sed.
prepare_ids() {
  local raw="$1" out="$2" b="${1%.idXML}"
  PeptideIndexer -in "$raw" -fasta "$DB_FASTA" -out "${b}.idx.idXML" \
    -decoy_string DECOY_ -decoy_string_position prefix -missing_decoy_action warn
  IDFilter -in "${b}.idx.idXML" -out "${b}.filt.idXML" -remove_decoys -score:psm 0.01
  sed -E 's#(<PeptideIdentification[^>]*score_type=)"q-value"#\1"Posterior Error Probability"#' \
    "${b}.filt.idXML" > "$out"
}

source "${WORK}/lib/common.sh"
