"""DealNews 공식 RSS (해외 딜). Slickdeals 가 막혀 있어 대체로 추가한 소스.

- 피드: https://www.dealnews.com/?rss=1 (페이지 <link rel="alternate"> 로 공개된 RSS)
- robots.txt 허용, 인증 불필요. 제목/링크/가격/상점/썸네일 URL 만 사용(본문 미수집).
"""
from __future__ import annotations

import re
from datetime import timezone
from calendar import timegm
from datetime import datetime

import feedparser

from .. import http
from ..models import Deal, SourceInfo
from ..parse import extract_price_usd

SOURCE = SourceInfo(key="dealnews", name="DealNews", homepage="https://www.dealnews.com/",
                    region="global", kind="community")
FEED = "https://www.dealnews.com/?rss=1"
# "free shipping w/ $49" 같은 배송 조건 금액은 가격이 아니므로 제외
_COND_RE = re.compile(r"(?:w/|with|on|over|orders? of|spend|min\.?)\s*\$\s?\d[\d,.]*", re.I)
# "Up to $250 off"(할인액), "$100 in Gift Cards"(액면가)도 가격이 아님
_NOT_PRICE_RE = re.compile(r"\$\s?\d[\d,.]*\s*(?:off|in)\b", re.I)
# "... for $80", "for From $950" 처럼 for 뒤 금액이 실제 판매가
_FOR_RE = re.compile(r"\bfor\s+(?:from\s+)?(\$\s?\d[\d,]*(?:\.\d{1,2})?)", re.I)


def _price(title: str) -> int | None:
    m = _FOR_RE.search(title)
    if m:
        return extract_price_usd(m.group(1))
    return extract_price_usd(_NOT_PRICE_RE.sub("", _COND_RE.sub("", title)))


def fetch(limit: int = 40) -> list[Deal]:
    feed = feedparser.parse(http.get(FEED).content)
    deals: list[Deal] = []
    for e in feed.entries:
        try:
            title = (e.get("title") or "").strip()
            link = (e.get("link") or "").strip()
            link = link.split("?iref=")[0]  # RSS 추적 파라미터 제거 → 정규 URL
            if not title or not link.startswith("http"):
                continue
            if title.startswith("Upcoming:"):  # 아직 시작 전인 딜 제외
                continue
            posted = None
            if e.get("published_parsed"):  # UTC struct_time → timegm (mktime 은 로컬시간으로 해석해 틀어짐)
                posted = datetime.fromtimestamp(timegm(e.published_parsed), timezone.utc).isoformat()
            thumb = None
            if e.get("media_content"):
                thumb = e.media_content[0].get("url")
            deals.append(Deal(
                source=SOURCE.key, title=title, url=link, posted_at=posted,
                price=_price(title), currency="USD",
                shop=e.get("dealnews_retailer"), category=e.get("dealnews_category"),
                thumbnail=thumb, product_url=None,
            ))
        except Exception:  # 항목 하나가 깨져도 전체는 계속
            continue
        if len(deals) >= limit:
            break
    return deals
