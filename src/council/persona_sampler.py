#!/usr/bin/env python3
"""Nemotron-Personas-Korea 기반 council persona sampling 유틸리티.

parquet 자체 파싱은 stdlib 범위를 벗어나므로, 이 모듈은 같은 스키마로 export된
JSON/JSONL/CSV 파일을 읽는다. 데이터가 없거나 파싱할 수 없으면 테스트와 로컬 실행이
깨지지 않도록 안전한 합성 fallback persona를 반환한다.
"""

import csv
import json
import random
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence


DEFAULT_SEED_DIR = Path("vault/personas/seeds/korea")
NEMOTRON_KOREA_NGC_URL = (
    "https://catalog.ngc.nvidia.com/orgs/nvidia/teams/nemotron-personas/"
    "resources/nemotron-personas-dataset-ko_kr?version=0.0.1"
)
NEMOTRON_KOREA_HF_DATASET_ID = "nvidia/Nemotron-Personas-Korea"
NEMOTRON_KOREA_HF_URL = f"https://huggingface.co/datasets/{NEMOTRON_KOREA_HF_DATASET_ID}"
NEMOTRON_KOREA_NGC_VERSION = "0.0.1"
NEMOTRON_KOREA_NGC_LICENSE = "NVIDIA Dataset License Agreement"
NEMOTRON_KOREA_HF_LICENSE = "cc-by-4.0"
NEMOTRON_KOREA_HF_DOWNLOAD_SIZE_BYTES = 1_982_395_106
NEMOTRON_KOREA_HF_DATASET_SIZE_BYTES = 4_195_142_595
NEMOTRON_KOREA_NGC_COMPRESSED_SIZE_BYTES_APPROX = 2_660_000_000

NEMOTRON_KOREA_HF_FIELDS = (
    "uuid",
    "professional_persona",
    "sports_persona",
    "arts_persona",
    "travel_persona",
    "culinary_persona",
    "family_persona",
    "persona",
    "cultural_background",
    "skills_and_expertise",
    "skills_and_expertise_list",
    "hobbies_and_interests",
    "hobbies_and_interests_list",
    "career_goals_and_ambitions",
    "sex",
    "age",
    "marital_status",
    "military_status",
    "family_type",
    "housing_type",
    "education_level",
    "bachelors_field",
    "occupation",
    "district",
    "province",
    "country",
)

NEMOTRON_KOREA_NGC_EXTENDED_FIELDS_OBSERVED = (
    "uuid",
    "professional_persona",
    "finance_persona",
    "healthcare_persona",
    "sports_persona",
    "arts_persona",
    "travel_persona",
    "culinary_persona",
    "family_persona",
    "persona",
    "detailed_persona",
    "openness",
    "conscientiousness",
    "extraversion",
    "agreeableness",
    "neuroticism",
    "cultural_background",
    "career_goals_and_ambitions",
    "skills_and_expertise",
    "skills_and_expertise_list",
    "hobbies_and_interests",
    "hobbies_and_interests_list",
    "sex",
    "age",
    "marital_status",
    "education_level",
    "bachelors_field",
    "occupation",
    "military_status",
    "family_type",
    "housing_type",
    "housing_tenure",
    "economic_activity_status",
    "income_bracket",
    "bmi_status",
    "blood_pressure_status",
    "blood_sugar_status",
    "waist_status",
    "smoking_status",
    "drinking_status",
    "province",
    "district",
    "country",
)

# Sampler output contract keeps legacy Muchanipo aliases while preserving the
# public Hugging Face and NGC field names. Missing fields are allowed because
# this module can operate on small exported fixtures without downloading the
# full NGC/HF dataset.
NEMOTRON_KOREA_FIELDS = tuple(
    dict.fromkeys(
        (
            *NEMOTRON_KOREA_HF_FIELDS,
            *NEMOTRON_KOREA_NGC_EXTENDED_FIELDS_OBSERVED,
            # Muchanipo legacy/canonical aliases
            "persona_id",
            "city",
            "sigungu",
            "gender",
            "industry",
            "education",
            "income_band",
            "household_type",
            "household_size",
            "region_type",
            "mobility_pattern",
            "digital_literacy",
            "media_preference",
            "policy_interest",
            "purchase_channel",
            "technology_attitude",
            "pain_points",
            "goals",
        )
    )
)

LEGACY_NEMOTRON_KOREA_FIELDS = (
    "persona_id",
    "country",
    "province",
    "city",
    "sigungu",
    "eup_myeon_dong",
    "age",
    "gender",
    "occupation",
    "industry",
    "education",
    "income_band",
    "household_type",
    "household_size",
    "marital_status",
    "housing_type",
    "region_type",
    "mobility_pattern",
    "digital_literacy",
    "media_preference",
    "policy_interest",
    "purchase_channel",
    "technology_attitude",
    "pain_points",
    "goals",
    "persona",
)

