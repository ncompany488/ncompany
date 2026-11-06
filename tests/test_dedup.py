"""dedup 판정 점검: python tests/test_dedup.py"""
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from hotdeal import dedup  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

T = "2026-11-06T12:00:00+09:00"


def d(source, title, price=None, shop=None, posted_at=T, i=[0]):
    i[0] += 1
    return {"id": f"{source}{i[0]}", "source": source, "title": title, "price": price,
            "shop": shop, "posted_at": posted_at, "currency": "KRW"}


SAME = [
    (d("arca", "국내산 닭한마리 닭볶음탕 1.1kg", 7500, "네이버"),
     d("ppomppu", "[네이버]국내산 닭 한마리 닭볶음탕 1.1kg (7,500원/네멤무료)", 7500, "네이버")),
    (d("arca", "빅스 갤럭시 폴드8 자급제 256,512GB 삼성카드 체감 168", 1915300, "지마켓"),
     d("ppomppu", "[G마켓]삼성전자 갤럭시폴드8 자급제 256GB외 종합(1,915,300원/무료)", 1915300, "G마켓")),
    (d("arca", "겨울준비 핫팩 20개", 7700, "네이버"), d("ppomppu", "[네이버]핫팩 20개입 (7,700원 / 무배)", 7700, "네이버")),
    (d("clien", "삼성 Mini LED TV 4k 163cm(65인치)"),
     d("arca", "삼성 Mini LED TV 4k 163cm(65인치) KU65MH75AFXKR 스탠드 (1등급)", 949000, "지마켓")),
]
DIFF = [
    (d("arca", "삼성 갤럭시 S26 자급제 256GB", 1150000), d("ppomppu", "[G마켓]삼성 갤럭시 S26 자급제 512GB", 1150000)),
    (d("arca", "삼성 갤럭시 S26 자급제 256GB", 1150000), d("ppomppu", "삼성 갤럭시 S25 자급제 256GB", 1150000)),
    (d("arca", "비비고 왕교자 1+1", 15000), d("ppomppu", "비비고 왕교자 2+1", 15000)),
    (d("arca", "LG 울트라기어 27G610A 모니터", 300000), d("ruliweb", "LG 울트라기어 27G810A 모니터", 300000)),
    (d("arca", "신라면 40개", 20000, "쿠팡"), d("ppomppu", "[G마켓]신라면 40개", 20000, "G마켓")),
    (d("arca", "신라면 40개", 20000), d("ppomppu", "신라면 40개", 26000)),
    (d("arca", "삼다수 2L 12병", 9000), d("ppomppu", "삼다수 500ml 20병", 9000)),
    (d("arca", "신라면 40개", 20000), d("ppomppu", "신라면 40개", 20000, posted_at="2026-11-01T12:00:00+09:00")),
    (d("arca", "넷플릭스 12개월 이용권", None), d("ppomppu", "넷플릭스 1개월 이용권", None)),
]

fail = 0
for a, b in SAME:
    if not dedup.same_deal(a, b):
        fail += 1
        print("놓침:", a["title"], "|", b["title"])
for a, b in DIFF:
    if dedup.same_deal(a, b):
        fail += 1
        print("잘못 묶음:", a["title"], "|", b["title"])

# 3000개 성능 + 그룹 id 안정성
random.seed(1)
words = "삼성 엘지 애플 라면 생수 모니터 키보드 마우스 이어폰 커피 과자 우유 세제 휴지 노트북 충전기".split()
srcs = ["arca", "ppomppu", "ruliweb", "clien", "fmkorea", "quasarzone"]
many = [d(random.choice(srcs), " ".join(random.sample(words, 4)) + f" {random.randint(1, 50)}개",
          random.randint(1, 300) * 1000, posted_at=f"2026-11-0{random.randint(4, 6)}T{random.randint(10, 23)}:00:00+09:00")
        for _ in range(3000)]
t0 = time.time()
g1 = dedup.group_deals(many)
sec = time.time() - t0
prev = {s["id"]: g["gid"] for g in g1 for s in g["sources"]}
g2 = dedup.group_deals(list(reversed(many)), prev)
again = {s["id"]: g["gid"] for g in g2 for s in g["sources"]}
if prev != again or len({g["gid"] for g in g2}) != len(g2):
    fail += 1
    print("그룹 id 가 바뀜")
print(f"3000개 그룹화 {sec:.2f}초, 그룹 {len(g1)}개")
if sec > 20:
    fail += 1
    print("너무 느림")

print("실패", fail, "건" if fail else "— 모두 통과")
sys.exit(1 if fail else 0)
