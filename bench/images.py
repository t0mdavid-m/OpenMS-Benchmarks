import subprocess
from pathlib import Path

from bench.config import Config, ImageSpec
from bench.gitref import checkout_worktree, resolve_ref


def image_tag(spec: ImageSpec, resolved_ref: str | None) -> str:
    if spec.kind == "pull":
        return spec.pull_ref
    if not resolved_ref:
        raise ValueError("build image requires a resolved 40-char ref")
    return f"openms-bench:{resolved_ref[:12]}"


def plan_build_command(spec: ImageSpec, worktree: Path, tag: str) -> list[str]:
    dockerfile = worktree / spec.dockerfile
    cmd = ["docker", "build", "-f", str(dockerfile),
           "--target", spec.target]
    for k, v in spec.build_args.items():
        cmd += ["--build-arg", f"{k}={v}"]
    cmd += ["-t", tag, str(worktree)]
    return cmd


def _image_exists(tag: str) -> bool:
    res = subprocess.run(["docker", "image", "inspect", tag],
                         capture_output=True, text=True)
    return res.returncode == 0


def _ensure_thirdparty(worktree: Path) -> None:
    # The worktree .git is a linkfile invisible in-container, so the Dockerfile's
    # in-container submodule init fails; pre-populate THIRDPARTY on the host. It
    # also supplies the bundled engines (Sage, Comet, MS-GF+).
    subprocess.run(["git", "-C", str(worktree), "submodule", "update",
                    "--init", "--depth", "1", "THIRDPARTY"],
                   check=True, timeout=1800)


def materialize_image(spec: ImageSpec, cfg: Config,
                      ref_override: str | None) -> str:
    if spec.kind == "pull":
        if not _image_exists(spec.pull_ref):
            subprocess.run(["docker", "pull", spec.pull_ref], check=True,
                           timeout=cfg.build_timeout_s)
        return spec.pull_ref

    ref = ref_override or spec.ref
    sha = resolve_ref(cfg.openms_repo, ref)
    tag = image_tag(spec, sha)
    if _image_exists(tag):
        return tag
    worktree = checkout_worktree(cfg.openms_repo, sha, Path(f"{sha[:12]}.worktree"))
    if not (worktree / spec.dockerfile).exists():
        raise FileNotFoundError(
            f"{worktree / spec.dockerfile} missing — ref cannot be containerized")
    _ensure_thirdparty(worktree)
    try:
        subprocess.run(plan_build_command(spec, worktree, tag),
                       check=True, timeout=cfg.build_timeout_s)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"docker build exceeded {cfg.build_timeout_s}s for {tag}") from e
    return tag
