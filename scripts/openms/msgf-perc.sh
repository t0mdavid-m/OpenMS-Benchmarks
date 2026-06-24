#!/usr/bin/env bash
set -euo pipefail
# Strict-comparison variant: same MS-GF+ search, FDR via PercolatorAdapter.
export FDR_BACKEND=percolator
source "${WORK}/lib/search-msgf.sh"
source "${WORK}/lib/common.sh"
