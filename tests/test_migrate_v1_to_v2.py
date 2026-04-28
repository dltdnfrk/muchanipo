from pathlib import Path

from conftest import load_script_module


migration = load_script_module("migrate_v1_to_v2", "scripts/migrate_v1_to_v2.py")


def _write_fixture_vault(root: Path) -> Path:
    vault = root / "vault"
    (vault / "personas").mkdir(parents=True)
    (vault / "insights").mkdir()
    (vault / "wiki").mkdir()
    (vault / "personas" / "operator.md").write_text(
        "---\n"
        "title: Operator\n"
        "role: farmer\n"
        "---\n"
        "# Operator\n",
        encoding="utf-8",
    )
    (vault / "insights" / "market.md").write_text(
        "---\n"
        "title: Market\n"
        "scores:\n"
        "  usefulness: 8\n"
        "  reliability: 7\n"
        "  novelty: 6\n"
        "  actionability: 5\n"
        "  completeness: 4\n"
        "  evidence_quality: 7\n"
        "  perspective_diversity: 6\n"
        "  coherence: 8\n"
        "  depth: 7\n"
        "  impact: 6\n"
        "rubric_max: 100\n"
        "---\n"
        "# Market\n",
        encoding="utf-8",
    )
    (vault / "cost-log.jsonl").write_text(
        '{"event":"reserved","status":"reserved","estimated_usd":0.1}\n',
        encoding="utf-8",
    )
    return vault


def test_migrate_v1_to_v2_dry_run_does_not_write(tmp_path):
    vault = _write_fixture_vault(tmp_path)

    result = migration.migrate_vault(vault, dry_run=True)

    assert result.changed_count == 3
    assert result.backup_dir is None
    assert not list(tmp_path.glob("vault.bak.*"))
    assert "value_axes:" not in (vault / "personas" / "operator.md").read_text(encoding="utf-8")
    assert "citation_fidelity" not in (vault / "insights" / "market.md").read_text(encoding="utf-8")


def test_migrate_v1_to_v2_adds_frontmatter_and_backup(tmp_path):
    vault = _write_fixture_vault(tmp_path)

    result = migration.migrate_vault(vault)

    assert result.changed_count == 3
    assert result.backup_dir is not None
    assert result.backup_dir.exists()
    assert (result.backup_dir / "personas" / "operator.md").exists()

    persona = (vault / "personas" / "operator.md").read_text(encoding="utf-8")
    assert "value_axes:\n" in persona
    assert "time_horizon: \"mid\"\n" in persona
    assert "risk_tolerance: 0.5\n" in persona
    assert 'stakeholder_priority: ["primary", "secondary", "tertiary"]\n' in persona
    assert "innovation_orientation: 0.5\n" in persona

    insight = (vault / "insights" / "market.md").read_text(encoding="utf-8")
    assert "citation_fidelity: 0\n" in insight
    assert "density: 0\n" in insight
    assert "coverage_breadth: 0\n" in insight
    assert "rubric_max: 130\n" in insight

    index = (vault / "wiki" / "index.md").read_text(encoding="utf-8")
    assert "| [personas/operator.md](../personas/operator.md) | personas | Operator |" in index
    assert "| [insights/market.md](../insights/market.md) | insights | Market |" in index


def test_migrate_v1_to_v2_is_idempotent(tmp_path):
    vault = _write_fixture_vault(tmp_path)

    first = migration.migrate_vault(vault)
    persona_after_first = (vault / "personas" / "operator.md").read_text(encoding="utf-8")
    insight_after_first = (vault / "insights" / "market.md").read_text(encoding="utf-8")
    index_after_first = (vault / "wiki" / "index.md").read_text(encoding="utf-8")

    second = migration.migrate_vault(vault)

    assert first.changed_count == 3
    assert second.changed_count == 0
    assert second.backup_dir is None
    assert (vault / "personas" / "operator.md").read_text(encoding="utf-8") == persona_after_first
    assert (vault / "insights" / "market.md").read_text(encoding="utf-8") == insight_after_first
    assert (vault / "wiki" / "index.md").read_text(encoding="utf-8") == index_after_first
    assert len(list(tmp_path.glob("vault.bak.*"))) == 1


def test_migrate_v1_to_v2_reports_cost_log_warnings(tmp_path):
    vault = _write_fixture_vault(tmp_path)
    (vault / "cost-log.jsonl").write_text('{"event":"reserved"}\nnot-json\n', encoding="utf-8")

    result = migration.migrate_vault(vault, dry_run=True)

    assert any("missing status" in warning for warning in result.warnings)
    assert any("invalid cost-log json" in warning for warning in result.warnings)


def test_migrate_v1_to_v2_skips_unsupported_yaml_without_rewriting(tmp_path):
    vault = _write_fixture_vault(tmp_path)
    persona = vault / "personas" / "operator.md"
    original = (
        "---\n"
        "title: Operator\n"
        "aliases:\n"
        "  - Field Ops\n"
        "---\n"
        "# Operator\n"
    )
    persona.write_text(original, encoding="utf-8")

    result = migration.migrate_vault(vault, dry_run=True)

    assert persona.read_text(encoding="utf-8") == original
    assert any("unsupported frontmatter skipped" in warning for warning in result.warnings)
