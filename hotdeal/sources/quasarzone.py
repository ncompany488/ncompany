"""퀘이사존 지름/핫딜 게시판 수집기 — 비활성.

사유: quasarzone.com 은 Cloudflare 뒤에 있어 일반 요청(robots.txt 포함)에 403 을 반환한다.
봇 차단/챌린지를 우회하지 않는 것이 원칙이므로 수집하지 않는다.
허용 방법(공식 RSS/API 제공, 제휴 등)이 생기면 fetch 를 구현하고 ENABLED 를 True 로 바꾼다.
"""
from __future__ import annotations

from ..models import Deal, SourceInfo

SOURCE = SourceInfo(key="quasarzone", name="퀘이사존", region="kr", kind="community",
                    homepage="https://quasarzone.com/bbs/qb_saleinfo")
ENABLED = False


def fetch(limit: int = 40) -> list[Deal]:
    raise RuntimeError("quasarzone: Cloudflare 403 으로 차단됨 (ENABLED=False)")
