#!/usr/bin/env bash
# Engine search step: Comet. Sourced by lfq-comet and lfq-comet-perc.
# Same shared logical params as Sage, mapped to CometAdapter flags.
run_search() {
  local mzml="$1" db="$2" out_id="$3"
  CometAdapter \
    -in "$mzml" -database "$db" -out "$out_id" \
    -enzyme Trypsin -missed_cleavages 2 \
    -fixed_modifications "Carbamidomethyl (C)" \
    -variable_modifications "Oxidation (M)" \
    -precursor_mass_tolerance "${PREC_TOL_PPM}" -precursor_error_units ppm \
    -fragment_mass_tolerance "${FRAG_TOL_DA}" -fragment_error_units Da \
    -threads "$THREADS"
}
