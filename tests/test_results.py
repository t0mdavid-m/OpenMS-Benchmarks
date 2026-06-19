import csv
from pathlib import Path

from bench.results import append_rows

IDENTITY = {
    "run_timestamp": "2026-06-19T10:00:00Z",
    "openms_sha": "abc123",
    "openms_tag": "develop",
    "workflow": "lfq-sage",
    "engine": "sage",
    "dataset": "proteobench_module2",
    "instrument": "QExactiveHF",
    "threads": "4",
    "host_cpu": "test-cpu",
}


def test_append_writes_header_and_rows(tmp_path: Path):
    out = tmp_path / "results.tsv"
    append_rows(out, IDENTITY, [("num_precursors_quantified", 12345.0, "count"),
                                ("wall_clock_s", 42.5, "s")])
    rows = list(csv.DictReader(out.open(encoding="utf-8"), delimiter="\t"))
    assert len(rows) == 2
    assert rows[0]["metric_name"] == "num_precursors_quantified"
    assert rows[0]["openms_sha"] == "abc123"
    assert rows[1]["metric_value"] == "42.5"


def test_append_is_additive_without_duplicate_header(tmp_path: Path):
    out = tmp_path / "results.tsv"
    append_rows(out, IDENTITY, [("a", 1.0, "u")])
    append_rows(out, IDENTITY, [("b", 2.0, "u")])
    text = out.read_text(encoding="utf-8")
    assert text.count("metric_name") == 1  # header only once
    rows = list(csv.DictReader(out.open(encoding="utf-8"), delimiter="\t"))
    assert {r["metric_name"] for r in rows} == {"a", "b"}
