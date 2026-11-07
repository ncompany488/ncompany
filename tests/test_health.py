"""고장 감지 로직 점검 (네트워크 없이, 가짜 GitHub): python tests/test_health.py"""
import io
import json
import os
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
sys.stdout.reconfigure(encoding="utf-8")
import health  # noqa: E402

fails = 0


def check(cond, msg):
    global fails
    if not cond:
        fails += 1
        print("실패:", msg)


# ---------- 가짜 GitHub ----------
class Resp:
    def __init__(self, code, data):
        self.status_code = code
        self._data = data
        self.content = b"x" if data is not None else b""

    def json(self):
        return self._data


class FakeGitHub:
    def __init__(self):
        self.issues: dict[int, dict] = {}
        self.calls: list[tuple[str, str]] = []
        self.next = 1
        self.fail = False
        self.seen_auth: set[str] = set()

    def request(self, method, url, json=None, timeout=None, headers=None):
        self.seen_auth.add(headers["Authorization"])
        path = url.split("/repos/o/r", 1)[1]
        self.calls.append((method, path))
        if self.fail:
            return Resp(500, {"message": "boom"})
        if method == "GET" and path.startswith("/issues?"):
            if "page=1" not in path:
                return Resp(200, [])
            return Resp(200, [i for i in self.issues.values() if i["state"] == "open"])
        if method == "POST" and path == "/issues":
            n = self.next
            self.next += 1
            self.issues[n] = {"number": n, "state": "open", "comments": [], **json}
            return Resp(201, self.issues[n])
        if method == "POST" and path.endswith("/comments"):
            n = int(path.split("/")[2])
            self.issues[n]["comments"].append(json["body"])
            return Resp(201, {})
        if method == "PATCH":
            n = int(path.split("/")[2])
            self.issues[n].update(json)
            return Resp(200, self.issues[n])
        return Resp(404, None)

    def open_for(self, key):
        return [i for i in self.issues.values() if i["state"] == "open" and health.marker(key) in i["body"]]


def status(**src):
    out = {"run_at": "t", "sources": {}}
    for k, v in src.items():
        if v == "ok":
            out["sources"][k] = {"ok": True, "count": 30, "error": None, "blocked": False}
        elif v == "zero":
            out["sources"][k] = {"ok": True, "count": 0, "error": None, "blocked": False}
        elif v == "err":
            out["sources"][k] = {"ok": False, "count": 0, "error": "HTTPError: 500", "blocked": False}
        elif v == "blocked":
            out["sources"][k] = {"ok": False, "count": 0, "error": "RobotsDisallowed: x", "blocked": True}
    return out


tmp = Path(tempfile.mkdtemp())
health.STATUS = tmp / "status.json"
health.HEALTH = tmp / "data" / "health.json"
os.environ["GITHUB_TOKEN"] = "SECRET-TOKEN-XYZ"
os.environ["GITHUB_REPOSITORY"] = "o/r"
gh = FakeGitHub()


def run(st, session=None):
    health.STATUS.write_text(json.dumps(st), encoding="utf-8")
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = health.main([], session=session or gh)
    out = buf.getvalue()
    check(rc == 0, "항상 0 으로 끝나야 함")
    check("SECRET-TOKEN-XYZ" not in out, "토큰이 출력됨")
    return json.loads(health.HEALTH.read_text(encoding="utf-8"))


# 1) 7회 연속 실패 → 아직 이슈 없음, 8회째 → 이슈 1개
for i in range(7):
    h = run(status(a="err", b="ok", arca="blocked"))
check(h["sources"]["a"]["fail_streak"] == 7, f"연속 실패 7 기대: {h['sources']['a']}")
check(not gh.open_for("a"), "7회에서 이슈가 열리면 안 됨")
h = run(status(a="err", b="ok", arca="blocked"))
check(len(gh.open_for("a")) == 1, "8회째 이슈 1개")
check(gh.open_for("a") and gh.open_for("a")[0]["labels"] == [health.LABEL], "라벨")
check(gh.open_for("a") and gh.open_for("a")[0]["title"].startswith(health.TITLE_PREFIX), "제목 접두어")

# 2) 계속 실패해도 중복 이슈 없음
for i in range(5):
    run(status(a="err", b="ok", arca="blocked"))
check(len(gh.open_for("a")) == 1, "중복 이슈가 생김")

# 3) 차단 소스(arca)는 몇 번이든 이슈 없음, 횟수도 0
check(not gh.open_for("arca"), "차단 소스에 이슈가 열림")
check(h["sources"]["arca"]["fail_streak"] == 0 and h["sources"]["arca"]["state"] == "blocked", "차단 상태 기록")

# 4) 한 번 기준 아래로 회복 직전(0개) → 이슈 그대로, 정상 수집 → 댓글 + 닫힘
run(status(a="zero", b="ok", arca="blocked"))
check(len(gh.open_for("a")) == 1, "0개 1회로 이슈가 닫히면 안 됨")
h = run(status(a="ok", b="ok", arca="blocked"))
check(not gh.open_for("a"), "회복 후 이슈가 닫혀야 함")
closed = [i for i in gh.issues.values() if health.marker("a") in i["body"]]
check(closed and closed[0]["comments"] and closed[0].get("state_reason") == "completed", "회복 댓글·닫힘")
check(h["sources"]["a"]["fail_streak"] == 0, "회복 후 연속 실패 0")

