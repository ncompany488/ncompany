"""뽐뿌 뽐뿌게시판(국내 핫딜) 수집기.

RSS(rss.php?id=ppomppu)는 댓글·추천·카테고리·종료 여부가 없어서
목록 HTML(zboard.php)을 파싱한다. 인코딩은 EUC-KR(cp949).
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from hotdeal import http
from hotdeal.models import Deal, SourceInfo
from hotdeal.parse import (extract_price_krw, extract_shop, parse_kr_datetime,
                           to_int)

BOARD_ID = "ppomppu"
LIST_URL = "https://www.ppomppu.co.kr/zboard/zboard.php"
SOURCE = SourceInfo(key="ppomppu", name="뽐뿌",
                    homepage=f"{LIST_URL}?id={BOARD_ID}", region="kr")

MAX_BACKFILL_PAGES = 999  # page=1000 부터는 서버가 403 (2026-11 실측: 999 쪽은 약 6.5개월 전)


def _abs(src: str | None) -> str | None:
    if not src or "noimage" in src:
        return None
    return "https:" + src if src.startswith("//") else src


def _parse_row(tr) -> Deal | None:
    a = tr.select_one("a.baseList-title")
    if a is None:
        return None
    m = re.search(r"[?&]id=(\w+).*?[?&]no=(\d+)", a.get("href", ""))
    if not m or m.group(1) != BOARD_ID:  # 목록 중간에 끼는 타 게시판(쇼핑포럼·자유게시판 등) 홍보 행 제외
        return None
    # 세션·페이지 파라미터를 버린 대표 URL
    url = f"https://www.ppomppu.co.kr/zboard/view.php?id={m.group(1)}&no={m.group(2)}"
    title = a.get_text(" ", strip=True)
    # "[쿠팡]" 머리말은 em 태그로 분리돼 있어 공백이 끼므로 붙여서 다시 만든다
    head = a.select_one("em.baseList-head")
    if head:
        h = head.get_text(strip=True)
        title = h + title[len(h):].strip()
    cat = tr.select_one("small.baseList-small")
    thumb = tr.select_one("a.baseList-thumb img")
    cmt = tr.select_one("span.baseList-c")
    rec = tr.select_one("td.baseList-rec")
    views = tr.select_one("td.baseList-views")
    time_td = tr.select_one("td[title]")
    time_el = tr.select_one("time.baseList-time")
    posted = parse_kr_datetime(time_td["title"]) if time_td else None
    if not posted and time_el:  # title 속성이 없는 행은 보이는 시각(예: 10:32:18)으로
        posted = parse_kr_datetime(time_el.get_text(strip=True))
    ended = "end2" in (a.get("class") or []) or tr.select_one("img[src*=end_icon]") is not None
    likes = None
    if rec and rec.get_text(strip=True):
        likes = to_int(rec.get_text().split("-")[0])  # "추천 - 반대"
    return Deal(
        source=SOURCE.key, title=title, url=url,
        posted_at=posted,
        price=extract_price_krw(title),
        shop=extract_shop(title),
        category=cat.get_text(strip=True).strip("[]") if cat else None,
        thumbnail=_abs(thumb.get("src")) if thumb else None,
        comments=to_int(cmt.get_text()) if cmt else 0,
        likes=likes, views=to_int(views.get_text()) if views else None,
        ended=ended,
    )


def fetch_page(page: int) -> list[Deal]:
    """목록 N페이지(1부터) 의 딜. 페이지가 비었거나 끝이면 []."""
    r = http.get(LIST_URL, params={"id": BOARD_ID, "page": page}, encoding="cp949")
    soup = BeautifulSoup(r.text, "lxml")
    deals, seen = [], set()
    for tr in soup.select("tr.baseList"):  # 공지(baseNotice)는 제외됨
        try:
            d = _parse_row(tr)
        except Exception:  # 한 줄이 깨져도 나머지는 계속
            continue
        if d and d.url not in seen:
            seen.add(d.url)
            deals.append(d)
    return deals


def fetch(limit: int = 40) -> list[Deal]:
    deals, seen = [], set()
    for page in (1, 2, 3):  # 한 페이지가 ~28개라 모자라면 다음 페이지
        for d in fetch_page(page):
            if d.url not in seen:
                seen.add(d.url)
                deals.append(d)
        if len(deals) >= limit:
            break
    return deals[:limit]
