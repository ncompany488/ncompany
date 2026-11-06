"""에펨코리아 핫딜 (fmkorea.com/hotdeal) - 비활성.

사유: robots.txt 가 일반 봇에게 `Disallow: /` 이고 메인(/)·/best·/best2·/humor 만 허용한다.
/hotdeal 은 허용 목록에 없어 http.get 이 RobotsDisallowed 를 던진다.
사이트가 봇 차단을 명시했으므로 우회하지 않는다. robots.txt 정책이 바뀌면 다시 검토.
"""
from __future__ import annotations

from ..models import Deal, SourceInfo

SOURCE = SourceInfo(key="fmkorea", name="펨코",
                    homepage="https://www.fmkorea.com/hotdeal", region="kr")
ENABLED = False  # robots.txt 가 /hotdeal 수집을 허용하지 않음


def fetch(limit: int = 40) -> list[Deal]:
    from .. import http
    http.get("https://www.fmkorea.com/hotdeal")  # RobotsDisallowed 발생 예정
    return []
