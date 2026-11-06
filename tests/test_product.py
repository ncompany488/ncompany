"""상품 식별·역대 최저가 점검: python tests/test_product.py"""
import itertools
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from hotdeal.history import History  # noqa: E402
from hotdeal.product import PARSER_VERSION, parse_product as p  # noqa: E402

fails = 0


def check(cond, msg):
    global fails
    if not cond:
        fails += 1
        print("실패:", msg)


def key(t):
    r = p(t)
    return r.key if r else None


def same(a, b):
    ra, rb = p(a), p(b)
    return bool(ra and rb and (ra.key == rb.key or ra.alt_key == rb.alt_key))


# ---------- 같은 상품 / 다른 상품 ----------
check(key("신라면 120g x 20봉") == key("[쿠팡] 농심 신라면 120g 20개 (15,900원/무료)"), "신라면 표기 차이는 같은 상품")
check(key("신라면 120g 20개") != key("신라면 블랙 134g 8개"), "신라면 ≠ 신라면 블랙")
check(key("신라면 블랙 컵 101g 12개") != key("신라면 블랙 134g 8개"), "블랙 봉지 ≠ 블랙 컵")
check(key("농심 신라면 툼바 4개입 x 4") == key("신라면 투움바 16개"), "툼바 = 투움바")
check(key("신라면 투움바 16개") != key("신라면 16개"), "투움바 ≠ 신라면")
check(key("아이폰 17 Pro 256GB") != key("아이폰 16 Pro 256GB"), "모델 번호 구별")
check(key("아이폰 17 Pro 256GB") != key("아이폰 17 Pro 512GB"), "GB 는 키에 남음 (용량 구별)")
check(p("신라면블랙 8개").alt_key == p("신라면 블랙 8개").alt_key or key("신라면블랙 8개") == key("신라면 블랙 8개"),
      "띄어쓰기 차이 흡수")
# C-1-1 용량 표기 유무와 무관하게 같은 상품
for a, b in [("[쿠팡] 신라면 5개 (2,400원)", "[쿠팡] 농심 신라면 120g x 20입 (5,060원/무료)"),
             ("신라면 5개", "신라면 600g"), ("삼양라면 20개", "삼양라면 120g 10개"),
             ("햇반 210g 1+1", "햇반 210g 24개"), ("초코파이 48P 1872g", "초코파이 48P 1872g 1박스"),
             ("닥터페퍼 제로 350ml 24개", "닥터페퍼 제로 500ml 24개")]:
    check(key(a) == key(b), f"같은 상품: {a} / {b}")
# C-1-3 다른 상품
for a, b in [("[쿠팡] 스위치2 포코피아 69,450원", "[예판런](NS2)스위치2 포코피아 번들 718000원 무배"),
             ("국내산 삼겹살 1kg", "미국산 삼겹살 1kg"), ("국내산 삼겹살 1kg", "삼겹살 1kg"),
             ("곰곰 무항생제 계란 30구", "계란 30구"), ("[메가MGC커피] (HOT)아메리카노", "[스타벅스] 아메리카노"),
             ("비비고 왕교자 1.05kg", "왕교자 1.05kg"), ("오뚜기 피자 2+2", "피자 4개")]:
    check(not same(a, b), f"다른 상품: {a} / {b}")
check(p("뚜레쥬르 제품교환권 1만원권") is None and p("[11번가]뚜레쥬르제품교환권 2만원권 (16,600원/무료)") is None, "교환권 제외")
# C-1-8 잘린 제목
tales = ["[카카오톡딜]PS5 테일즈 오브 이터니아 리마스터(39560원/배송비30...",
         "[지마켓] ps5 테일즈 오브 이터니아 리마스터/ 39560원/3000", "[네이버] PS5 테일즈 오브 이터니아 리마스터 / 39,800원"]
