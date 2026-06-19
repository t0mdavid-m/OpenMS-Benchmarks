import subprocess
from pathlib import Path


def _image_exists(tag: str) -> bool:
    res = subprocess.run(["docker", "image", "inspect", tag],
                         capture_output=True, text=True)
    return res.returncode == 0


def build_image(worktree: Path, sha: str, threads: int) -> str:
    worktree = Path(worktree)
    tag = f"openms-bench:{sha[:12]}"
    if _image_exists(tag):
        return tag
    dockerfile = worktree / "dockerfiles" / "Dockerfile"
    if not dockerfile.exists():
        raise FileNotFoundError(
            f"{dockerfile} missing — this ref cannot be containerized")
    subprocess.run(
        ["docker", "build",
         "-f", str(dockerfile),
         "--target", "tools-thirdparty",
         "--build-arg", f"NUM_BUILD_CORES={threads}",
         "-t", tag,
         str(worktree)],
        check=True,
    )
    return tag
