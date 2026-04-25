"""Research Intent Capture (C21) — gstack THINK/PLAN/REFLECT 패턴 차용.

사용자 한 줄 입력을 정밀한 design doc + 4-perspective plan + retro learnings로 변환해
Council/eval-agent 루프에 정확한 입력을 공급한다.

원본 영감: https://github.com/garrytan/gstack (2026-03-12 출시, 7-phase loop)

모듈은 각자 직접 import (lazy):
    from src.intent.office_hours import OfficeHours    # THINK
    from src.intent.plan_review import PlanReview      # PLAN (commit B 예정)
    from src.intent.learnings_log import LearningsLog  # REFLECT (commit C 예정)
    from src.intent.retro import Retro                 # REFLECT (commit C 예정)
"""