FARMER_OCCUPATION_KEYWORDS = (
    "농가",
    "농민",
    "농업",
    "축산",
    "원예",
    "시설재배",
    "스마트팜",
    "farmer",
    "agriculture",
)


class KoreaPersonaSampler:
    """한국 seed persona를 필터링하고 샘플링한다."""

    def __init__(
        self,
        data_path: Optional[Any] = None,
        records: Optional[Iterable[Dict[str, Any]]] = None,
        seed: Optional[int] = None,
    ) -> None:
        self.data_path = Path(data_path) if data_path is not None else None
        self._records = list(records) if records is not None else None
        self._random = random.Random(seed)

    def sample(self, n: int = 10, filter: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """조건에 맞는 persona를 최대 n개 반환한다.

        filter는 {"province": "경상북도", "occupation": "농업"}처럼 필드별 부분 일치로
        적용한다. 데이터가 없으면 같은 filter를 반영한 합성 dummy persona를 반환한다.
        """

        if n <= 0:
            return []

        criteria = filter or {}
        records = self._load_records()
        matched = [record for record in records if self._matches(record, criteria)]

        if not matched:
            return self._fallback_personas(n, criteria)

        normalized = [self._normalize(record) for record in matched]
        if len(normalized) <= n:
            return normalized[:n]
        return self._random.sample(normalized, n)

    def agtech_farmer_seed(self, n: int = 10) -> List[Dict[str, Any]]:
        """AgTech 회의용 농가/농업 종사자 seed를 반환한다.

        252 시군구 x 농가 직업 cross filter를 의도하지만, stdlib sampler에서는 직업/산업
        키워드 기반으로 우선 좁히고 없으면 안전 fallback을 사용한다.
        """

        records = self._load_records()
        matched = [record for record in records if self._is_agtech_farmer(record)]
        if not matched:
            return self._fallback_personas(n, {"occupation": "농업", "domain": "agtech"})

        normalized = [self._normalize(record) for record in matched]
        if len(normalized) <= n:
            return normalized[:n]
        return self._random.sample(normalized, n)

    def _load_records(self) -> List[Dict[str, Any]]:
        if self._records is not None:
            return [dict(record) for record in self._records if isinstance(record, dict)]

        if self.data_path is None or not self.data_path.exists():
            return []

        suffix = self.data_path.suffix.lower()
        try:
            if suffix == ".json":
                return self._load_json(self.data_path)
            if suffix in {".jsonl", ".ndjson"}:
                return self._load_jsonl(self.data_path)
            if suffix == ".csv":
                return self._load_csv(self.data_path)
        except (OSError, json.JSONDecodeError, csv.Error):
            return []

        # parquet 등 stdlib로 처리할 수 없는 형식은 fallback으로 넘긴다.
        return []

    @staticmethod
    def _load_json(path: Path) -> List[Dict[str, Any]]:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            data = data.get("records", [])
        return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []

    @staticmethod
    def _load_jsonl(path: Path) -> List[Dict[str, Any]]:
        records = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                item = json.loads(line)
                if isinstance(item, dict):
                    records.append(item)
        return records

    @staticmethod
    def _load_csv(path: Path) -> List[Dict[str, Any]]:
        with path.open("r", encoding="utf-8", newline="") as f:
            return [dict(row) for row in csv.DictReader(f)]

    @classmethod
    def _matches(cls, record: Dict[str, Any], criteria: Dict[str, Any]) -> bool:
        for key, expected in criteria.items():
            if expected is None:
                continue
            value = cls._field_text(record, key)
            if str(expected).casefold() not in value.casefold():
                return False
        return True

    @classmethod
    def _is_agtech_farmer(cls, record: Dict[str, Any]) -> bool:
        text = " ".join(
            cls._field_text(record, key)
            for key in ("occupation", "industry", "persona", "pain_points", "goals")
        ).casefold()
        return any(keyword.casefold() in text for keyword in FARMER_OCCUPATION_KEYWORDS)

    @staticmethod
    def _field_text(record: Dict[str, Any], key: str) -> str:
        value = record.get(key, "")
        if isinstance(value, (list, tuple, set)):
            return " ".join(str(item) for item in value)
        return "" if value is None else str(value)

    @classmethod
    def _normalize(cls, record: Dict[str, Any]) -> Dict[str, Any]:
        normalized = {field: record.get(field, "") for field in NEMOTRON_KOREA_FIELDS}
        normalized.update(record)
        normalized["persona_id"] = normalized.get("persona_id") or normalized.get("uuid") or ""
        normalized["gender"] = normalized.get("gender") or normalized.get("sex") or ""
        normalized["sigungu"] = normalized.get("sigungu") or normalized.get("district") or ""
        normalized["city"] = normalized.get("city") or normalized.get("sigungu") or ""
        normalized["education"] = normalized.get("education") or normalized.get("education_level") or ""
        normalized["goals"] = normalized.get("goals") or normalized.get("career_goals_and_ambitions") or ""
        normalized.setdefault("source", "Nemotron-Personas-Korea")
        normalized["persona"] = cls._persona_text(normalized)
        return normalized

    @staticmethod
    def _persona_text(record: Dict[str, Any]) -> str:
        existing = record.get("persona")
        if existing:
            return str(existing)

        province = record.get("province") or "한국"
        sigungu = record.get("sigungu") or record.get("city") or "지역"
        occupation = record.get("occupation") or "지역 이해관계자"
        goals = record.get("goals") or "현장 제약과 실용성을 중시한다"
        return f"{province} {sigungu}의 {occupation}. {goals}."

    @classmethod
    def _fallback_personas(cls, n: int, criteria: Dict[str, Any]) -> List[Dict[str, Any]]:
        province = str(criteria.get("province") or "전라북도")
        occupation = str(criteria.get("occupation") or "농업 현장 전문가")
        domain = str(criteria.get("domain") or "korea-persona")
        personas = []
        for idx in range(n):
            sigungu = f"fallback-sigungu-{idx + 1:03d}"
            record = {
                "persona_id": f"synthetic-korea-{domain}-{idx + 1:03d}",
                "country": "KR",
                "province": province,
                "city": sigungu,
                "sigungu": sigungu,
                "occupation": occupation,
                "industry": "agriculture" if "농" in occupation or domain == "agtech" else "local",
                "region_type": "rural" if domain == "agtech" else "mixed",
                "digital_literacy": "medium",
                "technology_attitude": "pragmatic",
                "pain_points": "노동력, 비용, 판로, 데이터 신뢰성",
                "goals": "현장 부담을 줄이고 검증 가능한 의사결정을 원한다",
                "source": "synthetic-fallback",
            }
            personas.append(cls._normalize(record))
        return personas


def nemotron_korea_dataset_metadata() -> Dict[str, Any]:
    """Return static provenance for the Korean Nemotron persona source.

    This is intentionally metadata-only. The NGC resource is large and
    license-gated differently from the public Hugging Face mirror, so runtime
    code must not download or silently treat either location as already
    integrated evidence.
    """

    return {
        "ngc": {
            "url": NEMOTRON_KOREA_NGC_URL,
            "resource": "nemotron-personas-dataset-ko_kr",
            "team": "nemotron-personas",
            "org": "nvidia",
            "version": NEMOTRON_KOREA_NGC_VERSION,
            "license": NEMOTRON_KOREA_NGC_LICENSE,
            "compressed_size_bytes_approx": NEMOTRON_KOREA_NGC_COMPRESSED_SIZE_BYTES_APPROX,
        },
        "huggingface": {
            "url": NEMOTRON_KOREA_HF_URL,
            "dataset_id": NEMOTRON_KOREA_HF_DATASET_ID,
            "license": NEMOTRON_KOREA_HF_LICENSE,
            "gated": False,
            "private": False,
            "download_size_bytes": NEMOTRON_KOREA_HF_DOWNLOAD_SIZE_BYTES,
            "dataset_size_bytes": NEMOTRON_KOREA_HF_DATASET_SIZE_BYTES,
        },
        "schema": {
            "hf_feature_count": len(NEMOTRON_KOREA_HF_FIELDS),
            "hf_fields": list(NEMOTRON_KOREA_HF_FIELDS),
            "ngc_extended_documented_field_count": 51,
            "ngc_extended_fields_observed": list(NEMOTRON_KOREA_NGC_EXTENDED_FIELDS_OBSERVED),
            "canonical_output_fields": list(NEMOTRON_KOREA_FIELDS),
        },
        "access": {
            "download_required": False,
            "large_dataset_bytes": NEMOTRON_KOREA_NGC_COMPRESSED_SIZE_BYTES_APPROX,
            "approved_for_auto_download": False,
        },
        "integration_boundary": "metadata_adapter_only_no_dataset_download",
        "product_verdict_boundary": "does_not_satisfy_source_facet_council_report_pass",
    }
