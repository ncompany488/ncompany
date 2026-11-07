"""역대 최저가 기록(history.py) 점검: python tests/test_history.py
F-002 조건부 현재 딜은 조건부 기록끼리 비교 / F-003 통화·해외 사이트별 키 공간 분리."""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from hotdeal.history import History  # noqa: E402

fails = 0


def check(cond, msg):
    global fails
    if not cond:
        fails += 1
        print("실패:", msg)


def deal(t, price, url, src="ppomppu", date="2026-09-01T10:00:00+09:00", **kw):
    return {"title": t, "price": price, "url": url, "source": src, "posted_at": date, **kw}


def group(t, price, currency="KRW", srcs=(("now", "ppomppu"),), date="2026-11-06T10:00:00+09:00"):
    return {"title": t, "price": price, "currency": currency, "posted_at": date,
            "sources": [{"url": u, "source": s} for u, s in srcs]}


def pid_of(h, url):
    return next((pid for pid, p in h.products.items() if url in p["obs"]), None)


MEGA = "[네이버]메가MGC커피 아메리카노(HOT)"

# ---------- F-002: 조건부 현재 딜 ----------
h = History()
h.observe([deal(f"{MEGA} (1,180원/무료)", 1180, "m1", date="2026-09-01T10:00:00+09:00"),
           deal(f"{MEGA} (1,180원/무료)", 1180, "m2", date="2026-10-01T10:00:00+09:00")])
r = h.product_for_group(group(f"{MEGA} (네멤 1,100원/무료)", 1100))
check(r["cond"] is True, "네멤 = 조건부")
check(r["verdict"] != "lowest", f"일반가 1,180 기록만 있으면 네멤 1,100 은 lowest 아님: {r['verdict']}")
check(r["verdict"] == "first", f"조건부 기록이 없으면 first(기록 부족): {r['verdict']}")
check(r["history"]["basis"] == "cond", f"basis cond: {r['history'].get('basis')}")
check(r["history"]["low_unit"]["price"] == 1180, "일반가 최저는 참고용으로 유지")
check(r["diff_pct"] is None, "비교 안 했으면 diff 없음")

hc = History()
hc.observe([deal(f"{MEGA} (네멤 1,200원/무료)", 1200, "c1", date="2026-09-01T10:00:00+09:00"),
            deal(f"{MEGA} (네멤 1,250원/무료)", 1250, "c2", date="2026-10-01T10:00:00+09:00"),
            deal(f"{MEGA} (1,000원/무료)", 1000, "p1", date="2026-10-05T10:00:00+09:00"),
            deal(f"{MEGA} (1,050원/무료)", 1050, "p2", date="2026-10-15T10:00:00+09:00")])
r = hc.product_for_group(group(f"{MEGA} (네멤 1,100원/무료)", 1100))
check(r["verdict"] == "lowest" and r["history"]["basis"] == "cond",
      f"조건부 1,200·1,250 기록 + 조건부 1,100 → lowest/cond: {r['verdict']} {r['history']['basis']}")
check(r["history"]["low_cond"]["price"] == 1200, f"조건부 기준이면 low_cond 항상 표시: {r['history']['low_cond']}")
check(r["history"]["cond_samples"] == 2 and r["history"]["samples"] == 2, "표본 수 따로")
r = hc.product_for_group(group(f"{MEGA} (네멤 1,230원/무료)", 1230))
check(r["verdict"] == "near" and r["diff_pct"] == 2.5,
      f"조건부 1,230 vs 조건부 최저 1,200: {r['verdict']} {r['diff_pct']}")
# 현재 일반가 딜은 그대로 일반가끼리 (조건부 1,200 보다 비싸도 일반가 최저 1,000 과 비교)
r = hc.product_for_group(group(f"{MEGA} (990원/무료)", 990))
check(r["verdict"] == "lowest" and r["history"]["basis"] == "plain", f"일반가 990 → lowest/plain: {r['verdict']}")
r = hc.product_for_group(group(f"{MEGA} (1,040원/무료)", 1040))
check(r["verdict"] == "near" and r["diff_pct"] == 4.0, f"일반가 1,040 → near 4.0: {r['verdict']} {r['diff_pct']}")
check(r["history"]["mode"] == "total", "비교 기준(mode) 필드")

# ---------- F-003: 통화·지역별 키 공간 ----------
GL = {"ppomppu_global", "slickdeals"}
hg = History(global_sources=GL)
hg.observe([
    deal("Samsung T7 Shield 2TB Portable SSD", 12999, "u1", "slickdeals", "2026-09-01T10:00:00+09:00", currency="USD"),
    deal("Samsung T7 Shield 2TB Portable SSD", 13999, "u2", "slickdeals", "2026-10-01T10:00:00+09:00", currency="USD"),
    deal("Samsung T7 Shield 2TB Portable SSD", 189000, "k1", "ppomppu", "2026-09-02T10:00:00+09:00"),
    deal("[ebay]크록스 클래식 클로그 (45,075원/무료)", 45075, "g1", "ppomppu_global", "2026-09-03T10:00:00+09:00"),
    deal("[지마켓]크록스 클래식 클로그 (49,000원/무료)", 49000, "d1", "ppomppu", "2026-09-04T10:00:00+09:00"),
    deal("Some cheap thing", 99, "cheap", "slickdeals", currency="USD"),        # $0.99 → 기록 안 함
    deal("Samsung T7 Shield 2TB Portable SSD", 500, "jpy", "x", currency="JPY"),  # 모르는 통화 → 기록 안 함
])
check(pid_of(hg, "u1") == pid_of(hg, "u2") and pid_of(hg, "u1") != pid_of(hg, "k1"),
      f"같은 제목 KRW·USD 다른 pid: {pid_of(hg, 'u1')} / {pid_of(hg, 'k1')}")
