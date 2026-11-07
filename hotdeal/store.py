"""수집 결과 누적 저장소 (JSON 파일).

data/store.json : 최근 N시간의 개별 딜 (다음 실행 때 이어서 사용)
site/data/deals.json : 화면용 그룹 목록
site/data/status.json : 소스별 마지막 수집 상태
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from .parse import KST, now_kst

ROOT = Path(__file__).resolve().parent.parent
STORE_PATH = ROOT / "data" / "store.json"
SITE_DATA = ROOT / "site" / "data"
KEEP_HOURS = 72
MAX_DEALS = 3000


def _read(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _write(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


def load_store() -> dict:
    return _read(STORE_PATH, {"deals": {}, "deal_group": {}})


def to_kst(s: str | None) -> str | None:
    """ISO 시각을 KST(+09:00) 문자열로 통일 (문자열 비교·정렬이 맞도록). 시간대 없으면 KST 로 간주."""
    dt = parse_iso(s)
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=KST)
    return dt.astimezone(KST).replace(microsecond=0).isoformat()


def merge(store: dict, fresh: list[dict]) -> list[str]:
    """새로 받은 딜을 저장소에 합치고, 처음 보는 딜 id 목록을 돌려준다."""
    now = now_kst().replace(microsecond=0).isoformat()
    deals: dict = store.setdefault("deals", {})
    for d in deals.values():  # 예전에 저장된 UTC 등도 한 번에 정리
        d["posted_at"] = to_kst(d.get("posted_at"))
    new_ids = []
    for d in fresh:
        d["posted_at"] = to_kst(d.get("posted_at"))
        old = deals.get(d["id"])
        if old is None:
            d["first_seen"] = now
            new_ids.append(d["id"])
        else:
            d["first_seen"] = old.get("first_seen", now)
            # 원본에서 값이 빠져도 예전 값 유지
            for k, v in old.items():
                if d.get(k) is None and v is not None:
                    d[k] = v
        # 날짜만 있는 게시판(딜바다·어미새 등)은 0시로 들어와 정렬이 밀림 → 처음 본 날과 같으면 처음 본 시각으로
        pa = d.get("posted_at") or ""
        if pa.endswith("T00:00:00+09:00") and pa[:10] == (d.get("first_seen") or "")[:10]:
            d["posted_at"] = d["first_seen"]
        d["last_seen"] = now
        deals[d["id"]] = d
    return new_ids


def prune(store: dict) -> None:
    # last_seen·first_seen 은 이 모듈이 항상 같은 KST 형식으로 쓰므로 문자열 비교로 충분
    cutoff = (now_kst() - timedelta(hours=KEEP_HOURS)).isoformat()
    deals = store["deals"]
    for k in [k for k, d in deals.items() if (d.get("last_seen") or "") < cutoff]:
        del deals[k]
    if len(deals) > MAX_DEALS:
        for k, _ in sorted(deals.items(), key=lambda kv: kv[1].get("first_seen") or "")[: len(deals) - MAX_DEALS]:
            del deals[k]
    live = set(deals)
    store["deal_group"] = {k: v for k, v in store.get("deal_group", {}).items() if k in live}


def save_store(store: dict) -> None:
    _write(STORE_PATH, store)


def write_site(groups: list[dict], status: dict, sources_meta: list[dict]) -> None:
    def key(g):  # 시간대가 섞여도 맞게 실제 시각으로 정렬
        t = parse_iso(to_kst(g.get("posted_at") or g.get("first_seen")))
        return t.timestamp() if t else 0.0
    groups = sorted(groups, key=key, reverse=True)
    _write(SITE_DATA / "deals.json", {
        "updated_at": now_kst().replace(microsecond=0).isoformat(),
        "sources": sources_meta,
        "groups": groups,
    })
    _write(SITE_DATA / "status.json", status)


def parse_iso(s: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(s) if s else None
    except ValueError:
        return None
