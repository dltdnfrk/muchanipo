"""Worker별 Git worktree 생성/정리 유틸리티."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path


class WorktreeError(RuntimeError):
    """Worktree 작업 실패."""


class WorktreeExistsError(WorktreeError):
    """이미 예약되었거나 생성된 worker worktree."""


_SAFE_COMPONENT = re.compile(r"[^A-Za-z0-9_.-]+")


def _clean_component(value: str, label: str) -> str:
    cleaned = _SAFE_COMPONENT.sub("-", value.strip()).strip(".-")
    if not cleaned:
        raise ValueError(f"{label} must contain at least one safe character")
    return cleaned


class WorktreeManager:
    """
    팀 worker별 독립 Git worktree를 관리한다.

    경로 규칙:
      .omc/team/<team>/worktrees/<worker>/

    같은 worker_id를 동시에 create할 때는 .locks/<worker> 디렉토리 생성을
    atomic reservation으로 사용한다.
    """

    def __init__(
        self,
        repo_root: Path | str | None = None,
        team: str = "default",
        base_ref: str = "HEAD",
        state_root: Path | str | None = None,
    ) -> None:
        self.repo_root = Path(repo_root or Path.cwd()).resolve()
        self.team = _clean_component(team, "team")
        self.base_ref = base_ref
        self.worktrees_root = (
            Path(state_root).resolve()
            if state_root is not None
            else self.repo_root / ".omc" / "team" / self.team / "worktrees"
        )
        self.locks_root = self.worktrees_root / ".locks"

    def create(self, worker_id: str) -> Path:
        """worker_id에 대응하는 detached Git worktree를 생성하고 경로를 반환한다."""
        worker = _clean_component(worker_id, "worker_id")
        worktree_path = self.worktrees_root / worker
        lock_path = self.locks_root / worker

        self.worktrees_root.mkdir(parents=True, exist_ok=True)
        self.locks_root.mkdir(parents=True, exist_ok=True)

        try:
            lock_path.mkdir()
        except FileExistsError as exc:
            raise WorktreeExistsError(f"worktree already reserved: {worker}") from exc

        if worktree_path.exists():
            self._remove_lock(lock_path)
            raise WorktreeExistsError(f"worktree already exists: {worker}")

        try:
            self._git("worktree", "add", "--detach", str(worktree_path), self.base_ref)
        except WorktreeError:
            self._remove_lock(lock_path)
            if worktree_path.exists():
                shutil.rmtree(worktree_path, ignore_errors=True)
            raise

        return worktree_path

    def cleanup(self, worker_id: str) -> None:
        """worker worktree와 reservation lock을 정리한다."""
        worker = _clean_component(worker_id, "worker_id")
        worktree_path = self.worktrees_root / worker
        lock_path = self.locks_root / worker

        if worktree_path.exists():
            try:
                self._git("worktree", "remove", "--force", str(worktree_path))
            except WorktreeError:
                shutil.rmtree(worktree_path, ignore_errors=True)
            self._git("worktree", "prune", check=False)

        self._remove_lock(lock_path)

    def list_active(self) -> dict[str, Path]:
        """현재 관리 루트 아래 active worker worktree 목록을 반환한다."""
        if not self.worktrees_root.exists():
            return {}

        active: dict[str, Path] = {}
        for path in sorted(self.worktrees_root.iterdir()):
            if not path.is_dir() or path.name == ".locks":
                continue
            active[path.name] = path
        return active

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["git", "-C", str(self.repo_root), *args],
            capture_output=True,
            text=True,
            check=False,
        )
        if check and result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip()
            raise WorktreeError(f"git {' '.join(args)} failed: {detail}")
        return result

    @staticmethod
    def _remove_lock(lock_path: Path) -> None:
        shutil.rmtree(lock_path, ignore_errors=True)
