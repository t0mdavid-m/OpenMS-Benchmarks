import csv
import sys
from pathlib import Path

KEY = ["run_timestamp", "openms_sha", "openms_tag", "workflow", "engine",
       "dataset", "instrument", "threads", "host_cpu"]


def pivot(rows: list[dict]) -> tuple[list[str], list[dict]]:
    present_keys = [k for k in KEY if any(k in r for r in rows)]
    wide: dict[tuple, dict] = {}
    metric_cols: list[str] = []
    for r in rows:
        ident = tuple(r.get(k, "") for k in present_keys)
        bucket = wide.setdefault(ident, {k: r.get(k, "") for k in present_keys})
        name = r["metric_name"]
        if name not in metric_cols:
            metric_cols.append(name)
        bucket[name] = r["metric_value"]
    return present_keys + metric_cols, list(wide.values())


def main() -> int:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("results/results.tsv")
    with src.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh, delimiter="\t"))
    cols, wide = pivot(rows)
    w = csv.DictWriter(sys.stdout, fieldnames=cols, delimiter="\t",
                       extrasaction="ignore")
    w.writeheader()
    w.writerows(wide)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
