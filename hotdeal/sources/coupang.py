"""쿠팡 특가 (공식몰).

비활성: robots.txt 조차 Akamai 'Access Denied' 로 차단. 골드박스 수집 불가.
허용 경로/공식 피드가 생기면 fetch 를 구현하고 ENABLED 를 True 로.
"""
from __future__ import annotations

from ..models import Deal, SourceInfo

ENABLED = False
SOURCE = SourceInfo(key="coupang", name="쿠팡", homepage="https://www.coupang.com/",
                    region="kr", kind="official")


def fetch(limit: int = 40) -> list[Deal]:
    raise NotImplementedError("접근 불가로 비활성")
