"""
screener.py - 부하(트레이너)가 넓은 종목군에서 자기 스타일 '매수' 후보를 스스로 찾는다.
------------------------------------------------------------------
각 brain의 decide()를 종목 전체의 최신봉에 돌려, 지금 '매수' 신호를 내는 종목을
트레이너별로 추출한다. = 운영모델의 1단계(부하가 후보 선별). 기존 brains 그대로 재사용.

출력: results/screener_<트레이너>.csv + 콘솔 요약 (이후 analyst.py가 이 후보를 분석).
실행: python screener.py [N]   (N = 스캔할 종목 수, 기본 50)

⚠️ KR 광역은 이 라이브러리의 KRX 목록 조회가 깨져(404) 미지원 → 현재 S&P500만. (한계)
"""

import sys
import csv
import random

import main
from sprinter_brain import SprinterBrain
from marathoner_brain import MarathonerBrain
from pioneer_brain import PioneerBrain

BRAINS = {"마라토너": MarathonerBrain, "스프린터": SprinterBrain, "파이오니어": PioneerBrain}
START = "2024-06-01"   # 지표 워밍업 충분(마라토너 MA60+) ~ 최신까지
SEED = 7


def universe(n):
    """S&P500에서 고정 seed로 섞어 n종목. (객관적 모집단, 승자 cherry-pick 방지)"""
    import FinanceDataReader as fdr
    syms = [s for s in fdr.StockListing("S&P500")["Symbol"].tolist() if isinstance(s, str)]
    random.seed(SEED)
    random.shuffle(syms)
    return syms[:n]


def scan(n=50):
    """n종목을 스캔해 트레이너별 '매수' 후보 리스트를 돌려준다."""
    found = {t: [] for t in BRAINS}
    used = 0
    for code in universe(n):
        try:
            df = main.load_prices(code, START)
        except Exception:
            continue
        if len(df) < 70:          # 지표 워밍업 부족 종목 제외
            continue
        used += 1
        for tname, cls in BRAINS.items():
            d = cls().add_indicators(df)
            action, reason = cls().decide(d, None)   # 보유 없음 기준 → 매수 신호만 본다
            if action == "매수":
                row = d.iloc[-1]
                found[tname].append({
                    "code": code,
                    "price": round(float(row["Close"]), 2),
                    "rsi": round(float(row["RSI"]), 1) if "RSI" in d.columns else None,
                    "reason": reason,
                })
    return found, used


def save(found):
    main.RESULTS_DIR.mkdir(exist_ok=True)
    for tname, cands in found.items():
        f = main.RESULTS_DIR / f"screener_{tname}.csv"
        with open(f, "w", newline="", encoding="utf-8-sig") as fp:
            w = csv.writer(fp)
            w.writerow(["code", "price", "rsi", "reason"])
            for c in cands:
                w.writerow([c["code"], c["price"], c["rsi"], c["reason"]])


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    print(f"S&P500에서 {n}종목 스캔 중...", flush=True)
    found, used = scan(n)
    save(found)
    print(f"사용 {used}종목. 트레이너별 '매수' 후보:")
    for t, cands in found.items():
        print(f"  {t:<8} {len(cands)}개 → {[c['code'] for c in cands][:10]}")
    print("results/screener_*.csv 저장 완료. (다음: analyst.py가 이 후보를 분석)")
