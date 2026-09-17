"""
서킷 브레이커 (자동 손실 차단) - 기획서 3.3의 '가장 중요한 부분'
------------------------------------------------------------------
개별 손절을 빠져나간 위험도 이 그물이 한 번 더 잡는다.
어떤 트레이너든 (1) 맡긴 돈 대비 누적 손실이 한도를 넘거나
(2) 하루 만에 급락하면 → 전량 정리하고 그 트레이너를 멈춘다.

두뇌(decide)와 무관하게, 매일 '지금 지갑이 얼마짜리냐'만 보고 판단한다.
숫자(누적 -10% / 하루 -7%)는 기본값이자 출발점 — CONFIG로 조절한다.
"""

from __future__ import annotations


class CircuitBreaker:
    def __init__(self, cum_limit: float = 0.10, day_limit: float = 0.07):
        self.cum_limit = cum_limit   # 맡긴 돈 대비 누적 손실 한도 (예: 0.10 = -10%)
        self.day_limit = day_limit   # 하루 낙폭 한도 (예: 0.07 = -7%)

    def check(self, start_value: float, prev_value: float, today_value: float):
        """멈춰야 하면 쉬운 설명 문장을 돌려주고, 괜찮으면 None을 돌려준다.
        start_value: 처음 맡긴 돈 / prev_value: 어제 평가금액 / today_value: 오늘 평가금액"""
        cum = today_value / start_value - 1 if start_value else 0.0
        if cum <= -self.cum_limit:
            return (f"누적 {cum*100:.1f}% 손실로 한도(-{self.cum_limit*100:.0f}%)에 닿았어요. "
                    f"더 잃기 전에 전부 팔고 이 트레이너를 멈춰요.")
        day = today_value / prev_value - 1 if prev_value else 0.0
        if day <= -self.day_limit:
            return (f"하루 만에 {day*100:.1f}% 급락(한도 -{self.day_limit*100:.0f}%)했어요. "
                    f"전부 팔고 이 트레이너를 멈춰요.")
        return None


if __name__ == "__main__":
    # 자체 점검: 발동해야 할 때 발동하고, 아닐 때 안 하는지
    cb = CircuitBreaker(cum_limit=0.10, day_limit=0.07)
    assert cb.check(100, 95, 89) is not None          # 누적 -11% → 발동
    assert cb.check(100, 100, 92) is not None          # 하루 -8% → 발동
    assert cb.check(100, 100, 95) is None              # 누적 -5%, 하루 -5% → 통과
    assert cb.check(100, 0, 89) is not None             # 어제값 없어도 누적으로 발동
    assert cb.check(100, 108, 105) is None             # 이익 구간 → 통과
    print("[PASS] CircuitBreaker 자체 점검 통과")
