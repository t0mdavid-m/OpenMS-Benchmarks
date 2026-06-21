#!/usr/bin/env bash
set -euo pipefail

# Strict-comparison variant: same Comet search, but FDR via PercolatorAdapter
# (generic features) instead of the IDPosteriorErrorProbability path.
export FDR_BACKEND=percolator

# shellcheck source=/dev/null
source "$(dirname "$0")/../lib/search-comet.sh"   # defines run_search()
# shellcheck source=/dev/null
source "$(dirname "$0")/../common.sh"
