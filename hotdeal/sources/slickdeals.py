"""Slickdeals 프론트페이지 RSS (해외 딜).

비활성: slickdeals.net 의 robots.txt 가 Cloudflare 봇 확인 페이지(403)로 막혀 있어
robots 허용 여부를 확인할 수 없다(공용 http 는 이 경우 전부 금지로 처리). 우회하지 않는다.
RSS 자체(https://slickdeals.net/newsearch.php?mode=frontpage&searcharea=deals&searchin=first&rss=1)
는 단순 요청에 200 으로 응답하지만, 정책상 확인 불가이므로 꺼 둔다. 대체: dealnews.py.
허용되는 경로가 확인되면 아래 fetch 를 구현해 ENABLED 를 True 로 바꾼다
(제목 가격은 extract_price_usd, 'Thumb Score: +N' 은 likes).
"""
from __future__ import annotations

from ..models import Deal, SourceInfo

ENABLED = False
SOURCE = SourceInfo(key="slickdeals", name="Slickdeals", homepage="https://slickdeals.net/",
                    region="global", kind="community")


def fetch(limit: int = 40) -> list[Deal]:
    raise NotImplementedError("robots.txt 확인 불가로 비활성")
