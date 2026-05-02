from pathlib import Path

from src.research.mempalace import build_memory_manifest, remember_memory, search_memory_palace


def test_mempalace_search_indexes_wing_room_and_markdown_snippets(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    note = vault / "agtech" / "market.md"
    note.parent.mkdir(parents=True)
    note.write_text(
        "\n".join(
            [
                "# Strawberry diagnostics",
                "농가 현장 진단키트 구매의사와 가격 저항을 기록한다.",
                "",
                "## Distribution channel",
                "농협 유통과 지역 실증 파트너가 초기 판매 채널이다.",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MUCHANIPO_MEMPALACE_ROOT", str(vault))

    results = search_memory_palace("농가 진단키트 가격", wing="agtech", limit=3)

    assert results
    first = results[0]
    assert first["source"].startswith("mempalace:agtech/market.md#")
    assert first["wing"] == "agtech"
    assert first["room"] == "Strawberry diagnostics"
    assert "진단키트" in first["text"]
    assert first["score"] > 0


def test_mempalace_search_supports_room_filter(tmp_path):
    root = tmp_path / "vault"
    page = root / "research.md"
    root.mkdir()
    page.write_text(
        "# Root\n일반 기록\n\n## Pricing Room\n가격 검증과 지불의사\n",
        encoding="utf-8",
    )

    results = search_memory_palace("가격 지불의사", room="Pricing", roots=[root])

    assert len(results) == 1
    assert results[0]["room"] == "Pricing Room"


def test_mempalace_runtime_persists_memory_and_manifest(tmp_path):
    root = tmp_path / "memory"

    saved = remember_memory(
        title="딸기 진단 가격",
        text="농가 진단키트 가격 저항과 구매 의사 기록",
        wing="agtech",
        room="pricing",
        metadata={"source": "interview"},
        root=root,
    )
    manifest = build_memory_manifest(root=root)
    results = search_memory_palace("가격 구매 의사", wing="agtech", room="pricing", roots=[root])

    assert saved["path"] == "agtech/pricing/딸기-진단-가격.md"
    assert saved["source"].startswith("mempalace:agtech/pricing/딸기-진단-가격.md#")
    assert saved["sha256"]
    assert manifest["record_count"] == 1
    assert manifest["wings"] == ["agtech"]
    assert manifest["rooms"] == ["pricing"]
    assert manifest["records"][0]["sha256"] == saved["sha256"]
    assert results
    assert results[0]["wing"] == "agtech"
    assert results[0]["room"] == "딸기 진단 가격"
