import subprocess
from pathlib import Path

import pytest

from bench.gitref import resolve_ref, checkout_worktree


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


@pytest.fixture
def tiny_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "f.txt").write_text("hi", encoding="utf-8")
    _git(repo, "add", "f.txt")
    _git(repo, "commit", "-m", "c1")
    return repo


def test_resolve_ref_returns_full_sha(tiny_repo: Path):
    sha = resolve_ref(tiny_repo, "main")
    assert len(sha) == 40
    assert sha == _git(tiny_repo, "rev-parse", "main")


def test_checkout_worktree_materializes_tree(tiny_repo: Path, tmp_path: Path):
    sha = resolve_ref(tiny_repo, "main")
    dest = tmp_path / "wt"
    checkout_worktree(tiny_repo, sha, dest)
    assert (dest / "f.txt").read_text(encoding="utf-8") == "hi"
    assert (dest / ".git").exists()  # worktree has a .git link file


def test_resolve_ref_accepts_raw_sha(tiny_repo: Path):
    sha = resolve_ref(tiny_repo, "main")
    # Passing a raw SHA must return the same SHA (constraint: branches AND SHAs).
    assert resolve_ref(tiny_repo, sha) == sha


def test_checkout_worktree_idempotent_when_dest_exists(tiny_repo: Path, tmp_path: Path):
    sha = resolve_ref(tiny_repo, "main")
    dest = tmp_path / "wt"
    checkout_worktree(tiny_repo, sha, dest)
    # Second call on an existing dest must succeed (stale-worktree safety).
    checkout_worktree(tiny_repo, sha, dest)
    assert (dest / "f.txt").read_text(encoding="utf-8") == "hi"


def test_checkout_worktree_relative_dest_resolved_absolute(tiny_repo: Path, tmp_path: Path, monkeypatch):
    sha = resolve_ref(tiny_repo, "main")
    workdir = tmp_path / "cwd"
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    returned = checkout_worktree(tiny_repo, sha, Path("rel.worktree"))
    # Returned path must be absolute and live under the cwd, NOT inside the repo.
    assert returned.is_absolute()
    assert (workdir / "rel.worktree" / "f.txt").read_text(encoding="utf-8") == "hi"
    assert not (tiny_repo / "rel.worktree").exists()


def test_resolve_ref_local_first_ignores_unreachable_remote(tiny_repo: Path):
    # A bogus, unreachable remote must NOT block resolving a LOCAL ref.
    _git(tiny_repo, "remote", "add", "origin", "git@example.invalid:nope/nope.git")
    sha = resolve_ref(tiny_repo, "main")  # resolves locally, no fetch needed
    assert len(sha) == 40
