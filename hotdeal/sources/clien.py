"""클리앙 알뜰구매 게시판 수집기 (HTML 목록 파싱).

- RSS 는 없음(404). robots.txt 가 쿼리스트링(/*?*)을 막으므로 ?page= 같은 파라미터 없이
  첫 페이지(약 30건)만 가져온다.
- 목록의 정렬/분류 쿼리(?od=...)는 잘라서 canonical URL 로 만든다.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from .. import http
from ..models import Deal, SourceInfo
from ..parse import extract_price_krw, extract_shop, parse_kr_datetime, to_int

SOURCE = SourceInfo(key="clien", name="클리앙", region="kr", kind="community",
                    homepage="https://www.clien.net/service/board/jirum")
ENABLED = True

BASE = "https://www.clien.net"
LIST_URL = BASE + "/service/board/jirum"


def _hits(s: str) -> int | None:
    """'658', '23.1 k' 같은 조회수 표기를 정수로."""
    s = (s or "").strip().lower().replace(",", "")
    m = re.match(r"([\d.]+)\s*k$", s)
    if m:
        return int(float(m.group(1)) * 1000)
    return to_int(s)


def _parse_row(row) -> Deal | None:
    a = row.select_one("a[data-role=list-title-text]") or row.select_one(".list_subject a")
    if not a or not a.get("href"):
        return None
    m = re.search(r"/service/board/jirum/(\d+)", a["href"])
    if not m:
        return None
    url = f"{BASE}/service/board/jirum/{m.group(1)}"
    title = a.get_text(" ", strip=True)
    if not title:
        return None

    # 댓글 수 (제목 옆 배지가 아닌 data 속성 사용)
    comments = to_int(row.get("data-comment-count"))
    # 추천 수
    like_el = row.select_one("[data-role=list-like-count] em")
    likes = to_int(like_el.get_text()) if like_el else None
    hit_el = row.select_one(".list_hit .hit")
    views = _hits(hit_el.get_text()) if hit_el else None
    # 작성 시각 (timestamp 가 전체 날짜)
    ts = row.select_one(".list_time .timestamp")
    posted = parse_kr_datetime(ts.get_text(strip=True)) if ts else None
    # 분류
    cat_el = row.select_one(".keyword .icon_keyword")
    category = cat_el.get_text(strip=True) if cat_el else None
    # 썸네일 (기본 no-image 는 제외)
    img = row.select_one(".list_thumbnail img")
    thumb = img.get("src") if img and img.get("src", "").startswith("http") else None

    classes = row.get("class") or []
    ended = "sold_out" in classes or bool(row.select_one(".icon_info"))

    return Deal(
        source=SOURCE.key, title=title, url=url, posted_at=posted,
        price=extract_price_krw(title), shop=extract_shop(title),
        category=category, thumbnail=thumb, comments=comments, likes=likes,
        views=views, ended=ended,
    )


def fetch(limit: int = 40) -> list[Deal]:
    html = http.get(LIST_URL).text
    soup = BeautifulSoup(html, "lxml")
    deals: list[Deal] = []
    # data-role="list-row" 인 것만 실제 글 (공지·상단 고정·광고 행 제외)
    for row in soup.select("div.list_item[data-role=list-row]"):
        if "notice" in (row.get("class") or []):
            continue
        try:
            d = _parse_row(row)
        except Exception:  # 한 줄이 깨져도 전체는 계속
            continue
        if d:
            deals.append(d)
        if len(deals) >= limit:
            break
    return deals
