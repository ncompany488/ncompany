"""텔레그램 키워드 알림.

서버 없이 동작하도록, 수집이 돌 때마다:
  1) 봇에게 온 명령(/add, /del, /list ...)을 getUpdates 로 읽어 구독 정보를 갱신
  2) 새로 발견된 딜 그룹 중 키워드에 맞는 것을 구독자에게 전송
구독 정보(채팅 id·키워드)는 공개 저장소에 올라가므로 봇 토큰으로 만든 키로 암호화해 저장한다.

키워드 문법 (띄어쓰기 = 모두 포함):
  /add 에어팟 프로          → '에어팟'과 '프로'가 모두 들어간 딜
  /add 모니터 -중고         → '중고' 가 들어간 딜은 제외
  /add 라면 <15000          → 15,000원 이하만 (만 단위도 가능: <1.5만)
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import time
from html import escape
from pathlib import Path

import requests
from cryptography.fernet import Fernet, InvalidToken

from .store import ROOT

STATE_PATH = ROOT / "data" / "alerts.enc"
API = "https://api.telegram.org/bot{token}/{method}"
MAX_SUBSCRIBERS = 500
MAX_RULES = 30
MAX_RULE_LEN = 60         # 키워드 한 줄 최대 글자 수
MAX_ALERTS_PER_RUN = 15   # 한 사람에게 한 번에 보내는 최대 개수
MAX_MSG = 4000            # 텔레그램 한 메시지 한도(4096)보다 조금 작게
SEND_GAP = 0.05           # 전송 간격(초) — 텔레그램 초당 30건 제한
SITE_URL = os.environ.get("SITE_URL", "")

HELP = (
    "🔥 <b>핫딜 허브 알림봇</b>\n"
    "키워드를 등록하면 새 핫딜이 올라올 때 알려드려요. (수집 주기만큼 지연될 수 있어요)\n\n"
    "<code>/add 에어팟 프로</code> — 두 단어 모두 포함\n"
    "<code>/add 모니터 -중고</code> — '중고' 제외\n"
    "<code>/add 라면 &lt;15000</code> — 15,000원 이하만 (<code>&lt;1.5만</code> 도 가능)\n"
    "<code>/list</code> — 내 키워드 보기\n"
    "<code>/del 번호</code> 또는 <code>/del 키워드</code> — 삭제\n"
    "<code>/pause</code> · <code>/resume</code> — 알림 일시정지/재개\n"
    "<code>/stop</code> — 내 정보 전부 삭제"
)


# ---------- 저장 (암호화) ----------

def _fernet(token: str) -> Fernet:
    key = hashlib.sha256(("hotdeal-hub:" + token).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def load_state(token: str) -> dict:
    try:
        raw = STATE_PATH.read_bytes()
    except FileNotFoundError:
        return {"offset": 0, "subs": {}}
    try:
        return json.loads(_fernet(token).decrypt(raw))
    except (InvalidToken, json.JSONDecodeError):
        # 봇 토큰이 바뀌면 예전 파일은 못 읽음 → 새로 시작
        print("[alerts] 구독 파일을 풀 수 없음(토큰 변경?) → 새로 시작")
        return {"offset": 0, "subs": {}}


def save_state(token: str, state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_bytes(_fernet(token).encrypt(json.dumps(state, ensure_ascii=False).encode()))


# ---------- 규칙 ----------

_MAXP = re.compile(r"(?:<=?|≤)(\d[\d,]*(?:\.\d+)?)(만)?(원)?")


def parse_rule(text: str) -> dict | None:
    text = " ".join(text.split())[:MAX_RULE_LEN]
    inc, exc, max_price = [], [], None
    for tok in text.split():
        m = _MAXP.fullmatch(tok)
        if m:
            v = float(m.group(1).replace(",", "")) * (10000 if m.group(2) else 1)
            max_price = int(round(v))  # 2.3만 → 23000 (부동소수 오차 방지)
        elif tok.startswith("-") and len(tok) > 1:
            exc.append(tok[1:].lower())
        else:
            inc.append(tok.lower())
    if not inc:
        return None
    return {"inc": inc, "exc": exc, "max": max_price, "text": text}


def rule_matches(rule: dict, group: dict) -> bool:
    hay = " ".join([group.get("title") or "", group.get("shop") or ""]
                   + [s.get("title") or "" for s in group.get("sources", [])]).lower()
    hay_nospace = hay.replace(" ", "")
    if not all(w in hay or w in hay_nospace for w in rule["inc"]):
        return False
    if any(w in hay or w in hay_nospace for w in rule["exc"]):
        return False
    if rule.get("max") is not None:
        if (group.get("currency") or "KRW") != "KRW" or group.get("price") is None:
            return False
        if group["price"] > rule["max"]:
            return False
    return True


# ---------- 텔레그램 API ----------

class TelegramError(RuntimeError):
    def __init__(self, method: str, code: int | None, desc: str, retry_after: int | None = None):
        super().__init__(f"telegram {method}: [{code}] {desc}")
        self.code, self.desc, self.retry_after = code, desc, retry_after


def _call(token: str, method: str, **params):
    r = requests.post(API.format(token=token, method=method), json=params, timeout=20)
    try:
        data = r.json()
    except ValueError:
        raise TelegramError(method, r.status_code, "응답이 JSON 이 아님")
    if not data.get("ok"):
        retry = (data.get("parameters") or {}).get("retry_after")
        raise TelegramError(method, data.get("error_code"), str(data.get("description")), retry)
    return data["result"]


SENT, DEAD, FAILED = "sent", "dead", "failed"


def _send(token: str, chat_id: str, text: str) -> str:
    """SENT / DEAD(차단·탈퇴 → 구독 삭제) / FAILED(일시 오류 → 다음에 다시)."""
    for attempt in range(2):
        try:
            _call(token, "sendMessage", chat_id=int(chat_id), text=text[:4096], parse_mode="HTML",
                  disable_web_page_preview=True)
            time.sleep(SEND_GAP)
            return SENT
        except TelegramError as e:
            print(f"[alerts] send fail {chat_id}: {e}")
            if e.code == 403 or (e.code == 400 and "chat not found" in e.desc.lower()):
                return DEAD
            if e.code == 429 and e.retry_after and attempt == 0:
                time.sleep(min(e.retry_after, 30))
                continue
            return FAILED
        except Exception as e:  # 네트워크 오류 등
            print(f"[alerts] send fail {chat_id}: {e}")
            return FAILED
    return FAILED


def _clip(lines: list[str], limit: int = MAX_MSG) -> str:
    """줄 단위로 이어 붙이되 한도를 넘으면 '…' 으로 끝냄 (HTML 태그가 잘리지 않게)."""
    out, size = [], 0
    for ln in lines:
        if size + len(ln) + 1 > limit:
            out.append("…")
            break
        out.append(ln)
        size += len(ln) + 1
    return "\n".join(out)


def _reply_for(cmd: str, arg: str, chat: str, subs: dict) -> str | None:
    sub = subs.get(chat)
    if cmd in ("/start", "/help"):
        return HELP
    if cmd == "/add":
        rule = parse_rule(arg)
        if rule is None:
            return "사용법: <code>/add 키워드</code>"
        if sub is None and len(subs) >= MAX_SUBSCRIBERS:
            return "죄송해요, 구독자 수가 가득 찼어요."
        sub = subs.setdefault(chat, {"rules": [], "sent": [], "paused": False})
        if len(sub["rules"]) >= MAX_RULES:
            return f"키워드는 최대 {MAX_RULES}개까지예요."
        if any(r["text"] == rule["text"] for r in sub["rules"]):
            return "이미 등록된 키워드예요."
        sub["rules"].append(rule)
        return f"✅ 등록: <b>{escape(rule['text'])}</b>"
    if cmd == "/list":
        if not sub or not sub["rules"]:
            return "등록된 키워드가 없어요. <code>/add 키워드</code> 로 추가하세요."
        head = "📋 내 키워드" + (" (일시정지 중)" if sub.get("paused") else "")
        return _clip([head] + [f"{i + 1}. {escape(r['text'])}" for i, r in enumerate(sub["rules"])])
    if cmd == "/del":
        if not sub or not sub["rules"]:
            return "등록된 키워드가 없어요."
        a = " ".join(arg.split())
        idx = int(a) - 1 if a.isdigit() else next(
            (i for i, r in enumerate(sub["rules"]) if r["text"].lower() == a.lower()), -1)
        if 0 <= idx < len(sub["rules"]):
            r = sub["rules"].pop(idx)
            return f"🗑 삭제: {escape(r['text'])}"
        return "그런 키워드가 없어요. <code>/list</code> 로 확인하세요."
    if cmd in ("/pause", "/resume"):
        if not sub:
            return "등록된 키워드가 없어요. <code>/add 키워드</code> 로 추가하세요."
        sub["paused"] = cmd == "/pause"
        return "⏸ 알림을 멈췄어요." if sub["paused"] else "▶️ 알림을 다시 보내요."
    if cmd == "/stop":
        subs.pop(chat, None)
        return "모든 정보를 삭제했어요. 다시 쓰려면 /start"
    return "모르는 명령이에요. /help 를 보내 보세요."


def handle_commands(token: str, state: dict) -> None:
    subs: dict = state.setdefault("subs", {})
    for _ in range(20):  # 한 번에 최대 100개씩 오므로 남은 게 없을 때까지
        try:
            updates = _call(token, "getUpdates", offset=state.get("offset", 0), timeout=0,
                            allowed_updates=["message", "my_chat_member"])
        except Exception as e:
            print(f"[alerts] getUpdates 실패: {e}")
            return
        if not updates:
            return
        for u in updates:
            state["offset"] = u["update_id"] + 1
            # 사용자가 봇을 차단/그룹에서 내보냄 → 구독 삭제
            mcm = u.get("my_chat_member") or {}
            if (mcm.get("new_chat_member") or {}).get("status") in ("kicked", "left"):
                subs.pop(str((mcm.get("chat") or {}).get("id", "")), None)
                continue
            msg = u.get("message") or {}
            chat = str((msg.get("chat") or {}).get("id", ""))
            text = (msg.get("text") or "").strip()
            if not chat or not text.startswith("/"):
                continue
            parts = text.split(maxsplit=1)  # 줄바꿈으로 구분해도 동작
            cmd = parts[0].split("@")[0].lower()
            reply = _reply_for(cmd, parts[1] if len(parts) > 1 else "", chat, subs)
            if reply and _send(token, chat, reply) == DEAD:
                subs.pop(chat, None)
        if len(updates) < 100:
            return


def _fmt_price(g: dict) -> str:
    p = g.get("price")
    if p is None:
        return ""
    if g.get("currency") == "USD":
        return f"${p / 100:,.2f}"
    return f"{p:,}원"


def _link(url: str | None, label: str) -> str:
    if not url or not re.match(r"https?://", url, re.I):
        return escape(label)
    return f"<a href=\"{escape(url, quote=True)}\">{escape(label)}</a>"


def _format(g: dict, names: dict[str, str]) -> str:
    title = g["title"] if len(g["title"]) <= 200 else g["title"][:200] + "…"
    lines = [f"🔥 <b>{escape(title)}</b>"]
    meta = " · ".join(x for x in [_fmt_price(g), escape(g.get("shop") or "")] if x)
    if meta:
        lines.append(meta)
    lines += [f"• {_link(s.get('url'), names.get(s['source'], s['source']))}" for s in g["sources"]]
    if SITE_URL:
        lines.append(_link(SITE_URL, "핫딜 허브에서 보기"))
    return _clip(lines)


def notify(token: str, state: dict, new_groups: list[dict], names: dict[str, str]) -> int:
    sent_total = 0
    dead = []
    for chat, sub in state.get("subs", {}).items():
        if sub.get("paused") or not sub.get("rules"):
            continue
        sent = sub.setdefault("sent", [])
        already = set(sent)
        count = 0
        for g in new_groups:
            if g.get("ended") or g["gid"] in already:
                continue
            if not any(rule_matches(r, g) for r in sub["rules"]):
                continue
            if count >= MAX_ALERTS_PER_RUN:
                break
            res = _send(token, chat, _format(g, names))
            if res == DEAD:
                dead.append(chat)
                break
            if res == FAILED:
                break  # 일시 오류 → 이 사람은 이번 회차 중단 (보낸 것으로 기록하지 않음)
            already.add(g["gid"])
            sent.append(g["gid"])
            count += 1
        sub["sent"] = sent[-1000:]
        sent_total += count
    for chat in dead:
        state["subs"].pop(chat, None)
    return sent_total


def run(new_groups: list[dict], names: dict[str, str]) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("[alerts] TELEGRAM_BOT_TOKEN 없음 → 알림 건너뜀")
        return
    state = load_state(token)
    try:
        handle_commands(token, state)
        n = notify(token, state, new_groups, names)
    finally:
        save_state(token, state)  # 중간에 오류가 나도 처리한 명령(offset)은 저장
    print(f"[alerts] 구독자 {len(state['subs'])}명, 전송 {n}건")
