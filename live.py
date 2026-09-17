"""
===========================================================
 라이브 가상매매 (매일 한 번 실행) - 진짜 돈 0원
===========================================================
main.py 는 과거 전체를 한 번에 훑는 백테스트.
live.py 는 '오늘 하루'만 판단하고 그 결과를 저장해, 내일 이어서 돌린다.
→ 과거에 끼워맞추지 않은 '미래(포워드)' 검증. 기획서 3.4의 학습 모드.

▶ 실행 (하루 한 번, 장 마감 뒤 추천):
    python live.py

  매일 자동으로 돌리고 싶으면 cron 한 줄 (예: 평일 오후 4시):
    0 16 * * 1-5  cd /경로/files && python live.py >> live.log 2>&1

상태는 state/ 폴더의 JSON에 저장됩니다. 지우면 처음부터 다시 시작해요.
같은 날 두 번 실행해도 하루치가 중복 반영되지 않습니다(멱등).
"""

import sys
import csv
import json
import traceback
from pathlib import Path
from datetime import datetime
from dataclasses import asdict

import main  # CONFIG, load_prices 재사용
from paper_wallet import PaperWallet, Holding
from sprinter_brain import SprinterBrain
from marathoner_brain import MarathonerBrain
from pioneer_brain import PioneerBrain
from risk_guard import CircuitBreaker

STATE_DIR = Path(__file__).parent / "state"   # 트레이너별 지갑·포지션 상태(JSON)
_IND = ["MA5", "MA20", "MA60", "RSI"]


def _wallet_to_dict(w: PaperWallet) -> dict:
    return asdict(w)   # holdings 안의 Holding 도 dict 로 풀림


def _wallet_from_dict(d: dict) -> PaperWallet:
    w = PaperWallet(name=d["name"], cash=d["cash"], fee_rate=d["fee_rate"])
    w.holdings = {k: Holding(**v) for k, v in d["holdings"].items()}
    w.log = d["log"]
    return w


def _load_state(stock_name, name):
    f = STATE_DIR / f"{stock_name}_{name}.json"
    if not f.exists():
        return None
    return json.loads(f.read_text(encoding="utf-8"))


def _save_state(stock_name, name, wallet, position, prev_value, stopped, last_date):
    STATE_DIR.mkdir(exist_ok=True)
    f = STATE_DIR / f"{stock_name}_{name}.json"
    f.write_text(json.dumps({
        "wallet": _wallet_to_dict(wallet), "position": position,
        "prev_value": prev_value, "stopped": stopped, "last_date": last_date,
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def _append_equity(stock_name, name, date_str, value):
    STATE_DIR.mkdir(exist_ok=True)
    f = STATE_DIR / f"{stock_name}_{name}_평가금액.csv"
    new = not f.exists()
    with open(f, "a", newline="", encoding="utf-8-sig") as fp:
        w = csv.writer(fp)
        if new:
            w.writerow(["날짜", "평가금액"])
        w.writerow([date_str, round(value, 1)])


def step_one(name, brain, cap, code, stock_name, cash, breaker):
    """이 트레이너·이 종목의 '오늘 하루'를 처리하고 상태를 저장. 사람이 읽을 한 줄을 돌려준다."""
    df = brain.add_indicators(main.load_prices(code, main.CONFIG["시작일"]))
    today = df.iloc[-1]
    today_date = df.index[-1].date().isoformat()
    price = float(today["Close"])

    st = _load_state(stock_name, name)
    if st is None:
        wallet = PaperWallet(name=name); wallet.deposit(cash)
        position = None; prev_value = None; stopped = False; last_date = None
    else:
        wallet = _wallet_from_dict(st["wallet"]); position = st["position"]
        prev_value = st["prev_value"]; stopped = st["stopped"]; last_date = st["last_date"]

    if last_date == today_date:
        return f"{stock_name}/{name}: 오늘({today_date})은 이미 처리했어요. (중복 실행 방지)"

    if today[[c for c in _IND if c in df.columns]].isnull().any():
        msg = "지표가 아직 부족해서 관망."
    else:
        if position is not None:
            position["days_held"] += 1
        today_value = wallet.value({code: price})
        hit = None if stopped else breaker.check(cash, prev_value, today_value)
        if hit is not None:
            if position is not None:
                wallet.sell(code, price, position["shares"]); position = None
            stopped = True
            msg = "🛑 서킷 브레이커: " + hit
        elif stopped:
            msg = "이미 정지됨 (서킷 브레이커 발동 후 재개 대기)."
        else:
            action, reason = brain.decide(df, position)
            msg = f"{action} — {reason}"
            if action == "매수" and position is None:
                shares = max(1, int(cash * cap / price))
                if wallet.buy(code, price, shares):
                    position = {"buy_price": price, "days_held": 0, "shares": shares}
            elif action == "매도" and position is not None:
                wallet.sell(code, price, position["shares"]); position = None

    value_now = wallet.value({code: price})
    _save_state(stock_name, name, wallet, position, value_now, stopped, today_date)
    _append_equity(stock_name, name, today_date, value_now)
    return f"[{today_date}] {stock_name}/{name}: {msg} | 평가금액 {value_now:,.0f}원"


def run():
    print("=" * 55)
    print(" 라이브 가상매매 (오늘 하루) — 진짜 돈 0원")
    print("=" * 55)
    total = main.CONFIG["총_가상자금"]
    ratios = main.CONFIG["배분비율"]
    caps = main.CONFIG["종목상한"]
    cb = main.CONFIG["서킷브레이커"]
    breaker = CircuitBreaker(cum_limit=cb["누적한도"], day_limit=cb["일일한도"])
    brains = {"마라토너": MarathonerBrain(), "스프린터": SprinterBrain(), "파이오니어": PioneerBrain()}

    for 종목명, code in main.CONFIG["종목목록"].items():
        for name, brain in brains.items():
            cash = int(total * ratios[name])
            print(step_one(name, brain, caps[name], code, 종목명, cash, breaker))

    print("=" * 55)
    print("※ 가상매매입니다. 상태는 state/ 폴더에 저장돼 내일 이어집니다.")
    print("=" * 55)


if __name__ == "__main__":
    try:
        run()
    except SystemExit:
        raise
    except Exception:
        err = traceback.format_exc()
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open("error_log.txt", "a", encoding="utf-8") as f:
            f.write(f"\n[{stamp}] (live.py)\n{err}\n")
        print("\n오류로 안전하게 멈췄어요. error_log.txt 를 Claude Code로 열어 '고쳐줘'라고 하세요.")
        sys.exit(1)
