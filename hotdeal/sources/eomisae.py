"""어미새(eomisae.co.kr) 패션정보(/os) 게시판 수집기 — 남성 패션 세일 정보 (HTML 카드 목록).

- robots.txt: `Disallow: /*?` 이지만 `Allow: /*?*page=` 가 더 길어서 ?page=N 만 허용.
- 날짜만 제공(yy.mm.dd), 썸네일·조회·댓글·추천 제공. 가격은 제목의 ₩/원 표기.
- /rss 는 전 게시판(요청·후기 포함) 혼합이라 잡음이 커서 쓰지 않는다.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from .. import http
from ..models import Deal, SourceInfo
from ..parse import extract_price_krw, extract_shop, parse_kr_datetime, to_int

BASE = "https://eomisae.co.kr"
LIST_URL = BASE + "/os"
SOURCE = SourceInfo(key="eomisae", name="어미새", region="kr", kind="community", homepage=LIST_URL)
ENABLED = True
MAX_BACKFILL_PAGES = 1  # ?page=2 가 403 으로 막힘(2026-11 실측) → 백필 불가


def _parse_card(div) -> Deal | None:
    a = div.select_one("h3 a")
    if a is None:
        return None
    m = re.match(r"^/os/(\d+)", a.get("href", ""))
    title = " ".join(a.get_text(" ", strip=True).split())
    if not m or not title or title.startswith("list_ad"):  # 광고 카드(list_adsense·list_ad_link) 제외
        return None
    spans = div.select(".card_content > p span")
    cat = spans[0].get_text(strip=True).rstrip(",") if spans else None
    date = spans[1].get_text(strip=True) if len(spans) > 1 else None
    nums = [to_int(s.get_text()) for s in div.select(".infos span.fr")]  # 조회, 댓글, 추천 순
    img = div.select_one("img.tmb")
    thumb = img.get("src") if img else None
    if thumb and thumb.startswith("//"):
        thumb = "https:" + thumb
    return Deal(
        source=SOURCE.key, title=title, url=f"{LIST_URL}/{m.group(1)}",
        posted_at=parse_kr_datetime(date) if date else None,
        price=extract_price_krw(title), shop=extract_shop(title), category=cat or None,
        thumbnail=thumb,
        views=nums[0] if len(nums) > 0 else None,
        comments=nums[1] if len(nums) > 1 else None,
        likes=nums[2] if len(nums) > 2 else None,
        ended=("품절" in title or "종료" in title),
    )


def fetch_page(page: int) -> list[Deal]:
    params = {"page": page} if page > 1 else None
    soup = BeautifulSoup(http.get(LIST_URL, params=params).text, "lxml")
    deals, seen = [], set()
    for div in soup.select("div.rt_area"):
        try:
            d = _parse_card(div)
        except Exception:
            continue
        if d and d.url not in seen:
            seen.add(d.url)
            deals.append(d)
    return deals


def fetch(limit: int = 40) -> list[Deal]:
    deals, seen = [], set()
    for page in (1,):  # ?page=2 는 403 (봇 차단) → 우회하지 않고 1쪽만
        for d in fetch_page(page):
            if d.url not in seen:
                seen.add(d.url)
                deals.append(d)
        if len(deals) >= limit:
            break
    return deals[:limit]
