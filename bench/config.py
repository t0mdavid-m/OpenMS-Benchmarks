import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Config:
    openms_repo: Path
    data_cache: Path
    results_tsv: Path
    workflows_dir: Path
    datasets_dir: Path
    threads: int
    http_base: str
    rsync_user: str | None
    rsync_host: str | None
    rsync_port: int | None
    rsync_key: str | None


def load_config(path: Path) -> Config:
    data = tomllib.loads(Path(path).read_text(encoding="utf-8"))
    root = Path(path).resolve().parent
    rsync = data.get("rsync", {})
    return Config(
        openms_repo=Path(data.get("openms_repo", "OpenMS")),
        data_cache=Path(data.get("data_cache", root / "data" / "cache")),
        results_tsv=Path(data.get("results_tsv", root / "results" / "results.tsv")),
        workflows_dir=Path(data.get("workflows_dir", root / "workflows")),
        datasets_dir=Path(data.get("datasets_dir", root / "datasets")),
        threads=int(data.get("threads", 4)),
        http_base=data.get(
            "http_base",
            "https://archive.openms.org/openms/benchmarks/pride-benchmarks/",
        ),
        rsync_user=rsync.get("user"),
        rsync_host=rsync.get("host"),
        rsync_port=rsync.get("port"),
        rsync_key=rsync.get("key"),
    )
