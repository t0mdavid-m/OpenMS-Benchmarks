import subprocess
from pathlib import Path


def _image_exists(tag: str) -> bool:
    res = subprocess.run(["docker", "image", "inspect", tag],
                         capture_output=True, text=True)
    return res.returncode == 0


def _ensure_thirdparty(worktree: Path) -> None:
    """Pre-populate the THIRDPARTY submodule on the host before docker build.

    The build context is a git worktree whose .git is a linkfile to a host
    path that does not exist inside the container, so the Dockerfile's
    in-container `git submodule update --init THIRDPARTY` fails. The Dockerfile
    skips that step when THIRDPARTY/All and THIRDPARTY/Linux/<arch> already
    exist, so we populate it here. THIRDPARTY also supplies the bundled search
    engines (Sage, Comet) the workflows need.
    """
    subprocess.run(
        ["git", "-C", str(worktree), "submodule", "update",
         "--init", "--depth", "1", "THIRDPARTY"],
        check=True,
    )


def build_image(worktree: Path, sha: str, threads: int) -> str:
    worktree = Path(worktree)
    tag = f"openms-bench:{sha[:12]}"
    if _image_exists(tag):
        return tag
    dockerfile = worktree / "dockerfiles" / "Dockerfile"
    if not dockerfile.exists():
        raise FileNotFoundError(
            f"{dockerfile} missing — this ref cannot be containerized")
    _ensure_thirdparty(worktree)
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
