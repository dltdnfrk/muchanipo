from concurrent.futures import ThreadPoolExecutor

from conftest import load_script_module


def test_orchestrator_paths_are_project_root_relative(repo_root):
    orchestrator = load_script_module("orchestrator", "src/runtime/orchestrator.py")

    assert orchestrator.PROJECT_ROOT == repo_root
    assert orchestrator.PROGRAM_MD == repo_root / "config" / "program.md"
    assert orchestrator.WIKI_LOG == repo_root / "wiki" / "log.md"
    assert orchestrator.RAW_DIR == repo_root / "raw"
    assert orchestrator.LOGS_DIR == repo_root / "logs"
    assert orchestrator.INGEST_SCRIPT == repo_root / "src" / "ingest" / "muchanipo-ingest.py"
    assert orchestrator.INSIGHT_SCRIPT == repo_root / "src" / "search" / "insight-forge.py"
    assert orchestrator.COUNCIL_SCRIPT == repo_root / "src" / "council" / "council-runner.py"
    assert orchestrator.EVAL_SCRIPT == repo_root / "src" / "eval" / "eval-agent.py"
    assert orchestrator.VAULT_SCRIPT == repo_root / "src" / "hitl" / "vault-router.py"


def test_acquire_lock_allows_only_one_concurrent_owner(monkeypatch, tmp_path):
    orchestrator = load_script_module("orchestrator_lock_race", "src/runtime/orchestrator.py")
    monkeypatch.setattr(orchestrator, "LOCK_FILE", tmp_path / ".orchestrator.lock")

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: orchestrator.acquire_lock(), range(8)))

    assert results.count(True) == 1
    assert results.count(False) == 7
    assert orchestrator.LOCK_FILE.read_text(encoding="utf-8").strip()

    orchestrator.release_lock()
    assert not orchestrator.LOCK_FILE.exists()


def test_acquire_lock_replaces_stale_lock(monkeypatch, tmp_path):
    orchestrator = load_script_module("orchestrator_stale_lock", "src/runtime/orchestrator.py")
    lock_file = tmp_path / ".orchestrator.lock"
    lock_file.write_text("999999999", encoding="utf-8")
    monkeypatch.setattr(orchestrator, "LOCK_FILE", lock_file)

    assert orchestrator.acquire_lock() is True
    assert int(lock_file.read_text(encoding="utf-8")) == orchestrator.os.getpid()

    orchestrator.release_lock()
