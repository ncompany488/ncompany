"""예의 바른 HTTP 클라이언트: robots.txt 준수, 타임아웃, 재시도, 사이트별 간격."""
from __future__ import annotations

import re
import time
from urllib.parse import urlparse

import requests

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0 Safari/537.36 HotdealHubBot/0.1"
)
BOT_NAME = "HotdealHubBot"
MIN_INTERVAL = 1.5  # 같은 호스트 요청 간 최소 간격(초)

_session = requests.Session()
_session.headers.update({
    "User-Agent": USER_AGENT,
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
})
_robots: dict[str, "Robots"] = {}
_last_hit: dict[str, float] = {}


class RobotsDisallowed(Exception):
    pass


class Robots:
    """와일드카드(*, $)를 지원하는 robots.txt 해석기 (Google 규칙: 가장 긴 매칭 우선, 동률이면 Allow)."""

    def __init__(self, text: str = "", deny_all: bool = False):
        self.deny_all = deny_all
        self.groups: dict[str, list[tuple[bool, re.Pattern, int]]] = {}
        self.delays: dict[str, float] = {}  # Crawl-delay (초)
        agents: list[str] = []
        last_was_rule = False
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            k, v = (x.strip() for x in line.split(":", 1))
            k = k.lower()
            if k == "user-agent":
                if last_was_rule:
                    agents = []
                agents.append(v.lower())
                last_was_rule = False
            elif k == "crawl-delay":
                last_was_rule = True
                try:
                    for a in agents:
                        self.delays[a] = float(v)
                except ValueError:
                    pass
            elif k in ("allow", "disallow"):
                last_was_rule = True
                if not v:
                    continue  # 빈 Disallow = 전부 허용
                pat = re.escape(v).replace(r"\*", ".*")
                if pat.endswith(r"\$"):
                    pat = pat[:-2] + "$"
                for a in agents:
                    self.groups.setdefault(a, []).append((k == "allow", re.compile(pat), len(v)))

    def crawl_delay(self, agent: str) -> float:
        return self.delays.get(agent.lower(), self.delays.get("*", 0.0))

    def can_fetch(self, agent: str, url: str) -> bool:
        if self.deny_all:
            return False
        p = urlparse(url)
        path = (p.path or "/") + ("?" + p.query if p.query else "")
        rules = self.groups.get(agent.lower()) or self.groups.get("*") or []
        best: tuple[int, bool] | None = None
        for allow, pat, ln in rules:
            if pat.match(path) and (best is None or ln > best[0] or (ln == best[0] and allow)):
                best = (ln, allow)
        return True if best is None else best[1]


def _robots_for(url: str) -> "Robots":
    p = urlparse(url)
    base = f"{p.scheme}://{p.netloc}"
    if base not in _robots:
        try:
            r = _session.get(base + "/robots.txt", timeout=10)
            looks_html = "html" in r.headers.get("Content-Type", "") or r.text.lstrip()[:1] == "<"
            if r.status_code == 200 and not looks_html:
                rb = Robots(r.text)
            elif r.status_code == 404 or r.status_code == 410:
                rb = Robots()  # robots.txt 없음 → 제한 없음
            else:
                # 403(봇 차단)·HTML 차단 페이지·5xx → 판단 불가, 안전하게 전부 금지
                rb = Robots(deny_all=True)
        except requests.RequestException:
            rb = Robots(deny_all=True)
        _robots[base] = rb
    return _robots[base]


def allowed(url: str) -> bool:
    rb = _robots_for(url)
    return rb.can_fetch(BOT_NAME, url) and rb.can_fetch("*", url)


def get(url: str, *, params: dict | None = None, encoding: str | None = None,
        headers: dict | None = None, retries: int = 2, timeout: int = 15) -> requests.Response:
    """robots.txt 가 허용하는 URL 만 가져온다. 실패 시 예외."""
    full = requests.Request("GET", url, params=params).prepare().url or url
    if not allowed(full):
        raise RobotsDisallowed(full)
    host = urlparse(url).netloc
    # robots.txt 의 Crawl-delay 가 더 길면 그 값을 따른다
    interval = max(MIN_INTERVAL, _robots_for(full).crawl_delay(BOT_NAME))
    wait = interval - (time.time() - _last_hit.get(host, 0))
    if wait > 0:
        time.sleep(wait)
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            r = _session.get(url, params=params, headers=headers, timeout=timeout)
            _last_hit[host] = time.time()
            if r.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(2 * (attempt + 1))
                continue
            r.raise_for_status()
            if encoding:
                r.encoding = encoding
            elif r.encoding and r.encoding.lower() == "iso-8859-1":
                r.encoding = r.apparent_encoding
            return r
        except requests.RequestException as e:
            last_exc = e
            resp = getattr(e, "response", None)
            if resp is not None and 400 <= resp.status_code < 500 and resp.status_code != 429:
                raise  # 403·404 등은 다시 시도해도 같으므로 바로 실패 (봇 차단 서버를 두드리지 않음)
            if attempt < retries:
                time.sleep(2 * (attempt + 1))
    raise last_exc  # type: ignore[misc]
