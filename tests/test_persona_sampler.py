import json

from src.council.persona_sampler import KoreaPersonaSampler, NEMOTRON_KOREA_FIELDS


def test_sample_filters_records_by_province_and_occupation():
    records = [
        {
            "persona_id": "p1",
            "province": "경상북도",
            "sigungu": "상주시",
            "occupation": "사과 농가",
            "goals": "스마트 관수 비용을 낮추고 싶다",
        },
        {
            "persona_id": "p2",
            "province": "서울특별시",
            "sigungu": "마포구",
            "occupation": "마케터",
        },
    ]
    sampler = KoreaPersonaSampler(records=records, seed=7)

    result = sampler.sample(n=5, filter={"province": "경상북도", "occupation": "농가"})

    assert [persona["persona_id"] for persona in result] == ["p1"]
    assert result[0]["source"] == "Nemotron-Personas-Korea"
    assert "상주시" in result[0]["persona"]


def test_sample_loads_jsonl_export(tmp_path):
    path = tmp_path / "korea.jsonl"
    rows = [
        {"persona_id": "p1", "province": "전라남도", "occupation": "시설재배 농업인"},
        {"persona_id": "p2", "province": "강원특별자치도", "occupation": "관광업"},
    ]
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows), encoding="utf-8")

    sampler = KoreaPersonaSampler(data_path=path)

    result = sampler.sample(n=2, filter={"occupation": "농업"})

    assert len(result) == 1
    assert result[0]["persona_id"] == "p1"


def test_missing_data_uses_safe_fallback_personas(tmp_path):
    sampler = KoreaPersonaSampler(data_path=tmp_path / "missing.parquet")

    result = sampler.sample(n=3, filter={"province": "충청남도", "occupation": "농가"})

    assert len(result) == 3
    assert all(persona["source"] == "synthetic-fallback" for persona in result)
    assert all(persona["province"] == "충청남도" for persona in result)
    assert all(persona["occupation"] == "농가" for persona in result)
    assert set(NEMOTRON_KOREA_FIELDS).issubset(result[0].keys())


def test_agtech_farmer_seed_prefers_farmer_records():
    sampler = KoreaPersonaSampler(
        records=[
            {"persona_id": "p1", "occupation": "축산 농업인", "industry": "농업"},
            {"persona_id": "p2", "occupation": "도시 기획자", "industry": "공공"},
        ]
    )

    result = sampler.agtech_farmer_seed(n=10)

    assert [persona["persona_id"] for persona in result] == ["p1"]
