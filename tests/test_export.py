"""상품 샤드·검색 인덱스(export.py) 점검: python tests/test_export.py
계약: docs/contract-product-pages.md"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from hotdeal import export  # noqa: E402
from hotdeal.category import CATEGORIES  # noqa: E402
from hotdeal.history import History  # noqa: E402

fails = 0


def check(cond, msg):
    global fails
    if not cond:
        fails += 1
        print("실패:", msg)


# ---------- fnv1a32 · 샤드 번호 (프런트 JS 와 같은 값이어야 함) ----------
check(export.fnv1a32(b"") == 0x811C9DC5, "fnv1a32('')")
check(export.fnv1a32(b"a") == 0xE40C292C, "fnv1a32('a')")
check(export.fnv1a32(b"foobar") == 0xBF9CF968, "fnv1a32('foobar')")
# 한글은 UTF-8 바이트로 (Node: Math.imul 구현으로 교차 확인한 값)
check(export.fnv1a32("신라면".encode("utf-8")) == 0x2DECFCAC, "fnv1a32('신라면')")
check(export.shard_of("신라면") == "44" and export.shard_of("") == "05" and export.shard_of("foobar") == "40", "shard_of 값")
check(export.shard_of("a") == f"{0xE40C292C % 64:02d}", "shard_of('a')")
check(all(len(export.shard_of(x)) == 2 for x in ("", "x", "usd:abc", "g:신라면")), "두 자리")


def deal(t, price, url, date, src="ppomppu"):
    return {"title": t, "price": price, "url": url, "source": src, "posted_at": date}


h = History()
h.observe([
    # 개당 (n): 신라면 120g × N
    deal("[쿠팡]농심 신라면 120g 5개 (4,000원/무료)", 4000, "r1", "2026-08-01T10:00:00+09:00"),
    deal("[쿠팡]농심 신라면 120g 20개 (14,000원/무료)", 14000, "r2", "2026-09-01T10:00:00+09:00"),
    deal("[쿠팡]농심 신라면 120g 10개 (카드 6,000원/무료)", 6000, "r3", "2026-09-20T10:00:00+09:00"),  # 조건부
    deal("[쿠팡]농심 신라면 120g 10개 (7,900원/무료)", 7900, "r4", "2026-10-15T10:00:00+09:00"),
    # 100ml당 (w): 용량이 다른 콜라
    deal("[G마켓]코카콜라 제로 350ml 24개 (16,000원/무료)", 16000, "c1", "2026-08-05T10:00:00+09:00"),
    deal("[G마켓]코카콜라 제로 500ml 20개 (19,000원/무료)", 19000, "c2", "2026-09-05T10:00:00+09:00"),
    deal("[G마켓]코카콜라 제로 1.5L 12개 (36,000원/무료)", 36000, "c3", "2026-10-05T10:00:00+09:00"),
    # 총액 (total): 전자제품
    deal("[G마켓]삼성 갤럭시 S26 자급제 256GB (1,150,000원/무료)", 1150000, "g1", "2026-08-10T10:00:00+09:00"),
    deal("[G마켓]삼성 갤럭시 S26 자급제 256GB (1,090,000원/무료)", 1090000, "g2", "2026-09-10T10:00:00+09:00"),
    deal("[G마켓]삼성 갤럭시 S26 자급제 256GB (1,120,000원/무료)", 1120000, "g3", "2026-10-10T10:00:00+09:00"),
])
check(len(h.products) == 3, f"상품 3개: {list(h.products)}")
pid_of = {u: pid for pid, p in h.products.items() for u in p["obs"]}

with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    (td / "products").mkdir()
    (td / "products" / "99.json").write_text("{}", encoding="utf-8")       # 옛 샤드 → 지워져야 함
    (td / "products" / "keep.txt").write_text("x", encoding="utf-8")       # 샤드 이름이 아니면 그대로
    groups = [{"title": "x", "product": {"pid": "없는상품"}}, {"title": "y", "product": None}]
    rep = export.export_site(h, groups, td)
    check(groups[0]["product"]["pid"] is None, "내보내지 않은 pid → null")
    check(not (td / "products" / "99.json").exists(), "안 만든 샤드 파일 삭제")
    check((td / "products" / "keep.txt").exists(), "샤드가 아닌 파일은 유지")
    check(rep["shards"]["products"] == 3 and rep["search"]["entries"] == 3, f"보고: {rep}")

    shards = {}
    for f in (td / "products").glob("*.json"):
        data = json.loads(f.read_text(encoding="utf-8"))
        for pid in data:
            check(export.shard_of(pid) == f.stem, f"{pid} 는 {export.shard_of(pid)}.json 에 있어야 함 ({f.name})")
        shards.update(data)
    check(set(shards) == set(h.products), "모든 상품이 샤드에")
    for pid, prod in shards.items():
        check(set(prod) >= {"name", "cat", "basis", "unit_label", "obs"}, f"Product 필드: {set(prod)}")
        check(prod["cat"] in CATEGORIES, f"cat: {prod['cat']}")
        check(prod["basis"] in ("개", "100g", "100ml", None), f"basis: {prod['basis']}")
        ds = [o["d"] for o in prod["obs"]]
        check(ds == sorted(ds), f"{pid} obs 날짜 오름차순")
        for o in prod["obs"]:
            check(set(o) == {"d", "p", "u", "n", "g", "t", "url", "s", "c", "e"}, f"obs 필드: {set(o)}")
            check(o["c"] in (0, 1) and o["e"] in (0, 1), "c/e 는 0|1")
            check(isinstance(o["p"], int), "p 정수")

    search = json.loads((td / "search.json").read_text(encoding="utf-8"))
    check([e["id"] for e in search] == [pid_of["r4"], pid_of["g3"], pid_of["c3"]], f"최근 기록 순: {[e['id'] for e in search]}")
    for e in search:
        # P-008: 빈 값·기본값은 키째 생략 (app.js 는 없는 키 = 없음). 키 이름은 계약 그대로
        check(set(e) <= {"id", "n", "cat", "b", "ul", "lu", "lp", "ld", "k"} and {"id", "n", "k"} <= set(e), f"검색 필드: {set(e)}")
        check(all(v is not None and v != "" for v in e.values()), f"null 값 없음: {e}")
        check(e.get("ul") != "개" and ("ul" not in e or e.get("b")), f"ul 은 기본값 '개'·총액 기준이면 생략: {e}")
        check("lu" not in e or e.get("b"), f"총액 기준이면 lu 생략 (lp 가 총액 최저): {e}")

ramen, cola, phone = shards[pid_of["r1"]], shards[pid_of["c1"]], shards[pid_of["g1"]]
check(ramen["basis"] == "개" and ramen["cat"] == "식품", f"신라면 개당·식품: {ramen['basis']} {ramen['cat']}")
check([o["u"] for o in ramen["obs"]] == [800, 700, 600, 790], f"신라면 개당 단가: {[o['u'] for o in ramen['obs']]}")
check([o["c"] for o in ramen["obs"]] == [0, 0, 1, 0], "조건부 표시")
check(cola["basis"] == "100ml", f"콜라 100ml당: {cola['basis']}")
check(phone["basis"] is None and [o["u"] for o in phone["obs"]] == [1150000, 1090000, 1120000], "총액 기준이면 u=총액")
s_by = {e["id"]: e for e in search}
r = s_by[pid_of["r1"]]
check((r["lu"], r["lp"], r["ld"], r["k"]) == (700, 14000, "2026-09-01", 4), f"신라면 최저(조건부 제외): {r}")
check(s_by[pid_of["g1"]]["lp"] == 1090000 and "b" not in s_by[pid_of["g1"]], "갤럭시 최저 총액 (b·lu 생략)")

# ---------- 카드(product_for_group)와 숫자 일치 (상품 3개) ----------
# 가장 최근 글을 현재 딜로 하는 그룹 → basis·unit_label·그 글의 u, 그리고 역대 최저(low_unit) = 검색 lu
for last_url in ("r4", "c3", "g3"):
    pid = pid_of[last_url]
    prod, e = shards[pid], s_by[pid]
    o = h.products[pid]["obs"][last_url]
    g = {"title": o["title"], "price": o["price"], "posted_at": o["date"], "url": last_url,
         "sources": [{"url": last_url, "source": o["source"]}]}
    card = h.product_for_group(g)
    check(card["pid"] == pid, f"group.product.pid = {pid}: {card['pid']}")
    check(card["unit"] == prod["basis"], f"{pid} basis {prod['basis']} == 카드 unit {card['unit']}")
    check(card["unit_label"] == prod["unit_label"], f"{pid} unit_label")
    if card["unit"]:
        check(card["unit_price"] == prod["obs"][-1]["u"], f"{pid} 현재 단가 {card['unit_price']} == u {prod['obs'][-1]['u']}")
    lo = card["history"]["low_unit"]
    want = lo["unit_price"] if card["unit"] else lo["price"]
    check(want == (e["lu"] if card["unit"] else e["lp"]) and lo["price"] == e["lp"] and lo["date"][:10] == e["ld"],
          f"{pid} 카드 역대 최저 {lo['unit_price']}/{lo['price']} == 검색 {e.get('lu')}/{e['lp']}")

# ---------- annotate_categories / pid ----------
gs = [{"title": "[네이버]핫팩 20개입 (7,700원 / 무배)", "shop": "네이버",
       "sources": [{"title": "[네이버]핫팩 20개입", "category": "기타", "source": "ppomppu"}]},
      {"title": "아무거나", "sources": []}]
export.annotate_categories(gs)
check(gs[0]["category"] == "생활" and gs[1]["category"] == "기타", f"annotate_categories: {[g['category'] for g in gs]}")
h.annotate(gs)
check(gs[0]["product"] is None or "pid" in gs[0]["product"], "annotate 결과에 pid 키")
nr = h.product_for_group({"title": "[쿠팡]농심 신라면 120g 10개 (7,000원/무료)", "price": 7000,
                          "posted_at": "2026-11-01T10:00:00+09:00", "sources": [{"url": "new", "source": "ppomppu"}]})
check(nr["pid"] == pid_of["r1"], "기록에 있는 상품이면 pid")
nn = h.product_for_group({"title": "[쿠팡]처음보는 과자 100g 3개 (3,000원/무료)", "price": 3000,
                          "sources": [{"url": "n2", "source": "ppomppu"}]})
check(nn is not None and nn["pid"] is None, f"기록에 없으면 pid null: {nn and nn['pid']}")

# ---------- P-008: 기록 1건뿐인 오래된 상품은 검색에서 빠짐 (샤드에는 남음) ----------
from datetime import timedelta  # noqa: E402
from hotdeal.parse import now_kst  # noqa: E402
hs = History()
recent = (now_kst() - timedelta(days=5)).isoformat()
old = (now_kst() - timedelta(days=export.SEARCH_SINGLE_DAYS + 30)).isoformat()
hs.observe([deal("[쿠팡]새로 본 과자 100g 3개 (3,000원/무료)", 3000, "s1", recent),
            deal("[쿠팡]오래된 단일 과자 100g 3개 (3,000원/무료)", 3000, "s2", old),
            deal("[쿠팡]오래된 두번 과자 100g 3개 (3,000원/무료)", 3000, "s3", old),
            deal("[쿠팡]오래된 두번 과자 100g 3개 (2,900원/무료)", 2900, "s4", old)])
with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    rep = export.export_site(hs, [], td)
    ids = [e["n"] for e in json.loads((td / "search.json").read_text(encoding="utf-8"))]
    check(rep["shards"]["products"] == 3 and rep["search"]["entries"] == 2 and rep["search"]["dropped_old"] == 1,
          f"오래된 단일 기록 상품만 검색 제외: {rep} {ids}")
    check(not any("단일" in n for n in ids), f"검색 목록: {ids}")

if fails:
    print(f"❌ 실패 {fails}건")
    sys.exit(1)
print("✅ export 테스트 통과")
