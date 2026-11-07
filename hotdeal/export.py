"""상품 페이지·과거 검색용 사이트 데이터 (docs/contract-product-pages.md).

  site/data/products/NN.json   NN = fnv1a32(pid UTF-8) % 64, 두 자리   { pid: Product }
  site/data/search.json        [ {id, n, cat, b, ul, lu, lp, ld, k}, ... ]  최근 기록 순, 최대 20,000

숫자는 history.py 의 비교 규칙(_norm·_infer·_compat·_val·_valid)을 그대로 써서 카드(group.product)와 맞춘다.
상품의 '그래프 기준'(basis)은 가장 최근 기록을 현재 딜로 보고 product_for_group 과 같은 방식으로 고른 비교 기준:
  우선순위 n(개당) → c(캡슐당 등) → w(100g·100ml당) → total(총액) 중 일반가 표본이 MIN_SAMPLES 이상인 첫 기준,
  없으면 (표본 수, 기록 수)가 가장 많은 기준.
  u  = 그 기준의 단가 (기준이 안 맞는 기록은 null). 총액 기준(basis null)이면 u = 총액.
  lu = 조건부가 아닌 기록 중 최저 u (history._valid 와 같은 이상치 제외 후). lp·ld = 그 기록의 총액·날짜.

사용 (collect.py):
    hist.annotate(groups); annotate_categories(groups); hist.save()
    export_site(hist, groups)          # 샤드 + 검색 인덱스, 기록에 없는 product.pid 는 null 로
"""
from __future__ import annotations

import json
import re
from datetime import timedelta
from pathlib import Path
from typing import Iterable, Optional

from .category import categorize, categorize_many
from .history import MIN_SAMPLES, REPOST_DAYS, History, _dt
from .store import ROOT

SITE_DATA = ROOT / "site" / "data"
N_SHARDS = 64
SEARCH_MAX = 20000
_ORDER = ("n", "c", "w", "total")
_SHARD_FILE = re.compile(r"^\d{2}\.json$")


def fnv1a32(data: bytes) -> int:
    h = 0x811C9DC5
    for b in data:
        h ^= b
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def shard_of(pid: str) -> str:
    return f"{fnv1a32(pid.encode('utf-8')) % N_SHARDS:02d}"


# ---------- 카테고리 ----------
def annotate_categories(groups: list[dict]) -> None:
    """g["category"] = 그룹 대표 제목 + 각 사이트 글(제목·게시판 분류)의 점수 합."""
    for g in groups:
        items = [(g.get("title") or "", None, g.get("shop"), None)]
        for s in g.get("sources", []):
            items.append((s.get("title") or "", s.get("category"), None, s.get("source")))
        g["category"] = categorize_many(items)


def _product_category(obs_newest_first: list[dict]) -> str:
    """가장 최근 기록 제목으로. '기타'면 그다음 기록 제목도 (최대 5개) 본다."""
    for o in obs_newest_first[:5]:
        c = categorize(o.get("title") or "", None, None, o.get("source"))
        if c != "기타":
            return c
    return "기타"


# ---------- 상품 하나 ----------
def _modes(x: dict) -> list[str]:
    return [m for m in _ORDER if (m == "n" and x["n"]) or (m == "w" and x["w"]) or (m == "c" and x["c"])
            or (m == "total" and not (x["n"] or x["w"] or x["c"]))]


