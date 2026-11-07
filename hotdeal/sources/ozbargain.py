"""OzBargain (호주) 공식 RSS — 해외 딜.

- 피드: https://www.ozbargain.com.au/deals/feed (robots.txt 허용: Disallow 는 /api/ /goto/ 등만)
- 통화는 AUD 이므로 price 는 비워 둔다(프론트/환산 로직이 USD 가정일 수 있음). 제안: AUD 지원 시 가격 추가.
- 제공 필드: 추천(votes-pos), 댓글 수, 클릭 수(조회 대용), 만료 시각, 썸네일.
  <ozb:meta .../> 속성은 정규식으로 읽는다.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

import feedparser

from .. import http
from ..models import Deal, SourceInfo

SOURCE = SourceInfo(key="ozbargain", name="OzBargain", region="global", kind="community",
                    homepage="https://www.ozbargain.com.au/")
# 호주 달러(AUD)라 가격 비교가 안 되고 국내 사용자에게 쓸모가 적어 꺼 둠 (2026-11-07 총괄 결정)
ENABLED = False
FEED = "https://www.ozbargain.com.au/deals/feed"
_SHOP_RE = re.compile(r"@\s*(.+?)\s*$")
_ITEM_RE = re.compile(r"<item>.*?</item>", re.S)
_LINK_RE = re.compile(r"<link>([^<]+)</link>")
_META_RE = re.compile(r"<ozb:meta\s([^>]*?)/>", re.S)
_ATTR_RE = re.compile(r'([\w-]+)="([^"]*)"')


def _metas(xml: str) -> dict[str, dict[str, str]]:
    """링크 → ozb:meta 속성."""
    out = {}
    for block in _ITEM_RE.findall(xml):
        lm, mm = _LINK_RE.search(block), _META_RE.search(block)
        if lm and mm:
            out[lm.group(1).strip()] = dict(_ATTR_RE.findall(mm.group(1)))
    return out


def _int(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def fetch(limit: int = 40) -> list[Deal]:
    content = http.get(FEED).content
    meta = _metas(content.decode("utf-8", "replace"))
    feed = feedparser.parse(content)
    now = datetime.now(timezone.utc)
    deals: list[Deal] = []
    for e in feed.entries:
        try:
            title = (e.get("title") or "").strip()
            link = (e.get("link") or "").strip()
            if not title or not link.startswith("http"):
                continue
            posted = None
            if e.get("published_parsed"):
                from calendar import timegm
                posted = datetime.fromtimestamp(timegm(e.published_parsed), timezone.utc).isoformat()
            m = _SHOP_RE.search(title)
            cats = [t.get("term") for t in e.get("tags", []) if "/cat/" in (t.get("scheme") or "")]
            mt = meta.get(link, {})
            ended = False
            if mt.get("expiry"):
                try:
                    ended = datetime.fromisoformat(mt["expiry"]) < now
                except ValueError:
                    pass
            thumb = (e.get("media_thumbnail") or [{}])[0].get("url") or mt.get("image")
            deals.append(Deal(
                source=SOURCE.key, title=title, url=link, posted_at=posted,
                currency="AUD", shop=m.group(1) if m else None,
                category=cats[0] if cats else None, thumbnail=thumb,
                comments=_int(mt.get("comment-count")), likes=_int(mt.get("votes-pos")),
                views=_int(mt.get("click-count")), ended=ended,
            ))
        except Exception:
            continue
        if len(deals) >= limit:
            break
    return deals
