#!/usr/bin/env bash
# Shared DDA-LFQ chain. Sourced by each engine's run.sh, which must define
# run_search() that consumes $MZML_DIR + $DB_FASTA and writes $IDXML_DIR/<base>.idXML.
set -euo pipefail

: "${INPUT_DIR:?}" "${FASTA:?}" "${OUT_DIR:?}" "${THREADS:?}"
: "${PREC_TOL_PPM:?}" "${FRAG_TOL_DA:?}" "${DESIGN_TSV:?}"

WORK="$OUT_DIR/work"
mkdir -p "$WORK"

# 1) Target+decoy database (ProteoBench FASTA is target-only).
DB_FASTA="$WORK/db_with_decoys.fasta"
DecoyDatabase -in "$FASTA" -out "$DB_FASTA" \
  -decoy_string DECOY_ -decoy_string_position prefix -enzyme Trypsin

# 2) Per-file ID processing. The default chain computes PEP, filters at 1% PSM FDR,
#    and restores PEP as the main score (ProteomicsLFQ requires PEP). An engine's run.sh
#    may override prepare_ids() BEFORE sourcing this file (e.g. ProSE, whose score
#    IDPosteriorErrorProbability cannot model). Contract:
#      prepare_ids RAW_SEARCH_IDXML OUT_IDXML
#    -> OUT_IDXML has 1%-FDR PSMs with 'Posterior Error Probability' as the main score.
prepare_ids_default() {
  local raw="$1" out="$2" b="${1%.idXML}"
  PeptideIndexer -in "$raw" -fasta "$DB_FASTA" -out "${b}.idx.idXML" \
    -decoy_string DECOY_ -decoy_string_position prefix -missing_decoy_action warn
  IDPosteriorErrorProbability -in "${b}.idx.idXML" -out "${b}.pep.idXML"
  FalseDiscoveryRate -in "${b}.pep.idXML" -out "${b}.fdr.idXML" \
    -PSM true -protein false -threads "$THREADS"
  IDFilter -in "${b}.fdr.idXML" -out "${b}.filt.idXML" -score:psm 0.01
  IDScoreSwitcher -in "${b}.filt.idXML" -out "$out" \
    -new_score "Posterior Error Probability_score" \
    -new_score_orientation lower_better -new_score_type "Posterior Error Probability"
}
# Percolator FDR path (strict cross-engine footing for the engines OpenMS supports).
# PSMFeatureExtractor adds the engine-specific features Percolator needs to discriminate
# (generic features alone collapse every PSM into one PEP bin). PSMFeatureExtractor only
# supports Comet, X!Tandem and MSGF+ -- so this backend is only wired to lfq-comet-perc
# and lfq-msgf-perc. PercolatorAdapter rescores with target-decoy competition; the main
# score becomes the Percolator q-value, on which we filter at 1% PSM FDR. Finally we
# promote Percolator's PEP (meta 'MS:1001493') to the main score ProteomicsLFQ requires.
prepare_ids_percolator() {
  local raw="$1" out="$2" b="${1%.idXML}"
  PeptideIndexer -in "$raw" -fasta "$DB_FASTA" -out "${b}.idx.idXML" \
    -decoy_string DECOY_ -decoy_string_position prefix -missing_decoy_action warn
  PSMFeatureExtractor -in "${b}.idx.idXML" -out "${b}.feat.idXML" -threads "$THREADS"
  PercolatorAdapter -in "${b}.feat.idXML" -out "${b}.perc.idXML" \
    -post_processing_tdc -score_type q-value -threads "$THREADS"
  IDFilter -in "${b}.perc.idXML" -out "${b}.filt.idXML" -score:psm 0.01
  IDScoreSwitcher -in "${b}.filt.idXML" -out "$out" \
    -new_score "MS:1001493" -new_score_orientation lower_better \
    -new_score_type "Posterior Error Probability"
}

# Backend selection. FDR_BACKEND=percolator routes through the Percolator path above
# (used by the -perc workflow variants). Default (idpep) keeps the per-engine behavior:
# engine override if defined, else the IDPosteriorErrorProbability default.
if [[ "${FDR_BACKEND:-idpep}" == "percolator" ]]; then
  prepare_ids() { prepare_ids_percolator "$@"; }
elif ! declare -F prepare_ids >/dev/null; then
  prepare_ids() { prepare_ids_default "$@"; }
fi

mkdir -p "$WORK/idxml"
FILTERED_IDS=()
QUANT_MZML=()
shopt -s nullglob
mzml_files=("$INPUT_DIR"/*.mzML)
if [ ${#mzml_files[@]} -eq 0 ]; then
  echo "ERROR: no .mzML files found in $INPUT_DIR" >&2
  exit 1
fi
for mz in "${mzml_files[@]}"; do
  base="$(basename "$mz" .mzML)"
  raw_id="$WORK/idxml/${base}.idXML"
  run_search "$mz" "$DB_FASTA" "$raw_id"                       # defined by run.sh
  prepare_ids "$raw_id" "$WORK/idxml/${base}.final.idXML"      # default or engine override
  FILTERED_IDS+=("$WORK/idxml/${base}.final.idXML")
  QUANT_MZML+=("$mz")
done

# 3) Quantify with ProteomicsLFQ (MBR off baseline, top-3 protein quant).
ProteomicsLFQ \
  -in "${QUANT_MZML[@]}" \
  -ids "${FILTERED_IDS[@]}" \
  -design "$DESIGN_TSV" \
  -fasta "$DB_FASTA" \
  -targeted_only true \
  -ProteinQuantification:top:N 3 \
  -out "$WORK/out.mzTab" \
  -out_msstats "$WORK/msstats.csv" \
  -threads "$THREADS"

# 4) Transform MSstats CSV -> canonical quant.tsv (long format).
#    MSstats columns: ProteinName,PeptideSequence,PrecursorCharge,FragmentIon,
#    ProductCharge,IsotopeLabelType,Condition,BioReplicate,Run,Intensity
awk -F',' 'NR==1{
    for(i=1;i<=NF;i++){h[$i]=i}
    print "precursor\tcharge\tprotein\tcondition\treplicate\tintensity"; next
  }
  {
    printf "%s\t%s\t%s\t%s\t%s\t%s\n",
      $h["PeptideSequence"], $h["PrecursorCharge"], $h["ProteinName"],
      $h["Condition"], $h["BioReplicate"], $h["Intensity"]
  }' "$WORK/msstats.csv" > "$OUT_DIR/quant.tsv"

echo "wrote $OUT_DIR/quant.tsv ($(wc -l < "$OUT_DIR/quant.tsv") lines)" >&2
