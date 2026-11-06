"""쿨앤조이 지름/알뜰정보 게시판 (coolenjoy.net/bbs/jirum) - 비활성.

사유: robots.txt 가 `User-agent: *` 에 `Disallow: /` 이고 Googlebot·Yeti(네이버)만 허용한다.
게시판·RSS 모두 http.get 이 RobotsDisallowed 를 던진다. 우회하지 않는다.
(참고: robots.txt 의 `Disallow link?$` 줄도 비표준 형태.) 정책이 바뀌면 다시 검토.
"""
from __future__ import annotations

from ..models import Deal, SourceInfo

SOURCE = SourceInfo(key="coolenjoy", name="쿨앤조이",
                    homepage="https://coolenjoy.net/bbs/jirum", region="kr")
ENABLED = False  # robots.txt 가 일반 봇 전체 차단


def fetch(limit: int = 40) -> list[Deal]:
    from .. import http
    http.get("https://coolenjoy.net/bbs/jirum")  # RobotsDisallowed 발생 예정
    return []
