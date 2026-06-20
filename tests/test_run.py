import re
from pathlib import Path

from bench.datasets import load_dataset
from bench.run import write_design_tsv, _container_name


def test_container_name_sanitizes():
    sha = "a" * 40
    name = _container_name(sha, "lfq-sage", "proteobench_module2")
    assert name.startswith("bench-aaaaaaaaaaaa-")
    # Only allowed chars: alphanumeric, underscore, dot, hyphen
    assert not re.search(r"[^A-Za-z0-9_.\-]", name), (
        f"container name has invalid chars: {name!r}"
    )
    assert len(name) <= 120


def test_container_name_replaces_slashes():
    name = _container_name("b" * 40, "my/workflow", "some/dataset")
    assert "/" not in name
    assert not re.search(r"[^A-Za-z0-9_.\-]", name), (
        f"container name has invalid chars: {name!r}"
    )


def test_container_name_truncates():
    long_wf = "w" * 200
    name = _container_name("c" * 40, long_wf, "ds")
    assert len(name) <= 120


def test_design_tsv_maps_conditions(tmp_path: Path):
    ds = load_dataset(Path("datasets/proteobench_module2"))
    dest = tmp_path / "design.tsv"
    write_design_tsv(ds, tmp_path, dest)
    lines = dest.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("Fraction_Group")
    assert len(lines) == 1 + 6  # header + 6 runs
    assert any("\tA\tA_1" in ln for ln in lines[1:])
    assert any("\tB\tB_3" in ln for ln in lines[1:])
    assert all(ln.split("\t")[2].startswith("/data/") for ln in lines[1:])
