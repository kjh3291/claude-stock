"""
스프린터 두뇌 (단타형 트레이너의 판단 규칙)
------------------------------------------------------
이 부품은 "지금 살까? 팔까? 가만있을까?"만 결정합니다.
실제 사고파는 건 가짜 지갑(paper_wallet)이 합니다. 두뇌와 손을 분리한 것.

스프린터 규칙 (기획서 기준):
- 살 때:  5일선이 20일선을 위로 뚫음(골든크로스) + RSI 70 미만
- 익절:   +3% 오르면 판다
- 손절:   -2% 내리면 판다
- 시간제한: 산 지 3일 지나면 정리 (기세 없으면 미련 없이)

⚠️ 위험 방어 장치(이 파일에 미리 넣음):
- 데이터가 부족하면(20일치 미만) 아무 것도 안 한다 (섣부른 판단 금지)
- 값이 비었거나(NaN) 이상하면 '관망'으로 안전하게 처리
"""

from __future__ import annotations  # 파이썬 3.9에서도 'dict | None' 표기가 되게 함

import pandas as pd
import ta


class SprinterBrain:
    def __init__(self, take_profit=0.05, stop_loss=0.015, max_hold_days=3,
                 rsi_ceiling=70, rsi_floor=55, cross_lookback=3):
        # tune.py 5종목·train/test 근거로 진입 문턱을 높여 수수료를 이기게 조정:
        #   rsi_floor 0→55 (약한 크로스 매수 차단), take_profit 0.03→0.05, stop_loss 0.02→0.015.
        #   기존 기본값(문턱 없음)은 검증 -22,685(전 조합 손실)였으나, 이 값은 훈련 +51,290·
        #   검증 +11,560 으로 '안 본 기간'에서도 흑자. 매매 57→37회로 줄여 MDD도 -9.5%→-4.9%.
        #   ponytail: 문턱 60/65는 표본부족(11~18회)으로 불안정 → 안정적 55 채택. 잠정값, live 검증 필수.
        self.take_profit = take_profit      # +5%
        self.stop_loss = stop_loss          # -1.5%
        self.max_hold_days = max_hold_days  # 3일
        self.rsi_ceiling = rsi_ceiling      # RSI 이 값 이상이면 과열 → 안 삼
        self.rsi_floor = rsi_floor          # RSI 이 값 미만이면 기세 약함 → 안 삼 (진입 문턱, 0=끔)
        self.cross_lookback = cross_lookback  # 골든크로스를 며칠 전까지 인정할지 (1=신선한 크로스만)

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """가격표(df)에 이동평균선과 RSI 칸을 추가한다."""
        df = df.copy()
        df['MA5'] = ta.trend.sma_indicator(df['Close'], window=5)
        df['MA20'] = ta.trend.sma_indicator(df['Close'], window=20)
        df['RSI'] = ta.momentum.rsi(df['Close'], window=14)
        return df

    def decide(self, df: pd.DataFrame, position: dict | None):
        """
        오늘 무엇을 할지 결정한다.
        df: 오늘까지의 가격 데이터 (지표 포함)
        position: 지금 이 종목을 들고 있으면 {'buy_price':.., 'days_held':..}, 없으면 None
        반환: ('매수'|'매도'|'관망', 쉬운 설명 문장)
        """
        # --- 방어: 데이터가 부족하면 아무 것도 안 한다 ---
        if len(df) < 20 or df[['MA5', 'MA20', 'RSI']].iloc[-1].isnull().any():
            return ('관망', '데이터가 아직 부족해서 판단을 미뤘어요. (섣불리 움직이지 않아요)')

        today = df.iloc[-1]

        # === 이미 이 종목을 들고 있는 경우: 팔지 말지 ===
        if position is not None:
            change = (today['Close'] - position['buy_price']) / position['buy_price']
            if change >= self.take_profit:
                return ('매도', f'+{change*100:.1f}% 올라서 목표(+{self.take_profit*100:.1f}%) 달성! 욕심 안 부리고 팔아요.')
            if change <= -self.stop_loss:
                return ('매도', f'{change*100:.1f}% 내려서 손절선(-{self.stop_loss*100:.1f}%)에 닿았어요. 더 잃기 전에 팔아요.')
            if position['days_held'] >= self.max_hold_days:
                return ('매도', f'{self.max_hold_days}일이 지났는데 기세가 없어요. 미련 없이 정리해요.')
            return ('관망', f'현재 {change*100:+.1f}%. 아직 익절·손절선에 안 닿아서 지켜봐요.')

        # === 아직 안 들고 있는 경우: 살지 말지 ===
        # 골든크로스를 '딱 그날'만 보지 않고, 최근 며칠 안에 일어났고 지금도 유효하면 인정.
        # (프로그램이 하루 놓쳐도 기회를 살리기 위한 현실적 보정)
        recent = df.iloc[-(self.cross_lookback + 1):]
        crossed_recently = False
        for i in range(1, len(recent)):
            prev, cur = recent.iloc[i - 1], recent.iloc[i]
            if prev['MA5'] <= prev['MA20'] and cur['MA5'] > cur['MA20']:
                crossed_recently = True
                break
        still_above = today['MA5'] > today['MA20']   # 지금도 짧은 선이 위에 있어야 함
        rsi = today['RSI']
        rsi_ok = self.rsi_floor <= rsi < self.rsi_ceiling   # 너무 약하지도 뜨겁지도 않은 구간만

        if crossed_recently and still_above and rsi_ok:
            return ('매수', f'최근 짧은 선이 긴 선을 위로 뚫었고(기세 붙음) RSI도 {rsi:.0f}(적정 구간). 조금 사요.')
        if crossed_recently and still_above and rsi >= self.rsi_ceiling:
            return ('관망', f'기세는 붙었지만 RSI가 {rsi:.0f}로 너무 뜨거워요. 이번엔 참아요.')
        if crossed_recently and still_above and rsi < self.rsi_floor:
            return ('관망', f'크로스는 났지만 RSI {rsi:.0f}로 기세가 약해요. 문턱 미달, 참아요.')
        return ('관망', '아직 뚜렷한 매수 신호가 없어요. 기다려요.')