check(len({key(t) for t in tales}) == 1, f"잘린 제목 같은 상품: {[key(t) for t in tales]}")
# C-1-9
check(key("맥심 모카골드 커피믹스 190T") == key("모카골드 커피믹스 190t"), "제조사 유무")
check(key("[네이버] 멤버십 신라면 20입") == key("신라면 20개"), "멤버십 잔여어 제거")

# ---------- 수량 (C-1-2) ----------
cases = [
    ("신라면 120g x 20봉", "count", 20), ("신라면 툼바 4개입 x 4", "count", 16), ("와플 24개입, 960g, 1개", "count", 24),
    ("구운란 60구", "count", 60), ("새우 900g 1+1", "size_g", 1800), ("과자 10개 1+1", "count", 20),
    ("[지마켓] 칠성사이다 350ml 48캔 (2박스)", "count", 48), ("포카리스웨트 340ml x 48CAN (2박스)", "count", 48),
    ("[지마켓]스팀 수면안대 2+2 총 40매", "content", 40), ("블랙모어스 오메가3 80캡슐(40일분) 3+1병", "count", 4),
    ("블랙모어스 오메가3 80캡슐(40일분) 3+1병", "content", 320), ("[토스]땡큐 팝업티슈, 150입, 9팩", "count", 9),
    ("[겜우리] PS5 EA SPORTS FC27 예약 판매", "count", None), ("모노케어 멀티탭 3구 1+1", "count", 2),
    ("쿠쿠 인덕션 3구", "count", None), ("[토스] 스파클 2L 24페트", "count", 24), ("맥심 모카골드 커피믹스 190T", "count", 190),
    ("카누 0.9g 150T", "count", 150), ("카누 0.9g 150T", "size_g", 135), ("대란 30구 2판", "count", 60),
    ("사미헌 갈비탕 1kg 5팩(총 5kg)", "count", 5), ("사미헌 갈비탕 1kg 5팩(총 5kg)", "usize", 1000),
    ("하겐다즈 파인트 2+2", "count", 4), ("맨투맨 1+1", "count", 2), ("햇반 210g 1+1", "count", 2),
    ("스팸 200g 5+1", "count", 6), ("오리온 초코파이 48P 1872g(1박스)", "count", 48),
]
for t, attr, want in cases:
    r = p(t)
    got = getattr(r, attr) if r else "None"
    check(got == want, f"{t} → {attr}={got} (기대 {want})")
check(p("햅쌀 20kg").unit == "100g" and p("햅쌀 20kg").size_g == 20000, "무게만 있으면 100g당")
check(p("신라면 120g x 20봉").unit_price(15900) == 795, "개당 가격")
check(p("[스포츠리서치] 오메가3 180정").content_unit == "알", "정 → '알' 표시 (정당 오독 방지)")
check(p("[네이버]네추럴라이즈 오메가3 180캡슐 (37,500원/무배)").unit_label == "캡슐", "캡슐당")

# ---------- 비교 제외 (C-1-5) ----------
for t in ["신라면5 + 너구리5 + 짜파게티5", "하겐다즈 파인트 3개 골라담기", "올리브영 1만원 기프트카드",
          "알뜰폰 요금제 7GB", "[iOS] 앱 일시 무료", "스케쳐스 부츠 4종 택1", "두유 190ml 32입 외 다양",
          "[네이버페이] 라방 랜덤 5원", "1206-1209 인천-요나고", "마법사의 밤 한국어판 예약 판매 예정 (11월 6일 오후 ~ 11월 15"]:
    check(p(t) is None, f"제외해야 함: {t}")
# C-1-12 놓치던 단일 상품
for t in ["코크제로 350ml*24입 + 투명텀블러 증정", "[쿠팡] 크런키 초콜릿 34g 24개/17,220원 와우무배",
          "[겜우리] PS4/NS 마법사의 밤 한정판 예약 판매 / 88,000원"]:
    check(p(t) is not None, f"단일 상품 인식: {t}")
