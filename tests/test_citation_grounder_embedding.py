import os

import pytest

from conftest import load_script_module


grounder = load_script_module("citation_grounder_embedding", "src/eval/citation_grounder.py")


@pytest.fixture(autouse=True)
def reset_embedding_state(monkeypatch):
    monkeypatch.delenv("EMBEDDING_OFFLINE", raising=False)
    grounder._reset_embedding_cache()
    yield
    grounder._reset_embedding_cache()


@pytest.mark.parametrize(
    "quote,source",
    [
        (
            "The authors imply adoption pressure is rising among growers.",
            "Survey commentary indicates farmers increasingly feel market pull toward new tools.",
        ),
        (
            "The study suggests procurement teams prefer lower integration risk.",
            "Interview notes show buyers favor vendors that keep rollout uncertainty low.",
        ),
        (
            "Operators are likely to buy when support costs are predictable.",
            "The field memo says customers adopt faster when maintenance burden is easy to forecast.",
        ),
        (
            "The report indicates demand is concentrated in export-oriented farms.",
            "The source describes strongest customer pull from growers selling into overseas channels.",
        ),
        (
            "The author implies training gaps slow software rollout.",
            "The document signals that missing user education delays tool deployment.",
        ),
    ],
)
def test_embedding_accepts_paraphrases_when_lexical_scores_are_low(monkeypatch, quote, source):
    fake_model = _FakeEmbeddingModel(default=[1.0, 0.0, 0.0])
    monkeypatch.setattr(grounder, "_load_embedding_model", lambda: fake_model)

    ok, score, details = grounder.semantic_match(quote, source)

    assert ok is True
    assert score >= 0.85
    assert details["method"] == "embedding"
    assert details["jaccard"] < 0.6
    assert details["trigram"] < 0.6


def test_embedding_rejects_unrelated_text(monkeypatch):
    fake_model = _FakeEmbeddingModel(
        default=[1.0, 0.0, 0.0],
        overrides={"payment": [0.0, 1.0, 0.0]},
    )
    monkeypatch.setattr(grounder, "_load_embedding_model", lambda: fake_model)

    ok, score, details = grounder.semantic_match(
        "The authors imply adoption pressure is rising among growers.",
        "The payment system provisions accounts and retries failed invoices.",
    )

    assert ok is False
    assert score < 0.85
    assert details["method"] != "embedding"


def test_embedding_offline_uses_hash_bag_fallback(monkeypatch):
    monkeypatch.setenv("EMBEDDING_OFFLINE", "1")
    grounder._reset_embedding_cache()

    score = grounder._embedding_similarity(
        "buyers prefer predictable support costs and low rollout risk",
        "customers prefer predictable support costs with low deployment risk",
    )

    assert 0.0 <= score <= 1.0
    assert grounder._EMBEDDING_CACHE_STATS["source_misses"] == 1
    assert os.environ["EMBEDDING_OFFLINE"] == "1"


def test_same_source_text_embedding_is_cached(monkeypatch):
    fake_model = _FakeEmbeddingModel(default=[1.0, 0.0, 0.0])
    monkeypatch.setattr(grounder, "_load_embedding_model", lambda: fake_model)
    source = "Survey commentary indicates farmers increasingly feel market pull toward new tools."

    grounder.semantic_match("The authors imply adoption pressure is rising among growers.", source)
    grounder.semantic_match("The document signals demand momentum among farming operators.", source)

    assert fake_model.encoded_texts.count(source) == 1
    assert grounder._EMBEDDING_CACHE_STATS["source_misses"] == 1
    assert grounder._EMBEDDING_CACHE_STATS["source_hits"] == 1


def test_ground_claims_uses_embedding_match_with_source_text(monkeypatch):
    fake_model = _FakeEmbeddingModel(default=[1.0, 0.0, 0.0])
    monkeypatch.setattr(grounder, "_load_embedding_model", lambda: fake_model)
    evidence = [
        {
            "id": "E1",
            "quote": "Survey commentary indicates farmers increasingly feel market pull toward new tools.",
            "source_text": "Survey commentary indicates farmers increasingly feel market pull toward new tools.",
        }
    ]

    result = grounder.ground_claims(
        consensus="The authors imply adoption pressure is rising among growers.",
        evidence=evidence,
    )

    verdict = result["per_claim_verdict"][0]
    assert verdict["status"] == "supported"
    assert verdict["match_method"] == "embedding"
    assert verdict["match_details"]["embedding_cosine"] >= 0.85
    assert verdict["supporting_evidence_ids"] == ["E1"]


class _FakeEmbeddingModel:
    def __init__(self, default, overrides=None):
        self.default = list(default)
        self.overrides = overrides or {}
        self.encoded_texts = []

    def encode(self, texts, normalize_embeddings=True):
        vectors = []
        for text in texts:
            self.encoded_texts.append(text)
            vectors.append(self._vector_for(text))
        return vectors

    def _vector_for(self, text):
        lowered = text.lower()
        for marker, vector in self.overrides.items():
            if marker in lowered:
                return list(vector)
        return list(self.default)
