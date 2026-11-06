"""모든 수집기가 공통으로 쓰는 딜 데이터 형식."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class SourceInfo:
    key: str            # 영문 식별자 (예: "ppomppu")
    name: str           # 화면 표시 이름 (예: "뽐뿌")
    homepage: str       # 게시판 주소
    region: str = "kr"  # "kr" | "global"
    kind: str = "community"  # "community" | "official"


@dataclass
class Deal:
    source: str                     # SourceInfo.key
    title: str                      # 원문 제목 (그대로)
    url: str                        # 원문 게시글 링크 (절대 URL)
    posted_at: Optional[str] = None # ISO8601, KST(+09:00) 또는 타임존 포함
    price: Optional[int] = None     # 원화 정수. 해외는 아래 currency 참고
    currency: str = "KRW"           # "KRW" | "USD" ...
    shop: Optional[str] = None      # 판매처 (쿠팡, 11번가, Amazon ...)
    category: Optional[str] = None  # 원본 게시판 카테고리 문자열
    thumbnail: Optional[str] = None
    comments: Optional[int] = None
    likes: Optional[int] = None     # 추천/좋아요
    views: Optional[int] = None
    ended: bool = False             # 품절/종료 표시
    product_url: Optional[str] = None  # 실제 상품 링크 (알 수 있을 때만)
    id: str = field(default="")

    def __post_init__(self) -> None:
        self.title = " ".join((self.title or "").split())
        if not self.id:
            self.id = hashlib.sha1(f"{self.source}|{self.url}".encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        return asdict(self)
