import json

from src.council.persona_sampler import (
    KoreaPersonaSampler,
    NEMOTRON_KOREA_FIELDS,
    nemotron_korea_dataset_metadata,
)


def test_dataset_metadata_preserves_ngc_and_hf_boundaries_without_download():
    metadata = nemotron_korea_dataset_metadata()

    assert metadata["ngc"]["resource"] == "nemotron-personas-dataset-ko_kr"
    assert metadata["ngc"]["version"] == "0.0.1"
    assert metadata["ngc"]["license"] == "NVIDIA Dataset License Agreement"
    assert metadata["huggingface"]["dataset_id"] == "nvidia/Nemotron-Personas-Korea"
    assert metadata["huggingface"]["license"] == "cc-by-4.0"
    assert metadata["access"]["download_required"] is False
    assert metadata["access"]["large_dataset_bytes"] > 1_000_000_000
    assert metadata["schema"]["hf_feature_count"] == 26
    assert metadata["schema"]["ngc_extended_documented_field_count"] == 51
    assert metadata["integration_boundary"] == "metadata_adapter_only_no_dataset_download"


def test_sample_normalizes_public_hf_schema_without_vertical_defaults():
    sampler = KoreaPersonaSampler(
        records=[
            {
                "uuid": "03b4f36a18e6469386d0286dddd513c8",
                "province": "광주",
                "district": "광주-서구",
                "sex": "남자",
                "age": 74,
                "occupation": "하역 및 적재 관련 단순 종사원",
                "education_level": "초등학교",
                "persona": "광주 서구에서 평생 하역 일을 하며 살아온 70대 가장",
                "career_goals_and_ambitions": "건강을 유지하며 생활비를 마련하고 싶다",
            }
        ]
    )

    result = sampler.sample(n=1, filter={"province": "광주", "occupation": "하역"})

    assert result[0]["persona_id"] == "03b4f36a18e6469386d0286dddd513c8"
    assert result[0]["uuid"] == "03b4f36a18e6469386d0286dddd513c8"
    assert result[0]["sigungu"] == "광주-서구"
    assert result[0]["gender"] == "남자"
    assert result[0]["education"] == "초등학교"
    assert result[0]["goals"] == "건강을 유지하며 생활비를 마련하고 싶다"
    assert result[0]["industry"] == ""
    assert result[0]["source"] == "Nemotron-Personas-Korea"


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
