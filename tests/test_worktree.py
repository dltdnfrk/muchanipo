import shutil
import subprocess
import threading
from pathlib import Path

import pytest

from src.runtime.worktree import WorktreeExistsError, WorktreeManager


pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git is required")


def _run_git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git(repo, "init")
    _run_git(repo, "config", "user.email", "test@example.com")
    _run_git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("# test\n", encoding="utf-8")
    _run_git(repo, "add", "README.md")
    _run_git(repo, "commit", "-m", "initial")
    return repo


def test_create_cleanup_and_list_active(tmp_path):
    repo = _init_repo(tmp_path)
    manager = WorktreeManager(repo_root=repo, team="alpha")

    path = manager.create("worker-1")

    assert path == repo / ".omc" / "team" / "alpha" / "worktrees" / "worker-1"
    assert (path / "README.md").read_text(encoding="utf-8") == "# test\n"
    assert manager.list_active() == {"worker-1": path}

    manager.cleanup("worker-1")

    assert not path.exists()
    assert manager.list_active() == {}


def test_duplicate_worker_is_rejected_by_atomic_lock(tmp_path):
    repo = _init_repo(tmp_path)
    manager = WorktreeManager(repo_root=repo, team="race")

    first = manager.create("worker-1")

    with pytest.raises(WorktreeExistsError):
        manager.create("worker-1")

    manager.cleanup("worker-1")
    assert not first.exists()


def test_concurrent_create_allows_only_one_winner(tmp_path):
    repo = _init_repo(tmp_path)
    manager = WorktreeManager(repo_root=repo, team="race")
    barrier = threading.Barrier(2)
    results: list[str] = []

    def create_same_worker() -> None:
        barrier.wait()
        try:
            manager.create("worker-1")
            results.append("created")
        except WorktreeExistsError:
            results.append("exists")

    threads = [threading.Thread(target=create_same_worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(results) == ["created", "exists"]
    assert list(manager.list_active()) == ["worker-1"]
    manager.cleanup("worker-1")