check(pid_of(hg, "u1").startswith("usd:") and not pid_of(hg, "k1").startswith(("usd:", "g:")), "USD 접두, 국내 KRW 는 옛 키")
check(pid_of(hg, "g1") != pid_of(hg, "d1") and pid_of(hg, "g1").startswith("g:"),
      f"해외 사이트 원화 ↔ 국내 원화 다른 pid: {pid_of(hg, 'g1')} / {pid_of(hg, 'd1')}")
check(pid_of(hg, "cheap") is None and pid_of(hg, "jpy") is None, "$1 미만·모르는 통화는 기록 안 함")
check(hg.products[pid_of(hg, "u1")]["obs"]["u1"]["currency"] == "USD"
      and "currency" not in hg.products[pid_of(hg, "k1")]["obs"]["k1"], "obs 에 통화 (KRW 는 생략)")
check(not any(o.get("currency") == "USD" for pid, p in hg.products.items() if not pid.startswith("usd:")
              for o in p["obs"].values()), "USD obs 가 다른 공간에 0건")

r = hg.product_for_group(group("Samsung T7 Shield 2TB Portable SSD", 11999, "USD", (("u_now", "slickdeals"),)))
check(r and r["verdict"] == "lowest" and r["currency"] == "USD" and r["history"]["samples"] == 2,
      f"USD 2건 + 더 싼 USD → lowest/USD: {r and (r['verdict'], r['currency'])}")
check(r["history"]["low_unit"]["price"] == 12999, "USD 최저가는 센트 그대로")
r = hg.product_for_group(group("Samsung T7 Shield 2TB Portable SSD", 185000, "KRW"))
check(r["currency"] == "KRW" and r["verdict"] == "first" and r["history"]["samples"] == 1,
      f"국내 KRW 그룹은 USD 기록을 보지 않음: {r['verdict']} {r['history']}")
r = hg.product_for_group(group("[ebay]크록스 클래식 클로그 (40,000원/무료)", 40000, "KRW", (("g_now", "ppomppu_global"),)))
check(r["history"]["samples"] == 1 and r["history"]["low_unit"]["url"] == "g1", "해외 원화 그룹은 해외 원화 기록만")
r = hg.product_for_group(group("[지마켓]크록스 클래식 클로그 (40,000원/무료)", 40000, "KRW",
                               (("a", "ppomppu_global"), ("b", "ppomppu"))))
check(r["history"]["low_unit"]["url"] == "d1", "국내 글이 섞인 그룹은 국내 공간")
check(hg.product_for_group(group("Samsung T7 Shield 2TB Portable SSD", 500, "JPY")) is None, "모르는 통화 그룹 → None")

# 기본값(해외 목록 없음)은 예전과 같음: 해외 사이트 원화 글도 국내 공간
h0 = History()
h0.observe([deal("[ebay]크록스 클래식 클로그 (45,075원/무료)", 45075, "g1", "ppomppu_global")])
check(pid_of(h0, "g1") == "크록스클래식클로그", f"global_sources 없으면 옛 키: {pid_of(h0, 'g1')}")

# 저장·불러오기: 해외 목록은 파일에 누적, 인자 없이 불러도 유지(재분류 없음). 새 해외 사이트가 늘면 재분류
tmp = Path(tempfile.mkdtemp()) / "h.json"
h0.save(tmp)
check(json.loads(tmp.read_text(encoding="utf-8"))["global_sources"] == [], "빈 목록 저장")
check(not History.load(tmp).rebuilt, "같은 조건이면 재분류 없음")
h1 = History.load(tmp, global_sources=GL)
check(h1.rebuilt and pid_of(h1, "g1") == "g:크록스클래식클로그", f"해외 사이트 추가 → 재분류로 이동: {pid_of(h1, 'g1')}")
h1.save(tmp)
h2 = History.load(tmp)
check(not h2.rebuilt and h2.global_sources == GL and pid_of(h2, "g1").startswith("g:"), "인자 없이 불러도 해외 목록 유지")
check(not History.load(tmp, global_sources={"slickdeals"}).rebuilt, "목록이 줄어도 재분류·이동 없음")
hg.save(tmp)
h3 = History.load(tmp)
check(h3.products[pid_of(h3, "u1")]["obs"]["u1"]["currency"] == "USD", "USD obs 저장 왕복")
h3.rebuild()
check(pid_of(h3, "u1").startswith("usd:") and pid_of(h3, "g1").startswith("g:") and pid_of(h3, "k1") == pid_of(hg, "k1"),
      "재분류해도 공간 유지")
# 옛 파일(global_sources·currency 없음) 그대로 읽힘
old = json.loads(tmp.read_text(encoding="utf-8"))
old.pop("global_sources")
for p in old["products"].values():
    for o in p["obs"].values():
        o.pop("currency", None)
old["products"] = {k: v for k, v in old["products"].items() if not k.startswith(("usd:", "g:"))}
h4 = History(old)
check(not h4.rebuilt and pid_of(h4, "k1") == pid_of(hg, "k1"), "옛 파일 호환")

print("실패", fails, "건" if fails else "— 모두 통과")
sys.exit(1 if fails else 0)
