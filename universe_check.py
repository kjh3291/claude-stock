"""
universe_check.py - 편향 줄인 광역 종목 검증 ⚠️ "이긴 종목만 골랐나?" 점검
------------------------------------------------------------------
main.py의 5종목은 사람이 하인드사이트로 고른 것 → selection bias로 수익이 부풀려질 수 있다.
이 도구는 S&P500 전체에서 **고정 seed로 무작위 추출**한 종목에 지금 규칙을 그대로 돌려,
규칙이 cherry-pick 없이 '아무 종목에서나' 버티는지 **분포**로 본다.

핵심 지표는 평균이 아니라 **중앙값 + 손실 종목 비율** (평균은 소수 대박주에 가려짐).

실행: python universe_check.py  (시간 걸림 — 수십 종목 fetch. 백그라운드 권장)
"""

import random
import statistics

import main
from sprinter_brain import SprinterBrain
from marathoner_brain import MarathonerBrain
from pioneer_brain import PioneerBrain
from risk_guard import CircuitBreaker

SEED = 42         # 고정 → 재현 가능한 무작위 표본
SAMPLE_N = 40     # 뽑을 종목 수
START = "2018-01-01"
MIN_ROWS = 400    # 너무 짧은(신규 상장) 종목 제외

BRAINS = {"마라토너": MarathonerBrain, "스프린터": SprinterBrain, "파이오니어": PioneerBrain}


def _sample_symbols():
    import FinanceDataReader as fdr
    sp = fdr.StockListing("S&P500")
    syms = [s for s in sp["Symbol"].tolist() if isinstance(s, str)]
    random.seed(SEED)
    return random.sample(syms, min(SAMPLE_N, len(syms)))


def run():
    print("=" * 68)
    print(" 광역 종목 검증 — S&P500 무작위 표본 (현재 채택 규칙 그대로)")
    print(f" seed={SEED}, 목표 {SAMPLE_N}종목, {START}~, 최소 {MIN_ROWS}일")
    print("=" * 68)

    total = main.CONFIG["총_가상자금"]; ratios = main.CONFIG["배분비율"]; caps = main.CONFIG["종목상한"]
    cbc = main.CONFIG["서킷브레이커"]; breaker = CircuitBreaker(cbc["누적한도"], cbc["일일한도"])

    symbols = _sample_symbols()
    # 종목당 한 번 fetch, 실패/짧은 것은 건너뜀
    data = {}
    skipped = 0
    for sym in symbols:
        try:
            df = main.load_prices(sym, START)
        except Exception:
            skipped += 1; continue
        if len(df) < MIN_ROWS:
            skipped += 1; continue
        data[sym] = df
    print(f"  사용 종목 {len(data)}개 (실패/제외 {skipped}개)\n")

    print(f"  {'트레이너':<8}{'종목수':>6}{'평균':>8}{'중앙값':>8}{'손실비율':>9}{'최악':>8}{'최고':>8}{'중앙MDD':>9}{'서킷':>7}")
    results = {}
    for tname, cls in BRAINS.items():
        cash = int(total * ratios[tname]); cap = caps[tname]
        rets, mdds, stopped = [], [], 0
        need = 60 if cls is MarathonerBrain else 20
        for sym, df in data.items():
            if len(df) < need + 5:
                continue
            r = main.run_one_trainer(tname, cls(), df, cash, cap, sym, breaker)
            rets.append(r["profit"] / cash * 100)
            mdds.append(r["mdd"] * 100)
            stopped += bool(r["stopped"])
        if not rets:
            continue
        results[tname] = rets
        losers = sum(1 for x in rets if x < 0)
        print(f"  {tname:<8}{len(rets):>6}{statistics.mean(rets):>+7.1f}%{statistics.median(rets):>+7.1f}%"
              f"{losers/len(rets)*100:>7.0f}%{min(rets):>+7.1f}%{max(rets):>+7.1f}%"
              f"{statistics.median(mdds):>8.1f}%{stopped:>4}/{len(rets)}")

    # 블렌디드(60/30/10) 종목별 수익률의 중앙값/손실비율 — 실제 포트폴리오에 가까운 그림
    if all(k in results for k in BRAINS):
        n = min(len(results[k]) for k in BRAINS)
        blended = [0.6 * results["마라토너"][i] + 0.3 * results["스프린터"][i] + 0.1 * results["파이오니어"][i]
                   for i in range(n)]
        losers = sum(1 for x in blended if x < 0)
        print(f"\n  블렌디드(60/30/10): 중앙값 {statistics.median(blended):+.1f}%, "
              f"손실 종목 {losers}/{n} ({losers/n*100:.0f}%), 최악 {min(blended):+.1f}%")

    print("\n" + "-" * 68)
    print("■ 점검한 것: S&P500에서 무작위(seed 고정) 추출한 종목에 현재 규칙을 그대로 적용,")
    print("  평균이 아닌 중앙값·손실비율로 '대박주에 가려진' 성적을 봄.")
    print("■ 사각지대(못 잡은 것):")
    print("  - survivorship bias: StockListing은 '현재 상장' 종목만 → 상장폐지된 실패 종목이 빠짐(낙관 편향).")
    print("  - 현재 S&P500 구성만 봄 = 2018년엔 없던/빠진 종목 차이(구성 편향).")
    print("  - KR 광역 미검증: 이 라이브러리의 KRX 목록 조회가 현재 깨짐(404) → 국내는 아직 광역 검증 못 함.")
    print("  - 단일 데이터소스, 수수료 0.015% 단순화(세금·슬리피지 제외), 표본 수 한계.")
    print("  - 과거일 뿐 미래 보장 아님 → 최종 판정은 live.py 포워드 검증.")
    print("-" * 68)


if __name__ == "__main__":
    run()
