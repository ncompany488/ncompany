"""hotdeal.parse 단위 테스트. pytest 없이도 실행 가능: python tests/test_parse.py"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hotdeal.http import Robots  # noqa: E402
from hotdeal.parse import (extract_price_krw, extract_price_usd, extract_shop,  # noqa: E402
                           parse_kr_datetime)


def test_krw_basic():
    assert extract_price_krw("[쿠팡] 상품 (12,900원/무료)") == 12900
    assert extract_price_krw("[스팀] 할인 (2,150원)") == 2150
    assert extract_price_krw("아이즈모바일 150GB + 5Mb 25000원 평생") == 25000
    assert extract_price_krw("REMAKE 8,960원 REBIRTH 9,420원") == 8960
    assert extract_price_krw("상품명만 있음") is None
    assert extract_price_krw("") is None


def test_krw_from_price_and_shipping():
    # V-002: '~' (부터) 뒤 '/3,000원' 은 배송비
    assert extract_price_krw("[딜바다] 오뚜기 진라면 (6,300원~/3,000원)") == 6300
    assert extract_price_krw("(6,300원~ / 3,000원)") == 6300
    assert extract_price_krw("(6,300원~13,000원/3,000원)") == 6300
    assert extract_price_krw("[알리]코인딜 신지모루 GAN 충전기 8,508~ 26,317원") == 8508
    assert extract_price_krw("오뚜기 2~3인분 9,900원") == 9900
    assert extract_price_krw("라면 (12,900원/3,000원)") == 12900


def test_krw_man_unit():
    assert extract_price_krw("[일마존] 어고트론 LX PRO /20만") == 200000
    assert extract_price_krw("모니터 24만") == 240000
    assert extract_price_krw("1.5만원") == 15000
    assert extract_price_krw("한정판 (8만8천원)") == 88000
    assert extract_price_krw("한정판 (8만 8,000원)") == 88000
    assert extract_price_krw("체감가 최대 30만원대") == 300000


def test_krw_not_prices():
    # 배송비 자리
    assert extract_price_krw("해장국 3팩 (34,500원/3,000원)") == 34500
    assert extract_price_krw("상품 (12,000원 / 배송비 3,000원)") == 12000
    # 상품권 액면가·무료배송 기준·할인액
    assert extract_price_krw("구글플레이 기프트코드 10만원권 8% 할인") is None
    assert extract_price_krw("컬쳐랜드상품권 3만원(27,900원/무료)") == 27900
    assert extract_price_krw("상품 (12,900원/3만원 이상 무료배송)") == 12900
    assert extract_price_krw("최대 5,000원 할인 쿠폰") is None
    assert extract_price_krw("올리브영 1만원 기프트카드") is None
    assert extract_price_krw("두유 24팩 (12,000원/개당 500원)") == 12000
    # 잘린 숫자·만 단위 비금액
    assert extract_price_krw("마법사의 밤 한정판 (8만 8...") is None
    assert extract_price_krw("1200만 화소 카메라") is None
    assert extract_price_krw("비비고 3만두") is None
    assert extract_price_krw("누적 10만 명 돌파") is None


def test_usd():
    assert extract_price_usd("Widget for $80 + free shipping") == 8000
    assert extract_price_usd("Phone for $1,300") == 130000
    assert extract_price_usd("TV for $1300") == 130000
    assert extract_price_usd("($49.99/$6)") == 4999
    assert extract_price_usd("(프라임 23.51$ / 일반 54.75$)") == 2351
    assert extract_price_usd("사운드바 (33.60달러/무료배송)") == 3360
    assert extract_price_usd("러닝화 / 35.40불") == 3540
    assert extract_price_usd("직배불가 (jpy 19,982)") is None


def test_shop():
    assert extract_shop("[쿠팡] 상품") == "쿠팡"
    assert extract_shop("상품 [쿠팡]") is None


def test_datetime():
    assert parse_kr_datetime("2026-11-06 14:03:22") == "2026-11-06T14:03:22+09:00"
    assert parse_kr_datetime("26/11/06") == "2026-11-06T00:00:00+09:00"
    assert parse_kr_datetime("2026.11.06 14:03") == "2026-11-06T14:03:00+09:00"
    assert parse_kr_datetime("") is None
    assert parse_kr_datetime("14:03").endswith("+09:00")


def test_robots_wildcards():
    rb = Robots("User-agent: *\nDisallow:/service/search*\nDisallow: /*?*\n")
    assert rb.can_fetch("bot", "https://www.clien.net/service/board/jirum")
    assert not rb.can_fetch("bot", "https://www.clien.net/service/board/jirum?po=1")
    assert not rb.can_fetch("bot", "https://www.clien.net/service/searchx")
    # 더 긴 Allow 가 짧은 와일드카드 Disallow 를 이긴다 (Google 규칙)
    rb = Robots("User-agent: *\nAllow:/service/board/\nDisallow: /*?*\n")
    assert rb.can_fetch("bot", "https://www.clien.net/service/board/jirum?po=1")
    assert not rb.can_fetch("bot", "https://www.clien.net/other?x=1")
    rb = Robots("User-agent: *\nCrawl-delay: 2\nDisallow: /*?xs=*\n")
    assert rb.crawl_delay("bot") == 2.0
    assert not rb.can_fetch("bot", "https://www.dealnews.com/a?xs=1")
    rb = Robots("User-agent: *\nDisallow: /*.php$\nDisallow: /private\n")
    assert not rb.can_fetch("bot", "https://x.com/a/b.php")
    assert rb.can_fetch("bot", "https://x.com/a/b.php?x=1")
    assert not rb.can_fetch("bot", "https://x.com/private/1")
    # 가장 긴 규칙 우선
    rb = Robots("User-agent: *\nDisallow: /\nAllow: /b/hotdeal\n")
    assert rb.can_fetch("bot", "https://arca.live/b/hotdeal?p=2")
    assert not rb.can_fetch("bot", "https://arca.live/b/other")
    # 봇 전용 그룹이 있으면 그 그룹을 따름
    rb = Robots("User-agent: HotdealHubBot\nDisallow: /\n\nUser-agent: *\nDisallow:\n")
    assert not rb.can_fetch("HotdealHubBot", "https://x.com/")
    assert rb.can_fetch("other", "https://x.com/")
    assert not Robots(deny_all=True).can_fetch("bot", "https://x.com/")


if __name__ == "__main__":
    n = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            n += 1
    print(f"OK ({n} tests)")
