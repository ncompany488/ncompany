"""아카라이브 핫딜 채널 (arca.live/b/hotdeal) 수집기 - 목록 페이지 HTML 파싱.

robots.txt 허용(/b/hotdeal). 공지·광고 행은 건너뛴다.
"""
from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .. import http
from ..models import Deal, SourceInfo
from ..parse import extract_price_krw, to_int, KST
from datetime import datetime

SOURCE = SourceInfo(key="arca", name="아카라이브",
                    homepage="https://arca.live/b/hotdeal", region="kr")
ENABLED = True

BASE = "https://arca.live"
LIST_URL = BASE + "/b/hotdeal"
_END_WORDS = ("종료", "품절", "마감")


def _text(el) -> str:
    return el.get_text(" ", strip=True) if el else ""


def _parse_row(row) -> Deal | None:
    a = row.select_one("a.hybrid-title") or row.select_one("a.title")
    if not a or not a.get("href"):
        return None
    # 댓글수([3])는 제목 링크 안에 있으므로 제거하기 전에 먼저 읽는다
    cm = a.select_one(".comment-count")
    # 제목: 링크 텍스트에서 댓글수([3]) 제거
    for junk in a.select(".info, .media-icon"):
        junk.extract()
    title = _text(a)
    if not title:
        return None
    # 쿼리스트링(?p=1) 제거 → 정규 URL
    url = urljoin(BASE, a["href"]).split("?")[0]

    shop = _text(row.select_one(".deal-store")) or None
    cat_el = row.select_one(".badges a.badge")
    category = _text(cat_el) or None

    price_txt = _text(row.select_one(".deal-price"))
    price = extract_price_krw(price_txt)

    posted = None
    t = row.select_one("time[datetime]")
    if t:
        try:  # datetime 은 UTC(Z) → KST 로 변환
            dt = datetime.fromisoformat(t["datetime"].replace("Z", "+00:00"))
            posted = dt.astimezone(KST).replace(microsecond=0).isoformat()
        except ValueError:
            pass

    img = row.select_one(".vrow-preview img")
    thumb = None
    if img and img.get("src"):
        thumb = urljoin("https:", img["src"])

    # 종료 표시: 행 클래스·제목 취소선 등 (현재 마크업에선 title 안 배지/텍스트로 나타남)
    ended = any(w in title[:8] for w in _END_WORDS) or bool(row.select_one(".deal-close, .badge-close"))
    classes = " ".join(row.get("class", []))
    if "closed" in classes:
        ended = True

    return Deal(
        source=SOURCE.key, title=title, url=url, posted_at=posted, price=price,
        shop=shop, category=category, thumbnail=thumb,
        comments=to_int(_text(cm)) if cm else 0,
        likes=to_int(_text(row.select_one(".col-rate"))),
        views=to_int(_text(row.select_one(".col-view"))),
        ended=ended,
    )


def fetch(limit: int = 40) -> list[Deal]:
    deals: list[Deal] = []
    seen: set[str] = set()
    for page in range(1, 4):  # 한 페이지 ~25개, 최대 3페이지
        r = http.get(LIST_URL, params={"p": page} if page > 1 else None)
        soup = BeautifulSoup(r.text, "lxml")
        rows = soup.select("div.list-table div.vrow.hybrid")  # 공지(a.vrow.notice)는 제외됨
        if not rows:
            break
        for row in rows:
            try:
                d = _parse_row(row)
            except Exception:  # 깨진 행 하나가 전체를 막지 않도록
                continue
            if d and d.url not in seen:
                seen.add(d.url)
                deals.append(d)
        if len(deals) >= limit:
            break
    return deals[:limit]