# C-1-7 조건부
for t, c in [("[네이버]농심 신라면 120g 20개(네이버멤버십12,240원/무료)", True), ("제주 삼다수 무라벨 2L X 6병 (3개월 미구매)", True),
             ("[롯데온] 칠성사이다 제로 355ml 24캔 (카드다양13,940원)", True), ("[쿠팡] 삼양라면 10개 4980원 와우무배", False),
             ("[쿠팡] 신라면 5개 (2,400원) (무료)", False)]:
    check(p(t).cond is c, f"조건부={c}: {t}")


# ---------- 역대 최저가 ----------
def deal(t, price, url, src="ppomppu", date="2026-09-01T10:00:00+09:00", **kw):
    return {"title": t, "price": price, "url": url, "source": src, "posted_at": date, **kw}


h = History()
h.observe([
    deal("신라면 120g 20개 (16,900원)", 16900, "u1", "ppomppu", "2026-09-01T10:00:00+09:00"),
    deal("신라면 120g 40개", 29900, "u2", "ruliweb", "2026-09-10T10:00:00+09:00"),
    deal("신라면 120g 20개", 15500, "u3", "clien", "2026-10-01T10:00:00+09:00", ended=True),
    deal("신라면 블랙 134g 8개", 6000, "u4", "ppomppu", "2026-10-02T10:00:00+09:00"),
])
g = {"title": "[쿠팡] 신라면 120g x 20봉", "price": 15900, "currency": "KRW", "sources": [{"url": "u_now"}],
     "posted_at": "2026-11-01T10:00:00+09:00"}
prod = h.product_for_group(g)
check(prod["unit_price"] == 795 and prod["unit"] == "개" and prod["unit_label"] == "봉", f"현재 개당 795: {prod['unit_price']}")
hi = prod["history"]
check(hi["samples"] == 3, f"신라면 과거 3건 (블랙 제외): {hi['samples']}")
check(hi["low_unit"]["url"] == "u2" and hi["low_unit"]["unit_price"] == 748 and hi["low_unit"]["cond"] is False, "개당 최저는 40개 묶음")
check(hi["low_same_count"]["url"] == "u3" and hi["low_same_count"]["price"] == 15500, "같은 20개 최저 15,500 (종료 딜도 기록)")
check(hi["low_same_count"]["ended"] is True, "종료 표시 유지")
check([t["count"] for t in hi["tiers"]] == [20, 40], "수량별 최저가 20/40")
check(prod["verdict"] == "higher" and prod["diff_pct"] == 6.4, f"판정: {prod['verdict']} {prod['diff_pct']}")
check(h.product_for_group(dict(g, price=14000))["verdict"] == "lowest", "더 싸면 역대최저")
check(h.product_for_group(dict(g, price=14960))["verdict"] == "equal", "같으면 equal")
g3 = {"title": "신라면 120g 20개", "price": 15500, "currency": "KRW", "sources": [{"url": "u3"}]}
check(h.product_for_group(g3)["history"]["samples"] == 2, "자기 자신 글은 과거 기록에서 제외")
check(h.product_for_group({"title": "새 상품 10개", "price": 1000, "currency": "KRW", "sources": []})["verdict"] == "first",
      "기록 없으면 first")

# C-1-1: 신라면 5개(용량 없음) 와 120g×20 이 서로의 기록을 봄
h1 = History()
h1.observe([deal("[쿠팡] 농심 신라면 120g x 20입 (5,060원/무료)", 5060, "a1", date="2026-10-28T10:00:00+09:00"),
            deal("[네이버] 농심 신라면 20입 (12,690원/무료)", 12690, "a2", date="2026-05-25T10:00:00+09:00")])
r = h1.product_for_group({"title": "[쿠팡] 신라면 5개 (2,400원)", "price": 2400, "currency": "KRW", "sources": [{"url": "x"}],
                          "posted_at": "2026-10-12T10:00:00+09:00"})
