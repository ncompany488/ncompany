"""가격 기록(history) 전수 회귀 지표 (C-2-5). 정답셋이 못 잡는 오류를 라운드마다 같은 숫자로 비교하려고 만든 도구.

사용: .venv/Scripts/python tools/product_report.py [history.json 경로] [--replay] [--json]
  · 경로를 안 주면 data/history.json 을 '읽기만' 한다 (아무 파일도 쓰지 않음). 사본을 줘도 됨.
  · 모든 기록을 '현재' 파서로 메모리에서 다시 분류한 뒤 센다 (PARSER_VERSION 이 같아도 강제 재분류).
  · --replay : 상품마다 기록을 시간순으로 재생해 판정(lowest/…)을 다시 내고, 급락 'lowest' 와 보류(suspect) 수를 셈 (수 초).
  · --json   : 지표를 JSON 한 줄로도 출력 (다음 라운드와 diff 용).
  · 환경변수 HOTDEAL_SRC 로 다른 소스 트리(예: 고치기 전 사본)의 hotdeal 패키지를 쓸 수 있음 → 전/후 비교.

지표 (낮을수록 좋음, '상품'·'2건 이상 비율'은 참고):
  products / obs / skipped     상품 수 · 상품으로 기록된 글 · 비교 제외된 글
  multi_obs_pct                기록 2건 이상인 상품 비율 (같은 상품이 잘 모일수록 높음)
  key_digits_only / key_short  숫자만 남은 키 · 2글자 이하 키
  key_residue                  키에 잔여어(임박·선물용·정상화·끌올·재업·쿠폰·적용시·카할·코인딜·산지직송·체험딜…)가 남은 상품
  mixed_basis                  한 상품 안에 수량 정보 있는 글과 전혀 없는 글이 섞임 (총액 vs 개당 혼합 위험)
  extreme_spread               같은 비교 기준(개당/100g당/총액) 단가가 5배 넘게 벌어진 상품
  spec_as_weight               디지털·가전 문맥(저장용량·5G·모델명·냉장고 L…)인데 무게·부피로 읽은 글 (R-5)
  cond_missed                  조건부 표기(카카오N원·퀵계좌·쿠폰가·국카·카할…)가 있는데 cond=False 인 글 (C-2-4)
  plan_event_passed            요금제·결제 이벤트 표기가 있는데 상품으로 통과한 글 (C-2-6)
  count_gt500_noncontent       개수 > 500 인데 내용물(정·캡슐·매·포·롤…)이 아닌 글 (C-1-2)
  unit_lt20                    개수가 있는데 개당 20원 미만인 글
  search_bytes                 지금 규칙으로 만들 search.json 크기 (쓰지 않고 계산만)
"""
from __future__ import annotations

import json
import os
import re
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, os.environ.get("HOTDEAL_SRC") or str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from hotdeal import export  # noqa: E402
from hotdeal.history import History  # noqa: E402
from hotdeal.product import PARSER_VERSION  # noqa: E402

RESIDUE = re.compile(r"임박|선물용|정상화|끌올|재업|쿠폰|적용시|카할|코인딜|산지직송|체험딜|한정수량|금반영|가격오류|"
                     r"혜택가|농할|퀵계좌|카카오페이|(?<![할주])머니|(?:삼|현|신|국|롯|농)카$")
SPEC_CTX = re.compile(r"\d\s*[gt]b|ssd|(?<![a-z])ram|램|메모리|갤럭시|아이폰|자급제|노트북|모니터|그래픽|rtx|라이젠|5g|"
                      r"냉장고|김치냉장고|제습기|가습기|에어\s*프라이어|세탁기|건조기|음식물\s*처리기|청소기|백팩|무선\s*마우스|"
                      r"(?<![a-z])[a-z]{1,4}-?\d+[a-z]+\d*(?![a-z])", re.I)
SPEC_NOT = re.compile(r"세제|필터|세정제|캡슐|토너|크림|원두|봉투|정리\s*용기|립밤|식품|간식", re.I)
COND_PAT = re.compile(r"카카오\s*(?:페이\s*)?(?:머니\s*)?[\d,]+\s*원|퀵\s*계좌|계좌\s*이체|쿠폰\s*가|적용\s*가|"
                      r"쿠폰[^()]{0,12}적용|국카|카할|(?<![가-힣a-z])(?:삼|현|신|롯|농)카\s*[\d,]+|혜택\s*가|농할|임박", re.I)
PLAN_PAT = re.compile(r"통화\s*:?\s*(?:\d|무제한|자유)|데이터\s*:?\s*\d+\s*g|\d+\s*gb\s*[/,]?\s*\d+\s*분|\d+\s*분\s*[/,]?\s*\d+\s*건|"
                      r"(?:skt|kt|lg)\s*망|알뜰\s*폰|유심|이상\s*결제\s*시?\s*[\d,]+|결제\s*시\s*[\d,]+\s*원\s*할인|"
                      r"콘텐츠\s*페이|컨텐츠\s*페이|\d\s*만?\s*원\s*당\s*[\d,]+", re.I)
CONTENT = {"정", "알", "캡슐", "매", "포", "롤", "스틱", "티백"}


def _basis(o: dict) -> str:
    if o.get("count"):
        return "n"
    if o.get("content"):
        return "c"
    if o.get("size_g"):
        return "w" + (o.get("base") or "")
    return "t"


