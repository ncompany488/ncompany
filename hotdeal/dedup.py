"""여러 커뮤니티에 올라온 같은 딜을 하나의 '그룹'으로 묶는다.

판정 기준:
  1) 실제 상품 링크(product_url)가 같으면 같은 딜
  2) 아니면 제목 유사도(띄어쓰기 무시, 글자 2개 묶음 비교)가 충분하고,
     가격이 비슷(또는 한쪽 미상)하며, 올라온 시간이 가까우면 같은 딜
  단, 아래는 무조건 다른 딜: 같은 사이트 글끼리 / 통화가 다름 / 판매처(대형몰)가 다름 /
  용량·크기 등 숫자 스펙이 다름(256GB vs 512GB) / 모델명이 다름 / 1+1 vs 2+1
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime
from functools import lru_cache
from urllib.parse import urlparse, parse_qsl, urlencode

# 맨 앞 [쇼핑몰] 태그, 그리고 가격·배송 정보가 든 괄호는 비교에서 뺀다
_LEAD_TAG = re.compile(r"^\s*[\[【][^\]】]*[\]】]")
_PRICE_PAREN = re.compile(r"[\[(（][^\])）]*(?:원|\$|달러|불|엔|jpy|무료|무배|배송|직배|fs)[^\])）]*[\])）]?")
# 가격 숫자 (256,512GB 처럼 단위가 붙은 건 가격이 아님)
_PRICE = re.compile(r"\d{1,3}(?:,\d{3})+\s*원?(?!\s*[a-z])|\d+(?:\.\d+)?\s*(?:만\s*)?원|\$\s?\d[\d,]*(?:\.\d+)?")
_NONWORD = re.compile(r"[^\w가-힣+.]+")
_STOP = {
    "무료", "무배", "배송", "무료배송", "할인", "특가", "핫딜", "카드", "쿠폰", "적용", "최저가",
    "역대가", "정가", "the", "and", "for", "with", "free", "shipping", "deal", "off",
    "종료", "품절", "재고", "구매", "가능", "와우", "회원", "멤버십", "추가", "체감", "체감가",
}
# 숫자 스펙: (숫자들)(단위) — 256,512gb 처럼 여러 값도 인식
_UNIT_ALIAS = {"개입": "개", "입": "개", "ea": "개", "킬로": "kg", "테라": "tb", "기가": "gb",
               '"': "인치", "inch": "인치", "형": "인치"}
# 영문 단위는 뒤에 영문·숫자가 없을 때만(27g610a 의 g 제외), 한글 단위는 뒤에 한글도 없을 때만(3인분의 '인' 등 오인식 방지)
_SPEC = re.compile(r"(?<![a-z\d.])(\d+(?:\.\d+)?(?:\s*[,/]\s*\d+(?:\.\d+)?)*)\s*"
                   r"(?:(gb|tb|kg|mg|ml|mah|hz|inch|cm|mm|g|l|w|ea|\")(?![a-z\d])"
                   r"|(기가|테라|킬로|인치|형|구|개월|개입|개|입|매|팩|봉|캔|병|롤|포|정|캡슐|박스|세트)(?![가-힣a-z\d]))")
_PLUS = re.compile(r"(?<![\d.])\d+(?:\+\d+)+(?![\d.])")  # 1+1, 2+1, 1+1+1
# 모델명: 영문과 숫자가 섞인 3글자 이상 (27g610a, ku65mh75afxkr, s26, ddr5 ...)
_MODEL = re.compile(r"(?<![a-z0-9])(?=[a-z0-9-]*\d)(?=[a-z0-9-]*[a-z])[a-z0-9]+(?:-[a-z0-9]+)*(?![a-z0-9])")
_NOT_MODEL = re.compile(r"\d+[a-z]{1,3}")  # 1ms, 5th, 1080p, 4k 같은 숫자+접미사는 모델명 아님

# 대형 판매처 이름 통일 (둘 다 아는 몰인데 서로 다르면 다른 딜). 앞쪽이 우선.
_SHOPS = {
    "amazon_jp": ("amazon.jp", "amazonjp", "amazon.co.jp", "아마존재팬", "일마존"),
    "gmarket": ("g마켓", "지마켓", "gmarket", "빅스마일"),
    "11st": ("11번가", "11st", "티멤"),
    "naver": ("네이버", "네멤", "스마트스토어", "naver"),
    "kakao": ("카카오", "톡딜", "톡스토어", "kakao"),
    "coupang": ("쿠팡", "coupang", "로켓"),
    "lotteon": ("롯데온", "lotteon"),
    "ssg": ("ssg", "쓱", "이마트"),
    "auction": ("옥션", "auction"),
    "ali": ("알리", "aliexpress"),
    "amazon": ("amazon", "아마존"),
    "ebay": ("ebay", "이베이"),
    "toss": ("토스",),
}

SIM_SAME_PRICE = 0.3   # 가격이 완전히 같으면(1,000 이상) 제목은 이 정도만 비슷해도 됨
SIM_THRESHOLD = 0.45   # 가격이 비슷(6% 이내)할 때
SIM_NOPRICE = 0.5      # 한쪽이라도 가격을 모를 때
PRICE_TOLERANCE = 0.06
TIME_WINDOW_H = 48     # 이 시간 이상 떨어지면 다른 딜


def _clean(title: str) -> str:
    t = _LEAD_TAG.sub(" ", title.lower())
    t = _PRICE_PAREN.sub(" ", t)
    return _PRICE.sub(" ", t)


def title_tokens(title: str) -> frozenset[str]:
    """비교용 단어 집합 (불용어 제외). 1+1, 1.1kg 같은 표기는 유지."""
    words = (w.strip(".") for w in _NONWORD.sub(" ", _clean(title)).split())
    return frozenset(w for w in words if w and w not in _STOP)


@lru_cache(maxsize=20000)
def _features(title: str):
    """(글자 2개 묶음, 숫자 스펙{단위: 값들}, N+N 표기, 모델명) — 제목별로 한 번만 계산."""
    clean = _clean(title)
    words = [w.strip(".") for w in _NONWORD.sub(" ", clean).split()]
    s = "".join(w for w in words if w and w not in _STOP)  # 띄어쓰기 무시
    bigrams = frozenset(s[i:i + 2] for i in range(len(s) - 1))
    specs: dict[str, frozenset] = {}
    spec_words = set()
    for m in _SPEC.finditer(clean):
        nums, u1, u2 = m.groups()
        unit = _UNIT_ALIAS.get(u1 or u2, u1 or u2)
        vals = frozenset(float(x) for x in re.split(r"\s*[,/]\s*", nums))
        specs[unit] = specs.get(unit, frozenset()) | vals
        spec_words.add(re.sub(r"\s+", "", m.group(0)))
    plus = frozenset(_PLUS.findall(clean))
    models = frozenset(m for m in _MODEL.findall(clean)
                       if len(m) >= 3 and m not in spec_words and not _NOT_MODEL.fullmatch(m))
    return bigrams, specs, plus, models


def _shop_key(shop: str | None) -> str | None:
    s = (shop or "").lower().replace(" ", "")
    if not s:
        return None
    for key, names in _SHOPS.items():
        if any(n in s for n in names):
            return key
    return None


def canonical_product_url(url: str | None) -> str | None:
    if not url:
        return None
    try:
        p = urlparse(url)
    except ValueError:
        return None
    keep = {"itemid", "productid", "prdno", "goodscode", "itemno", "vendoritemid", "id", "no"}
    q = [(k, v) for k, v in parse_qsl(p.query) if k.lower() in keep]
    path = p.path.rstrip("/")
    if not q and len(path) < 4:
        return None  # 메인 페이지 같은 링크는 상품을 특정하지 못함
    host = p.netloc.lower().removeprefix("www.").removeprefix("m.")
    return f"{host}{path}?{urlencode(sorted(q))}"


def _jaccard(a: frozenset, b: frozenset) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _ts(d: dict) -> float:
    s = d.get("posted_at") or d.get("first_seen")
    try:
        return datetime.fromisoformat(s).timestamp() if s else 0.0
    except ValueError:
        return 0.0


def _price_close(a: int | None, b: int | None) -> bool | None:
    """True/False, 또는 비교 불가면 None."""
    if a is None or b is None:
        return None
    hi = max(a, b)
    return hi == 0 or abs(a - b) / hi <= PRICE_TOLERANCE


def _conflict(fa, fb) -> bool:
    """숫자 스펙·N+N 표기·모델명이 서로 다르면 True."""
    _, sa, pa, ma = fa
    _, sb, pb, mb = fb
    if any(sa[u].isdisjoint(sb[u]) for u in sa.keys() & sb.keys()):
        return True
    if pa and pb and pa.isdisjoint(pb):
        return True
    return bool(ma and mb and ma.isdisjoint(mb))


def _key(d: dict) -> tuple:
    """비교에 쓰는 값들을 미리 계산 (딜마다 한 번)."""
    return (d["source"], d.get("currency") or "KRW", _ts(d),
            canonical_product_url(d.get("product_url")), _shop_key(d.get("shop")),
            d.get("price"), _features(d.get("title") or ""))


def _same(a: tuple, b: tuple) -> bool:
    src_a, cur_a, ta, url_a, shop_a, pa, fa = a
    src_b, cur_b, tb, url_b, shop_b, pb, fb = b
    if src_a == src_b:
        return False  # 같은 사이트 안의 글은 서로 다른 딜로 취급
    if cur_a != cur_b:
        return False
    if ta and tb and abs(ta - tb) > TIME_WINDOW_H * 3600:
        return False
    if url_a and url_a == url_b:
        return True
    if shop_a and shop_b and shop_a != shop_b:
        return False
    pc = _price_close(pa, pb)
    if pc is False or _conflict(fa, fb):
        return False
    sim = _jaccard(fa[0], fb[0])
    if pc and pa == pb and pa >= 1000:
        return sim >= SIM_SAME_PRICE
    return sim >= (SIM_THRESHOLD if pc else SIM_NOPRICE)


def same_deal(a: dict, b: dict) -> bool:
    return _same(_key(a), _key(b))


def group_deals(deals: list[dict], previous_groups: dict[str, str] | None = None) -> list[dict]:
    """딜 목록을 그룹 목록으로. previous_groups(딜id→그룹id)로 그룹 id 를 유지한다.

    모든 그룹을 다 비교하면 느리므로, 제목 글자 묶음을 충분히 공유하거나 상품 링크가 같은
    그룹만 후보로 골라 비교한다 (먼저 생긴 그룹 우선).
    """
    previous_groups = previous_groups or {}
    deals = sorted(deals, key=lambda d: (_ts(d), d["id"]))  # 실행마다 같은 순서
    min_sim = min(SIM_SAME_PRICE, SIM_THRESHOLD, SIM_NOPRICE)
    groups: list[list[tuple]] = []      # 그룹별 멤버 (key, deal)
    srcs: list[set] = []
    by_bigram: dict[str, set[int]] = {}
    by_url: dict[str, int] = {}
    for d in deals:
        k = _key(d)
        bigrams = k[6][0]
        shared: dict[int, int] = {}
        for bg in bigrams:
            for gi in by_bigram.get(bg, ()):
                shared[gi] = shared.get(gi, 0) + 1
        need = min_sim * len(bigrams)
        cands = {gi for gi, n in shared.items() if n >= need}
        if k[3] in by_url:
            cands.add(by_url[k[3]])
        hit = next((gi for gi in sorted(cands)
                    if k[0] not in srcs[gi] and any(_same(k, x) for x, _ in groups[gi])), None)
        if hit is None:
            hit = len(groups)
            groups.append([])
            srcs.append(set())
        groups[hit].append((k, d))
        srcs[hit].add(k[0])
        for bg in bigrams:
            by_bigram.setdefault(bg, set()).add(hit)
        if k[3]:
            by_url.setdefault(k[3], hit)
    used: set[str] = set()
    return [_summarize([d for _, d in g], previous_groups, used) for g in groups]


def _summarize(members: list[dict], previous_groups: dict[str, str], used: set[str]) -> dict:
    members = sorted(members, key=_ts)
    first = members[0]
    # 예전 그룹 id 재사용 (예전 그룹이 둘로 쪼개졌으면 먼저 차지한 쪽만 유지)
    gid = next((previous_groups[m["id"]] for m in members
                if previous_groups.get(m["id"]) and previous_groups[m["id"]] not in used), None)
    if gid is None:
        gid = hashlib.sha1(first["id"].encode()).hexdigest()[:12]
        while gid in used:
            gid = hashlib.sha1(gid.encode()).hexdigest()[:12]
    used.add(gid)
    prices = [m["price"] for m in members if m.get("price") is not None]
    likes = sum(m.get("likes") or 0 for m in members)
    comments = sum(m.get("comments") or 0 for m in members)
    rep = max(members, key=lambda m: (m.get("likes") or 0, -_ts(m)))
    return {
        "gid": gid,
        "title": rep["title"],
        "price": min(prices) if prices else None,
        "currency": first.get("currency") or "KRW",
        "shop": next((m["shop"] for m in members if m.get("shop")), None),
        "thumbnail": next((m["thumbnail"] for m in members if m.get("thumbnail")), None),
        "posted_at": first.get("posted_at") or first.get("first_seen"),
        "first_seen": min(m.get("first_seen") or "" for m in members) or None,
        "likes": likes,
        "comments": comments,
        "ended": all(m.get("ended") for m in members),
        "sources": [
            {k: m.get(k) for k in ("id", "source", "title", "url", "price", "likes",
                                   "comments", "views", "posted_at", "ended", "category")}
            for m in members
        ],
    }
