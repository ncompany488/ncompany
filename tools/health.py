"""수집 고장 감지: 수집이 끝난 뒤 site/data/status.json 을 읽어 소스별 연속 실패·0개 횟수를
data/health.json 에 누적하고, 기준을 넘으면 GitHub 이슈를 열고 회복되면 닫는다.

사용: python tools/health.py                 (collect.py 다음에 실행)
      python tools/health.py --check-failed  (tools/check.py 가 실패했을 때 이슈만 연다)

- GITHUB_TOKEN·GITHUB_REPOSITORY 가 없으면(내 PC) 기록만 하고 이슈는 건드리지 않는다.
- 이 스크립트는 어떤 경우에도 0 으로 끝난다 (모니터링 때문에 데이터 저장·배포가 막히면 안 됨).
- 차단(blocked)은 robots.txt 금지(RobotsDisallowed)만 뜻한다. 서버 HTTP 403 등은 진짜 고장 신호라 실패로 센다.
- collect.py 자체가 실패해 status.json 이 없거나 20분 넘게 오래됐으면 "collect.py 실행 실패" 이슈를 연다.
- 워크플로가 RESTORE_OUTCOME / COLLECT_OUTCOME (steps.*.outcome) 을 넘기면 원인을 정확히 구분한다:
  가져오기 실패 → "이전 데이터 가져오기 실패", 수집 실패 → "collect.py 실행 실패" (status.json 이 최신이면 "알림 단계 등").
  값이 없으면(내 PC 등) status.json 이 없거나 오래됐는지로만 판단한다.
- 토큰은 절대 출력하지 않는다 (에러 메시지에는 HTTP 상태 코드만).
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATUS = ROOT / "site" / "data" / "status.json"
HEALTH = ROOT / "data" / "health.json"
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

FAIL_THRESHOLD = 8   # 연속 실패 8회(15분 간격 ≈ 2시간) → 이슈
ZERO_THRESHOLD = 8   # 연속 0개 8회 → 이슈
LABEL = "source-broken"
TITLE_PREFIX = "[수집 고장]"
TOTAL_KEY = "_total"          # 전체 딜 0개
CHECK_KEY = "_check"          # tools/check.py 실패
COLLECT_KEY = "_collect"      # collect.py 실행 실패 (status.json 없음/오래됨)
TOTAL_ZERO_THRESHOLD = 2      # 전체 0개가 2회 연속일 때만 이슈 (한 번 삐끗한 실행은 무시)
RESTORE_KEY = "_restore"      # 이전 누적 데이터 가져오기 단계 실패
STALE_MINUTES = 20            # status.json 의 run_at 이 이보다 오래되면 이번 실행 결과가 아님
API = "https://api.github.com"


def marker(key: str) -> str:
    return f"<!-- hotdeal-health:{key} -->"


# ---------------- 연속 횟수 계산 (네트워크 없음) ----------------

def update_streaks(health: dict, status: dict) -> dict:
    """status.json 한 번 분량을 health 에 반영. 돌려주는 값: {key: 'broken'|'ok'|'neutral'}
    broken = 이슈가 있어야 함, ok = 이슈가 있으면 닫아야 함, neutral = 건드리지 않음(차단 등)."""
    src = health.setdefault("sources", {})
    verdict: dict[str, str] = {}
    total = 0
    for key, s in (status.get("sources") or {}).items():
        h = src.setdefault(key, {"fail_streak": 0, "zero_streak": 0})
        ok = bool(s.get("ok"))
        count = int(s.get("count") or 0)
        total += count
        if s.get("blocked"):
            # 차단(robots.txt 금지 = RobotsDisallowed)만 고장이 아님. 서버 403 은 blocked 가 아니라 실패로 센다 → 횟수 초기화, 이슈 판단 보류
            h["fail_streak"] = 0
            h["zero_streak"] = 0
            h["state"] = "blocked"
            verdict[key] = "neutral"
            continue
        if not ok:
            h["fail_streak"] = h.get("fail_streak", 0) + 1
            h["last_error"] = (s.get("error") or "")[:300]
            h["state"] = "error"
        else:
            h["fail_streak"] = 0
            if count == 0:
                h["zero_streak"] = h.get("zero_streak", 0) + 1
                h["state"] = "zero"
            else:
                h["zero_streak"] = 0
                h["state"] = "ok"
        if h["fail_streak"] >= FAIL_THRESHOLD or h["zero_streak"] >= ZERO_THRESHOLD:
            verdict[key] = "broken"
        elif h["state"] == "ok":
            verdict[key] = "ok"
        else:
            verdict[key] = "neutral"  # 아직 기준 미달 (열려 있던 이슈도 그대로 둠)
    # 이번 실행에 없는 소스(꺼졌거나 삭제됨) → 기록 정리, 열린 이슈는 닫음
    for key in list(src):
        if key not in (status.get("sources") or {}):
            del src[key]
            verdict[key] = "ok"
    if total == 0:
        health["total_zero_streak"] = health.get("total_zero_streak", 0) + 1
        # 1회째는 판단 보류(열려 있던 이슈도 그대로), 연속 2회째부터 이슈
        verdict[TOTAL_KEY] = "broken" if health["total_zero_streak"] >= TOTAL_ZERO_THRESHOLD else "neutral"
    else:
        health["total_zero_streak"] = 0
        verdict[TOTAL_KEY] = "ok"
    health["total_count"] = total
    health["run_at"] = status.get("run_at")
    return verdict


def describe(key: str, health: dict) -> tuple[str, str]:
    if key == TOTAL_KEY:
        return (f"{TITLE_PREFIX} 전체 딜 0개",
                "이번 수집에서 모든 소스를 합쳐 딜이 0개였습니다. 네트워크·공통 코드(collect.py, http.py) 문제일 수 있습니다.")
    if key == RESTORE_KEY:
        return (f"{TITLE_PREFIX} 이전 데이터 가져오기 실패",
                "data 브랜치의 이전 누적 데이터를 가져오는 단계가 실패해서 이번 실행은 수집·저장·배포를 하지 않았습니다. "
                "누적 기록 보호를 위해 일부러 멈춘 것이며 이전 사이트와 data 브랜치는 그대로입니다. 실행 기록의 해당 단계 로그를 확인하세요.")
    if key == COLLECT_KEY and health.get("collect_detail") == "fresh":
        return (f"{TITLE_PREFIX} collect.py 실행 실패 (알림 단계 등)",
                "collect.py 가 비정상 종료했지만 status.json 은 이번 실행 것이 남아 있습니다. 수집 이후 단계(텔레그램 알림 등)에서 "
                "오류가 났을 수 있습니다. 이번 실행은 data 브랜치 저장·배포를 하지 않았습니다. 실행 기록의 수집 단계 로그를 확인하세요.")
    if key == COLLECT_KEY:
        return (f"{TITLE_PREFIX} collect.py 실행 실패",
                "수집 단계(collect.py)가 실패했거나 결과(status.json)를 남기지 못했습니다. "
                "이번 실행은 data 브랜치 저장·배포를 하지 않았고 이전 사이트와 데이터는 그대로입니다. 실행 기록의 수집 단계 로그를 확인하세요.")
    if key == CHECK_KEY:
        return (f"{TITLE_PREFIX} 배포 전 점검(tools/check.py) 실패",
                "배포 전 점검이 실패해서 이번 실행은 수집·배포를 하지 않았습니다. "
                "이전 사이트와 data 브랜치는 그대로 유지됩니다. 고친 코드를 푸시하면 다음 실행에서 자동으로 다시 시도합니다.")
    h = health.get("sources", {}).get(key, {})
    if h.get("fail_streak", 0) >= FAIL_THRESHOLD:
        why = f"{h['fail_streak']}회 연속 수집 실패 (약 {h['fail_streak'] * 15}분)\n\n마지막 오류:\n```\n{h.get('last_error', '')}\n```"
    else:
        why = f"{h.get('zero_streak', 0)}회 연속으로 0개 수집 (사이트 구조가 바뀌었을 수 있음)"
    return (f"{TITLE_PREFIX} {key}",
            f"`{key}` 수집기가 고장난 것 같습니다: {why}\n\n"
            f"확인: `python tools/try_source.py {key}` · 수집기 파일 `hotdeal/sources/{key}.py`")


# ---------------- GitHub 이슈 ----------------

class GitHub:
    def __init__(self, token: str, repo: str, session=None):
        self._token = token
        self.repo = repo
        if session is None:
            import requests
            session = requests.Session()
        self.s = session

    def call(self, method: str, path: str, body: dict | None = None):
        r = self.s.request(method, f"{API}/repos/{self.repo}{path}", json=body, timeout=20,
                           headers={"Authorization": f"Bearer {self._token}",
                                    "Accept": "application/vnd.github+json",
                                    "X-GitHub-Api-Version": "2022-11-28"})
        if r.status_code >= 300:
            raise RuntimeError(f"GitHub API {method} {path} → HTTP {r.status_code}")  # 토큰은 안 넣음
        return r.json() if r.content else None

    def open_issues(self) -> dict[str, dict]:
        """우리가 연 이슈를 key 별로. 본문 표식으로 찾고, 라벨이 빠졌어도 찾을 수 있게 전체 열린 이슈를 훑음."""
        found: dict[str, dict] = {}
        for page in range(1, 6):
            items = self.call("GET", f"/issues?state=open&per_page=100&page={page}") or []
            for it in items:
                if "pull_request" in it:
                    continue
                body = it.get("body") or ""
                if "<!-- hotdeal-health:" in body:
                    key = body.split("<!-- hotdeal-health:", 1)[1].split(" -->", 1)[0]
                    found.setdefault(key, it)
            if len(items) < 100:
                break
        return found


def run_link() -> str:
    server, repo, rid = (os.environ.get(k, "") for k in ("GITHUB_SERVER_URL", "GITHUB_REPOSITORY", "GITHUB_RUN_ID"))
    return f"\n\n실행 기록: {server}/{repo}/actions/runs/{rid}" if server and repo and rid else ""


def sync_issues(gh: GitHub, verdict: dict[str, str], health: dict) -> None:
    existing = gh.open_issues()
    for key, v in sorted(verdict.items()):
        issue = existing.get(key)
        try:
            if v == "broken" and issue is None:
                title, body = describe(key, health)
                it = gh.call("POST", "/issues", {"title": title, "labels": [LABEL],
                                                 "body": f"{body}{run_link()}\n\n{marker(key)}\n"
                                                         "_회복되면 자동으로 닫힙니다._"})
                print(f"[health] 이슈 열림: #{it.get('number')} {title}")
            elif v == "ok" and issue is not None:
                n = issue["number"]
                gh.call("POST", f"/issues/{n}/comments", {"body": f"회복됨: 이번 실행에서 정상 수집됐습니다.{run_link()}"})
                gh.call("PATCH", f"/issues/{n}", {"state": "closed", "state_reason": "completed"})
                print(f"[health] 이슈 닫음: #{n} ({key})")
        except Exception as e:  # 하나 실패해도 나머지는 계속
            print(f"[health] 이슈 처리 실패 ({key}): {e}")


# ---------------- 실행 ----------------

def status_is_stale(status, now: datetime | None = None) -> bool:
    """status.json 이 없거나(깨짐 포함) run_at 이 STALE_MINUTES 보다 오래됐으면 True.
    run_at 을 해석할 수 없으면(예전 형식) 오래됐다고 단정하지 않는다."""
    if not isinstance(status, dict) or not isinstance(status.get("sources"), dict):
        return True
    try:
        t = datetime.fromisoformat(str(status.get("run_at")))
    except ValueError:
        return False
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (now or datetime.now(timezone.utc)) - t > timedelta(minutes=STALE_MINUTES)


def load_json(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


def make_github(session=None) -> GitHub | None:
    token, repo = os.environ.get("GITHUB_TOKEN", ""), os.environ.get("GITHUB_REPOSITORY", "")
    if not token or not repo:
        print("[health] GITHUB_TOKEN/GITHUB_REPOSITORY 없음 → 기록만 하고 이슈는 건너뜀")
        return None
    return GitHub(token, repo, session)


def main(argv: list[str], session=None) -> int:
    if "--check-failed" in argv:
        gh = make_github(session)
        if gh:
            try:
                sync_issues(gh, {CHECK_KEY: "broken"}, {})
            except Exception as e:
                print(f"[health] 이슈 확인 실패: {e}")
        return 0

    restore = os.environ.get("RESTORE_OUTCOME", "")
    collect = os.environ.get("COLLECT_OUTCOME", "")
    status = load_json(STATUS, None)
    if restore == "failure" or status_is_stale(status):
        if restore == "failure":
            print("[health] 이전 데이터 가져오기 단계 실패 → 수집은 실행되지 않음")
            v = {RESTORE_KEY: "broken", COLLECT_KEY: "ok"}
        else:
            print(f"[health] {STATUS.name} 가 없거나 {STALE_MINUTES}분 넘게 오래됨 → collect.py 실행 실패로 간주")
            v = {COLLECT_KEY: "broken", RESTORE_KEY: "ok"}
        gh = make_github(session)
        if gh:
            try:
                sync_issues(gh, v, {})
            except Exception as e:
                print(f"[health] 이슈 확인 실패: {e}")
        return 0
    health = load_json(HEALTH, {})
    if not isinstance(health, dict):
        health = {}
    verdict = update_streaks(health, status)
    verdict[RESTORE_KEY] = "ok"
    if collect == "failure":  # 최신 status.json 은 있지만 collect.py 가 비정상 종료 (알림 단계 등)
        health["collect_detail"] = "fresh"
        verdict[COLLECT_KEY] = "broken"
    else:
        health.pop("collect_detail", None)
        verdict[COLLECT_KEY] = "ok"  # 최신 status.json 이 있으니 collect.py 는 돌았음
    verdict[CHECK_KEY] = "ok"  # 여기까지 왔으면 배포 전 점검은 통과한 것
    health["updated_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    try:
        HEALTH.parent.mkdir(parents=True, exist_ok=True)
        HEALTH.write_text(json.dumps(health, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as e:
        print(f"[health] health.json 저장 실패: {e}")
    for key, h in sorted(health.get("sources", {}).items()):
        print(f"  {key:16} {h.get('state', '?'):7} 연속실패 {h.get('fail_streak', 0)} 연속0개 {h.get('zero_streak', 0)}")
    print(f"  전체 {health.get('total_count')}개")

    gh = make_github(session)
    if gh:
        try:
            sync_issues(gh, verdict, health)
        except Exception as e:
            print(f"[health] 이슈 확인 실패: {e}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except SystemExit:
        raise
    except Exception as e:  # 모니터링 오류로 배포가 막히면 안 됨
        print(f"[health] 예기치 못한 오류: {type(e).__name__}: {e}")
        raise SystemExit(0)