# 5) 연속 0개 8회 → 이슈 (실패와 별도 집계). 중간에 실패가 섞이면 0개 횟수는 유지
for i in range(4):
    run(status(a="ok", b="zero"))
run(status(a="ok", b="err"))
check(not gh.open_for("b"), "0개 4 + 실패 1 은 아직 이슈 아님")
for i in range(4):
    h = run(status(a="ok", b="zero"))
check(h["sources"]["b"]["zero_streak"] == 8, f"연속 0개 8 기대: {h['sources']['b']}")
check(len(gh.open_for("b")) == 1, "연속 0개 8회 이슈")

# 6) 전체 0개 → 연속 2회째부터 이슈(1회는 무시), 다음에 딜이 생기면 닫힘
h = run(status(a="zero", b="zero"))
check(h["total_zero_streak"] == 1 and not gh.open_for(health.TOTAL_KEY), "전체 0개 1회는 이슈 아님")
run(status(a="ok", b="ok"))
h = run(status(a="zero", b="zero"))
check(h["total_zero_streak"] == 1 and not gh.open_for(health.TOTAL_KEY), "중간에 딜이 생기면 연속 횟수 초기화")
run(status(a="zero", b="zero"))
check(len(gh.open_for(health.TOTAL_KEY)) == 1, "전체 0개 연속 2회 이슈")
run(status(a="zero", b="zero"))
check(len(gh.open_for(health.TOTAL_KEY)) == 1, "전체 0개 중복 이슈")
run(status(a="ok", b="ok"))
check(not gh.open_for(health.TOTAL_KEY), "전체 0개 이슈 닫힘")
check(not gh.open_for("b"), "b 회복 닫힘")

# 7) 꺼진 소스: status 에서 사라지면 기록 삭제 + 이슈 닫힘
for i in range(8):
    run(status(a="ok", c="err"))
check(len(gh.open_for("c")) == 1, "c 이슈")
h = run(status(a="ok"))
check("c" not in h["sources"] and not gh.open_for("c"), "사라진 소스 정리")

# 8) 접두어가 겹치는 key(ppomppu / ppomppu_global) 구분
for i in range(8):
    run(status(ppomppu="ok", ppomppu_global="err"))
check(len(gh.open_for("ppomppu_global")) == 1 and not gh.open_for("ppomppu"), "key 구분")
run(status(ppomppu="ok", ppomppu_global="err"))
check(len(gh.open_for("ppomppu_global")) == 1, "ppomppu 정상이 ppomppu_global 이슈를 닫으면 안 됨")

# 9) check.py 실패 → 이슈 1개(중복 없음), 다음 정상 실행에서 닫힘
for i in range(2):
    with redirect_stdout(io.StringIO()):
        health.main(["--check-failed"], session=gh)
check(len(gh.open_for(health.CHECK_KEY)) == 1, "점검 실패 이슈 1개")
run(status(ppomppu="ok", ppomppu_global="ok"))
check(not gh.open_for(health.CHECK_KEY), "점검 실패 이슈 닫힘")

# 9b) 서버 403(blocked=False 실패)은 차단이 아니라 실패로 센다
st = {"run_at": "t", "sources": {"f": {"ok": False, "count": 0, "error": "HTTPError: 403", "blocked": False}}}
for i in range(8):
    h = run(st)
check(h["sources"]["f"]["fail_streak"] == 8 and len(gh.open_for("f")) == 1, "403 은 실패로 집계되어 이슈")
run(status(ppomppu="ok", ppomppu_global="ok"))
check(not gh.open_for("f"), "f 사라지면 닫힘")

# 9c) collect.py 실패: status.json 없음 / 20분 넘게 오래됨 → 이슈 1개(중복 없음), 최신 결과가 오면 닫힘
from datetime import datetime, timedelta, timezone  # noqa: E402
health.STATUS.unlink()
for i in range(2):
    with redirect_stdout(io.StringIO()):
        health.main([], session=gh)
check(len(gh.open_for(health.COLLECT_KEY)) == 1, "status.json 없음 → 수집 실패 이슈 1개")
old = status(ppomppu="ok")
old["run_at"] = (datetime.now(timezone.utc) - timedelta(minutes=45)).isoformat()
with redirect_stdout(io.StringIO()):
    health.STATUS.write_text(json.dumps(old), encoding="utf-8")
    health.main([], session=gh)
check(len(gh.open_for(health.COLLECT_KEY)) == 1, "오래된 status.json → 이슈 유지(중복 없음)")
fresh = status(ppomppu="ok", ppomppu_global="ok")
fresh["run_at"] = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
run(fresh)
check(not gh.open_for(health.COLLECT_KEY), "최신 status.json → 수집 실패 이슈 닫힘")
check(health.status_is_stale(None) and not health.status_is_stale(fresh), "status_is_stale")

