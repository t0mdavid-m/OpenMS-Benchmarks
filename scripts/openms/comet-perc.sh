#!/usr/bin/env bash
set -euo pipefail
# Strict-comparison variant: same Comet search, FDR via PercolatorAdapter.
export FDR_BACKEND=percolator
source "${WORK}/lib/search-comet.sh"
source "${WORK}/lib/common.sh"
