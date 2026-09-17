"""
파이오니어 두뇌 (리스크형 트레이너의 판단 규칙)
------------------------------------------------------
셋 중 가장 공격적. 크게 노리되(+10%) 손절은 칼같이(-5%).

파이오니어 규칙 (기획서 기준):
- 살 때: 두 상황 중 하나
   (A) 강한 상승: 골든크로스(5>20일선) + 거래량이 평소보다 급증
   (B) 과냉 반등: RSI 35 이하로 눌렸다가 반등 시작 (실데이터 튜닝으로 30→35 완화)
- 익절: +10%
- 손절: -5% (칼같이)
- 한 종목 비중을 가장 작게 (위험하니까) — 이 규칙은 지갑/배분 쪽에서 강제

⚠️ 방어 장치:
- 거래량 데이터가 없으면 (A)는 건너뛰고 (B)만 본다
- 데이터 20일 미만이거나 값이 비면 관망
"""

from __future__ import annotations  # 파이썬 3.9에서도 'dict | None' 표기가 되게 함

import pandas as pd
import ta


class PioneerBrain:
    def __init__(self, take_profit=0.10, stop_loss=0.05, rsi_oversold=35, volume_surge=1.5):
        # rsi_oversold 30→35, volume_surge 1.8→1.5 로 완화 (tune.py 교차-시대 근거).
        # 교차검증: rsi 35는 2023~(+11,444)과 2018~2022(+10,361) '두 시대 모두' 흑자로 견고.
        #   rsi 40은 2023~엔 +26,544로 최고였으나 2018~2022(약세장 포함)에선 -2,287 손실
        #   = 상승장 과최적화라 채택 안 함. rsi 30(원래)도 견고하나 '너무 소극적'이라 35로 완화.
        # ⚠️ 여전히 잠정값 — live.py 포워드 검증 필요. 하락장에선 파이오니어가 가장 잘 물림
        #   (그래서 비중 10% + 서킷 브레이커로 방어).
        self.take_profit = take_profit     # +10%
        self.stop_loss = stop_loss         # -5%
        self.rsi_oversold = rsi_oversold   # RSI 이 값 이하 = 과냉(눌림). 낮을수록 매수 드묾
        self.volume_surge = volume_surge   # 거래량이 평균의 이 배수 이상이면 '급증'

    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()
        df['MA5'] = ta.trend.sma_indicator(df['Close'], window=5)
        df['MA20'] = ta.trend.sma_indicator(df['Close'], window=20)
        df['RSI'] = ta.momentum.rsi(df['Close'], window=14)
        if 'Volume' in df.columns:
            df['VolAvg20'] = df['Volume'].rolling(20).mean()
        return df

    def decide(self, df: pd.DataFrame, position: dict | None):
        # --- 방어 ---
        if len(df) < 20 or df[['MA5', 'MA20', 'RSI']].iloc[-1].isnull().any():
            return ('관망', '데이터가 아직 부족해서 판단을 미뤘어요.')

        today = df.iloc[-1]
        prev = df.iloc[-2]

        # === 들고 있는 경우 ===
        if position is not None:
            change = (today['Close'] - position['buy_price']) / position['buy_price']
            if change >= self.take_profit:
                return ('매도', f'+{change*100:.1f}%! 목표(+10%) 크게 달성했어요. 팔아요.')
            if change <= -self.stop_loss:
                return ('매도', f'{change*100:.1f}%로 손절선(-5%)에 닿았어요. 칼같이 정리해요.')
            return ('관망', f'현재 {change*100:+.1f}%. 목표·손절선 사이라 지켜봐요.')

        # === 안 들고 있는 경우 ===
        # (A) 강한 상승: 골든크로스 + 거래량 급증
        golden = (prev['MA5'] <= prev['MA20']) and (today['MA5'] > today['MA20'])
        vol_surged = False
        if 'VolAvg20' in df.columns and not pd.isnull(today.get('VolAvg20')):
            vol_surged = today['Volume'] > today['VolAvg20'] * self.volume_surge
        if golden and vol_surged:
            return ('매수', f'강한 상승 신호! 골든크로스 + 거래량 급증. 공격적으로 노려요.')

        # (B) 과냉 반등: RSI가 30 이하였다가 오늘 반등
        was_oversold = prev['RSI'] <= self.rsi_oversold
        rebounding = today['RSI'] > prev['RSI']
        if was_oversold and rebounding:
            return ('매수', f'많이 빠졌다가(RSI {prev["RSI"]:.0f}) 반등이 시작됐어요. 반등을 노려요.')

        return ('관망', '아직 강한 상승도, 과냉 반등도 아니에요. 기다려요.')
