from pathlib import Path

from bench.config import load_config


def test_load_config_reads_values(tmp_path: Path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text(
        'openms_repo = "OpenMS"\n'
        'threads = 4\n'
        'http_base = "https://archive.openms.org/openms/benchmarks/pride-benchmarks/"\n'
        '[rsync]\n'
        'user = "u"\n'
        'host = "h"\n'
        'port = 22\n'
        'key = "k"\n',
        encoding="utf-8",
    )
    cfg = load_config(cfg_file)
    assert cfg.threads == 4
    assert cfg.openms_repo == Path("OpenMS")
    assert cfg.rsync_user == "u"
    assert cfg.rsync_port == 22
    assert cfg.http_base == "https://archive.openms.org/openms/benchmarks/pride-benchmarks/"
    assert cfg.rsync_host == "h"
    assert cfg.rsync_key == "k"


def test_load_config_rsync_optional(tmp_path: Path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text('openms_repo = "OpenMS"\nthreads = 2\n', encoding="utf-8")
    cfg = load_config(cfg_file)
    assert cfg.rsync_user is None
    assert cfg.threads == 2
    assert cfg.http_base.startswith("https://")