def _val(o: dict, b: str):
    p = o.get("price")
    if p is None:
        return None
    if b == "n":
        return p / o["count"]
    if b == "c":
        return p / o["content"]
    if b.startswith("w"):
        return p * 100 / o["size_g"]
    return float(p)


def metrics(raw: dict, replay: bool = False) -> dict:
    raw = dict(raw)
    raw["version"] = -1                       # 강제 재분류 (현재 파서 기준)
    t0 = time.time()
    h = History(raw)
    m: dict = {"parser_version": PARSER_VERSION, "rebuild_s": round(time.time() - t0, 2)}
    prods = h.products
    obs = [(pid, u, o) for pid, p in prods.items() for u, o in p["obs"].items()]
    m["products"] = len(prods)
    m["obs"] = len(obs)
    m["skipped"] = len(h.skipped)
    m["multi_obs_pct"] = round(100 * sum(1 for p in prods.values() if len(p["obs"]) >= 2) / max(len(prods), 1), 1)
    keys = list(prods)
    bare = [k.split(":", 1)[1] if re.match(r"^(?:usd|g):", k) else k for k in keys]
    m["key_digits_only"] = sum(1 for k in bare if re.fullmatch(r"[\d.~x]+", k))
    m["key_short"] = sum(1 for k in bare if len(k) <= 2)
    res = [k for k in bare if RESIDUE.search(k)]
    m["key_residue"] = len(res)
    mixed = spread = 0
    for p in prods.values():
        os_ = list(p["obs"].values())
        has_q = any(o.get("count") or o.get("content") or o.get("size_g") for o in os_)
        has_none = any(not (o.get("count") or o.get("content") or o.get("size_g")) for o in os_)
        mixed += has_q and has_none
        by: dict = {}
        for o in os_:
            if o.get("cond"):
                continue
            b = _basis(o)
            v = _val(o, b)
            if v:
                by.setdefault(b, []).append(v)
        spread += any(len(v) >= 2 and max(v) > 5 * min(v) for v in by.values())
    m["mixed_basis"] = mixed
    m["extreme_spread"] = spread
    titles_obs = [(o.get("title") or "", o) for _, _, o in obs]
    m["spec_as_weight"] = sum(1 for t, o in titles_obs if o.get("size_g") and SPEC_CTX.search(t) and not SPEC_NOT.search(t)
                              and not o.get("count"))
    m["cond_missed"] = sum(1 for t, o in titles_obs if COND_PAT.search(t) and not o.get("cond"))
    m["plan_event_passed"] = sum(1 for t, o in titles_obs if PLAN_PAT.search(t))
    m["count_gt500_noncontent"] = sum(1 for _, o in titles_obs if (o.get("count") or 0) > 500 and o.get("label") not in CONTENT)
    m["unit_lt20"] = sum(1 for _, o in titles_obs if o.get("count") and o.get("unit_price") is not None and o["unit_price"] < 20)
    # search.json 크기 (쓰지 않음)
    views = export.product_views(h)
    import tempfile
    with tempfile.TemporaryDirectory() as td:              # 임시 폴더에만 써서 크기를 잼 (site/ 는 건드리지 않음)
        rep = export.write_search_index(h, Path(td) / "search.json", views)
    m["search_entries"] = rep["entries"]
    m["search_bytes"] = rep["bytes"]
    if replay:
        m.update(_replay(h))
    m["_examples"] = {"key_residue": res[:15]}
    return m


def _replay(h: History) -> dict:
    """상품마다 기록을 시간순으로 재생: i 번째 글을 현재 딜로, 그 앞 글들만 과거로 두고 판정."""
    verd: Counter = Counter()
    big_drop = suspect = 0
    for pid, pr in list(h.products.items()):
        obs = pr["obs"]
        if len(obs) < 2:
            continue
        items = sorted(obs.items(), key=lambda kv: kv[1].get("date") or "")
        for i in range(1, len(items)):
            u, o = items[i]
            pr["obs"] = dict(items[:i])
            g = {"title": o["title"], "price": o["price"], "currency": o.get("currency") or "KRW",
                 "sources": [{"url": u, "source": o.get("source")}], "posted_at": o.get("date")}
            try:
                r = h.product_for_group(g)
            finally:
                pr["obs"] = obs
            if not r:
                continue
            verd[r["verdict"]] += 1
            hi = r.get("history") or {}
            if hi.get("suspect"):
                suspect += 1
            if r["verdict"] == "lowest" and hi.get("mode") != "total":
                ref = hi.get("low_cond") if hi.get("basis") == "cond" else hi.get("low_unit")
                if ref and ref.get("unit_price") and r.get("unit_price") is not None \
                        and r["unit_price"] < 0.6 * ref["unit_price"]:
                    big_drop += 1
    return {"replay_verdicts": dict(verd), "replay_lowest_drop_gt40": big_drop, "replay_suspect": suspect}


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    path = Path(args[0]) if args else ROOT / "data" / "history.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    m = metrics(raw, replay="--replay" in sys.argv)
    ex = m.pop("_examples")
    width = max(len(k) for k in m)
    print(f"history 전수 지표 — {path}")
    for k, v in m.items():
        print(f"  {k:<{width}}  {v}")
    if ex["key_residue"]:
        print("  잔여어 키 예:", ", ".join(ex["key_residue"]))
    if "--json" in sys.argv:
        print(json.dumps(m, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
