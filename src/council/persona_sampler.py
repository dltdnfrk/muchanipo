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

# Nemotron parquet에서 기대하는 26개 필드 이름. 실제 upstream 컬럼명이 달라질 수 있어
# sampler는 이 목록을 강제하지 않고, 누락 필드는 fallback/profile text로 보완한다.
NEMOTRON_KOREA_FIELDS = (
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
