"""상품별 가격 기록과 역대 최저가.

data/history.json (data 브랜치에 계속 누적, 72시간 정리 대상 아님)
{
  "version": PARSER_VERSION,
  "global_sources": ["ppomppu_global", ...],  ← 해외 사이트 key (누적, 줄지 않음. 옛 파일엔 없음 = 빈 목록)
  "products": {
    "<pid>": {
      "name": "신라면", "unit": "개"|"100g"|"100ml"|null, "size": "120g"|null,
      "keys": ["신라면", ...],
      "obs": {"<글 URL>": {"price", "title", "source", "date", "ended",            ← 원본 (재분류 때 이것만 사용)
                          "count", "label", "usize", "size_g", "base", "content", "cunit", "cond", "unit_price",
                          "currency"(KRW 가 아닐 때만)}}
    }
  },
  "skipped": {"<URL>": {...}}   ← 재분류 때 상품이 아니게 된 옛 기록 (다음 버전에서 다시 검토, 정리 기간 동일)
}

키 공간 (통화·지역이 다른 가격은 절대 같은 상품에 섞지 않음 — pid·keys 앞에 접두):
  ""      국내 사이트의 원화 글 (옛 키 그대로)
  "usd:"  달러 딜 (가격·단가는 센트 정수). _MIN_PRICE 에 없는 통화는 기록 안 함
  "g:"    해외 사이트(global_sources)의 원화 표기 글 (환율·해외 배송비가 섞인 값)

비교 규칙 (같은 상품 안에서도 '비교 기준'이 같은 글끼리만):
  n  개당      — 둘 다 개수가 있고 개당 용량이 같거나 둘 다 모를 때 (박스·세트는 낱개와 따로)
  w  100g당    — 둘 다 총량(g/ml)을 알 때. 개당 용량이 다른 글(350ml vs 500ml)·무게로만 판 글은 이걸로
  c  캡슐당 등 — 둘 다 내용물 총수(캡슐·알·매·포·롤)를 알 때
  total 총액   — 둘 다 수량·용량 정보가 전혀 없을 때 (전자제품·게임)
  · 개수만 있는 글(신라면 5개)은 같은 상품에 개당 용량이 하나뿐이면(120g) 그 용량으로 총량을 추정해 w 비교에도 참여.
  · 현재 글이 쓸 기준은 비교 가능한 과거 표본이 가장 많은 것 (동률이면 n → c → w → total).
판정:
  · 조건부(cond: 카드·멤버십·와우·신규/미구매…) 가격은 일반가 최저·판정에서 빼고 low_cond 로 따로.
    현재 딜이 조건부면 반대로 조건부 기록끼리만 비교 (history.basis == "cond"). 조건부 기록이 부족하면 'first'.
  · 같은 가격이 3일 안에 다시 올라온 글(다른 사이트 교차 게시·재게시)은 표본 1건으로 셈.
    현재 딜과 같은 가격·3일 이내인 과거 글은 같은 딜로 보고 기록에서 제외.
  · 표본(samples) 2건 미만이면 'first'(기록 부족). 표본 3건 이하인데 값이 3배 넘게 차이 나면 역시 'first'.
  · cur < 최저 → 'lowest', cur == 최저 → 'equal', +5% 이내 'near', 그 외 'higher'.
  · (C-2-3) 'lowest' 인데 표본 ≤3, 단가 하락 >40%, 현재 총액이 최저 글 총액의 0.75~1.33배면 'first' 로 낮추고
    history.suspect = {"drop_pct", "price_ratio"} 를 남김 (화면은 'first' 를 배지 없음으로 처리 → 판정 값 종류는 그대로).
    근거 (R3, history 사본 18.8k obs 를 시간순으로 재생해 나온 'lowest' 479건 중 하락 >40% 12건, 손으로 확인):
      하락 >40% & 표본 ≤3 : 9건 = 오류 2 (대패삼겹살 1+1 2kg, 스탠리 '외 다양'→파서에서 제외로 수정) / 정상 7
                            (1.5L 페트 vs 캔, 대용량 묶음, 게임 반값 등) → '표본 ≤3 이면 보류' 만으로는 정상 7건을 잃음
      그중 총액 0.75~1.33배 : 2건 = 대패삼겹살(0.98, 오류) · 대극천 복숭아 2kg vs 1kg(1.12, 애매) / 정상 페트·묶음은 0건
      하락 >40% & 표본 ≥4 : 3건 (돈까스 16장 8팩 ×2 = 오류, 암바사 페트 = 정상) → 표본 많은 쪽은 건드리지 않음
"""
from __future__ import annotations

