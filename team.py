"""
team.py - 팀장 오케스트레이터: 하루치 '전체 의사결정 루프' (가상, 진짜 돈 0원)
------------------------------------------------------------------
운영모델을 한 번에 돌린다:
  ① screener → 트레이너별 '매수' 후보 (부하가 넓은 종목군에서 스스로 선별)
  ② analyst(claude -p) → 후보 위험점검·veto·확신도 (팀장인 나의 분석; 없으면 규칙 폴백)
  ③ 규칙 → 보유종목 매도 관리 + 서킷 브레이커 + 신규 매수
  ④ 가짜 지갑 체결 → state/team_<트레이너>.json 저장
트레이너별 1개 포트폴리오 지갑(여러 종목 보유). 같은 날 재실행하면 멱등으로 건너뜀.

실행: python team.py [N]   (N = 스크리너가 훑을 종목 수, 기본 40)
"""

import sys
import json
from datetime import datetime
from dataclasses import asdict
from pathlib import Path

import main
import screener
import analyst
from paper_wallet import PaperWallet, Holding
from sprinter_brain import SprinterBrain
from marathoner_brain import MarathonerBrain
from pioneer_brain import PioneerBrain
from risk_guard import CircuitBreaker

STATE_DIR = Path(__file__).parent / "state"
BRAINS = {"마라토너": MarathonerBrain, "스프린터": SprinterBrain, "파이오니어": PioneerBrain}
MAX_POSITIONS = 5          # 트레이너당 최대 보유 종목 수(과집중 방지)
START = "2024-06-01"       # 지표 워밍업


def _load(tname):
    f = STATE_DIR / f"team_{tname}.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def _save(tname, wallet, positions, prev_value, stopped, last_date, start_cash):
    STATE_DIR.mkdir(exist_ok=True)
    (STATE_DIR / f"team_{tname}.json").write_text(json.dumps({
        "wallet": asdict(wallet), "positions": positions, "prev_value": prev_value,
        "stopped": stopped, "last_date": last_date, "start_cash": start_cash,
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def _wallet_from_dict(d):
    w = PaperWallet(name=d["name"], cash=d["cash"], fee_rate=d["fee_rate"],
                    sell_tax_rate=d.get("sell_tax_rate", 0.0018), slippage=d.get("slippage", 0.0005))
    w.holdings = {k: Holding(**v) for k, v in d["holdings"].items()}
    w.log = d["log"]
    return w


def run_trainer(tname, cash, cap, breaker, screened):
    """이 트레이너의 오늘 하루: 보유관리 → 서킷 → 신규매수. 사람이 읽을 한 줄 반환."""
    brain = BRAINS[tname]()
    st = _load(tname)
    if st is None:
        wallet = PaperWallet(name=tname); wallet.deposit(cash)
        positions, prev_value, stopped, last_date, start_cash = {}, None, False, None, cash
    else:
        wallet = _wallet_from_dict(st["wallet"])
        positions, prev_value = st["positions"], st["prev_value"]
        stopped, last_date, start_cash = st["stopped"], st["last_date"], st["start_cash"]

    today = datetime.now().date().isoformat()
    if last_date == today:
        return f"{tname}: 오늘({today}) 이미 실행됨 (멱등)."

    logs, prices = [], {}

    # ① 보유 종목 매도 관리
    for code in list(positions.keys()):
        try:
            df = brain.add_indicators(main.load_prices(code, START))
        except Exception:
            continue
        price = float(df["Close"].iloc[-1]); prices[code] = price
        pos = positions[code]; pos["days_held"] = pos.get("days_held", 0) + 1
        action, reason = brain.decide(df, pos)
        if action == "매도" and wallet.sell(code, price, pos["shares"]):
            logs.append(f"매도 {code}@{price:.2f}({reason[:14]})"); del positions[code]

    # ② 서킷 브레이커 (포트폴리오 단위)
    if not stopped:
        hit = breaker.check(start_cash, prev_value, wallet.value(prices))
        if hit:
            for code, pos in list(positions.items()):
                p = prices.get(code, pos["buy_price"])
                if wallet.sell(code, p, pos["shares"]):
                    del positions[code]
            stopped = True; logs.append("🛑서킷:" + hit[:20])

    # ③ 신규 후보 → 팀장 분석(veto) → 매수
    if not stopped and len(positions) < MAX_POSITIONS:
        cands = [c for c in screened if c["code"] not in positions]
        cands = analyst.apply(cands, analyst.analyze(tname, cands))   # 팀장 분석; 부재 시 규칙 폴백
        cands.sort(key=lambda c: c.get("conviction") or 0, reverse=True)
        for c in cands:
            if len(positions) >= MAX_POSITIONS:
                break
            code, price = c["code"], c["price"]     # screener가 이미 '매수' 신호+가격 확인함
            shares = max(1, int(cash * cap / price))
            if wallet.buy(code, price, shares):
                positions[code] = {"buy_price": price, "days_held": 0, "shares": shares}
                prices[code] = price
                tip = f" 팀장:{c['note']}" if c.get("note") else ""
                logs.append(f"매수 {code}x{shares}@{price:.2f}{tip}")

    value_now = wallet.value(prices)
    _save(tname, wallet, positions, value_now, stopped, today, start_cash)
    body = "; ".join(logs) if logs else "변화 없음"
    return f"{tname}: 평가 {value_now:,.0f}원 | 보유 {len(positions)}종목 | {body}" + (" [정지]" if stopped else "")


def run(n=40):
    print("=" * 60)
    print(" 팀장 일일 루프 (가상, 진짜 돈 0원)")
    print("=" * 60)
    total = main.CONFIG["총_가상자금"]; ratios = main.CONFIG["배분비율"]; caps = main.CONFIG["종목상한"]
    cb = main.CONFIG["서킷브레이커"]; breaker = CircuitBreaker(cb["누적한도"], cb["일일한도"])
    print(f"① 스크리너 {n}종목 스캔 중...", flush=True)
    found, used = screener.scan(n)
    print(f"  스캔 {used}종목 완료. 트레이너별 후보: " +
          ", ".join(f"{t} {len(found.get(t, []))}" for t in BRAINS))
    print("②~④ 트레이너별 분석·판단·체결:")
    for tname in BRAINS:
        cash = int(total * ratios[tname])
        print("  " + run_trainer(tname, cash, caps[tname], breaker, found.get(tname, [])))
    print("=" * 60)
    print("※ 가상매매. 상태 state/team_*.json 저장 → 내일 이어짐. (analyst는 claude 없으면 규칙 폴백)")


if __name__ == "__main__":
    run(int(sys.argv[1]) if len(sys.argv) > 1 else 40)