# 9d) 단계 결과(env) 로 원인 구분
def run_env(st, restore="", collect=""):
    os.environ["RESTORE_OUTCOME"], os.environ["COLLECT_OUTCOME"] = restore, collect
    try:
        if st is None:
            health.STATUS.unlink()
            with redirect_stdout(io.StringIO()):
                health.main([], session=gh)
        else:
            run(st)
    finally:
        del os.environ["RESTORE_OUTCOME"], os.environ["COLLECT_OUTCOME"]


def titles(key):
    return [i["title"] for i in gh.open_for(key)]


# 가져오기 실패 (수집은 건너뜀, status.json 없음) → 가져오기 이슈만
run_env(None, restore="failure", collect="skipped")
check(len(gh.open_for(health.RESTORE_KEY)) == 1 and "가져오기" in titles(health.RESTORE_KEY)[0], "가져오기 실패 이슈")
check(not gh.open_for(health.COLLECT_KEY), "가져오기 실패인데 collect 이슈가 열림")
# 오래된 status.json 이 남아 있어도 가져오기 실패로 분류
oldst = status(ppomppu="ok")
oldst["run_at"] = (datetime.now(timezone.utc) - timedelta(minutes=300)).isoformat()
health.STATUS.write_text(json.dumps(oldst), encoding="utf-8")
os.environ["RESTORE_OUTCOME"] = "failure"
with redirect_stdout(io.StringIO()):
    health.main([], session=gh)
del os.environ["RESTORE_OUTCOME"]
check(len(gh.open_for(health.RESTORE_KEY)) == 1 and not gh.open_for(health.COLLECT_KEY), "오래된 status + 가져오기 실패")
# 정상 실행 → 가져오기 이슈 닫힘
fresh = status(ppomppu="ok", ppomppu_global="ok")
fresh["run_at"] = datetime.now(timezone.utc).isoformat()
run_env(fresh, restore="success", collect="success")
check(not gh.open_for(health.RESTORE_KEY), "가져오기 이슈 닫힘")
# collect 실패 + status 없음 → collect 이슈(일반 제목)
run_env(None, restore="success", collect="failure")
check(titles(health.COLLECT_KEY) == [f"{health.TITLE_PREFIX} collect.py 실행 실패"], f"collect 실패 제목: {titles(health.COLLECT_KEY)}")
check(not gh.open_for(health.RESTORE_KEY), "collect 실패인데 가져오기 이슈")
run_env(fresh, restore="success", collect="success")
check(not gh.open_for(health.COLLECT_KEY), "collect 이슈 닫힘")
# collect 실패 + 최신 status.json (알림 단계 등) → 변형 제목
run_env(fresh, restore="success", collect="failure")
check(len(gh.open_for(health.COLLECT_KEY)) == 1 and "알림 단계" in titles(health.COLLECT_KEY)[0], "알림 단계 collect 이슈")
run_env(fresh, restore="success", collect="success")
check(not gh.open_for(health.COLLECT_KEY), "알림 단계 이슈 닫힘")
# 결과를 모르면(env 없음) 기존 동작: 최신 status → 이슈 없음
run(fresh)
check(not gh.open_for(health.COLLECT_KEY) and not gh.open_for(health.RESTORE_KEY), "env 없음 + 최신 status → 이슈 없음")

# 10) GitHub API 고장 → 0 으로 끝나고 health.json 은 저장, 토큰 비출력
bad = FakeGitHub()
bad.fail = True
before = json.loads(health.HEALTH.read_text(encoding="utf-8"))["sources"]["ppomppu"]
h = run(status(ppomppu="zero", ppomppu_global="ok"), session=bad)
check(h["sources"]["ppomppu"]["zero_streak"] == before["zero_streak"] + 1, "API 실패해도 기록은 저장")

# 11) 토큰 없음 → 기록만, 네트워크 호출 없음
del os.environ["GITHUB_TOKEN"]
quiet = FakeGitHub()
run(status(ppomppu="ok"), session=quiet)
check(not quiet.calls, "토큰 없으면 API 호출 금지")

# 12) status.json 이 깨졌거나 health.json 이 깨져도 0
health.STATUS.write_text("{깨짐", encoding="utf-8")
with redirect_stdout(io.StringIO()):
    check(health.main([], session=quiet) == 0, "깨진 status.json")
health.HEALTH.write_text("[1,2", encoding="utf-8")
h = run(status(ppomppu="err"), session=quiet)
check(h["sources"]["ppomppu"]["fail_streak"] == 1, "깨진 health.json → 새로 시작")

# 13) 예전 status.json(blocked 필드 없음)도 처리
st = {"run_at": "t", "sources": {"x": {"ok": True, "count": 3, "error": None}}}
h = run(st, session=quiet)
check(h["sources"]["x"]["state"] == "ok", "blocked 필드 없는 status")

print("실패", fails, "건" if fails else "— 전체 통과")
sys.exit(1 if fails else 0)
