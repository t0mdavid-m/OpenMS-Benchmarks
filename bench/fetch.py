import csv
import gzip
import hashlib
import os
import shutil
import ssl
import subprocess
import urllib.request
from pathlib import Path

from bench.config import Config
from bench.datasets import Dataset, FileEntry


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


def _fetch_http(entry: FileEntry, dest: Path, verify_tls: bool = True,
                timeout: int = 120) -> None:
    ctx = None
    if not verify_tls:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    tmp = dest.with_name(dest.name + ".tmp")
    with urllib.request.urlopen(entry.http_url, context=ctx, timeout=timeout) as resp, tmp.open("wb") as out:
        while chunk := resp.read(1 << 20):
            out.write(chunk)
    os.replace(tmp, dest)


def _fetch_rsync(entry: FileEntry, dest: Path, cfg: Config) -> None:
    remote = f"{cfg.rsync_user}@{cfg.rsync_host}:{entry.rsync_path}"
    ssh = (f"ssh -i '{cfg.rsync_key}' -p {cfg.rsync_port} "
           f"-o StrictHostKeyChecking=no -o BatchMode=yes")
    subprocess.run(
        ["rsync", "-avz", f"--timeout={cfg.http_timeout_s}", "-e", ssh,
         remote, str(dest)],
        check=True, timeout=cfg.build_timeout_s,
    )


def fetch_dataset(dataset: Dataset, config: Config) -> Path:
    cache = Path(config.data_cache) / dataset.name
    cache.mkdir(parents=True, exist_ok=True)
    use_rsync = bool(config.rsync_host)

    pinned: dict[str, str] = {}
    for entry in dataset.files:
        dest = cache / entry.filename
        need = not dest.exists()
        if not need and entry.sha256 != "PENDING":
            try:
                verify_or_raise(dest, entry.sha256)
            except ValueError:
                need = True  # cached copy is corrupt/stale: refetch
        if need:
            if use_rsync and entry.rsync_path:
                _fetch_rsync(entry, dest, config)
            else:
                _fetch_http(entry, dest, config.verify_tls, config.http_timeout_s)
            verify_or_raise(dest, entry.sha256)
        if entry.sha256 == "PENDING":
            pinned[entry.filename] = sha256_file(dest)

    if pinned:
        _rewrite_manifest(dataset.path / "manifest.tsv", pinned)

    for entry in dataset.spectra():
        if entry.filename.endswith(".gz"):
            _decompress_gz(cache / entry.filename)
    return cache


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
