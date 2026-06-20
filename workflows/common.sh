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

# 2) Per-file search (engine-specific) -> idXML, then index + PSM-level FDR.
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
  run_search "$mz" "$DB_FASTA" "$raw_id"            # defined by run.sh

  PeptideIndexer -in "$raw_id" -fasta "$DB_FASTA" \
    -out "$WORK/idxml/${base}.idx.idXML" \
    -decoy_string DECOY_ -decoy_string_position prefix \
    -missing_decoy_action warn

  # Posterior Error Probability — ProteomicsLFQ requires PEP as the main score.
  IDPosteriorErrorProbability -in "$WORK/idxml/${base}.idx.idXML" \
    -out "$WORK/idxml/${base}.pep.idXML"

  # PSM-level q-value FDR (protein inference is ProteomicsLFQ's job).
  FalseDiscoveryRate -in "$WORK/idxml/${base}.pep.idXML" \
    -out "$WORK/idxml/${base}.fdr.idXML" \
    -PSM true -protein false -threads "$THREADS"

  # Filter at 1% PSM FDR (main score is the q-value here).
  IDFilter -in "$WORK/idxml/${base}.fdr.idXML" \
    -out "$WORK/idxml/${base}.filt.idXML" -score:psm 0.01

  # Restore PEP (stored as a meta value by FDR) as the main score for ProteomicsLFQ.
  IDScoreSwitcher -in "$WORK/idxml/${base}.filt.idXML" \
    -out "$WORK/idxml/${base}.pepscore.idXML" \
    -new_score "Posterior Error Probability_score" \
    -new_score_orientation lower_better \
    -new_score_type "Posterior Error Probability"

  FILTERED_IDS+=("$WORK/idxml/${base}.pepscore.idXML")
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
