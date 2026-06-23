#!/usr/bin/env bash
# Engine search step: MS-GF+ (Java; jar on PATH in the image). Sourced by
# lfq-msgf and lfq-msgf-perc. MS-GF+ uses instrument presets for fragment
# tolerance (high_res for the Orbitrap QExactiveHF), so no fragment-tol flag.
run_search() {
  local mzml="$1" db="$2" out_id="$3"
  MSGFPlusAdapter \
    -in "$mzml" -database "$db" -out "$out_id" \
    -executable MSGFPlus.jar \
    -enzyme Trypsin/P -max_missed_cleavages 2 \
    -instrument high_res \
    -fixed_modifications "Carbamidomethyl (C)" \
    -variable_modifications "Oxidation (M)" \
    -precursor_mass_tolerance "${PREC_TOL_PPM}" -precursor_error_units ppm \
    -threads "$THREADS"
}
