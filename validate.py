"""
validate.py - 과최적화 점검 도구 ⚠️ 규칙/파라미터를 바꿀 때마다 돌릴 것
------------------------------------------------------------------
"지금 값이 과거 데이터에 끼워맞춘(overfit) 건 아닌가?"를 자동으로 점검한다. 두 가지:

 1) 국면 리포트: 지금 채택값이 여러 시장 국면(2018 조정/2020 폭락/2022 약세장/2023~)에서
    버티는지. 한 국면만 좋고 다른 국면에서 무너지면 위험.
 2) 교차-시대 감사: 서로 다른 시대(2018~2022 vs 2023~)에 각각 튜닝했을 때, 지금 채택값이
    양쪽에서 상위로 뽑히는지. 한 시대만 상위면 '그 시대 과최적화' → ⚠️ 경고.

실행: python validate.py   (main.py 와 같은 라이브러리 필요, 시간이 좀 걸림)

원칙: 과거 검증은 끝이 있다. 여기까지 통과해도 '과거'일 뿐 — 진짜 판정은 live.py 포워드 검증.
"""

import main
import tune
from sprinter_brain import SprinterBrain
from marathoner_brain import MarathonerBrain
from pioneer_brain import PioneerBrain
from risk_guard import CircuitBreaker

# 2018년부터 역사가 있는 분산된 종목 (국면 리포트용)
STOCKS = {
    "삼성전자": "005930", "SK하이닉스": "000660", "카카오": "035720", "네이버": "035420",
    "애플": "AAPL", "MS": "MSFT", "엔비디아": "NVDA", "테슬라": "TSLA",
    "메타": "META", "아마존": "AMZN",
}
AUDIT_STOCKS = {"삼성전자": "005930", "SK하이닉스": "000660",
                "애플": "AAPL", "MS": "MSFT", "엔비디아": "NVDA"}  # 튜닝 감사(느려서 5개)

REGIMES = {
    "2018 조정":       ("2018-01-01", "2019-06-30"),
    "2020 코로나폭락":  ("2019-06-01", "2021-06-30"),
    "2022 약세장":      ("2021-06-01", "2023-06-30"),
    "2023~ 상승":       ("2023-01-01", "2026-12-31"),
    "전체(2018~)":      ("2018-01-01", "2026-12-31"),
}
ERAS = {"2018~2022": ("2018-01-01", "2022-12-31"),
        "2023~이후":  ("2023-01-01", "2026-12-31")}

BRAINS = {"마라토너": MarathonerBrain, "스프린터": SprinterBrain, "파이오니어": PioneerBrain}

_orig_load = main.load_prices
_CACHE = {}


def _full(code):
    """종목별 2018~ 전체 시세를 한 번만 받아 캐시."""
    if code not in _CACHE:
        _CACHE[code] = _orig_load(code, "2018-01-01")
    return _CACHE[code]


def regime_report():
    print("\n" + "#" * 72 + "\n# 1) 국면 리포트 — 지금 채택값이 여러 시장에서 버티나\n" + "#" * 72)
    total = main.CONFIG["총_가상자금"]; ratios = main.CONFIG["배분비율"]; caps = main.CONFIG["종목상한"]
    cbc = main.CONFIG["서킷브레이커"]; breaker = CircuitBreaker(cbc["누적한도"], cbc["일일한도"])
    for regime, (s, e) in REGIMES.items():
        print(f"\n[{regime}]  {s} ~ {e}")
        print(f"  {'트레이너':<8}{'평균수익률':>10}{'최악MDD':>9}{'손실종목':>9}{'서킷발동':>9}")
        for tname, cls in BRAINS.items():
            cash = int(total * ratios[tname]); cap = caps[tname]
            rets, mdds, losers, stopped = [], [], 0, 0
            need = 60 if cls is MarathonerBrain else 20
            for code in STOCKS.values():
                seg = _full(code).loc[s:e]
                if len(seg) < need + 5:
                    continue
                r = main.run_one_trainer(tname, cls(), seg, cash, cap, code, breaker)
                ret = r["profit"] / cash * 100
                rets.append(ret); mdds.append(r["mdd"] * 100)
                losers += ret < 0; stopped += bool(r["stopped"])
            if rets:
                print(f"  {tname:<8}{sum(rets)/len(rets):>+9.1f}%{min(mdds):>8.1f}%"
                      f"{losers:>6}/{len(rets)}{stopped:>6}/{len(rets)}")


def overfit_audit():
    print("\n" + "#" * 72 + "\n# 2) 교차-시대 감사 — 지금 값이 '그 시대 과최적화'는 아닌가\n" + "#" * 72)
    main.CONFIG["종목목록"] = dict(AUDIT_STOCKS)
    cur = [None, None]
    main.load_prices = lambda code, start: _full(code).loc[cur[0]:cur[1]]
    try:
        for name in tune.GRIDS:
            print(f"\n[{name}] 시대별 최고 조합 vs 지금 채택값(★) 순위")
            base_profits = []
            for era, (s, e) in ERAS.items():
                cur[0], cur[1] = s, e
                rows = tune.tune_one(name)
                top = rows[0]
                base = next((r for r in rows if r["기본값"] == "예"), None)
                key = [k for k in rows[0] if k not in (
                    "훈련_순손익", "훈련_MDD%", "검증_순손익", "검증_MDD%",
                    "검증_매수", "검증_승률%", "검증_정지", "기본값")]
                top_s = ", ".join(f"{k}={top[k]}" for k in key)
                print(f"  {era}: 최고=[{top_s}] 검증 {top['검증_순손익']:,}")
                if base:
                    rank = rows.index(base) + 1
                    print(f"          ★지금값 {rank}/{len(rows)}등, 검증 {base['검증_순손익']:,}")
                    base_profits.append((era, base["검증_순손익"], rank, len(rows)))
            # 과최적화 경고: 어느 시대든 지금값이 손실이거나 하위권이면 의심
            warn = [era for era, p, rk, n in base_profits if p < 0 or rk > n * 0.5]
            if warn:
                print(f"  ⚠️ 과최적화 의심: {', '.join(warn)} 에서 지금값이 손실 또는 하위권. 재검토 필요.")
            else:
                print("  ✅ 모든 시대에서 지금값이 흑자+상위권 — 국면에 안 휘둘림.")
    finally:
        main.load_prices = _orig_load


if __name__ == "__main__":
    print("데이터 받는 중(10종목, 2018~)...", flush=True)
    regime_report()
    overfit_audit()
    print("\n※ 과거 검증일 뿐 미래 보장 아님. 규칙 바꿀 때마다 이걸 돌리고, 최종은 live.py 포워드 검증.")
