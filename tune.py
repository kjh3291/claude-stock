"""
파라미터 튜닝 - 여러 값을 과거 데이터로 쓸어보고 성적을 '기록'한다.
------------------------------------------------------------------
과최적화를 막으려고 기간을 둘로 나눈다:
  - 훈련(train, 앞 60%): 여기서 좋은 값을 고른다
  - 검증(test, 뒤 40%): 그 값이 '안 본 기간'에서도 좋은지 확인한다
훈련만 좋고 검증이 나쁘면 = 과거에 끼워맞춘 것(overfit). 검증까지 좋아야 채택.

루프마다 나온 성적표를 버리지 않고 results/tune_*.csv 에 전부 남긴다.
표는 검증(out-of-sample) 순손익 높은 순으로 정렬한다.

⚠️ 검증까지 좋아도 미래 보장은 아니다. 고른 값은 live.py 로 포워드 검증할 것.

실행: python tune.py   (main.py 와 같은 라이브러리 필요)
"""

import csv
import inspect
import itertools

import main
from sprinter_brain import SprinterBrain
from pioneer_brain import PioneerBrain
from risk_guard import CircuitBreaker

TRAIN_RATIO = 0.6   # 앞 60%로 값 고르고, 뒤 40%로 재확인

# ===== 쓸어볼 값들 (여기 숫자만 바꾸면 됨) =====
GRIDS = {
    "스프린터": {   # 진입 문턱을 높여 매매 횟수를 줄이고 수수료를 이기는지 탐색
        "class": SprinterBrain,
        "params": {
            "take_profit":    [0.03, 0.05],
            "stop_loss":      [0.015, 0.02],
            "cross_lookback": [1, 3],           # 1=신선한 크로스만(매매 줄임)
            "rsi_floor":      [0, 45, 50, 55],  # 진입 문턱: 약한 기세 매수 차단
        },
    },
    "파이오니어": {  # 5종목·train/test로 35/1.5 완화가 견고한지 재확인
        "class": PioneerBrain,
        "params": {
            "volume_surge": [1.3, 1.5, 1.8],
            "rsi_oversold": [30, 35, 40],
            "take_profit":  [0.10],
            "stop_loss":    [0.05],
        },
    },
}
# ==============================================


def _combos(params):
    keys = list(params)
    for vals in itertools.product(*(params[k] for k in keys)):
        yield dict(zip(keys, vals))


def _defaults(cls):
    return {k: v.default for k, v in inspect.signature(cls.__init__).parameters.items()
            if v.default is not inspect.Parameter.empty}


def tune_one(name):
    """이 트레이너의 모든 값 조합을 종목 전체에 돌려, 훈련·검증 성적을 각각 집계."""
    spec = GRIDS[name]
    cls = spec["class"]
    cash = int(main.CONFIG["총_가상자금"] * main.CONFIG["배분비율"][name])
    cap = main.CONFIG["종목상한"][name]
    cb = main.CONFIG["서킷브레이커"]
    breaker = CircuitBreaker(cb["누적한도"], cb["일일한도"])
    defaults = _defaults(cls)

    # 데이터는 종목당 한 번만 로드하고 훈련/검증으로 쪼갠다
    stocks = {}
    for 종목명, code in main.CONFIG["종목목록"].items():
        df = main.load_prices(code, main.CONFIG["시작일"])
        split = int(len(df) * TRAIN_RATIO)
        stocks[종목명] = (code, df.iloc[:split], df.iloc[split:])

    rows = []
    for combo in _combos(spec["params"]):
        tr_profit = te_profit = 0.0
        tr_mdd = te_mdd = 0.0
        te_buys = te_closed = te_wins = te_stopped = 0
        for code, train_df, test_df in stocks.values():
            rt = main.run_one_trainer(name, cls(**combo), train_df, cash, cap, code, breaker)
            rv = main.run_one_trainer(name, cls(**combo), test_df, cash, cap, code, breaker)
            tr_profit += rt["profit"]; tr_mdd = min(tr_mdd, rt["mdd"])
            te_profit += rv["profit"]; te_mdd = min(te_mdd, rv["mdd"])
            te_buys += rv["buys"]; te_closed += rv["closed"]; te_wins += rv["wins"]
            te_stopped += 1 if rv["stopped"] else 0
        rows.append({
            **combo,
            "훈련_순손익": round(tr_profit), "훈련_MDD%": round(tr_mdd * 100, 1),
            "검증_순손익": round(te_profit), "검증_MDD%": round(te_mdd * 100, 1),
            "검증_매수": te_buys,
            "검증_승률%": round(te_wins / te_closed * 100, 1) if te_closed else "",
            "검증_정지": te_stopped,
            "기본값": "예" if all(combo.get(k) == defaults.get(k) for k in combo) else "",
        })
    # 검증(안 본 기간) 순손익 높은 순 → 같으면 덜 물린 순
    rows.sort(key=lambda x: (x["검증_순손익"], x["검증_MDD%"]), reverse=True)
    return rows


def _save(name, rows):
    main.RESULTS_DIR.mkdir(exist_ok=True)
    f = main.RESULTS_DIR / f"tune_{name}.csv"
    with open(f, "w", newline="", encoding="utf-8-sig") as fp:
        w = csv.DictWriter(fp, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    return f


def main_run():
    print("=" * 68)
    print(" 파라미터 튜닝 — 훈련(앞60%)으로 고르고 검증(뒤40%)으로 재확인")
    print(f" 종목: {', '.join(main.CONFIG['종목목록'])}  기간: {main.CONFIG['시작일']}~")
    print("=" * 68)
    for name in GRIDS:
        print(f"\n▼ [{name}] 조합 쓸어보는 중...")
        rows = tune_one(name)
        f = _save(name, rows)
        cols = [k for k in rows[0] if k != "기본값"]
        print(f"  {len(rows)}개 조합을 {f.name} 에 기록. 검증 성적 상위 5개:")
        print("   " + "  ".join(cols))
        for row in rows[:5]:
            mark = " ★기본값" if row["기본값"] else ""
            print("   " + "  ".join(str(row[c]) for c in cols) + mark)
        base = next((r for r in rows if r["기본값"]), None)
        if base and base not in rows[:5]:
            print(f"   (지금 기본값은 {len(rows)}개 중 {rows.index(base)+1}등: "
                  f"검증 순손익 {base['검증_순손익']:,})")
    print("\n" + "=" * 68)
    print("※ 훈련만 좋고 검증 나쁘면 과최적화. 검증까지 좋은 값만 채택하세요.")
    print("※ 검증까지 좋아도 미래 보장은 아니에요. 고른 값은 live.py 로 포워드 검증.")
    print("=" * 68)


if __name__ == "__main__":
    main_run()
