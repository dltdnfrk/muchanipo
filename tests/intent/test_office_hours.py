"""Tests for src/intent/office_hours.py — 6 Forcing Questions triggers."""

from __future__ import annotations

import pytest

from src.intent.office_hours import OfficeHours, DesignDoc


class TestSixForcingQuestions:
    def setup_method(self):
        self.oh = OfficeHours()

    def test_q1_demand_reality_with_money_keywords(self):
        text = "이 제품의 가격과 ROI를 알고 싶어요"
        doc = self.oh.reframe(text)
        assert "수요 신호 감지" in doc.demand_reality
        assert "Q1" in doc.to_brief()

    def test_q1_demand_reality_without_signal(self):
        text = "미래 기술에 대해 알고 싶어요"
        doc = self.oh.reframe(text)
        assert "수요 신호 미감지" in doc.demand_reality

    def test_q2_status_quo_with_current_keywords(self):
        text = "현재 사용하고 있는 기존 솔루션과 비교해주세요"
        doc = self.oh.reframe(text)
        assert "현재 상태 언급 감지" in doc.status_quo

    def test_q2_status_quo_without_signal(self):
        text = "새로운 아이디어를 제안해주세요"
        doc = self.oh.reframe(text)
        assert "지금 이 문제를 어떻게 해결" in doc.status_quo

    def test_q3_desperate_specificity_with_target(self):
        text = "누가 이 제품의 주요 고객인가요?"
        doc = self.oh.reframe(text)
        assert "타겟 언급 감지" in doc.desperate_specificity

    def test_q3_desperate_specificity_without_signal(self):
        text = "시장 전망이 궁금해요"
        doc = self.oh.reframe(text)
        assert "한 사람의 이름" in doc.desperate_specificity

    def test_q4_narrowest_wedge_with_mvp(self):
        text = "MVP로 빠르게 출시하고 싶어요"
        doc = self.oh.reframe(text)
        assert "빠른 실행 언급 감지" in doc.narrowest_wedge

    def test_q4_narrowest_wedge_without_signal(self):
        text = "완벽한 제품을 만들고 싶어요"
        doc = self.oh.reframe(text)
        assert "내일 출시" in doc.narrowest_wedge

    def test_q5_observation_surprise_with_learned(self):
        text = "사용자 관찰에서 예상치 못하게 배운 점은요?"
        doc = self.oh.reframe(text)
        assert "학습/발견 언급 감지" in doc.observation_surprise

    def test_q5_observation_surprise_without_signal(self):
        text = "기능 목록을 알려주세요"
        doc = self.oh.reframe(text)
        assert "예상치 못하게 배운 것" in doc.observation_surprise

    def test_q6_future_fit_with_scope(self):
        text = "의도적으로 제외할 범위는 out of scope입니다"
        doc = self.oh.reframe(text)
        assert "범위 제한 언급 감지" in doc.future_fit

    def test_q6_future_fit_without_signal(self):
        text = "모든 기능을 다 넣고 싶어요"
        doc = self.oh.reframe(text)
        assert "의도적으로 하지 않을 것" in doc.future_fit

    def test_each_question_applied_at_most_once(self):
        # The reframe() calls each _qX exactly once; running twice should
        # not duplicate or mutate state.
        text = "비용과 사용자, MVP, 그리고 제외할 기능이 있어요"
        doc1 = self.oh.reframe(text)
        doc2 = self.oh.reframe(text)
        assert doc1.demand_reality == doc2.demand_reality
        assert doc1.status_quo == doc2.status_quo
        assert doc1.desperate_specificity == doc2.desperate_specificity
        assert doc1.narrowest_wedge == doc2.narrowest_wedge
        assert doc1.observation_surprise == doc2.observation_surprise
        assert doc1.future_fit == doc2.future_fit

    def test_to_brief_contains_all_six_questions(self):
        text = "돈, 사용자, MVP, 관찰, 제외"
        doc = self.oh.reframe(text)
        brief = doc.to_brief()
        assert "Q1 Demand Reality" in brief
        assert "Q2 Status Quo" in brief
        assert "Q3 Desperate Specificity" in brief
        assert "Q4 Narrowest Wedge" in brief
        assert "Q5 Observation & Surprise" in brief
        assert "Q6 Future-Fit" in brief
