import os
import shutil
import subprocess
from pathlib import Path


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


def resolve_ref(repo: Path, ref: str) -> str:
    """Resolve a branch name or SHA to a full 40-char commit SHA.

    Resolves locally first to avoid unnecessary network fetches and the
    interactive-prompt hangs they can cause in non-interactive shells (e.g.
    an ssh host-key or credential prompt with no TTY). Only when the ref is
    not present locally does it fetch — bounded by a timeout and forced
    non-interactive so it can never hang.
    """
    repo = Path(repo)
    try:
        return _git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}")
    except subprocess.CalledProcessError:
        pass
    env = {**os.environ, "GIT_SSH_COMMAND":
           "ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15"}
    try:
        subprocess.run(
            ["git", "-C", str(repo), "fetch", "--all", "--tags", "--quiet"],
            check=False, timeout=180, env=env, capture_output=True, text=True,
        )
    except subprocess.TimeoutExpired:
        pass
    return _git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}")


def checkout_worktree(repo: Path, sha: str, dest: Path) -> Path:
    """Create a clean detached worktree at `dest` checked out at `sha`."""
    repo = Path(repo)
    dest = Path(dest).resolve()
    if dest.exists():
        # Remove a stale worktree registration then the dir.
        subprocess.run(["git", "-C", str(repo), "worktree", "remove",
                        "--force", str(dest)], capture_output=True, text=True)
        if dest.exists():
            shutil.rmtree(dest)
    _git(repo, "worktree", "add", "--detach", "--force", str(dest), sha)
    return dest
