from pathlib import Path

from bench.datasets import load_dataset
from bench.run import write_design_tsv


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
