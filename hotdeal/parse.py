"""제목에서 가격·쇼핑몰 추출, 날짜 정규화 등 공용 파서."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Optional

KST = timezone(timedelta(hours=9))

# "[쿠팡] 상품명 (12,900원/무료)" 같은 국내 핫딜 제목 관례
_SHOP_RE = re.compile(r"^\s*[\[【(]([^\]】)]{1,20})[\]】)]")
# 원화 금액 후보: "12,900원", "24만", "1.5만원", "8만8천원", "8만 8,000원"
# 띄어 쓴 '원' 뒤에 한글이 붙으면 단어의 일부("33 원정대", "PS5 원피스")라 금액이 아님
_KRW_RE = re.compile(
    r"(?<![\d.,])(?:"
    r"(?P<man>\d{1,4}(?:\.\d{1,2})?)\s*만"
    r"(?:\s*(?P<cheon>\d)\s*천|\s*(?P<low>\d,\d{3}|\d{1,4})(?=\s*원))?"
    r"|(?P<num>\d{1,3}(?:,\d{3})+|\d+)(?=원|\s+원(?![가-힣]))"
    r")(?P<won>원|\s+원(?![가-힣]))?"
)
# 금액 바로 뒤에 오면 판매가가 아님: 상품권 액면가(5만원권), 무료배송 기준(3만원 이상), 할인·적립액
_NOT_PRICE_AFTER = re.compile(
    r"\s*(?:권|이상|할인|쿠폰|적립|캐시백|페이백|상당|결제\s*시|구매\s*시|기프트|상품권|금액권|off)", re.I)
# 금액 바로 앞에 오면 판매가가 아님: 배송비, 개당 단가
_NOT_PRICE_BEFORE = re.compile(r"(?:배송비|택배비|배송료|당)\s*$")
# "1200만 화소", "10만 명" 처럼 만 단위지만 돈이 아닌 표기
_MAN_NOT_MONEY = re.compile(r"\s*(?:개|명|건|회|화소|관객|리뷰|장|포인트|마일|점|뷰)")
# "$12.99", "$1,300", "23.51$", "33.60달러", "35불"
_USD_RE = re.compile(
    r"\$\s?(\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)"
    r"|(?<![\d.,])(\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)\s*(?:\$|달러|불(?!가))"
)


def extract_shop(title: str) -> Optional[str]:
    m = _SHOP_RE.match(title or "")
    return m.group(1).strip() if m else None


def extract_price_krw(text: str) -> Optional[int]:
    """제목에서 원화 가격 추출. 여러 개면 가장 작은 값(보통 최종가).

    배송비·상품권 액면가·무료배송 기준·할인액·잘린 숫자는 가격으로 보지 않는다.
    """
    text = text or ""
    vals = []
    prev_end = None  # 직전 금액 후보가 끝난 위치
    for m in _KRW_RE.finditer(text):
        start, end = m.start(), m.end()
        after, before = text[end:], text[:start]
        # "(34,500원/3,000원)" 처럼 금액 바로 뒤 "/금액" 은 배송비 자리
        is_shipping = prev_end is not None and re.fullmatch(r"\s*/\s*", text[prev_end:start])
        prev_end = end
        if is_shipping or _NOT_PRICE_AFTER.match(after) or _NOT_PRICE_BEFORE.search(before):
            continue
        if m.group("man"):
            if not m.group("won") and not m.group("cheon"):
                nxt = after[:1]
                # "8만 8..." 처럼 뒤 숫자가 잘린 경우, "만두"·"1200만 화소" 같은 비금액은 버림
                if (nxt.isdigit() or ("가" <= nxt <= "힣")
                        or (after[:1].isspace() and _MAN_NOT_MONEY.match(after))
                        or re.match(r"\s+\d", after)):
                    continue
            v = round(float(m.group("man")) * 10000)
            if m.group("cheon"):
                v += int(m.group("cheon")) * 1000
            elif m.group("low"):
                v += int(m.group("low").replace(",", ""))
        else:
            v = int(m.group("num").replace(",", ""))
        if 0 < v < 100_000_000:
            vals.append(v)
    return min(vals) if vals else None


def extract_price_usd(text: str) -> Optional[int]:
    """달러 가격(첫 번째 표기)을 '센트' 정수로 반환."""
    m = _USD_RE.search(text or "")
    if not m:
        return None
    return round(float((m.group(1) or m.group(2)).replace(",", "")) * 100)


def to_int(s) -> Optional[int]:
    if s is None:
        return None
    digits = re.sub(r"[^\d]", "", str(s))
    return int(digits) if digits else None


def now_kst() -> datetime:
    return datetime.now(KST)


def parse_kr_datetime(s: str) -> Optional[str]:
    """국내 게시판의 다양한 시간 표기를 ISO8601(KST)로.

    지원: '2026-11-06 14:03:22', '2026.11.06 14:03', '26/11/06', '14:03', '14:03:22',
          '11-06', '11.06', '3분 전', '2시간 전', '어제'
    """
    if not s:
        return None
    s = s.strip()
    now = now_kst()
    m = re.match(r"(\d+)\s*(초|분|시간|일)\s*전", s)
    if m:
        n, unit = int(m.group(1)), m.group(2)
        delta = {"초": timedelta(seconds=n), "분": timedelta(minutes=n),
                 "시간": timedelta(hours=n), "일": timedelta(days=n)}[unit]
        return (now - delta).replace(microsecond=0).isoformat()
    if s.startswith("어제"):
        return (now - timedelta(days=1)).replace(microsecond=0).isoformat()
    m = re.match(r"(\d{2,4})[-./](\d{1,2})[-./](\d{1,2})(?:\s+(\d{1,2}):(\d{2})(?::(\d{2}))?)?", s)
    if m:
        y = int(m.group(1))
        y = y + 2000 if y < 100 else y
        dt = datetime(y, int(m.group(2)), int(m.group(3)),
                      int(m.group(4) or 0), int(m.group(5) or 0), int(m.group(6) or 0), tzinfo=KST)
        return dt.isoformat()
    m = re.match(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$", s)
    if m:
        dt = now.replace(hour=int(m.group(1)), minute=int(m.group(2)),
                         second=int(m.group(3) or 0), microsecond=0)
        if dt > now + timedelta(minutes=5):
            dt -= timedelta(days=1)
        return dt.isoformat()
    m = re.match(r"^(\d{1,2})[-./](\d{1,2})$", s)
    if m:
        dt = now.replace(month=int(m.group(1)), day=int(m.group(2)),
                         hour=0, minute=0, second=0, microsecond=0)
        if dt > now:
            dt = dt.replace(year=dt.year - 1)
        return dt.isoformat()
    return None
