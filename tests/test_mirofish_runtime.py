from types import SimpleNamespace

from src.agents.mirofish import build_mirofish_runtime_record, validate_mirofish_runtime_record
from src.evidence.artifact import EvidenceRef


def test_mirofish_runtime_records_full_local_workflow():
    report = SimpleNamespace(
        id="report-1",
        title="딸기 진단키트 수요 예측",
        confidence=0.72,
        evidence_refs=[
            EvidenceRef(
                id="ref-1",
                source_url="https://doi.org/10.1234/example",
                source_title="Example evidence",
                quote="market evidence",
                source_grade="A",
                provenance={"kind": "openalex", "source": "https://doi.org/10.1234/example"},
            )
        ],
    )
    council = SimpleNamespace(
        personas=[
            {"persona_id": "buyer", "name": "농가 구매자", "role": "buyer", "manifest": {"memory": ["price"]}},
            {"persona_id": "auditor", "name": "근거 감사자", "role": "auditor"},
        ],
        rounds=[SimpleNamespace(layer_id="market"), SimpleNamespace(layer_id="risk")],
        turn_transcript=[
            {"round": 1, "stage": "individual", "persona_id": "buyer", "prompt_chars": 50, "response_chars": 80},
            {"round": 1, "stage": "peer_review", "persona_id": "auditor", "prompt_chars": 60, "response_chars": 90},
        ],
    )

    record = build_mirofish_runtime_record(report=report, council=council)

    assert validate_mirofish_runtime_record(record)
    assert record["valid"] is True
    assert record["upstream"]["license"] == "AGPL-3.0"
    assert record["workflow_phases"] == [
        "graph_building",
        "environment_setup",
        "simulation",
        "report_generation",
        "deep_interaction",
    ]
    assert record["graph_building"]["seed_material_count"] == 1
    assert record["graph_building"]["world_node_count"] >= 4
    assert record["graph_building"]["world_edge_count"] >= 3
    assert record["environment_setup"]["agent_count"] == 2
    assert record["simulation"]["turn_count"] == 2
    assert record["simulation"]["temporal_memory_updates"]
    assert record["report_generation"]["report_agent_ready"] is True
    assert record["deep_interaction"]["ready"] is True
