#!/usr/bin/env bash
set -euo pipefail

# Same shared logical params as lfq-sage, mapped to CometAdapter flags.
run_search() {
  local mzml="$1" db="$2" out_id="$3"
  CometAdapter \
    -in "$mzml" -database "$db" -out "$out_id" \
    -enzyme Trypsin -allowed_missed_cleavages 2 \
    -fixed_modifications "Carbamidomethyl (C)" \
    -variable_modifications "Oxidation (M)" \
    -precursor_mass_tolerance "${PREC_TOL_PPM}" -precursor_error_units ppm \
    -fragment_mass_tolerance "${FRAG_TOL_DA}" -fragment_error_units Da \
    -threads "$THREADS"
}

# shellcheck source=/dev/null
source "$(dirname "$0")/../common.sh"
