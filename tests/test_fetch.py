import hashlib
from pathlib import Path

import pytest

from tools.fetch import sha256_file, verify_or_raise, _rewrite_manifest, _decompress_gz


def test_sha256_file(tmp_path: Path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"hello")
    assert sha256_file(f) == hashlib.sha256(b"hello").hexdigest()


def test_verify_or_raise_detects_mismatch(tmp_path: Path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"hello")
    good = hashlib.sha256(b"hello").hexdigest()
    verify_or_raise(f, good)  # no raise
    with pytest.raises(ValueError):
        verify_or_raise(f, "deadbeef")


def test_verify_skips_when_pending(tmp_path: Path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"hello")
    verify_or_raise(f, "PENDING")  # PENDING means "not pinned yet": no raise


def test_decompress_gz(tmp_path):
    import gzip
    from tools.fetch import _decompress_gz
    raw = b"hello mzml content"
    gz = tmp_path / "x.mzML.gz"
    with gzip.open(gz, "wb") as fh:
        fh.write(raw)
    out = _decompress_gz(gz)
    assert out.name == "x.mzML"
    assert out.read_bytes() == raw
    # idempotent: second call returns same file, no error
    assert _decompress_gz(gz).read_bytes() == raw


def test_rewrite_manifest_pins_pending_and_preserves_columns(tmp_path: Path):
    import csv
    m = tmp_path / "manifest.tsv"
    m.write_text(
        "filename\trole\tcondition\treplicate\tsha256\n"
        "a.mzML\tspectra\tA\t1\tPENDING\n"
        "db.fasta\tfasta\t\t\tabc123\n",
        encoding="utf-8",
    )
    _rewrite_manifest(m, {"a.mzML": "deadbeef"})
    rows = list(csv.DictReader(m.open(encoding="utf-8"), delimiter="\t"))
    assert rows[0]["sha256"] == "deadbeef"        # PENDING pinned
    assert rows[0]["condition"] == "A"            # other columns preserved
    assert rows[1]["sha256"] == "abc123"          # non-PENDING untouched
    assert list(rows[0].keys()) == ["filename", "role", "condition", "replicate", "sha256"]
