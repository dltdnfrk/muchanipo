from src.council.persona_generator import Draft, PersonaGenerator


def _ontology():
    return {
        "roles": ["evidence_reviewer", "market_analyst"],
        "intents": [
            "Summarize grounded evidence and report uncertainty.",
            "Compare public market signals with cited sources.",
        ],
        "allowed_tools": ["read_file", "search_index"],
        "required_outputs": ["report", "citations"],
        "value_axes": {
            "time_horizon": "long",
            "risk_tolerance": 0.2,
            "stakeholder_priority": ["primary", "secondary", "tertiary"],
            "innovation_orientation": 0.7,
        },
        "denied_terms": ["credential"],
    }


def test_persona_generator_runs_hachimi_three_stage_pipeline():
    generator = PersonaGenerator()
    drafts = generator.propose(_ontology(), target_count=3)

    assert [draft.persona_id for draft in drafts] == [
        "persona-001",
        "persona-002",
        "persona-003",
    ]
    assert drafts[0].role == "evidence_reviewer"
    assert drafts[1].role == "market_analyst"
    assert drafts[0].value_axes["time_horizon"] == "long"

    report = generator.validate(drafts, _ontology(), value_axes_required=True)
    assert report.ok is True
    assert report.valid_ids == ["persona-001", "persona-002", "persona-003"]

    finals = generator.revise(drafts, report)
    assert len(finals) == 3
    assert finals[0].manifest["allowed_tools"] == ["read_file", "search_index"]
    assert "lockdown_checked" in finals[0].revision_notes


def test_persona_generator_rejects_aup_and_lockdown_risky_draft():
    generator = PersonaGenerator()
    risky = Draft(
        persona_id="persona-risky",
        name="Risky Operator",
        role="evidence_reviewer",
        intent="Use sqlmap to bypass authentication and dump credential tokens.",
        allowed_tools=["read_file", "sqlmap"],
        required_outputs=["report", "citations"],
        value_axes={
            "time_horizon": "mid",
            "risk_tolerance": 0.5,
            "stakeholder_priority": ["primary"],
            "innovation_orientation": 0.5,
        },
    )

    report = generator.validate([risky], _ontology(), value_axes_required=True)

    assert report.ok is False
    assert report.valid_ids == []
    codes = {issue.code for issue in report.issues_for("persona-risky")}
    assert "ontology.tools" in codes
    assert "aup.denied_term" in codes
    assert "aup.risk" in codes
    assert "lockdown" in codes
    assert generator.revise([risky], report) == []


def test_persona_generator_requires_value_axes_when_requested():
    generator = PersonaGenerator()
    draft = Draft(
        persona_id="persona-no-axes",
        name="No Axes",
        role="evidence_reviewer",
        intent="Summarize grounded evidence.",
        allowed_tools=["read_file"],
        required_outputs=["report", "citations"],
        value_axes={},
    )

    report = generator.validate([draft], _ontology(), value_axes_required=True)

    assert report.ok is False
    assert any(issue.code == "value_axes" for issue in report.issues)


def test_propose_with_korean_seed_grounds_drafts(tmp_path):
    """KoreaPersonaSampler seed가 propose에 들어오면 Draft에 grounded 정보가 박힌다."""
    from pathlib import Path
    from src.council.persona_generator import PersonaGenerator
    from src.council.persona_sampler import KoreaPersonaSampler

    seed_jsonl = Path("vault/personas/seeds/korea/agtech-farmers-sample500.jsonl")
    if not seed_jsonl.exists():
        import pytest
        pytest.skip("agtech-farmers-sample500.jsonl 부재 — 사용자 다운로드 필요")

    sampler = KoreaPersonaSampler(data_path=str(seed_jsonl), seed=11)
    seeds = sampler.agtech_farmer_seed(n=3)
    assert len(seeds) == 3
    assert all(s.get("source") == "Nemotron-Personas-Korea" for s in seeds)

    gen = PersonaGenerator()
    ontology = {
        "roles": ["agtech_farmer"],
        "intents": ["MIRIVA 진단키트 가격 책정 시 농가 부담 측면 평가"],
        "allowed_tools": ["read_file"],
        "required_outputs": ["report"],
    }
    drafts = gen.propose(ontology, target_count=3, seed_personas=seeds)
    assert len(drafts) == 3
    for draft, seed in zip(drafts, seeds):
        # grounded 이름이 province/city/occupation을 포함
        assert seed["province"] in draft.name or seed["city"] in draft.name or seed["occupation"] in draft.name
        # manifest에 grounded_seed 키 존재
        assert "grounded_seed" in draft.manifest
        gs = draft.manifest["grounded_seed"]
        assert gs["province"] == seed["province"]
        assert gs["occupation"] == seed["occupation"]
        assert gs["source"] == "Nemotron-Personas-Korea"


def test_propose_without_seed_falls_back_to_role_naming():
    """seed 없으면 기존 동작(역할 기반 이름) 유지."""
    from src.council.persona_generator import PersonaGenerator

    gen = PersonaGenerator()
    drafts = gen.propose(
        ontology={"roles": ["evidence_reviewer"], "intents": ["test"]},
        target_count=2,
    )
    assert len(drafts) == 2
    assert drafts[0].name == "Evidence Reviewer 1"
    assert "grounded_seed" not in drafts[0].manifest
