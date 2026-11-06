"""수집기 하나를 실제로 돌려보고 결과를 검사한다.

사용: .venv/Scripts/python tools/try_source.py ppomppu [출력개수]
"""
from __future__ import annotations

import importlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from hotdeal.models import Deal  # noqa: E402


def check(deals: list[Deal]) -> list[str]:
    problems = []
    if not deals:
        problems.append("딜이 0개")
    for d in deals:
        if not d.title:
            problems.append(f"빈 제목: {d.url}")
        if not d.url.startswith("http"):
            problems.append(f"상대 URL: {d.url}")
        if d.title != d.title.strip() or not d.title.strip():
            problems.append(f"제목 공백: {d.url}")
        # 게시 시각이 미래면 타임존 처리가 틀린 것
        if d.posted_at:
            dt = datetime.fromisoformat(d.posted_at)
            if dt.tzinfo is None:
                problems.append(f"타임존 없는 posted_at: {d.posted_at}")
            elif dt > datetime.now(timezone.utc) + timedelta(minutes=10):
                problems.append(f"미래 시각 posted_at: {d.posted_at} {d.url}")
    if deals:
        n = len(deals)
        for f in ("posted_at", "price", "shop"):
            filled = sum(1 for d in deals if getattr(d, f) is not None)
            if filled / n < 0.5:
                problems.append(f"{f} 채움률 낮음 {filled}/{n}")
        if len({d.url for d in deals}) != n:
            problems.append("URL 중복 있음")
    return problems


def main() -> None:
    key = sys.argv[1]
    mod = importlib.import_module(f"hotdeal.sources.{key}")
    deals = mod.fetch()
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 5
    for d in deals[:n]:
        print(json.dumps(d.to_dict(), ensure_ascii=False))
    print(f"--- {len(deals)}개")
    probs = check(deals)
    print("문제:", probs or "없음")


if __name__ == "__main__":
    main()