check(r["history"] and r["history"]["samples"] == 2 and r["history"]["low_unit"]["url"] == "a1",
      f"신라면 5개 ↔ 120g×20 비교: {r['history']}")

# C-1-4: 표본 1건 / 교차 게시는 lowest 아님
h2 = History()
h2.observe([deal("햅쌀 새청무 20kg", 56800, "p1", "ppomppu", "2026-11-05T10:00:00+09:00")])
r = h2.product_for_group({"title": "햅쌀 새청무 20kg", "price": 56800, "currency": "KRW", "sources": [{"url": "a"}],
                          "posted_at": "2026-11-05T12:00:00+09:00"})
check(r["verdict"] == "first", f"같은 날 다른 사이트 같은 가격 = 같은 딜 → first: {r['verdict']}")
h2.observe([deal("햅쌀 새청무 20kg", 60000, "p2", "ruliweb", "2026-10-01T10:00:00+09:00")])
r = h2.product_for_group({"title": "햅쌀 새청무 20kg", "price": 50000, "currency": "KRW", "sources": [], "posted_at": "2026-11-06T10:00:00+09:00"})
check(r["verdict"] == "lowest" and r["history"]["samples"] == 2, f"표본 2건이면 lowest: {r['verdict']} {r['history']['samples']}")
h2b = History()
h2b.observe([deal("라면 10개", 9000, "q1", "a", "2026-10-01T10:00:00+09:00"),
             deal("라면 10개", 9000, "q2", "b", "2026-10-02T10:00:00+09:00")])
r = h2b.product_for_group({"title": "라면 10개", "price": 8000, "currency": "KRW", "sources": [], "posted_at": "2026-11-06T10:00:00+09:00"})
check(r["verdict"] == "first" and r["history"]["samples"] == 1, "교차 게시 2건 = 표본 1건")

# C-1-6 / R-1: 개수 모르는 글과 개당가를 섞지 않음 (하겐다즈)
h3 = History()
h3.observe([deal("하겐다즈 파인트 3개", 22320, "h1", date="2026-08-01T10:00:00+09:00"),
            deal("하겐다즈 파인트 4통", 28712, "h2", date="2026-09-01T10:00:00+09:00")])
r = h3.product_for_group({"title": "[오늘의집] 하겐다즈 파인트 2+2 28,886원", "price": 28886, "currency": "KRW", "sources": []})
check(r["count"] == 4 and r["verdict"] in ("near", "lowest", "equal", "higher") and (r["diff_pct"] or 0) < 10,
      f"하겐다즈 2+2 개당 비교: {r['verdict']} {r['diff_pct']}")
# 개당 용량이 다르면 100ml당 비교 (350ml vs 500ml 를 개당으로 같다고 보지 않음)
h4 = History()
h4.observe([deal("닥터페퍼 제로 500ml 24개", 24000, "d1", date="2026-08-01T10:00:00+09:00"),
            deal("닥터페퍼 제로 500ml 24개", 25000, "d2", date="2026-09-01T10:00:00+09:00")])
r = h4.product_for_group({"title": "닥터페퍼 제로 350ml 24개", "price": 13000, "currency": "KRW", "sources": []})
check(r["unit"] == "100ml" and r["history"]["low_unit"]["unit_price"] == 200, f"용량 다르면 100ml당: {r['unit']}")
# C-1-7 조건부
h5 = History()
h5.observe([deal("삼다수 무라벨 2L 12병", 9880, "s1", date="2026-08-01T10:00:00+09:00"),
            deal("삼다수 무라벨 2L 12병", 10090, "s2", date="2026-09-01T10:00:00+09:00"),
            deal("삼다수 무라벨 2L X 6병 (3개월 미구매)", 3030, "s3", date="2026-10-01T10:00:00+09:00")])
