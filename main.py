"""
===========================================================
 AI 트레이너 가상매매 (학습 모드) - 내 컴퓨터에서 실행하는 메인 파일
===========================================================
진짜 돈은 절대 쓰지 않습니다. 실제 시세를 가져와 '가짜 지갑'으로 연습만 합니다.

▶ 실행 방법 (터미널에서):
    python main.py

▶ 처음 한 번만 준비:
    pip install finance-datareader ta backtesting

이 파일이 하는 일:
  1) 실제 주가를 인터넷에서 가져온다 (예: 삼성전자, 애플)
  2) 세 트레이너(마라토너/스프린터/파이오니어)가 각자 규칙으로 가상매매
  3) 결과를 정직하게 보여주고, 오류가 나면 안전하게 멈추고 기록한다

오류가 나면: 프로그램이 멈추고 error_log.txt 에 자세히 적힙니다.
그 파일을 Claude Code로 열어 "이 오류 고쳐줘"라고 하면 됩니다.
"""

import sys
import csv
import traceback
from pathlib import Path
from datetime import datetime

# --- 우리가 만든 부품들 ---
from paper_wallet import PaperWallet
from sprinter_brain import SprinterBrain
from marathoner_brain import MarathonerBrain
from pioneer_brain import PioneerBrain
from risk_guard import CircuitBreaker


# ================= 설정 (여기 숫자만 바꾸면 됩니다) =================
CONFIG = {
    "종목목록": {
        "삼성전자": "005930",     # 국내 종목코드
        "SK하이닉스": "000660",
        "애플": "AAPL",           # 미국 종목은 티커
        "마이크로소프트": "MSFT",
        "엔비디아": "NVDA",
    },
    "시작일": "2023-01-01",     # 이 날부터의 데이터로 연습
    "총_가상자금": 1_000_000,    # 가짜 돈 100만원
    "배분비율": {"마라토너": 0.60, "스프린터": 0.30, "파이오니어": 0.10},
    # 한 종목에 트레이너 예산의 몇 %까지 넣을지 (기획서 2-1). 위험할수록 작게.
    "종목상한": {"마라토너": 0.30, "스프린터": 0.20, "파이오니어": 0.15},
    # 서킷 브레이커: 누적/하루 손실이 이 한도를 넘으면 자동 전량정리+정지 (기획서 3.3)
    "서킷브레이커": {"누적한도": 0.10, "일일한도": 0.07},
}
# ================================================================

RESULTS_DIR = Path(__file__).parent / "results"  # 성적표·거래로그 CSV가 저장되는 곳


def load_prices(code: str, start: str):
    """실제 주가 데이터를 가져온다. 실패하면 친절한 메시지와 함께 알린다."""
    try:
        import FinanceDataReader as fdr
    except ImportError:
        raise SystemExit(
            "\n[준비 필요] 라이브러리가 없어요. 터미널에 이걸 입력하세요:\n"
            "    pip install finance-datareader ta backtesting\n"
        )
    df = fdr.DataReader(code, start)
    if df is None or len(df) == 0:
        raise ValueError(f"'{code}' 데이터를 가져오지 못했어요. 종목코드나 인터넷 연결을 확인하세요.")
    # 거래량 칼럼 이름 정리 (파이오니어가 사용)
    if "Volume" not in df.columns and "거래량" in df.columns:
        df = df.rename(columns={"거래량": "Volume"})
    return df


def _max_drawdown(curve):
    """평가금액 곡선에서 최대 낙폭(MDD)을 계산. 고점 대비 가장 깊이 빠진 비율(음수)."""
    if not curve:
        return 0.0
    peak = curve[0]
    mdd = 0.0
    for v in curve:
        peak = max(peak, v)
        mdd = min(mdd, v / peak - 1)  # 지금이 고점 대비 몇 % 아래인가
    return mdd


def run_one_trainer(name, brain, df, cash, cap, code, breaker=None):
    """트레이너 한 명이 이 종목을 가상매매. 정직한 성적표를 돌려준다.
    cap: 이 종목에 넣을 수 있는 예산 비율 (기획서 종목상한). 매수 시점 가격으로 주식 수 결정.
    breaker: 서킷 브레이커. 매일 decide 전에 검사해 한도 넘으면 전량정리+정지."""
    wallet = PaperWallet(name=name)
    wallet.deposit(cash)
    df = brain.add_indicators(df)

    position = None
    buys = closed = wins = 0
    last_reason = "판단할 만큼 데이터가 쌓이지 않았어요."
    equity_curve = []          # 하루하루 평가금액 (MDD·검증용)
    stopped = False            # 서킷 브레이커 발동 후 남은 기간 매매 중단
    breaker_reason = None
    prev_value = None
    need = 60 if isinstance(brain, MarathonerBrain) else 20

    for day in range(need, len(df)):
        window = df.iloc[: day + 1]
        row = window.iloc[-1]
        if row[[c for c in ["MA5", "MA20", "MA60", "RSI"] if c in window.columns]].isnull().any():
            continue
        price = float(row["Close"])
        if position is not None:
            position["days_held"] += 1

        # --- 서킷 브레이커: 오늘 지갑값으로 먼저 검사 (decide보다 우선) ---
        today_value = wallet.value({code: price})
        if not stopped and breaker is not None:
            hit = breaker.check(cash, prev_value, today_value)
            if hit is not None:
                if position is not None:   # 들고 있으면 전량 강제 정리
                    entry = position["buy_price"]
                    if wallet.sell(code, price, position["shares"]):
                        closed += 1
                        if price > entry:
                            wins += 1
                    position = None
                stopped = True
                breaker_reason = hit
                last_reason = "🛑 서킷 브레이커: " + hit

        if not stopped:
            action, reason = brain.decide(window, position)
            last_reason = reason
            if action == "매수" and position is None:
                # 살 주식 수 = 종목상한 예산 안에서, 매수 당일 가격으로 (미래 데이터 참조 없음)
                shares = max(1, int(cash * cap / price))
                if wallet.buy(code, price, shares):
                    position = {"buy_price": price, "days_held": 0, "shares": shares}
                    buys += 1
            elif action == "매도" and position is not None:
                entry = position["buy_price"]
                if wallet.sell(code, price, position["shares"]):
                    closed += 1
                    if price > entry:
                        wins += 1
                    position = None

        value_now = wallet.value({code: price})
        equity_curve.append((window.index[-1].date().isoformat(), value_now))
        prev_value = value_now

    last_price = float(df["Close"].iloc[-1])
    final = wallet.value({code: last_price})
    still = position is not None
    unreal = (last_price - position["buy_price"]) * position["shares"] if still else 0.0
    return {
        "name": name, "profit": final - cash, "buys": buys, "closed": closed, "wins": wins,
        "win_rate": (wins / closed * 100) if closed else None,
        "still_holding": still, "unrealized": unreal,
        "mdd": _max_drawdown([v for _, v in equity_curve]),
        "last_reason": last_reason,
        "stopped": stopped, "breaker_reason": breaker_reason,
        "log": wallet.log,
        "equity_curve": equity_curve,
    }