import json
import statistics
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Optional

from .parse import now_kst
from .product import PARSER_VERSION, ProductInfo, parse_product
from .store import ROOT, parse_iso, to_kst

HISTORY_PATH = ROOT / "data" / "history.json"
KEEP_DAYS = 400          # 이 기간 동안 새 기록이 없는 상품은 삭제
KEEP_RECENT = 40         # 상품마다 최근 기록 몇 개는 항상 보관
MAX_TIERS = 8            # 화면에 보낼 수량별 최저가 개수
NEAR_PCT = 5.0           # 역대 최저 대비 이 % 이내면 '근접'
OUTLIER_RATIO = 0.3      # 중앙값의 30% 미만 가격은 제목 해석 오류로 보고 최저가 계산에서 제외
MIN_SAMPLES = 2          # 'lowest' 등 판정에 필요한 비교 가능한 과거 표본 수
SMALL_SPREAD = 3.0       # 표본 3건 이하에서 값이 이 배수 넘게 벌어지면 판정 보류
REPOST_DAYS = 3          # 같은 가격이 이 기간 안에 다시 올라오면 같은 딜
# C-2-3 급락 판정 보류: 표본 ≤3 · 단가가 과거 최저보다 40% 넘게 낮음 · 총액은 과거 최저 글의 0.75~1.33배
# (= 거의 같은 돈에 1.7배 넘는 양 → 대개 '1+1 2kg' 같은 수량 해석 오류). 근거는 모듈 설명 아래 표.
SUSPECT_MAX_SAMPLES = 3
SUSPECT_DROP = 0.40
SUSPECT_PRICE_BAND = (0.75, 1.33)
MIN_PRICE = 200          # (원화) 이보다 싼 글은 포인트 적립·이벤트로 보고 기록하지 않음
_MIN_PRICE = {"KRW": MIN_PRICE, "USD": 100}   # 통화별 최소 가격 (USD 는 센트 = $1). 없는 통화는 기록 안 함
_BOXY = {"박스", "세트"}
_ORDER = ("n", "c", "w", "total")


def _obs_fields(info: ProductInfo, price: int) -> dict:
    return {"count": info.count, "label": info.label, "usize": info.usize, "size_g": info.size_g,
            "base": info.base, "content": info.content, "cunit": info.content_unit, "cond": info.cond,
            "unit_price": info.unit_price(price)}


def _cur(c: Optional[str]) -> str:
    return (c or "KRW").upper()


def _dt(s: Optional[str]) -> Optional[datetime]:
    try:
        return parse_iso(to_kst(s)) if s else None   # 시간대 없는 값도 KST 로
    except Exception:
        return None


