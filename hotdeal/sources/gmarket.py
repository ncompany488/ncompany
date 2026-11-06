"""G마켓 특가 (공식몰).

비활성: robots.txt 는 허용이나 슈퍼딜/빅스마일 페이지가 봇 요청에 403(봇 차단)을 반환. 우회하지 않는다.
허용 경로/공식 피드가 생기면 fetch 를 구현하고 ENABLED 를 True 로.
"""
from __future__ import annotations

from ..models import Deal, SourceInfo

ENABLED = False
SOURCE = SourceInfo(key="gmarket", name="G마켓", homepage="https://www.gmarket.co.kr/",
                    region="kr", kind="official")


def fetch(limit: int = 40) -> list[Deal]:
    raise NotImplementedError("접근 불가로 비활성")
