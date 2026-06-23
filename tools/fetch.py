"""Out-of-band data prep helper. NOT in the run path.

Fetches + sha-verifies + gunzips spectra/FASTA into an input-bundle folder that a
benchmark's `input:` (in benchmarks.yaml) points at. Reads a legacy-style
manifest.tsv (`filename, role, condition, replicate, sha256`); a `PENDING` sha256
is pinned in place after download. HTTP-only and self-contained — it deliberately
has no dependency on the `bench` package or the live harness.

Usage:
    python tools/fetch.py MANIFEST.tsv --base-url URL/ --out data/<bundle> \
        [--fasta-url URL] [--no-verify-tls]
"""
import argparse
import csv
import gzip
import hashlib
import os
import shutil
import ssl
import sys
import urllib.request
from pathlib import Path


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_or_raise(path: Path, expected: str) -> None:
    if expected == "PENDING":
        return
    actual = sha256_file(path)
    if actual != expected:
        raise ValueError(f"checksum mismatch for {path}: "
                         f"expected {expected}, got {actual}")


def _decompress_gz(path: Path) -> Path:
    """Decompress a .gz file to its sibling without the .gz suffix (idempotent)."""
    out = path.with_name(path.name[:-3])  # strip ".gz"
    if out.exists():
        return out
    tmp = out.with_name(out.name + ".tmp")
    with gzip.open(path, "rb") as fin, tmp.open("wb") as fout:
        shutil.copyfileobj(fin, fout, length=1 << 20)
    os.replace(tmp, out)
    return out


def _rewrite_manifest(manifest: Path, pinned: dict[str, str]) -> None:
    with manifest.open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    for r in rows:
        if r["filename"] in pinned and r["sha256"].strip() == "PENDING":
            r["sha256"] = pinned[r["filename"]]
    with manifest.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, delimiter="\t")
        w.writeheader()
        w.writerows(rows)


def _fetch_http(url: str, dest: Path, verify_tls: bool = True,
                timeout: int = 120) -> None:
    ctx = None
    if not verify_tls:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    tmp = dest.with_name(dest.name + ".tmp")
    with urllib.request.urlopen(url, context=ctx, timeout=timeout) as resp, tmp.open("wb") as out:
        while chunk := resp.read(1 << 20):
            out.write(chunk)
    os.replace(tmp, dest)


def fetch_bundle(manifest: Path, base_url: str, out_dir: Path,
                 fasta_url: str | None = None, verify_tls: bool = True,
                 timeout: int = 120) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    base_url = base_url.rstrip("/") + "/"
    with Path(manifest).open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh, delimiter="\t"))

    pinned: dict[str, str] = {}
    for r in rows:
        fname = r["filename"]
        sha = r["sha256"].strip()
        dest = out_dir / fname
        is_fasta = r["role"].strip() == "fasta"
        url = fasta_url if (is_fasta and fasta_url) else base_url + fname
        need = not dest.exists()
        if not need and sha != "PENDING":
            try:
                verify_or_raise(dest, sha)
            except ValueError:
                need = True
        if need:
            _fetch_http(url, dest, verify_tls, timeout)
            verify_or_raise(dest, sha)
        if sha == "PENDING":
            pinned[fname] = sha256_file(dest)
        if r["role"].strip() == "spectra" and fname.endswith(".gz"):
            _decompress_gz(dest)

    if pinned:
        _rewrite_manifest(Path(manifest), pinned)
    return out_dir


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="fetch")
    ap.add_argument("manifest", type=Path)
    ap.add_argument("--base-url", required=True)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--fasta-url", default=None)
    ap.add_argument("--no-verify-tls", action="store_true")
    ap.add_argument("--timeout", type=int, default=120)
    args = ap.parse_args(argv)
    fetch_bundle(args.manifest, args.base_url, args.out, args.fasta_url,
                 verify_tls=not args.no_verify_tls, timeout=args.timeout)
    print(f"bundle ready at {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