r = h5.product_for_group({"title": "삼다수 무라벨 2L 12병", "price": 9900, "currency": "KRW", "sources": []})
hi = r["history"]
check(hi["low_unit"]["url"] == "s1" and hi["low_cond"]["url"] == "s3" and hi["low_cond"]["cond"] is True,
      f"조건부는 low_cond 로 분리: {hi['low_unit']['url']} {hi['low_cond']}")
check(r["verdict"] == "near", f"조건부 제외하고 판정: {r['verdict']}")
check(any(t["cond"] for t in hi["tiers"]), "조건부 최저는 tiers 에 cond 로 표시")

# 이상치(제목 해석 오류로 너무 싼 값)는 최저가에서 제외
h6 = History()
h6.observe([deal("라면 10개", v, f"x{i}", f"s{i}", f"2026-0{i + 1}-01T10:00:00+09:00") for i, v in enumerate([9000, 9500, 8800, 9200, 900])])
low = h6.product_for_group({"title": "라면 10개", "price": 9100, "currency": "KRW", "sources": []})["history"]["low_unit"]["price"]
check(low == 8800, f"이상치 제외: {low}")
check(not h6.observe([deal("[네이버페이] 클릭 12원", 12, "pt")]), "포인트 글은 기록 안 함")

# 저장·불러오기 왕복 + 버전
tmp = Path(tempfile.mkdtemp()) / "h.json"
h.save(tmp)
saved = json.loads(tmp.read_text(encoding="utf-8"))
check(saved.get("version") == PARSER_VERSION, "버전 저장")
h7 = History.load(tmp)
check(not h7.rebuilt and h7.product_for_group(g)["history"]["low_unit"]["url"] == "u2", "저장 왕복")

# 옛 형식(버전 없음, 옛 키) → 자동 재분류, 기록 보존
old = {"products": {
    "신라면|120g": {"keys": ["신라면|120g"], "obs": {"o1": {"price": 5060, "title": "[쿠팡] 농심 신라면 120g x 20입 (5,060원/무료)",
                                                            "source": "ruliweb", "date": "2026-10-28T10:00:00+09:00", "ended": False}}},
    "신라면": {"keys": ["신라면"], "obs": {"o2": {"price": 2400, "title": "[쿠팡] 신라면 5개 (2,400원) (무료)", "source": "ruliweb",
                                               "date": "2026-10-12T10:00:00+09:00", "ended": True}}},
    "라방랜덤": {"keys": ["라방랜덤"], "obs": {"o3": {"price": 5, "title": "[네이버페이] 라방 랜덤 5원", "source": "ruliweb",
                                                 "date": "2026-10-12T10:00:00+09:00"}}},
}}
tmp.write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
h8 = History.load(tmp)
check(h8.rebuilt and list(h8.products) == ["신라면"] and set(h8.products["신라면"]["obs"]) == {"o1", "o2"},
      f"재분류: {list(h8.products)}")
check(h8.products["신라면"]["obs"]["o2"]["ended"] is True and "o3" in h8.skipped, "재분류 시 원본·제외 기록 보존")
big = {"products": {"x": {"keys": [], "obs": {f"u{i}": {"price": 1000 + i, "title": f"테스트 상품{i % 3000} 120g {i % 7 + 1}개",
                                                       "date": "2026-10-01T10:00:00+09:00"} for i in range(30000)}}}}
t0 = time.time()
History(big)
dt = time.time() - t0
check(dt < 20, f"3만 건 재분류 {dt:.1f}s")


# ---------- 실제 제목 정답셋 ----------
fx = json.loads((Path(__file__).parent / "fixtures" / "product_titles.json").read_text(encoding="utf-8"))["items"]
parsed = [(it, p(it["t"])) for it in fx]
skip_ok = sum(1 for it, r in parsed if (r is None) == bool(it.get("skip")))
prods = [(it, r) for it, r in parsed if not it.get("skip") and r is not None]
false_merge, split, same_pairs = [], 0, 0
for (a, ra), (b, rb) in itertools.combinations(prods, 2):
    joined = ra.key == rb.key or ra.alt_key == rb.alt_key
    if a["g"] == b["g"]:
        same_pairs += 1
        split += not joined
    elif joined:
        false_merge.append((a["t"], b["t"]))