def product_view(pid: str, p: dict) -> Optional[tuple[dict, dict]]:
    """(샤드용 Product, 검색 항목) 또는 가격 있는 기록이 없으면 None."""
    items = []
    for u, o in p.get("obs", {}).items():
        if o.get("price") is None:
            continue
        x = History._norm(o)
        x["url"], x["dt"] = u, _dt(o.get("date"))
        items.append(x)
    if not items:
        return None
    items.sort(key=lambda x: x["src"].get("date") or "")
    History._infer(items)
    ref = items[-1]   # 가장 최근 기록 = 현재 카드라고 보고 기준을 고름

    # product_for_group 과 같게: 현재 딜(ref) 자신과 그 교차 게시(같은 가격·3일 이내)는 빼고 과거 기록으로 표본 수를 셈
    past = [x for x in items[:-1]
            if not (x["price"] == ref["price"] and x["dt"] is not None and ref["dt"] is not None
                    and abs(x["dt"] - ref["dt"]) <= timedelta(days=REPOST_DAYS))]
    chosen, best, best_score = None, None, (-1, -1)
    for m in _modes(ref):
        comp = [{**x, "v": History._val(m, x)} for x in past if History._compat(m, ref, x)]
        comp = History._valid(m, [x for x in comp if x["v"] is not None])
        pool = [x for x in comp if x["cond"] == ref["cond"]]   # 현재가 조건부면 조건부끼리 (history.basis)
        score = (History._clusters(pool), len(comp))
        if chosen is None and score[0] >= MIN_SAMPLES:
            chosen = m
        if score > best_score:
            best, best_score = m, score
    mode = chosen or best or "total"

    basis = {"n": "개", "c": "개", "w": "100ml" if ref["wb"] == "ml" else "100g", "total": None}[mode]
    label = ref["label"] if mode == "n" else (ref["cb"] or "개") if mode == "c" else "개"

    obs_out, comp = [], []
    for x in items:
        o = x["src"]
        v = History._val(mode, x) if History._compat(mode, ref, x) else None
        if v is not None:
            comp.append({**x, "v": v})
        obs_out.append({
            "d": o.get("date"), "p": o["price"], "u": round(v) if v is not None else None,
            "n": x["n"], "g": round(x["w"]) if x["w"] else None,
            "t": o.get("title"), "url": x["url"], "s": o.get("source"),
            "c": 1 if x["cond"] else 0, "e": 1 if o.get("ended") else 0,
        })
    newest_first = [x["src"] for x in reversed(items)]
    cat = _product_category(newest_first)
    prod = {"name": p.get("name"), "cat": cat, "basis": basis, "unit_label": label, "obs": obs_out}
    if pid.startswith("usd:"):
        prod["cur"] = "USD"     # 계약 밖 추가 필드: 가격이 센트 단위 (p·u)

    low = None
    plain = [x for x in History._valid(mode, comp) if not x["cond"]]
    if plain:
        low = min(plain, key=lambda x: (x["v"], x["src"].get("date") or ""))
    entry = {"id": pid, "n": p.get("name"), "cat": cat, "b": basis, "ul": label,
             "lu": round(low["v"]) if low else None, "lp": low["price"] if low else None,
             "ld": ((low["src"].get("date") or "")[:10] or None) if low else None,
             "k": len(obs_out)}
    return prod, {"_last": ref["src"].get("date") or "", **entry}


def product_views(hist: History) -> dict[str, tuple[dict, dict]]:
    out = {}
    for pid, p in hist.products.items():
        v = product_view(pid, p)
        if v is not None:
            out[pid] = v
    return out


# ---------- 파일 쓰기 ----------
def _dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _write(path: Path, text: str) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    return len(text.encode("utf-8"))


def write_product_shards(hist: History, out_dir: Path = SITE_DATA / "products",
                         views: Optional[dict] = None) -> dict:
    """샤드 파일 쓰기 + 더 이상 안 만드는 NN.json 삭제. 반환: {"files", "products", "bytes", "largest"}."""
    views = product_views(hist) if views is None else views
    shards: dict[str, dict] = {}
    for pid, (prod, _) in views.items():
        shards.setdefault(shard_of(pid), {})[pid] = prod
    out_dir = Path(out_dir)
    total, largest = 0, ("", 0)
    for nn, data in sorted(shards.items()):
        b = _write(out_dir / f"{nn}.json", _dump(data))
        total += b
        if b > largest[1]:
            largest = (f"{nn}.json", b)
    if out_dir.exists():
        for f in out_dir.iterdir():
            if _SHARD_FILE.match(f.name) and f.stem not in shards:
                f.unlink()
    return {"files": len(shards), "products": len(views), "bytes": total, "largest": largest}


def write_search_index(hist: History, path: Path = SITE_DATA / "search.json",
                       views: Optional[dict] = None) -> dict:
    """가격 있는 상품만, 최근 기록 순, 최대 SEARCH_MAX. 반환: {"entries", "bytes"}."""
    views = product_views(hist) if views is None else views
    entries = sorted((e for _, e in views.values()), key=lambda e: e["_last"], reverse=True)[:SEARCH_MAX]
    out = [{k: v for k, v in e.items() if k != "_last"} for e in entries]
    return {"entries": len(out), "bytes": _write(Path(path), _dump(out))}


def export_site(hist: History, groups: Optional[Iterable[dict]] = None, data_dir: Path = SITE_DATA) -> dict:
    """샤드 + 검색 인덱스를 한 번 계산으로 쓰고, groups 의 product.pid 중 내보내지 않은 상품은 null 로."""
    data_dir = Path(data_dir)
    views = product_views(hist)
    for g in groups or ():
        pr = g.get("product")
        if pr and pr.get("pid") not in views:
            pr["pid"] = None
    return {"shards": write_product_shards(hist, data_dir / "products", views),
            "search": write_search_index(hist, data_dir / "search.json", views)}
