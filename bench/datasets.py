import csv
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class FileEntry:
    filename: str
    rsync_path: str
    http_url: str
    sha256: str
    role: str
    condition: str | None
    replicate: int | None


@dataclass
class GroundTruth:
    exclude_regex: str
    suffix_map: dict[str, str]
    expected_log2: dict[str, float]
    ratio_direction: str
    conditions: dict[str, list[str]]


@dataclass
class Dataset:
    name: str
    category: str
    instrument: str
    path: Path
    files: list[FileEntry]
    ground_truth: GroundTruth
    precursor_tol_ppm: float
    fragment_tol_da: float

    def spectra(self) -> list[FileEntry]:
        return [f for f in self.files if f.role == "spectra"]

    def fasta(self) -> FileEntry:
        for f in self.files:
            if f.role == "fasta":
                return f
        raise ValueError(f"dataset {self.name!r} has no fasta entry")


def load_dataset(path: Path) -> Dataset:
    path = Path(path)
    gt_raw = yaml.safe_load((path / "ground_truth.yaml").read_text(encoding="utf-8"))
    meta = gt_raw["meta"]
    http_base = meta["http_base"].rstrip("/") + "/"
    remote_dir = meta.get("remote_dir", meta["name"])
    rel = f"{meta['category']}/{meta['instrument']}/{remote_dir}"

    files: list[FileEntry] = []
    with (path / "manifest.tsv").open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            is_fasta = row["role"].strip() == "fasta"
            fasta_override = meta.get("fasta_http_url")
            if is_fasta and fasta_override:
                http_url = fasta_override
                rsync_path = ""
            else:
                http_url = f"{http_base}{rel}/{row['filename']}"
                rsync_path = f"/benchmarks/pride-benchmarks/{rel}/{row['filename']}"
            files.append(FileEntry(
                filename=row["filename"],
                rsync_path=rsync_path,
                http_url=http_url,
                sha256=row["sha256"].strip(),
                role=row["role"].strip(),
                condition=(row["condition"].strip() or None),
                replicate=(int(row["replicate"]) if row["replicate"].strip() else None),
            ))

    rule = gt_raw["species_rule"]
    gt = GroundTruth(
        exclude_regex=rule.get("exclude_regex", ""),
        suffix_map=rule["suffix_map"],
        expected_log2={k: float(v) for k, v in gt_raw["expected_log2_ratio"].items()},
        ratio_direction=gt_raw["ratio_direction"],
        conditions=gt_raw["conditions"],
    )
    return Dataset(
        name=meta["name"],
        category=meta["category"],
        instrument=meta["instrument"],
        path=path,
        files=files,
        ground_truth=gt,
        precursor_tol_ppm=float(meta["precursor_tol_ppm"]),
        fragment_tol_da=float(meta["fragment_tol_da"]),
    )


def discover_datasets(root: Path) -> list[Dataset]:
    root = Path(root)
    return [load_dataset(p) for p in sorted(root.iterdir())
            if (p / "ground_truth.yaml").exists()]
