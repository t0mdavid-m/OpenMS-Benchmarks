# proteobench_module2 input bundle

ProteoBench LFQ DDA module 2 (Q Exactive HF; HYE mixed-species, A/B 3×3).

This folder is a **bring-your-own input bundle**: the harness mounts it read-only
at `/input` and runs each tool's script against it. The harness does **not** fetch
or verify data anymore — you populate this folder yourself.

## What must be here

- `spec.yaml` — committed (design, tolerances, species rules, expected ratios).
- 6 spectra, **decompressed** `.mzML` (filenames listed in `spec.yaml`):
  - `LFQ_Orbitrap_DDA_Condition_A_Sample_Alpha_0{1,2,3}.mzML`
  - `LFQ_Orbitrap_DDA_Condition_B_Sample_Alpha_0{1,2,3}.mzML`
- `ProteoBenchFASTA_MixedSpecies_HYE.fasta`

The `.mzML` files and FASTA are **not committed** (size). Get them once with the
optional out-of-band helper, then they stay cached here:

```bash
# checksums + remote layout are preserved in git history at
#   datasets/proteobench_module2/manifest.tsv  (pre-refactor)
python tools/fetch.py <manifest.tsv> \
    --base-url https://archive.openms.org/openms/benchmarks/pride-benchmarks/lfq/QExactiveHF/ProteoBench_Module_2/ \
    --out data/proteobench_module2 \
    --no-verify-tls          # archive.openms.org has a hostname-mismatched cert
```

`tools/fetch.py` sha-verifies every file, pins any `PENDING` checksum back into the
manifest, and gunzips `.gz` spectra to the bare `.mzML` names `spec.yaml` expects.

## Ground truth

Mixed HYE: HUMAN 1:1 (log2 0.0), YEAST 2:1 (log2 1.0), E. coli 1:4 (log2 -2.0),
direction A/B. Contaminants (`Cont_` prefix) are excluded before species assignment.
