"""알림 로직 점검 (실제 텔레그램 없이): python tests/test_alerts.py"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")
from hotdeal import alerts  # noqa: E402

TOKEN = "123:TEST"
fails = 0


def check(cond, msg):
    global fails
    if not cond:
        fails += 1
        print("실패:", msg)


# ---------- 가짜 텔레그램 ----------
sent: list[tuple[str, str]] = []
pending: list[dict] = []
blocked: set[str] = set()
flaky: set[str] = set()
uid = [100]


def fake_call(token, method, **p):
    if method == "getUpdates":
        out = [u for u in pending if u["update_id"] >= p.get("offset", 0)][:100]
        return out
    if method == "sendMessage":
        chat = str(p["chat_id"])
        if chat in blocked:
            raise alerts.TelegramError(method, 403, "Forbidden: bot was blocked by the user")
        if chat in flaky:
            raise alerts.TelegramError(method, 500, "Internal Server Error")
        check(len(p["text"]) <= 4096, "메시지 길이 4096 초과")
        sent.append((chat, p["text"]))
        return {}
    raise AssertionError(method)


def msg(chat, text):
    uid[0] += 1
    pending.append({"update_id": uid[0], "message": {"chat": {"id": int(chat)}, "text": text}})


alerts._call = fake_call
alerts.SEND_GAP = 0
alerts.STATE_PATH = Path(tempfile.mkdtemp()) / "alerts.enc"


def replies(chat):
    return [t for c, t in sent if c == chat]


# ---------- 규칙 파싱·매칭 ----------
r = alerts.parse_rule("라면  <1.5만 -컵")
check(r == {"inc": ["라면"], "exc": ["컵"], "max": 15000, "text": "라면 <1.5만 -컵"}, f"parse {r}")
check(alerts.parse_rule("x <2.3만")["max"] == 23000, "2.3만 부동소수 오차")
check(alerts.parse_rule("x <15,000원")["max"] == 15000, "쉼표 가격")
check(alerts.parse_rule("<10000") is None, "키워드 없이 가격만")
check(alerts.parse_rule("   ") is None, "빈 키워드")
check(len(alerts.parse_rule("가" * 500)["text"]) <= alerts.MAX_RULE_LEN, "긴 키워드 자르기")

g_ramen = {"gid": "g1", "title": "[쿠팡] 신라면 40개 (15,000원)", "price": 15000, "currency": "KRW",
           "shop": "쿠팡", "ended": False,
           "sources": [{"source": "ppomppu", "title": "신라면 40개", "url": "https://x.test/1"}]}
check(alerts.rule_matches(alerts.parse_rule("신라면 <15000"), g_ramen), "가격 상한 이하 매칭")
check(not alerts.rule_matches(alerts.parse_rule("신라면 <14999"), g_ramen), "가격 상한 초과")
check(alerts.rule_matches(alerts.parse_rule("신 라면"), g_ramen), "여러 단어 모두 포함")
check(not alerts.rule_matches(alerts.parse_rule("신라면 -쿠팡"), g_ramen), "제외어")
check(alerts.rule_matches(alerts.parse_rule("신라면40개"), g_ramen), "띄어쓰기 무시")
check(not alerts.rule_matches(alerts.parse_rule("신라면 <1만"),
                              dict(g_ramen, currency="USD", price=500)), "USD 는 원화 상한 제외")

# ---------- 명령 처리 ----------
A, B, C = "111", "222", "-333"
msg(A, "/start")
msg(A, "/add 에어팟 프로")
msg(A, "/add 라면 <1.5만 -컵")
msg(A, "/add@hotdeal_bot <b>모니터</b>")
msg(A, "/add 에어팟  프로")          # 공백만 다른 중복
msg(A, "/add")
msg(A, "/list")
msg(B, "/add\n신라면")               # 줄바꿈 구분
msg(B, "/pause")
msg(C, "/resume")                    # 구독 없음
msg(A, "/del 2")
msg(A, "/del <B>모니터</B>")         # 대소문자 무시 텍스트 삭제
msg(A, "/del 9")
msg(A, "/foo")
msg(A, "그냥 대화")

state = alerts.load_state(TOKEN)
check(state == {"offset": 0, "subs": {}}, "처음 상태")
alerts.handle_commands(TOKEN, state)
check(state["offset"] == uid[0] + 1, f"offset 이동 {state['offset']}")
ra = replies(A)
check(ra[0] == alerts.HELP, "/start 도움말")
check("&lt;b&gt;모니터" in ra[3], f"HTML 이스케이프 {ra[3]}")
check(ra[4] == "이미 등록된 키워드예요.", f"중복 {ra[4]}")
check(ra[5].startswith("사용법"), "빈 /add")
check("1. 에어팟 프로" in ra[6] and "3. &lt;b&gt;" in ra[6], f"/list {ra[6]}")
check("라면" in ra[7] and "&lt;b&gt;모니터" in ra[8], f"/del {ra[7:9]}")
check(ra[9].startswith("그런 키워드가 없어요"), "없는 번호")
check(ra[10].startswith("모르는 명령"), "모르는 명령")
check(len(ra) == 11, f"일반 대화엔 답 안 함 ({len(ra)})")
check([x["text"] for x in state["subs"][A]["rules"]] == ["에어팟 프로"], "남은 규칙")
check(state["subs"][B]["rules"][0]["inc"] == ["신라면"] and state["subs"][B]["paused"], "B 상태")
check(C not in state["subs"] and replies(C), "구독 없는 /resume 은 안내만")

# 같은 업데이트 다시 안 읽음
n = len(sent)
alerts.handle_commands(TOKEN, state)
check(len(sent) == n, "offset 이후 재처리 없음")

# /list 길이 제한
for i in range(alerts.MAX_RULES + 2):
    msg("444", f"/add {'<&>' * 15}{i}")
msg("444", "/list")
alerts.handle_commands(TOKEN, state)
check(len(state["subs"]["444"]["rules"]) == alerts.MAX_RULES, "규칙 개수 제한")
check(len(replies("444")[-1]) <= 4096, "/list 길이")

# ---------- 알림 전송 ----------
names = {"ppomppu": "뽐뿌", "arca": "아카라이브"}
g_air = {"gid": "g2", "title": "에어팟 프로 3 <특가> & 쿠폰", "price": 299000, "currency": "KRW",
         "shop": "쿠팡", "ended": False,
         "sources": [{"source": "ppomppu", "title": "에어팟 프로3", "url": "https://p.test/?a=1&b=\"2\""},
                     {"source": "arca", "title": "에어팟프로", "url": "javascript:alert(1)"}]}
g_end = dict(g_air, gid="g3", ended=True)
n = len(sent)
alerts.notify(TOKEN, state, [g_air, g_end, g_ramen], names)
new = sent[n:]
check([c for c, _ in new] == [A], f"A 에게만 1건 (B 는 일시정지) {new}")
text = new[0][1]
check("&lt;특가&gt; &amp;" in text and "a=1&amp;b=&quot;2&quot;" in text, f"알림 이스케이프 {text}")
check("javascript:" not in text, "http 가 아닌 링크 제거")
n = len(sent)
alerts.notify(TOKEN, state, [g_air], names)
check(len(sent) == n, "같은 그룹 재전송 안 함")

# 일시 오류 → 보낸 것으로 기록 안 함, 차단 → 구독 삭제
state["subs"][B]["paused"] = False
flaky.add(B)
alerts.notify(TOKEN, state, [g_ramen], names)
check("g1" not in state["subs"][B]["sent"] and B in state["subs"], "일시 오류 처리")
flaky.clear()
blocked.add(B)
alerts.notify(TOKEN, state, [dict(g_ramen, gid="g9")], names)
check(B not in state["subs"], "차단한 사용자 삭제")

# 차단 이벤트(my_chat_member)로도 삭제
uid[0] += 1
pending.append({"update_id": uid[0], "my_chat_member": {"chat": {"id": int(A)},
                                                          "new_chat_member": {"status": "kicked"}}})
alerts.handle_commands(TOKEN, state)
check(A not in state["subs"], "kicked 이벤트로 삭제")

# 한 번에 보내는 최대 개수
msg("555", "/add 딜")
alerts.handle_commands(TOKEN, state)
many = [dict(g_ramen, gid=f"m{i}", title=f"딜 {i}") for i in range(40)]
n = len(sent)
alerts.notify(TOKEN, state, many, names)
check(len(sent) - n == alerts.MAX_ALERTS_PER_RUN, "1회 최대 전송 수")

# /stop
msg("555", "/stop")
alerts.handle_commands(TOKEN, state)
check("555" not in state["subs"], "/stop 삭제")

# ---------- 암호화 저장 ----------
alerts.save_state(TOKEN, state)
raw = alerts.STATE_PATH.read_bytes()
check(b"444" not in raw and "모니터".encode() not in raw, "평문 노출 없음")
check(alerts.load_state(TOKEN) == state, "암호화 왕복")
check(alerts.load_state("999:OTHER") == {"offset": 0, "subs": {}}, "다른 토큰으론 못 읽음")

print("실패", fails, "건" if fails else "— 모두 통과")
sys.exit(1 if fails else 0)
