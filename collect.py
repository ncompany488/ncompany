"""전체 수집 실행: 모든 소스 수집 → 저장소 병합 → 중복 그룹화 → 사이트 데이터 → 텔레그램 알림.

사용: .venv/Scripts/python collect.py            (전체)
      .venv/Scripts/python collect.py --no-alerts
      .venv/Scripts/python collect.py --backfill 300 [--only ppomppu,ruliweb]   (과거 페이지로 가격 기록 채우기)
"""
from __future__ import annotations

import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from hotdeal import alerts, dedup, http, store
from hotdeal.history import History
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


def backfill(pages: int) -> None:
    """과거 목록 페이지를 훑어 가격 기록만 채운다 (화면 목록·알림에는 넣지 않음).
    사이트별로 동시에 돌리고, 같은 사이트 안의 간격은 http.get 이 지킨다."""
    import threading
    from hotdeal.history import KEEP_DAYS
    hist = History.load()
    lock = threading.Lock()
    keep_cutoff = (now_kst() - timedelta(days=KEEP_DAYS)).isoformat()

    def run(mod) -> str:
        n_pages = min(pages, getattr(mod, "MAX_BACKFILL_PAGES", pages))
        got = 0
        for page in range(1, n_pages + 1):
            deals = None
            for attempt in range(1, 5):
                try:
                    deals = [d.to_dict() for d in mod.fetch_page(page)]
                    break
                except Exception as e:
                    resp = getattr(e, "response", None)
                    if resp is not None and resp.status_code == 429 and attempt < 4:
                        # 속도 제한: 사이트가 알려준 시간(없으면 1분·2분·3분)만큼 쉬고 같은 페이지 재시도
                        ra = resp.headers.get("Retry-After", "")
                        wait = int(ra) if ra.isdigit() else 60 * attempt
                        print(f"  {mod.SOURCE.key} {page}페이지 429 → {wait}초 대기", flush=True)
                        time.sleep(wait)
                        continue
                    print(f"  {mod.SOURCE.key} {page}페이지에서 중단: {type(e).__name__}: {e}"[:200], flush=True)
                    break
            if deals is None:
                break
            if not deals:
                break
            with lock:
                got += hist.observe(deals)
            # 보관 기간(KEEP_DAYS)보다 오래된 페이지까지 왔으면 더 요청하지 않음 (어차피 정리돼 버려짐)
            newest = max((d.get("posted_at") or "" for d in deals), default="")
            if newest and newest < keep_cutoff:
                print(f"  {mod.SOURCE.key}: {page}페이지에서 보관 기간 이전 도달 → 중단", flush=True)
                break
                if page % 50 == 0:
                    hist.save()  # 중간 저장 (중단돼도 진행분 유지)
                    print(f"  {mod.SOURCE.key}: {page}/{n_pages}페이지, 기록 {got}건", flush=True)
        return f"{mod.SOURCE.key}: 기록 {got}건"

    only = None
    if "--only" in sys.argv:
        only = set(sys.argv[sys.argv.index("--only") + 1].split(","))
    mods = [m for m in load_all() if hasattr(m, "fetch_page") and (only is None or m.SOURCE.key in only)]
    http.MIN_INTERVAL = 3.0  # 백필은 대량 요청이라 평소(1.5초)보다 천천히
    with ThreadPoolExecutor(max_workers=len(mods) or 1) as ex:
        for line in ex.map(run, mods):
            print(" ", line, flush=True)
    hist.save()
    print(f"백필 끝: 상품 {len(hist.products)}개")


def main() -> None:
    if "--backfill" in sys.argv:
        i = sys.argv.index("--backfill")
        backfill(int(sys.argv[i + 1]) if len(sys.argv) > i + 1 else 100)
        return
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
                                      "error": err, "seconds": round(sec, 1),
                                      # robots.txt 금지·서버 차단은 고장이 아니라 '수집 불가'
                                      "blocked": bool(err and err.startswith("RobotsDisallowed"))}
            print(f"  {key:16} {'OK ' if err is None else 'ERR'} {len(deals):3}개 {sec:5.1f}s {err or ''}")
            fresh.extend(deals)

    new_ids = set(store.merge(st, fresh))
    store.prune(st)
    groups = dedup.group_deals(list(st["deals"].values()), st.get("deal_group"))
    st["deal_group"] = {s["id"]: g["gid"] for g in groups for s in g["sources"]}
    store.save_store(st)

    # 상품별 가격 기록 → 역대 최저가
    try:  # 가격 기록이 실패해도 목록 저장·배포는 계속
        hist = History.load()
        hist.observe(st["deals"].values())
        with_hist = hist.annotate(groups)
        hist.save()
        print(f"가격 기록: 상품 {len(hist.products)}개, 이번 목록 중 과거 기록 있는 딜 {with_hist}개")
    except Exception:
        traceback.print_exc()

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
