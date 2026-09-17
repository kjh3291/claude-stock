"""
가짜 지갑 (Paper Trading Wallet) - 학습 모드의 심장
------------------------------------------------------
진짜 돈은 절대 쓰지 않습니다. 컴퓨터 안의 가상 돈으로만 사고팔기를 흉내 냅니다.
세 트레이너(스프린터/마라토너/파이오니어)가 각자 이 지갑을 하나씩 가집니다.

초보자용 설명:
- deposit(): 지갑에 가짜 돈을 넣는다
- buy():     가짜 돈으로 주식을 산다 (수수료도 흉내)
- sell():    가진 주식을 판다
- value():   지금 이 지갑이 총 얼마짜리인지 계산한다
- 모든 거래는 자동으로 기록된다 (나중에 세금/복기용)
"""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Holding:
    """한 종목을 얼마에 몇 주 샀는지 기록."""
    shares: int          # 보유 주식 수
    avg_price: float     # 평균 매입 단가


@dataclass
class PaperWallet:
    name: str                         # 트레이너 이름 (예: "스프린터")
    cash: float = 0.0                 # 지금 남은 현금
    fee_rate: float = 0.00015         # 매매 수수료율 (0.015%, 양방향)
    sell_tax_rate: float = 0.0018     # 매도 시 증권거래세 (국내 ~0.18%, 기획서 9절)
    slippage: float = 0.0005          # 체결 미끄러짐 가정 (0.05%, 시장가 근사)
    holdings: dict = field(default_factory=dict)   # {종목코드: Holding}
    log: list = field(default_factory=list)        # 모든 거래 기록
    # ponytail: 매도세는 국내 기준. 미국은 거래세 없음(여기선 보수적으로 전부 부과 = 비용 과대추정).
    #           해외 양도세는 연간 정산이라 건별 시뮬 제외(기획서 9절). 실거래 땐 시장별 분기 필요.

    # --- 돈 넣기 ---
    def deposit(self, amount: float):
        """지갑에 가짜 돈을 넣는다."""
        self.cash += amount
        self._record("입금", None, 0, amount)

    # --- 사기 ---
    def buy(self, code: str, price: float, shares: int) -> bool:
        """price 가격에 shares 주 만큼 산다. 돈이 부족하면 사지 않고 False."""
        exec_price = price * (1 + self.slippage)   # 살 땐 조금 더 비싸게 체결(현실)
        cost = exec_price * shares
        fee = cost * self.fee_rate
        total = cost + fee
        if total > self.cash:
            return False  # 현금 부족 -> 매수 실패 (규칙: 예산 안에서만)
        self.cash -= total
        if code in self.holdings:
            h = self.holdings[code]
            # 평균 단가 다시 계산 (기존 것 + 새로 산 것)
            new_shares = h.shares + shares
            h.avg_price = (h.avg_price * h.shares + exec_price * shares) / new_shares
            h.shares = new_shares
        else:
            self.holdings[code] = Holding(shares=shares, avg_price=exec_price)
        self._record("매수", code, shares, total)
        return True

    # --- 팔기 ---
    def sell(self, code: str, price: float, shares: int) -> bool:
        """가진 주식을 판다. 가진 것보다 많이 팔 수는 없다."""
        if code not in self.holdings or self.holdings[code].shares < shares:
            return False
        exec_price = price * (1 - self.slippage)   # 팔 땐 조금 더 싸게 체결(현실)
        proceeds = exec_price * shares
        fee = proceeds * self.fee_rate
        tax = proceeds * self.sell_tax_rate        # 매도 시 증권거래세
        net = proceeds - fee - tax
        self.cash += net
        self.holdings[code].shares -= shares
        if self.holdings[code].shares == 0:
            del self.holdings[code]
        self._record("매도", code, shares, net)
        return True

    # --- 지금 총 얼마짜리인가 ---
    def value(self, prices: dict) -> float:
        """현금 + (보유 주식을 지금 시세로 판다면 받을 돈). prices = {종목코드: 현재가}"""
        stock_value = sum(
            h.shares * prices.get(code, h.avg_price)
            for code, h in self.holdings.items()
        )
        return self.cash + stock_value

    def _record(self, kind, code, shares, amount):
        self.log.append({
            "시각": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "종류": kind, "종목": code, "수량": shares, "금액": round(amount, 1),
        })


if __name__ == "__main__":
    # 자체 점검: 수수료·매도세·슬리피지가 실제로 비용으로 빠지는지
    w = PaperWallet(name="테스트")
    w.deposit(1_000_000)
    # 같은 가격에 사고팔면 비용만큼 손실이어야 (본전이면 버그)
    assert w.buy("X", 1000, 100)
    before = w.cash
    assert w.sell("X", 1000, 100)
    round_trip_cost = 1_000_000 - w.cash
    notional = 1000 * 100   # 거래금액 10만원
    pct = round_trip_cost / notional * 100
    # 예상 왕복 비용 ≈ 매수(슬리피지+수수료) + 매도(슬리피지+수수료+세금) ≈ 0.25~0.40%
    assert 0.25 < pct < 0.40, f"왕복 비용 이상: {pct:.2f}%"
    assert not w.holdings, "전량 매도 후 보유 남음"
    # 잔고보다 많이 못 삼
    assert w.buy("Y", 1000, 10**9) is False
    print(f"[PASS] 왕복 비용 {round_trip_cost:,.0f}원({pct:.2f}%) — 비용 반영 확인")
