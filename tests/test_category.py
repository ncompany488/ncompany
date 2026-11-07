"""카테고리 분류(category.py) 점검: python tests/test_category.py
fixtures/category_titles.json — 실제 제목에 사람이 붙인 정답 (set: tuned = 규칙 만들 때 본 것, holdout* = 나중에 따로 뽑은 것)."""
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from hotdeal.category import CATEGORIES, categorize, categorize_many  # noqa: E402

fails = 0


def check(cond, msg):
    global fails
    if not cond:
        fails += 1
        print("실패:", msg)


fx = json.loads((ROOT / "tests" / "fixtures" / "category_titles.json").read_text(encoding="utf-8"))
check(len(fx) >= 150, f"정답 제목 150개 이상: {len(fx)}")
check(all(o["expected"] in CATEGORIES for o in fx), "정답은 계약의 카테고리 목록 안")

wrong = []
for o in fx:
    got = categorize(o["title"], o.get("source_category"), o.get("shop"), o.get("source"))
    check(got in CATEGORIES, f"결과는 목록 안: {got}")
    if got != o["expected"]:
        wrong.append((o["expected"], got, o["title"][:60]))
acc = 1 - len(wrong) / len(fx)
by_set = Counter(o.get("set") for o in fx)
print(f"정확도 {acc:.1%} ({len(fx) - len(wrong)}/{len(fx)}) {dict(by_set)}")
for w in wrong:
    print("  틀림:", w)
check(acc >= 0.85, f"정확도 85% 이상: {acc:.1%}")
for st in by_set:
    xs = [o for o in fx if o.get("set") == st]
    a = sum(categorize(o["title"], o.get("source_category"), o.get("shop"), o.get("source")) == o["expected"]
            for o in xs) / len(xs)
    check(a >= 0.85, f"{st} 묶음 정확도 85% 이상: {a:.1%}")

# 게시판 분류가 있는 글(현재 목록의 딜)에서 '기타' 비율 < 15%
store_like = [o for o in fx if o.get("source_category") is not None]
etc = sum(categorize(o["title"], o["source_category"], o.get("shop"), o.get("source")) == "기타" for o in store_like)
check(etc / len(store_like) < 0.15, f"게시판 분류 있는 글의 기타 비율 15% 미만: {etc}/{len(store_like)}")

# ---------- 개별 규칙 (회귀) ----------
cases = [
    ("[롯데온]26년 햇 고춧가루 1kg (16,940원/무료)", "식품/건강", None, None, "식품"),
    ("[네이버]드리미안 경추베개 (32,900원 / 3,500원)", "의류/잡화", None, None, "생활"),     # 뽐뿌 분류보다 제목
    ("[G마켓]키친타올 3겹 100매 9팩 5270원. 무배", "의류/잡화", None, None, "생활"),
    ("돌체구스토 지니오S 커피머신+스타벅스 캡슐커피 2박스", "기타", None, None, "가전"),     # 머신이 결정
    ("[Ebay]Refurb: HP Elitebook 830 Laptop; i7-1185G7, 32GB RAM, 256GB SSD", None, "Ebay", None, "디지털"),
    ("[에픽게임즈/스팀] Sorry We're Closed, Galaxy Kart 일시 무료", "이벤트정보", "에픽게임즈/스팀", None, "게임"),
    ("[WearOS] SamWatch Analog B Sports 2024 일시 무료", "이벤트정보", "WearOS", None, "디지털"),
    ("도루코 페이스6 면도날세트(12입)+증정(메가커피)", "생활용품", None, None, "생활"),        # 사은품 무시
    ("[롯데온] 딥큐 3in1 캡슐세제 100개 (15,900원/무료)", "기타", None, None, "생활"),         # 'in1 캡슐' ≠ 영양제
    ("[G마켓]헤지스 소가죽 카드지갑 (23,250원/무배)", None, None, None, "패션"),               # '가죽' ≠ 죽
    ("[G마켓]슬레진저 초경량 헬스 워킹화 (13,670원/무료)", None, None, None, "패션"),          # '슬레진저' ≠ 진저
    ("[11번가] 구글플레이 기프트코드 10만원권 8% 할인", "상품권", "11번가", None, "상품권·포인트"),
    ("1206-1209 인천-요나고", "기타", None, None, "여행·티켓"),
    ("[지마켓]PALIT 지포스 RTX 5070 Infinity 3 D7 12GB", None, None, None, "PC부품"),
    ("유니클로 커버롤 ₩34,500", "국내", None, "eomisae", "패션"),
    ("Tutellpet 7-Liter Automatic Cat Feeder with Camera for $47.99", "Pets", "Amazon", None, "유아·반려"),
    ("Samsonite One-Day Black Friday Deals at Macy's", "Luggage & Travel Gear", "Macy's", None, "생활"),
    ("아무 정보 없는 제목", None, None, None, "기타"),
]
for title, cat, shop, src, exp in cases:
    got = categorize(title, cat, shop, src)
    check(got == exp, f"{title[:40]} → {exp} (결과 {got})")

# 여러 글 점수 합치기: 대표 제목이 애매해도 게시판 분류가 모이면 그쪽
check(categorize_many([("어떤 상품", None, None, None), ("어떤 상품", "식품/건강", None, "ppomppu"),
                       ("어떤 상품", "음식", None, "ruliweb")]) == "식품", "categorize_many 합산")
check(categorize_many([]) == "기타", "빈 목록 → 기타")

if fails:
    print(f"❌ 실패 {fails}건")
    sys.exit(1)
print("✅ category 테스트 통과")
