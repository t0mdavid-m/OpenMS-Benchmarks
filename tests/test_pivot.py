from pivot import pivot


def test_pivot_groups_by_run_identity():
    rows = [
        {"openms_sha": "a", "workflow": "w", "dataset": "d",
         "metric_name": "wall_clock_s", "metric_value": "10"},
        {"openms_sha": "a", "workflow": "w", "dataset": "d",
         "metric_name": "num_precursors_quantified", "metric_value": "5000"},
    ]
    cols, wide = pivot(rows)
    assert len(wide) == 1
    assert wide[0]["wall_clock_s"] == "10"
    assert wide[0]["num_precursors_quantified"] == "5000"
    assert "wall_clock_s" in cols