cnt_items = [(it, r) for it, r in prods if "n" in it]
cnt_ok = sum(1 for it, r in cnt_items if r.count == it["n"] and ("c" not in it or r.content == it["c"]))
print(f"정답셋 {len(fx)}건: 제외 정확도 {skip_ok}/{len(fx)} ({skip_ok / len(fx):.1%}), "
      f"오병합 {len(false_merge)}쌍, 분리율 {split}/{same_pairs} ({split / max(same_pairs, 1):.1%}), "
      f"개수 정확도 {cnt_ok}/{len(cnt_items)} ({cnt_ok / max(len(cnt_items), 1):.1%})")
for a, b in false_merge:
    print("  오병합:", a, "|", b)
for it, r in cnt_items:
    if r.count != it["n"] or ("c" in it and r.content != it["c"]):
        print(f"  개수 틀림: {it['t']} → {r.count}/{r.content} (기대 {it['n']}/{it.get('c')})")
for it, r in parsed:
    if (r is None) != bool(it.get("skip")):
        print(f"  제외 판단 틀림: {it['t']} → {'None' if r is None else r.key}")
check(len(fx) >= 120, "정답셋 120건 이상")
check(not false_merge, "정답셋 오병합 0")
check(cnt_ok / max(len(cnt_items), 1) >= 0.95, "개수 정확도 95% 이상")
check(skip_ok / len(fx) >= 0.95, "제외 정확도 95% 이상")
check(len({r.key for it, r in prods if it["g"] == "shin"}) == 1, "신라면 정답셋 한 상품")

# ---------- 최종 검증(R1) 재작업 ----------
for t in ["[쿠팡] 오징어땅콩 98g 16개 (토스15,450원/무료)", "모나리자 미용티슈 (스카 15,990원)",
          "[11번가] 하늘보리 500ml 20개 (T멤 9,900원)", "햇반 210g 24개 모니모 결제", "특정 결제 수단 적용가 라면 10개"]:
    r = p(t)
    check(r is not None and r.cond, f"조건부 감지: {t}")
# 같은 개당 용량 표본이 충분하면 다른 용량(100ml당)보다 개당 비교를 우선
hb = History()
hb.observe([
    {"title": "하늘보리 무라벨 1.5L 12개", "price": 11500, "url": "hb1", "source": "s", "posted_at": "2026-09-01T10:00:00+09:00"},
    {"title": "하늘보리 무라벨 1.5L 12개", "price": 11600, "url": "hb2", "source": "s", "posted_at": "2026-09-20T10:00:00+09:00"},
    {"title": "하늘보리 무라벨 1.5L 12개", "price": 11700, "url": "hb3", "source": "s", "posted_at": "2026-10-10T10:00:00+09:00"},
    {"title": "하늘보리 무라벨 500ml 20개", "price": 12240, "url": "hb4", "source": "s", "posted_at": "2026-09-05T10:00:00+09:00"},
    {"title": "하늘보리 무라벨 500ml 20개", "price": 11440, "url": "hb5", "source": "s", "posted_at": "2026-10-01T10:00:00+09:00"},
])
hp = hb.product_for_group({"title": "하늘보리 무라벨 500ml 20개", "price": 10900, "currency": "KRW",
                           "posted_at": "2026-11-06T10:00:00+09:00", "sources": [{"url": "hb_now"}]})
check(hp["unit"] == "개" and hp["verdict"] == "lowest", f"하늘보리 500ml×20 은 개당 비교로 역대최저: {hp['unit']} {hp['verdict']}")

print("실패", fails, "건" if fails else "— 모두 통과")
sys.exit(1 if fails else 0)