class History:
    def __init__(self, data: Optional[dict] = None, global_sources: Iterable[str] = ()):
        """global_sources: 해외 사이트 key (SOURCE.region == "global"). 그 사이트의 원화 글은 국내와 따로 기록.
        파일에 저장된 목록과 합쳐 쓰고 줄이지 않음 (사이트를 꺼도·인자 없이 불러도 분류가 흔들리지 않게).
        새 해외 사이트가 늘면 그 사이트 옛 기록을 옮기려고 한 번 재분류."""
        data = data or {}
        self.products: dict[str, dict] = data.get("products", {})
        self.skipped: dict[str, dict] = data.get("skipped", {})
        saved = set(data.get("global_sources") or [])
        self.global_sources: set[str] = saved | set(global_sources)
        self._index: dict[str, str] = {}
        self.rebuilt = False
        if (self.products or self.skipped) and (data.get("version") != PARSER_VERSION
                                                or not self.global_sources <= saved):
            self.rebuild()
        else:
            self._reindex()

    def _reindex(self) -> None:
        self._index = {}
        for pid, p in self.products.items():
            for k in p.get("keys", []):
                self._index.setdefault(k, pid)

    # ---------- 저장 ----------
    @classmethod
    def load(cls, path: Path = HISTORY_PATH, global_sources: Iterable[str] = ()) -> "History":
        try:
            return cls(json.loads(path.read_text(encoding="utf-8")), global_sources)
        except (FileNotFoundError, json.JSONDecodeError):
            return cls(None, global_sources)

    def save(self, path: Path = HISTORY_PATH) -> None:
        self.prune()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"version": PARSER_VERSION, "global_sources": sorted(self.global_sources),
                                   "products": self.products, "skipped": self.skipped},
                                  ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        tmp.replace(path)

    # ---------- 재분류 (키 규칙이 바뀌었을 때) ----------
    def rebuild(self) -> None:
        """모든 기록을 제목으로 다시 분류. 원본(price/title/source/date/ended)은 그대로 보존."""
        old: dict[str, dict] = {}
        for p in self.products.values():
            for u, o in p.get("obs", {}).items():
                old[u] = o
        for u, o in self.skipped.items():
            old.setdefault(u, o)
        self.products, self.skipped, self._index = {}, {}, {}
        cache: dict[str, Optional[ProductInfo]] = {}
        for u, o in old.items():
            base = {"price": o.get("price"), "title": o.get("title"), "source": o.get("source"),
                    "date": o.get("date"), "ended": bool(o.get("ended"))}
            cur = _cur(o.get("currency"))
            if cur != "KRW":
                base["currency"] = cur
            title = base["title"] or ""
            if title not in cache:
                cache[title] = parse_product(title)
            info = cache[title]
            price = base["price"]
            space = self._space(cur, base["source"])
            if info is None or price is None or space is None or price < _MIN_PRICE[cur]:
                self.skipped[u] = base
                continue
            pid = self._find_or_create(info, space)
            self.products[pid]["obs"][u] = {**base, **_obs_fields(info, price)}
        self.rebuilt = True

    # ---------- 상품 찾기 ----------
    def _space(self, currency: Optional[str], source: Optional[str]) -> Optional[str]:
        """키 공간 접두 ('' 국내 원화 · 'usd:' · 'g:' 해외 사이트 원화). 기록할 수 없는 통화면 None."""
        c = _cur(currency)
        if c not in _MIN_PRICE:
            return None
        if c != "KRW":
            return c.lower() + ":"
        return "g:" if source in self.global_sources else ""

    def _group_space(self, g: dict) -> Optional[str]:
        """그룹의 키 공간. 원화 그룹은 글이 전부 해외 사이트일 때만 해외 공간 (국내 글이 하나라도 있으면 국내)."""
        c = _cur(g.get("currency"))
        if c != "KRW":
            return self._space(c, None)
        srcs = [s.get("source") for s in g.get("sources", [])]
        return "g:" if srcs and all(s in self.global_sources for s in srcs) else ""

    def _find(self, info, space: str = "") -> Optional[str]:
        return self._index.get(space + info.key) or self._index.get(space + info.alt_key)

    def _find_or_create(self, info, space: str = "") -> str:
        pid = self._find(info, space)
        if pid is None:
            pid = space + info.key
            self.products[pid] = {"name": info.name, "unit": info.unit, "size": info.size, "keys": [], "obs": {}}
        p = self.products[pid]
        for k in (space + info.key, space + info.alt_key):
            if k not in p["keys"]:
                p["keys"].append(k)
            self._index.setdefault(k, pid)
        return pid

    # ---------- 기록 추가 ----------
    def observe(self, deals: Iterable[dict]) -> int:
        """딜(개별 글) 목록을 기록에 반영. 반영한 개수."""
        n = 0
        for d in deals:
            price = d.get("price")
            cur = _cur(d.get("currency"))
            space = self._space(cur, d.get("source"))
            if price is None or space is None or not d.get("url") or price < _MIN_PRICE[cur]:
                continue
            info = parse_product(d.get("title") or "")
            if info is None:
                continue
            pid = self._find_or_create(info, space)
            self.products[pid]["obs"][d["url"]] = {
                **({"currency": cur} if cur != "KRW" else {}),
                "price": price,
                "title": d.get("title"),
                "source": d.get("source"),
                "date": to_kst(d.get("posted_at") or d.get("first_seen")) or now_kst().replace(microsecond=0).isoformat(),
                "ended": bool(d.get("ended")),
                **_obs_fields(info, price),
            }
            self.skipped.pop(d["url"], None)
            n += 1
        return n

    # ---------- 비교 ----------
    @staticmethod
    def _norm(o: dict) -> dict:
        """저장된 obs 또는 현재 딜을 비교용 값으로."""
        return {"price": o.get("price"), "n": o.get("count"), "label": o.get("label") or "개",
                "uw": o.get("usize"), "w": o.get("size_g"), "wb": o.get("base"),
                "c": o.get("content"), "cb": o.get("cunit"), "cond": bool(o.get("cond")), "src": o}

    @staticmethod
    def _infer(items: list[dict]) -> None:
        """개수만 있는 글에 같은 상품의 유일한 개당 용량을 채워 총량 추정 (신라면 5개 → 120g×5)."""
        sizes = {(round(x["uw"], 1), x["wb"]) for x in items if x["n"] and x["uw"]}
        if len(sizes) != 1:
            return
        (uw, wb), = sizes
        for x in items:
            if x["n"] and not x["uw"] and not x["w"]:
                x["uw"], x["wb"], x["w"], x["inferred"] = uw, wb, round(uw * x["n"]), True

    @staticmethod
    def _compat(mode: str, a: dict, b: dict) -> bool:
        if mode == "n":
            if not (a["n"] and b["n"]) or ((a["label"] in _BOXY) != (b["label"] in _BOXY)):
                return False
            if (a["uw"] is None) != (b["uw"] is None):
                return False
            if a["uw"] is not None and (a["wb"] != b["wb"] or abs(a["uw"] - b["uw"]) > 0.02 * max(a["uw"], b["uw"])):
                return False
            ca = a["c"] / a["n"] if a["c"] else None
            cb_ = b["c"] / b["n"] if b["c"] else None
            return ca is None or cb_ is None or abs(ca - cb_) < 0.5
        if mode == "w":
            return bool(a["w"] and b["w"] and a["wb"] == b["wb"])
        if mode == "c":
            return bool(a["c"] and b["c"] and a["cb"] == b["cb"])
        return not (a["n"] or a["w"] or a["c"] or b["n"] or b["w"] or b["c"])

    @staticmethod
    def _val(mode: str, x: dict) -> Optional[float]:
        p = x["price"]
        if p is None:
            return None
        if mode == "n":
            return p / x["n"] if x["n"] else None
        if mode == "w":
            return p * 100 / x["w"] if x["w"] else None
        if mode == "c":
            return p / x["c"] if x["c"] else None
        return float(p)

    @staticmethod
    def _tier(mode: str, x: dict):
        if mode == "n":
            return (x["n"], x["uw"] or 0)
        if mode == "w":
            return (x["w"] or 0, 0)
        if mode == "c":
            return (x["c"] or 0, 0)
        return (0, 0)

    @staticmethod
    def _clusters(items: list[dict]) -> int:
        """같은 가격·3일 이내 글은 1건으로 센 표본 수."""
        by_price: dict = {}
        for x in items:
            by_price.setdefault(x["price"], []).append(x["dt"])
        n = 0
        for dts in by_price.values():
            known = sorted(d for d in dts if d is not None)
            n += sum(1 for d in dts if d is None)
            last = None
            for d in known:
                if last is None or d - last > timedelta(days=REPOST_DAYS):
                    n += 1
                    last = d
        return n

    @staticmethod
    def _valid(mode: str, items: list[dict]) -> list[dict]:
        vals = [x["v"] for x in items]
        if len(vals) < 4:
            return items
        med = statistics.median(vals)
        return [x for x in items if x["v"] >= med * OUTLIER_RATIO]

    @staticmethod
    def _public(mode: str, x: dict) -> dict:
        o = x["src"]
        v = x.get("v")
        return {"price": o["price"], "count": x["c"] if mode == "c" else x["n"],
                "size_g": round(x["w"]) if x["w"] else None,
                "unit_price": round(v) if (v is not None and mode != "total") else None,
                "title": o.get("title"), "url": x["url"], "source": o.get("source"), "date": o.get("date"),
                "ended": bool(o.get("ended")), "cond": bool(o.get("cond"))}

    def product_for_group(self, g: dict) -> Optional[dict]:
        """화면용 group.product. 비교 불가능한 딜이면 None."""
        currency = _cur(g.get("currency"))
        space = self._group_space(g)
        if space is None:
            return None
        info = parse_product(g.get("title") or "")
        if info is None:
            return None
        cur_price = g.get("price")
        pid = self._find(info, space)
        if cur_price is None and pid is None:
            return None  # 가격도 기록도 없으면 보여줄 게 없음 (앱 무료 등)
        mine = {s.get("url") for s in g.get("sources", [])} | {g.get("url")}
        cur = self._norm({"price": cur_price, **_obs_fields(info, cur_price or 0)})
        cur_dt = _dt(g.get("posted_at") or g.get("first_seen")) or now_kst()
        past: list[dict] = []
        if pid:
            for u, o in self.products[pid]["obs"].items():
                if u in mine or o.get("price") is None:
                    continue
                x = self._norm(o)
                x["url"], x["dt"] = u, _dt(o.get("date"))
                # 현재 딜과 같은 가격·3일 이내 = 같은 딜의 교차 게시 → 기록 아님
                if cur_price is not None and o["price"] == cur_price and x["dt"] is not None \
                        and abs(x["dt"] - cur_dt) <= timedelta(days=REPOST_DAYS):
                    continue
                past.append(x)
        self._infer(past + [cur])

        # 비교 기준 고르기
        cur_modes = [m for m in _ORDER if (m == "n" and cur["n"]) or (m == "w" and cur["w"])
                     or (m == "c" and cur["c"]) or (m == "total" and not (cur["n"] or cur["w"] or cur["c"]))]
        # 우선순위(_ORDER: 개당 → 캡슐당 → 100g당 → 총액) 중 판정에 충분한 표본이 있는 첫 기준을 쓴다.
        # (표본 수만 보고 고르면 '500ml×20' 이 '1.5L×12' 와 100ml당으로 비교되는 오판정이 생김)
        # 현재 딜이 조건부(카드·멤버십 가격)면 조건부 기록끼리, 아니면 일반가 기록끼리 비교
        use_cond = bool(info.cond)
        best_mode, best_items, best_score = cur_modes[0] if cur_modes else "total", [], (-1, -1)
        chosen = None
        for m in cur_modes:
            items = []
            for x in past:
                if self._compat(m, cur, x):
                    v = self._val(m, x)
                    if v is not None:
                        items.append({**x, "v": v})
            items = self._valid(m, items)
            pool = [x for x in items if x["cond"] == use_cond]
            score = (self._clusters(pool), len(items))
            if chosen is None and score[0] >= MIN_SAMPLES:
                chosen = (m, items)
            if score > best_score:
                best_mode, best_items, best_score = m, items, score
        mode, items = chosen or (best_mode, best_items)
        cur_val = self._val(mode, cur) if cur_price is not None else None

        unit = {"n": "개", "c": "개", "w": "100ml" if cur["wb"] == "ml" else "100g", "total": None}[mode]
        label = cur["label"] if mode == "n" else (info.content_unit or "개") if mode == "c" else "개"
        out = {"key": info.key, "pid": pid if pid in self.products else None,   # 상품 페이지 id (기록에 있을 때만)
               "name": info.name, "size": info.size, "size_g": info.size_g,
               "count": info.content if mode == "c" else info.count, "unit": unit, "unit_label": label,
               "unit_price": round(cur_val) if (cur_val is not None and mode != "total") else None,
               "cond": info.cond, "currency": currency, "verdict": None, "diff_pct": None, "history": None}
        if not items:
            out["verdict"] = "first" if cur_val is not None else None
            return out

        plain = [x for x in items if not x["cond"]]
        conds = [x for x in items if x["cond"]]
        key = lambda x: (x["v"], x["src"].get("date") or "")  # noqa: E731
        low = min(plain, key=key) if plain else None
        low_c = min(conds, key=key) if conds else None
        cur_tier = self._tier(mode, cur)
        same = [x for x in plain if self._tier(mode, x) == cur_tier]
        tiers: dict = {}
        for x in items:
            k = (self._tier(mode, x), x["cond"])
            if k not in tiers or x["v"] < tiers[k]["v"]:
                tiers[k] = x
        tier_list = []
        for (t, c), x in sorted(tiers.items(), key=lambda kv: (kv[0][0], kv[0][1])):
            if c:
                normal = tiers.get((t, False))
                if normal is not None and x["v"] >= normal["v"]:
                    continue    # 조건부인데 일반가보다 싸지 않으면 표시할 필요 없음
            tier_list.append(x)
        dates = [x["src"].get("date") for x in items if x["src"].get("date")]
        samples, cond_samples = self._clusters(plain), self._clusters(conds)
        out["history"] = {
            "samples": samples,                 # 일반가 표본 수
            "cond_samples": cond_samples,       # 조건부 표본 수
            "basis": "cond" if use_cond else "plain",   # 판정에 쓴 기록: 조건부끼리 / 일반가끼리
            "mode": mode,                       # 비교 기준 n(개당)·c(캡슐당 등)·w(100g당)·total(총액)
            "since": min(dates)[:10] if dates else None,
            "low_unit": self._public(mode, low) if low else None,
            "low_same_count": self._public(mode, min(same, key=lambda x: (x["price"], x["src"].get("date") or "")))
            if same else None,
            # 조건부 최저: 일반가보다 쌀 때만. 단 현재 딜이 조건부면 판정 대상이라 항상
            "low_cond": self._public(mode, low_c)
            if (low_c and (use_cond or low is None or low_c["v"] < low["v"])) else None,
            "tiers": [self._public(mode, x) for x in tier_list[:MAX_TIERS]],
        }
        ref, pool, n_pool = (low_c, conds, cond_samples) if use_cond else (low, plain, samples)
        if cur_val is None or ref is None or not ref["v"]:
            out["verdict"] = "first" if cur_val is not None else None
            return out
        vals = [x["v"] for x in pool] + [cur_val]
        if n_pool < MIN_SAMPLES or (n_pool <= 3 and max(vals) > SMALL_SPREAD * min(vals)):
            out["verdict"] = "first"    # 기록 부족 (또는 표본이 적은데 값이 너무 벌어짐)
            return out
        low_val = ref["v"]
        if round(cur_val) < round(low_val):
            out["verdict"] = "lowest"
            # C-2-3: 표본이 적은데 '거의 같은 총액으로 훨씬 많은 양' (단가 급락) → 수량 해석 오류 신호, 판정 보류
            ratio = cur_price / ref["price"] if ref.get("price") else None
            drop = 1 - cur_val / low_val
            if mode != "total" and n_pool <= SUSPECT_MAX_SAMPLES and drop > SUSPECT_DROP and ratio is not None \
                    and SUSPECT_PRICE_BAND[0] <= ratio <= SUSPECT_PRICE_BAND[1]:
                out["verdict"] = "first"
                out["history"]["suspect"] = {"drop_pct": round(drop * 100, 1), "price_ratio": round(ratio, 2)}
        elif round(cur_val) == round(low_val):
            out["verdict"] = "equal"
        else:
            diff = (cur_val / low_val - 1) * 100
            out["diff_pct"] = round(diff, 1)
            out["verdict"] = "near" if diff <= NEAR_PCT else "higher"
        return out

    def annotate(self, groups: list[dict]) -> int:
        n = 0
        for g in groups:
            g["product"] = self.product_for_group(g)
            if g["product"] and g["product"].get("history"):
                n += 1
        return n

    # ---------- 정리 ----------
    def prune(self) -> None:
        cutoff = (now_kst() - timedelta(days=KEEP_DAYS)).isoformat()
        for pid in list(self.products):
            p = self.products[pid]
            obs = p["obs"]
            if not obs or max((o.get("date") or "") for o in obs.values()) < cutoff:
                del self.products[pid]
                continue
            keep = set(sorted(obs, key=lambda u: obs[u].get("date") or "", reverse=True)[:KEEP_RECENT])
            # 수량·용량별(조건부 따로) 최저가 기록은 오래돼도 보관
            best_tier: dict = {}
            for u, o in obs.items():
                t = (o.get("count"), o.get("usize"), o.get("size_g"), o.get("content"), bool(o.get("cond")))
                v = o.get("unit_price") if o.get("unit_price") is not None else o.get("price")
                if v is None:
                    continue
                if t not in best_tier or v < best_tier[t][1]:
                    best_tier[t] = (u, v)
            keep |= {u for u, _ in best_tier.values()}
            if len(obs) > len(keep):
                p["obs"] = {u: o for u, o in obs.items() if u in keep}
        self.skipped = {u: o for u, o in self.skipped.items() if (o.get("date") or "") >= cutoff}
        self._reindex()
