"""전체 점검: 모든 에이전트 작업의 '완료' 기준.

사용: .venv/Scripts/python tools/check.py          (오프라인: 문법·테스트)
      .venv/Scripts/python tools/check.py --live   (+ 켜진 수집기를 실제로 돌려 검사)
"""
from __future__ import annotations

import importlib
import py_compile
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")


def main() -> int:
    failed: list[str] = []

    # 1) 모든 파이썬 파일 문법 (3.12 에서도 돌아야 하므로 최소한 컴파일 확인)
    for f in sorted(ROOT.glob("**/*.py")):
        if ".venv" in f.parts:
            continue
        try:
            py_compile.compile(str(f), doraise=True)
        except py_compile.PyCompileError as e:
            failed.append(f"문법: {f.relative_to(ROOT)} — {e.msg.strip()[:200]}")

    # 2) 수집기 모듈 규약
    from hotdeal.sources import load_all
    mods = load_all()
    keys = [m.SOURCE.key for m in mods]
    if len(keys) != len(set(keys)):
        failed.append(f"수집기 key 중복: {keys}")
    print(f"켜진 수집기 {len(mods)}개: {', '.join(keys)}")

    # 3) 테스트 파일 각각 실행 (pytest 없이)
    for t in sorted((ROOT / "tests").glob("test_*.py")):
        r = subprocess.run([sys.executable, str(t)], cwd=ROOT, capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
        ok = r.returncode == 0
        print(f"  {'OK  ' if ok else 'FAIL'} {t.name}")
        if not ok:
            failed.append(f"테스트: {t.name}\n{(r.stdout + r.stderr)[-1500:]}")

    # 4) 실제 수집 (선택)
    if "--live" in sys.argv:
        sys.path.insert(0, str(ROOT / "tools"))
        from try_source import check
        for m in mods:
            try:
                deals = m.fetch()
                probs = [p for p in check(deals) if "채움률" not in p]
                print(f"  {'OK  ' if not probs else 'WARN'} {m.SOURCE.key}: {len(deals)}개 {probs[:3] or ''}")
                if not deals:
                    failed.append(f"수집 0개: {m.SOURCE.key}")
            except Exception as e:
                failed.append(f"수집 실패: {m.SOURCE.key} — {type(e).__name__}: {e}"[:300])

    print()
    if failed:
        print(f"❌ 실패 {len(failed)}건")
        for f in failed:
            print(" -", f)
        return 1
    print("✅ 전체 통과")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
