from bench.config import MetricSpec
from bench.validate import parse_metrics_tsv, validate_metrics

SPECS = [
    MetricSpec("mean_abs_error_overall", "log2", True),
    MetricSpec("wall_clock_s", "s", True),
    MetricSpec("peak_mem_bytes", "bytes", False),
    MetricSpec("median_log2_ratio_*", "log2", False),
]


def test_valid_when_required_present_and_numeric():
    rows = [("mean_abs_error_overall", 0.1, "log2"),
            ("wall_clock_s", 12.0, "s"),
            ("median_log2_ratio_HUMAN", 0.0, "log2")]   # glob match
    v = validate_metrics(rows, SPECS)
    assert v.ok and not v.missing and not v.unknown


def test_missing_required_is_invalid():
    rows = [("wall_clock_s", 12.0, "s")]
    v = validate_metrics(rows, SPECS)
    assert not v.ok
    assert "mean_abs_error_overall" in v.missing


def test_unknown_metric_is_warning_not_failure():
    rows = [("mean_abs_error_overall", 0.1, "log2"),
            ("wall_clock_s", 12.0, "s"),
            ("surprise_metric", 1.0, "x")]
    v = validate_metrics(rows, SPECS)
    assert v.ok
    assert "surprise_metric" in v.unknown


def test_non_numeric_value_is_invalid():
    rows = [("mean_abs_error_overall", None, "log2"),
            ("wall_clock_s", 12.0, "s")]
    v = validate_metrics(rows, SPECS)
    assert not v.ok
    assert "mean_abs_error_overall" in v.non_numeric


def test_parse_metrics_tsv(tmp_path):
    p = tmp_path / "metrics.tsv"
    p.write_text("metric\tvalue\tunit\nwall_clock_s\t12.5\ts\n", encoding="utf-8")
    rows = parse_metrics_tsv(p)
    assert rows == [("wall_clock_s", 12.5, "s")]
