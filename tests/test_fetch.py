import hashlib
from pathlib import Path

import pytest

from bench.fetch import sha256_file, verify_or_raise


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
