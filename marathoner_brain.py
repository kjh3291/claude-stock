"""
마라토너 두뇌 (롱런형 트레이너의 판단 규칙)
------------------------------------------------------
스프린터와 정반대: 오래 보고, 여유 있게, 장기 상승이 깨질 때만 판다.

마라토너 규칙 (기획서 기준):
- 살 때:  20일선이 60일선 위(장기 상승 분위기) + RSI 40~50으로 눌렸을 때 (길게 보면 오르는데 잠깐 싸진 순간)
- 익절:   짧게 안 판다. 장기 상승이 깨질 때(20일선이 60일선을 아래로 뚫으면) 판다
- 손절:   -15% (장기라 흔들림을 넉넉히 견딤)
- 시간제한: 없음 (오래 들고 간다)

⚠️ 방어 장치:
- 60일선을 쓰므로 데이터가 60일치 미만이면 관망 (섣부른 판단 금지)
- 값이 비었으면(NaN) 안전하게 관망
"""

from __future__ import annotations  # 파이썬 3.9에서도 'dict | None' 표기가 되게 함

import pandas as pd
import ta


class MarathonerBrain:
    def __init__(self, stop_loss=0.15, rsi_low=40, rsi_high=50):
        self.stop_loss = stop_loss    # -15%
        self.rsi_low = rsi_low        # RSI 하단
        self.rsi_high = rsi_high      # RSI 상단 (이 사이일 때 '눌렸다'고 봄)

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df['MA20'] = ta.trend.sma_indicator(df['Close'], window=20)
        df['MA60'] = ta.trend.sma_indicator(df['Close'], window=60)
        df['RSI'] = ta.momentum.rsi(df['Close'], window=14)
        return df

    def decide(self, df: pd.DataFrame, position: dict | None):
        # --- 방어: 60일치 데이터가 없으면 관망 ---
        if len(df) < 60 or df[['MA20', 'MA60', 'RSI']].iloc[-1].isnull().any():
            return ('관망', '장기 판단에 필요한 데이터(60일)가 아직 부족해요. 기다려요.')

        today = df.iloc[-1]
        prev = df.iloc[-2]

        # === 들고 있는 경우: 팔지 말지 ===
        if position is not None:
            change = (today['Close'] - position['buy_price']) / position['buy_price']
            # 손절선 (넉넉하게)
            if change <= -self.stop_loss:
                return ('매도', f'{change*100:.1f}%까지 내려서 손절선(-15%)에 닿았어요. 여기서 정리해요.')
            # 장기 상승이 깨지면 (20일선이 60일선 아래로) 매도
            trend_broke = (prev['MA20'] >= prev['MA60']) and (today['MA20'] < today['MA60'])
            if trend_broke:
                return ('매도', f'장기 상승 흐름이 깨졌어요(20일선이 60일선 아래로). 정리해요. 현재 {change*100:+.1f}%.')
            return ('관망', f'장기 상승 유지 중. 하루 흔들림은 무시해요. 현재 {change*100:+.1f}%.')

        # === 안 들고 있는 경우: 살지 말지 ===
        long_uptrend = today['MA20'] > today['MA60']            # 장기 상승 분위기
        pulled_back = self.rsi_low <= today['RSI'] <= self.rsi_high  # 잠깐 눌림
        if long_uptrend and pulled_back:
            return ('매수', f'길게 보면 오르는 중인데(20>60일선) RSI가 {today["RSI"]:.0f}로 잠깐 눌렸어요. 나눠서 조금 사요.')
        if long_uptrend and not pulled_back:
            return ('관망', f'장기 상승은 맞지만 RSI {today["RSI"]:.0f}라 살 타이밍(눌림)이 아니에요. 기다려요.')
        return ('관망', '아직 장기 상승 분위기가 아니에요. 기다려요.')
