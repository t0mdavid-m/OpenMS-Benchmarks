import csv
from pathlib import Path

Metric = tuple[str, float, str]

COLUMNS = [
    "run_timestamp", "openms_sha", "openms_tag", "workflow", "engine",
    "dataset", "instrument", "threads", "host_cpu",
    "metric_name", "metric_value", "unit",
]


def append_rows(results_tsv: Path, identity: dict[str, str],
                metrics: list[Metric]) -> None:
    results_tsv = Path(results_tsv)
    results_tsv.parent.mkdir(parents=True, exist_ok=True)
    new_file = not results_tsv.exists()
    with results_tsv.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh, delimiter="\t")
        if new_file:
            writer.writerow(COLUMNS)
        for name, value, unit in metrics:
            row = [identity.get(c, "") for c in COLUMNS[:9]]
            row += [name, "%g" % float(value), unit]
            writer.writerow(row)
