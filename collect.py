"""전체 수집 실행: 모든 소스 수집 → 저장소 병합 → 중복 그룹화 → 사이트 데이터 → 텔레그램 알림.

사용: .venv/Scripts/python collect.py            (전체)
      .venv/Scripts/python collect.py --no-alerts
"""
from __future__ import annotations

import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from hotdeal import alerts, dedup, store
from hotdeal.parse import KST, now_kst
from hotdeal.sources import load_all

sys.stdout.reconfigure(encoding="utf-8")
ALERT_MAX_AGE_H = 6  # 이보다 오래된 글은 '새 딜'이어도 알림 안 보냄


def fetch_one(mod):
    t0 = time.time()
    try:
        deals = mod.fetch()
        return mod, [d.to_dict() for d in deals], None, time.time() - t0
    except Exception as e:
        traceback.print_exc()
        return mod, [], f"{type(e).__name__}: {e}"[:300], time.time() - t0


def main() -> None:
    mods = load_all()
    print(f"소스 {len(mods)}개: {', '.join(m.SOURCE.key for m in mods)}")
    st = store.load_store()
    first_run = not st.get("deals")
    status = {"run_at": now_kst().replace(microsecond=0).isoformat(), "sources": {}}
    fresh: list[dict] = []
    # 서로 다른 사이트는 병렬로 (같은 사이트 간격은 http.get 이 지킴)
    with ThreadPoolExecutor(max_workers=6) as ex:
        for mod, deals, err, sec in ex.map(fetch_one, mods):
            key = mod.SOURCE.key
            status["sources"][key] = {"ok": err is None, "count": len(deals),
                                      "error": err, "seconds": round(sec, 1)}
            print(f"  {key:16} {'OK ' if err is None else 'ERR'} {len(deals):3}개 {sec:5.1f}s {err or ''}")
            fresh.extend(deals)

    new_ids = set(store.merge(st, fresh))
    store.prune(st)
    groups = dedup.group_deals(list(st["deals"].values()), st.get("deal_group"))
    st["deal_group"] = {s["id"]: g["gid"] for g in groups for s in g["sources"]}
    store.save_store(st)

    meta = [{"key": m.SOURCE.key, "name": m.SOURCE.name, "homepage": m.SOURCE.homepage,
             "region": m.SOURCE.region, "kind": m.SOURCE.kind} for m in mods]
    store.write_site(groups, status, meta)
    merged = sum(1 for g in groups if len(g["sources"]) > 1)
    print(f"딜 {len(st['deals'])}개 → 그룹 {len(groups)}개 (여러 곳 공유 {merged}개), 신규 {len(new_ids)}개")

    if "--no-alerts" in sys.argv:
        return
    if first_run:
        print("[alerts] 첫 실행 → 기존 딜은 알림 없이 기록만")
    cutoff = now_kst() - timedelta(hours=ALERT_MAX_AGE_H)

    def fresh_enough(g) -> bool:
        # 작성 시각을 모르면 처음 본 시각 기준 (둘 다 없으면 새 글로 봄). 문자열 말고 시각으로 비교
        t = store.parse_iso(g.get("posted_at") or g.get("first_seen"))
        if t is not None and t.tzinfo is None:
            t = t.replace(tzinfo=KST)
        return t is None or t >= cutoff

    new_groups = [] if first_run else [
        g for g in groups
        if any(s["id"] in new_ids for s in g["sources"]) and fresh_enough(g)
    ]
    try:  # 알림이 실패해도 수집 결과 저장·배포는 계속되도록
        alerts.run(new_groups, {m["key"]: m["name"] for m in meta})
    except Exception:
        traceback.print_exc()


if __name__ == "__main__":
    main()