def save_logs(stock_name, r):
    """이 트레이너의 거래내역과 일별 평가금액을 results/ 폴더에 CSV로 저장."""
    RESULTS_DIR.mkdir(exist_ok=True)
    base = f"{stock_name}_{r['name']}"
    with open(RESULTS_DIR / f"{base}_거래내역.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["시각", "종류", "종목", "수량", "금액"])
        for e in r["log"]:
            w.writerow([e["시각"], e["종류"], e["종목"], e["수량"], e["금액"]])
    with open(RESULTS_DIR / f"{base}_평가금액.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["날짜", "평가금액"])
        for d, v in r["equity_curve"]:
            w.writerow([d, round(v, 1)])


def main():
    print("=" * 55)
    print(" AI 트레이너 가상매매 (학습 모드) — 진짜 돈 0원")
    print("=" * 55)

    total = CONFIG["총_가상자금"]
    ratios = CONFIG["배분비율"]
    caps = CONFIG["종목상한"]
    cb = CONFIG["서킷브레이커"]
    breaker = CircuitBreaker(cum_limit=cb["누적한도"], day_limit=cb["일일한도"])
    brains = {
        "마라토너": MarathonerBrain(),
        "스프린터": SprinterBrain(),
        "파이오니어": PioneerBrain(),
    }

    for 종목명, code in CONFIG["종목목록"].items():
        print(f"\n▼ [{종목명}] 데이터 불러오는 중...")
        df = load_prices(code, CONFIG["시작일"])
        print(f"  {len(df)}일치 데이터 확보 ({df.index[0].date()} ~ {df.index[-1].date()})")

        print(f"  {'트레이너':<8}{'순손익':>12}{'매수':>5}{'완료':>5}{'승률':>7}{'MDD':>7}{'보유중':>7}")
        for name, brain in brains.items():
            cash = int(total * ratios[name])
            r = run_one_trainer(name, brain, df, cash, caps[name], code, breaker)
            wr = f"{r['win_rate']:.0f}%" if r["win_rate"] is not None else "-"
            mdd = f"{r['mdd']*100:.0f}%"   # 고점 대비 최대 낙폭 (얼마나 깊이 물렸나)
            hold = "예" if r["still_holding"] else "아니오"
            print(f"  {r['name']:<8}{r['profit']:>+12,.0f}{r['buys']:>5}{r['closed']:>5}{wr:>7}{mdd:>7}{hold:>7}")
            if r["still_holding"]:
                print(f"      └ 아직 안 판 평가손익 {r['unrealized']:+,.0f}원 포함 (팔아야 확정)")
            if r["stopped"]:
                print(f"      └ {r['breaker_reason']}")
            print(f"      └ 마지막 판단: {r['last_reason']}")
            save_logs(종목명, r)

    print("\n" + "=" * 55)
    print("※ 이건 가상매매입니다. 진짜 돈은 들어가지 않았습니다.")
    print("※ 결과가 좋아도 미래 수익을 보장하지 않습니다. 여러 종목·기간으로 계속 검증하세요.")
    print(f"※ 거래내역·일별 평가금액이 '{RESULTS_DIR.name}' 폴더에 CSV로 저장됐어요.")
    print("=" * 55)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        # 오류가 나면 안전하게 멈추고, 자세히 기록한다
        err = traceback.format_exc()
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open("error_log.txt", "a", encoding="utf-8") as f:
            f.write(f"\n[{stamp}]\n{err}\n")
        print("\n" + "!" * 55)
        print(" 오류가 발생해서 안전하게 멈췄어요. (돈은 절대 안 나갔어요)")
        print(" 자세한 내용이 error_log.txt 에 저장됐어요.")
        print(" 그 파일을 Claude Code로 열어 '이 오류 고쳐줘'라고 하세요.")
        print("!" * 55)
        sys.exit(1)
