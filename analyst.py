"""
analyst.py - 로직이 팀장(Claude)에게 연락하는 다리. (운영모델 2단계)
------------------------------------------------------------------
프로그램이 후보를 들고 `claude -p`(헤드리스)로 나를 호출 → 내가 시장·뉴스·위험을 보고
분석/코칭을 JSON으로 회신 → 프로그램이 파싱해 규칙 판단에 반영.

구독 로그인 상태면 API 종량과금이 아니라 '구독 사용량'을 쓴다(ANTHROPIC_API_KEY 안 걸 때).
그래서 여기서는 env의 ANTHROPIC_API_KEY를 제거해 **구독 사용을 강제**한다.

🔒 안전 원칙(중요): 내가 없어도(미설치·타임아웃·한도초과·JSON깨짐) 프로그램은 멈추지 않는다.
   그 경우 analyze()는 None을 돌려주고, apply()는 후보를 규칙 그대로 통과시킨다(팀장 부재 → 규칙만).
   즉 내 응답은 '있으면 반영하는 오버레이'일 뿐, 매수/매도 방아쇠는 규칙이 당긴다.
"""

from __future__ import annotations

import os
import re
import json
import shutil
import subprocess
from pathlib import Path

PROMPTS_DIR = Path(__file__).parent / "prompts"
TIMEOUT = 150   # 초. 넘으면 포기하고 규칙 폴백


def _persona(trainer: str) -> str:
    f = PROMPTS_DIR / f"{trainer}.md"
    try:
        return f.read_text(encoding="utf-8") if f.exists() else ""
    except OSError:
        return ""


def _build_prompt(trainer: str, candidates: list[dict]) -> str:
    persona = _persona(trainer)
    lines = [f"- {c['code']}: 신호사유={c.get('reason','')} RSI={c.get('rsi','?')} 종가={c.get('price','?')}"
             for c in candidates]
    return f"""{persona}

너는 '{trainer}' 트레이너의 팀장(애널리스트)이다. 아래는 규칙이 '매수' 신호를 낸 후보다.
각 종목의 최근 시장 상황·악재·위험을 성실히 고려해 평가하라. 확신 없으면 hold, 위험하면 veto.

후보:
{chr(10).join(lines) if lines else "(없음)"}

반드시 아래 JSON 객체 '하나만' 출력하라(다른 설명 금지):
{{"analysis": [{{"code": "<종목>", "verdict": "buy|hold|veto", "conviction": 0.0~1.0, "note": "<한 줄 근거>"}}]}}
"""


def _extract_json(text: str):
    """모델 출력에서 첫 JSON 객체를 뽑아 파싱. 실패하면 None."""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def analyze(trainer: str, candidates: list[dict], timeout: int = TIMEOUT):
    """claude -p로 후보 분석을 요청. 성공 시 {code: {verdict,conviction,note}}, 실패 시 None(규칙 폴백)."""
    if not candidates or shutil.which("claude") is None:
        return None
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}  # 구독 강제
    try:
        r = subprocess.run(
            ["claude", "-p", _build_prompt(trainer, candidates)],
            capture_output=True, text=True, timeout=timeout, env=env,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if r.returncode != 0:
        return None
    data = _extract_json(r.stdout)
    if not isinstance(data, dict) or "analysis" not in data:
        return None
    return {it["code"]: it for it in data["analysis"] if isinstance(it, dict) and "code" in it}


def apply(candidates: list[dict], analysis):
    """분석 결과를 후보에 반영. analysis=None이면 규칙 그대로(팀장 부재 폴백), veto면 제외."""
    if analysis is None:
        return candidates
    kept = []
    for c in candidates:
        a = analysis.get(c["code"])
        if a and a.get("verdict") == "veto":
            continue
        if a:
            c = {**c, "conviction": a.get("conviction"), "note": a.get("note")}
        kept.append(c)
    return kept


if __name__ == "__main__":
    # 자체 점검: JSON 파싱 + 폴백/veto (실제 claude 호출은 하지 않음)
    d = _extract_json('앞말 {"analysis":[{"code":"AAPL","verdict":"veto","note":"악재"}]} 뒷말')
    assert d and d["analysis"][0]["code"] == "AAPL"
    assert _extract_json("설명만 있고 json 없음") is None
    cands = [{"code": "AAPL"}, {"code": "MSFT"}]
    assert apply(cands, None) == cands                       # 팀장 부재 → 규칙 그대로
    kept = apply(cands, {"AAPL": {"verdict": "veto"},
                         "MSFT": {"verdict": "buy", "conviction": 0.8, "note": "좋음"}})
    assert [c["code"] for c in kept] == ["MSFT"]             # veto 제외
    assert kept[0]["conviction"] == 0.8                       # 주석·확신도 반영
    print("[PASS] analyst JSON파싱·veto·폴백 점검 통과")
