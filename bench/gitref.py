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

    Fetches first so remote branches/PR refs are available.
    """
    repo = Path(repo)
    try:
        _git(repo, "fetch", "--all", "--tags", "--quiet")
    except subprocess.CalledProcessError:
        pass  # offline: fall back to whatever objects are local
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
