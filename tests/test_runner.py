from pathlib import Path

from bench.runner import _container_name, build_run_command


def test_container_name_is_sanitized():
    n = _container_name("openms-bench:abc123", "comet-perc")
    assert " " not in n and ":" not in n
    assert n.startswith("bench-")


def test_build_run_command_mounts_and_env():
    cmd = build_run_command(
        image_tag="openms-bench:abc123",
        scripts_dir=Path("/repo/scripts"),
        input_dir=Path("/repo/data/pb"),
        out_dir=Path("/repo/results/runs/abc123/comet/pb"),
        run_rel="openms/comet.sh",
        threads=4,
        container_name="bench-x",
    )
    joined = " ".join(cmd)
    assert "/work:ro" in joined and "/input:ro" in joined and ":/out" in joined
    assert "INPUT_DIR=/input" in cmd and "OUT_DIR=/out" in cmd and "WORK=/work" in cmd
    assert "THREADS=4" in cmd
    assert "bash /work/openms/comet.sh" in joined
    assert cmd[0:3] == ["docker", "run", "--rm"]
