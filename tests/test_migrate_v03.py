import csv
import json
from pathlib import Path

from src.migrate.v03_to_v04 import (
    BACKUP_SUFFIX,
    migrate_results_tsv,
    migrate_signoff_queue,
    migrate_vault,
    rollback,
    run_migration,
)


def _write_results(path: Path) -> None:
    path.write_text(
        "id\ttopic\tscore\n"
        "r1\t시장 검증\t72\n"
        "r2\t제품 전략\t81\n",
        encoding="utf-8",
    )


def _read_tsv(path: Path):
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def test_results_tsv_dry_run_does_not_write(tmp_path):
    results = tmp_path / "results.tsv"
    _write_results(results)

    result = migrate_results_tsv(results, dry_run=True)

    assert result.changed == [f"would update {results}"]
    assert "rubric_version" not in results.read_text(encoding="utf-8")
    assert not Path(str(results) + BACKUP_SUFFIX).exists()


def test_results_tsv_adds_rubric_version_and_can_rollback(tmp_path):
    results = tmp_path / "results.tsv"
    _write_results(results)

    migrate_results_tsv(results)

    rows = _read_tsv(results)
    assert [row["rubric_version"] for row in rows] == ["2.0.0", "2.0.0"]
    assert Path(str(results) + BACKUP_SUFFIX).exists()

    rollback([results])

    assert "rubric_version" not in results.read_text(encoding="utf-8")
    assert not Path(str(results) + BACKUP_SUFFIX).exists()


def test_vault_frontmatter_receives_v04_unknown_grounding(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    page = vault / "note.md"
    page.write_text(
        "---\n"
        "title: Sample\n"
        "confidence: 0.61\n"
        "---\n"
        "# Sample\n",
        encoding="utf-8",
    )

    result = migrate_vault(vault)

    assert result.changed == [f"updated {page}"]
    text = page.read_text(encoding="utf-8")
    assert "schema_version: v04\n" in text
    assert "citation_grounding_unknown: true\n" in text


def test_signoff_queue_json_receives_schema_version(tmp_path):
    queue = tmp_path / "signoff-queue"
    queue.mkdir()
    entry = queue / "sq-1.json"
    entry.write_text(json.dumps({"id": "sq-1", "status": "pending"}), encoding="utf-8")

    result = migrate_signoff_queue(queue)

    assert result.changed == [f"updated {entry}"]
    assert json.loads(entry.read_text(encoding="utf-8"))["schema_version"] == "v04"


def test_run_migration_dry_run_reports_fake_fixture_without_changes(tmp_path):
    results = tmp_path / "results.tsv"
    _write_results(results)
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "page.md").write_text("---\ntitle: Page\n---\n# Page\n", encoding="utf-8")
    queue = tmp_path / "signoff-queue"
    queue.mkdir()
    (queue / "sq-1.json").write_text('{"id":"sq-1"}\n', encoding="utf-8")

    result = run_migration(results, vault, queue, dry_run=True)

    assert len(result.changed) == 3
    assert "rubric_version" not in results.read_text(encoding="utf-8")
    assert "schema_version: v04" not in (vault / "page.md").read_text(encoding="utf-8")
    assert json.loads((queue / "sq-1.json").read_text(encoding="utf-8")) == {"id": "sq-1"}

