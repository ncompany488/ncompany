"""11번가 특가 (공식몰).

비활성: robots.txt 가 모든 봇에 대해 Disallow: / (일부 검색봇만 허용). 쇼킹딜 페이지·API 모두 수집 불가.
허용 경로/공식 피드가 생기면 fetch 를 구현하고 ENABLED 를 True 로.
"""
from __future__ import annotations

from ..models import Deal, SourceInfo

ENABLED = False
SOURCE = SourceInfo(key="st11", name="11번가", homepage="https://www.11st.co.kr/",
                    region="kr", kind="official")


def fetch(limit: int = 40) -> list[Deal]:
    raise NotImplementedError("접근 불가로 비활성")
