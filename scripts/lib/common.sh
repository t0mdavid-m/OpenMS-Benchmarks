#!/usr/bin/env bash
# Shared DDA-LFQ chain. Sourced by each engine's run script, which must define
# run_search() consuming ($mzml $db $out_id). Self-contained: provisions Python,
# builds design + DB, searches, quantifies, then self-scores into metrics.tsv.
set -euo pipefail

: "${INPUT_DIR:?}" "${OUT_DIR:?}" "${THREADS:?}" "${WORK:?}"

source "${WORK}/lib/emit.sh"

# --- provisioning (NOT timed) -------------------------------------------------
if ! command -v python3 >/dev/null 2>&1; then
  apt-get update -qq && apt-get install -y -qq python3 python3-yaml >/dev/null
fi

SPEC="${INPUT_DIR}/spec.yaml"
DESIGN_TSV="${OUT_DIR}/design.tsv"
python3 "${WORK}/lib/spec.py" --design "$SPEC" > "$DESIGN_TSV"
eval "$(python3 "${WORK}/lib/spec.py" --shell "$SPEC")"   # PREC_TOL_PPM, FRAG_TOL_DA, FASTA
: "${PREC_TOL_PPM:?}" "${FRAG_TOL_DA:?}" "${FASTA:?}"

RUNWORK="${OUT_DIR}/work"
mkdir -p "$RUNWORK/idxml"

# prepare_ids backends (unchanged from the original common.sh).
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
prepare_ids_percolator() {
  local raw="$1" out="$2" b="${1%.idXML}"
  PeptideIndexer -in "$raw" -fasta "$DB_FASTA" -out "${b}.idx.idXML" \
    -decoy_string DECOY_ -decoy_string_position prefix -missing_decoy_action warn
  PSMFeatureExtractor -in "${b}.idx.idXML" -out "${b}.feat.idXML" -threads "$THREADS"
  PercolatorAdapter -in "${b}.feat.idXML" -out "${b}.perc.idXML" \
    -post_processing_tdc -score_type q-value -threads "$THREADS"
  IDFilter -in "${b}.perc.idXML" -out "${b}.filt.idXML" -score:psm 0.01
  IDScoreSwitcher -in "${b}.filt.idXML" -out "${b}.pep.idXML" \
    -new_score "MS:1001493" -new_score_orientation lower_better \
    -new_score_type "Posterior Error Probability"
  sed -E 's#<UserParam type="(int|float|intList|floatList|stringList)" name="[^"]*" value="[^"]*"/>##g' \
    "${b}.pep.idXML" > "$out"
}
if [[ "${FDR_BACKEND:-idpep}" == "percolator" ]]; then
  prepare_ids() { prepare_ids_percolator "$@"; }
elif ! declare -F prepare_ids >/dev/null; then
  prepare_ids() { prepare_ids_default "$@"; }
fi

# --- measured phase: DB + search + quant -------------------------------------
metrics_init          # header written once, BEFORE timing
phase_start           # reset cgroup peak, start clock

# Target+decoy database (input FASTA is target-only).
DB_FASTA="${RUNWORK}/db_with_decoys.fasta"
DecoyDatabase -in "$FASTA" -out "$DB_FASTA" \
  -decoy_string DECOY_ -decoy_string_position prefix -enzyme Trypsin

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
  raw_id="$RUNWORK/idxml/${base}.idXML"
  run_search "$mz" "$DB_FASTA" "$raw_id"
  prepare_ids "$raw_id" "$RUNWORK/idxml/${base}.final.idXML"
  FILTERED_IDS+=("$RUNWORK/idxml/${base}.final.idXML")
  QUANT_MZML+=("$mz")
done

ProteomicsLFQ \
  -in "${QUANT_MZML[@]}" -ids "${FILTERED_IDS[@]}" \
  -design "$DESIGN_TSV" -fasta "$DB_FASTA" \
  -targeted_only true -ProteinQuantification:top:N 3 \
  -out "$RUNWORK/out.mzTab" -out_msstats "$RUNWORK/msstats.csv" \
  -threads "$THREADS"

awk -F',' 'NR==1{for(i=1;i<=NF;i++){h[$i]=i}
    print "precursor\tcharge\tprotein\tcondition\treplicate\tintensity"; next}
  {printf "%s\t%s\t%s\t%s\t%s\t%s\n",
     $h["PeptideSequence"], $h["PrecursorCharge"], $h["ProteinName"],
     $h["Condition"], $h["BioReplicate"], $h["Intensity"]}' \
  "$RUNWORK/msstats.csv" > "$OUT_DIR/quant.tsv"

phase_end             # append wall_clock_s + peak_mem_bytes (tool phase only)

# --- scoring (after measured phase) ------------------------------------------
python3 "${WORK}/lib/score.py" "$OUT_DIR/quant.tsv" "$SPEC" >> "$METRICS_FILE"
echo "wrote $METRICS_FILE" >&2
