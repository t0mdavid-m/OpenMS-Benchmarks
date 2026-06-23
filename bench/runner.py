import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from bench.config import Benchmark, Config


def _host_path(p: Path) -> str:
    return str(Path(p).resolve()).replace("\\", "/")


def _container_name(image_tag: str, benchmark: str) -> str:
    raw = f"bench-{image_tag}-{benchmark}"
    return re.sub(r"[^A-Za-z0-9_.-]", "-", raw)[:120]


def build_run_command(image_tag, scripts_dir, input_dir, out_dir, run_rel,
                      threads, container_name) -> list[str]:
    inner = f"bash /work/{run_rel}"
    return [
        "docker", "run", "--rm", "--name", container_name,
        "-v", f"{_host_path(scripts_dir)}:/work:ro",
        "-v", f"{_host_path(input_dir)}:/input:ro",
        "-v", f"{_host_path(out_dir)}:/out",
        "-e", "INPUT_DIR=/input",
        "-e", "OUT_DIR=/out",
        "-e", "WORK=/work",
        "-e", "OPENMS_BIN=/opt/OpenMS/bin",
        "-e", f"THREADS={threads}",
        image_tag, "bash", "-c", inner,
    ]


@dataclass
class RunResult:
    out_dir: Path
    returncode: int
    outer_wall_s: float


def run_benchmark(image_tag: str, benchmark: Benchmark, cfg: Config,
                  out_dir: Path) -> RunResult:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    name = _container_name(image_tag, benchmark.name)
    cmd = build_run_command(image_tag, cfg.scripts_dir, benchmark.input, out_dir,
                            benchmark.run, cfg.threads, name)
    log_path = out_dir / "error.log"
    start = time.monotonic()
    with log_path.open("w", encoding="utf-8") as log:
        try:
            proc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT,
                                  timeout=cfg.run_timeout_s)
            rc = proc.returncode
        except subprocess.TimeoutExpired:
            subprocess.run(["docker", "kill", name], capture_output=True)
            return RunResult(out_dir, 124, time.monotonic() - start)
    return RunResult(out_dir, rc, time.monotonic() - start)
