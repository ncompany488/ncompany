"""딜바다(dealbada.com) 국내핫딜 게시판 수집기 (HTML 목록 파싱, 그누보드).

- robots.txt: `User-agent: *` → `Allow: /` (프로필·쪽지·성인게시판만 금지). 목록 URL 허용 확인.
- RSS 없음. 목록 한 페이지 = 15건. 시각은 오늘 글만 HH:MM, 지난 글은 MM-DD(날짜만).
- 제목 형식: "[쇼핑몰] 상품명 (가격원/배송)" → 판매처/가격 추출 가능.
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from .. import http
from ..models import Deal, SourceInfo
from ..parse import extract_price_krw, extract_shop, parse_kr_datetime, to_int

BASE = "https://www.dealbada.com"
LIST_URL = BASE + "/bbs/board.php"
BOARD = "deal_domestic"
SOURCE = SourceInfo(key="dealbada", name="딜바다", region="kr", kind="community",
                    homepage=f"{LIST_URL}?bo_table={BOARD}")
ENABLED = True
MAX_BACKFILL_PAGES = 100  # 실제 깊이는 백필 시 확인 (글번호 ~33000 / 15건)


def _parse_row(tr) -> Deal | None:
    cls = tr.get("class") or []
    if "bo_notice" in cls or "best_article" in cls:
        return None
    a = tr.select_one("td.td_subject a")
    if a is None:
        return None
    m = re.search(r"wr_id=(\d+)", a.get("href", ""))
    if not m:
        return None
    # 댓글 수 span(.cnt_cmt)과 스크린리더용 "댓글 N 개"(.sound_only)가 제목 <a> 안에 들어 있다.
    # 그누보드는 댓글이 0개면 .cnt_cmt 자체가 없다 → 없으면 0. 숫자를 먼저 읽고 제거한 뒤 제목을 만든다.
    cmt = tr.select_one("td.td_subject .cnt_cmt")
    comments = (to_int(cmt.get_text()) if cmt else 0) or 0
    for junk in a.select(".cnt_cmt, .sound_only"):
        junk.decompose()
    title = " ".join(a.get_text(" ", strip=True).split())
    if not title:
        return None
    url = f"{LIST_URL}?bo_table={BOARD}&wr_id={m.group(1)}"
    cat = tr.select_one("td.td_cate")
    date = tr.select_one("td.td_date")
    nums = tr.select("td.td_num")  # [글번호, 조회수]
    views = to_int(nums[-1].get_text()) if len(nums) >= 2 else None
    likes = None  # 추천/비추천 "a / b" 중 앞쪽
    g = tr.select_one("td.td_num_g span")
    if g:
        likes = to_int(g.get_text())
    img = tr.select_one("td.td_img img")
    thumb = img.get("src") if img and img.get("src") else None
    if thumb and thumb.startswith("http://"):
        thumb = "https://" + thumb[len("http://"):]  # cdn.dealbada.com 은 https 지원 (혼합콘텐츠 방지)
    return Deal(
        source=SOURCE.key, title=title, url=url,
        posted_at=parse_kr_datetime(date.get_text(strip=True)) if date else None,
        price=extract_price_krw(title), shop=extract_shop(title),
        category=cat.get_text(strip=True) if cat else None,
        thumbnail=thumb, comments=comments, likes=likes, views=views,
        ended="[종료]" in title or "품절" in title[:10],
    )


def fetch_page(page: int) -> list[Deal]:
    """목록 N페이지(1부터)."""
    params: dict = {"bo_table": BOARD}
    if page > 1:
        params["page"] = page
    soup = BeautifulSoup(http.get(LIST_URL, params=params).text, "lxml")
    deals, seen = [], set()
    for tr in soup.select("table tbody tr"):
        try:
            d = _parse_row(tr)
        except Exception:
            continue
        if d and d.url not in seen:
            seen.add(d.url)
            deals.append(d)
    return deals


def fetch(limit: int = 40) -> list[Deal]:
    deals, seen = [], set()
    for page in (1, 2, 3):
        for d in fetch_page(page):
            if d.url not in seen:
                seen.add(d.url)
                deals.append(d)
        if len(deals) >= limit:
            break
    return deals[:limit]
