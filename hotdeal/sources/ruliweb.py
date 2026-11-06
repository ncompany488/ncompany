"""루리웹 핫딜·예판 게시판(market/board/1020) 수집기.

RSS 는 제공되지 않아 목록 HTML 을 파싱한다.
robots.txt 가 cate=, orderby= 등 정렬·분류 파라미터를 막으므로 기본 목록(page 만 사용)만 가져온다.
한계: 목록의 긴 제목은 사이트가 "..." 로 잘라서 보여준다(본문을 열지 않으므로 그대로 둠).
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from hotdeal import http
from hotdeal.models import Deal, SourceInfo
from hotdeal.parse import (extract_price_krw, extract_shop, parse_kr_datetime,
                           to_int)

LIST_URL = "https://bbs.ruliweb.com/market/board/1020"
SOURCE = SourceInfo(key="ruliweb", name="루리웹", homepage=LIST_URL, region="kr")


def _parse_row(tr) -> Deal | None:
    cls = tr.get("class") or []
    if "notice" in cls or "best" in cls:  # 공지·BEST 중복 행 제외
        return None
    a = tr.select_one("a.subject_link")
    if a is None:
        return None
    m = re.search(r"/read/(\d+)", a.get("href", ""))
    if not m:
        return None
    url = f"{LIST_URL}/read/{m.group(1)}"  # 뒤의 ? / #cmt 제거
    # 제목: 링크 안의 텍스트만 (댓글수 a/span 은 제외)
    title = "".join(t for t in a.find_all(string=True, recursive=False))
    title = " ".join(title.split())
    if not title:
        return None
    cat = tr.select_one("td.divsn")
    cmt = tr.select_one(".num_reply")
    time_td = tr.select_one("td.time")
    ended = any("[종료]" in s.get_text() for s in tr.select("td.subject span"))
    return Deal(
        source=SOURCE.key, title=title, url=url,
        posted_at=parse_kr_datetime(time_td.get_text(strip=True)) if time_td else None,
        price=extract_price_krw(title),
        shop=None if extract_shop(title) == (cat.get_text(strip=True) if cat else None) else extract_shop(title),  # [휴대폰] 같은 분류 머리말은 판매처 아님
        category=cat.get_text(strip=True) if cat else None,
        thumbnail=None,  # 목록에 썸네일 URL 없음
        comments=to_int(cmt.get_text()) if cmt else 0,
        likes=to_int(tr.select_one("td.recomd").get_text()) if tr.select_one("td.recomd") else None,
        views=to_int(tr.select_one("td.hit").get_text()) if tr.select_one("td.hit") else None,
        ended=ended,
    )


def fetch(limit: int = 40) -> list[Deal]:
    deals, seen = [], set()
    for page in (1, 2):
        params = {"page": page} if page > 1 else None
        r = http.get(LIST_URL, params=params, encoding="utf-8")
        soup = BeautifulSoup(r.text, "lxml")
        for tr in soup.select("tr.table_body"):
            try:
                d = _parse_row(tr)
            except Exception:  # 한 줄이 깨져도 계속
                continue
            if d and d.url not in seen:
                seen.add(d.url)
                deals.append(d)
        if len(deals) >= limit:
            break
    return deals[:limit]
