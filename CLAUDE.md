# 핫딜 허브 — 개발 규칙 (모든 세션·에이전트 공통)

커뮤니티 핫딜을 모아 보여주는 정적 사이트. GitHub Actions가 15분마다 `collect.py` 실행 → `site/` 를 GitHub Pages 로 배포.
- 저장소: `ncompany488/ncompany` · 사이트: https://ncompany488.github.io/ncompany/
- 사용자는 초보 개발자. 설명은 한국어로 쉽게, 사용자 손이 가는 작업은 최소화.

## 데이터 흐름과 경계
```
hotdeal/sources/*.py ──Deal──▶ store.merge ─▶ dedup.group_deals ─▶ site/data/deals.json ─▶ site/app.js
                                                           └─ 새 그룹 ─▶ alerts.py (텔레그램)
공통 규칙: hotdeal/models.py (Deal 형식) · hotdeal/http.py (robots·속도 제한)
```

## 파일 소유권 — 자기 영역 밖 파일은 고치지 말고 '제안'으로 보고
| 역할 (에이전트) | 소유 파일 |
|---|---|
| 총괄 (메인 세션) | `hotdeal/models.py`, `hotdeal/http.py`, `collect.py`, `CLAUDE.md`, `docs/feedback/BACKLOG.md`, `.claude/` |
| `collector` | `hotdeal/sources/*.py` (배정받은 파일만), `tools/try_source.py` |
| `processor` | `hotdeal/dedup.py`, `hotdeal/parse.py`, `hotdeal/product.py`, `hotdeal/history.py`, `tests/test_dedup.py`, `tests/test_parse.py`, `tests/test_product.py`, `tests/test_history.py`, `tests/fixtures/*`, `hotdeal/category.py`, `hotdeal/export.py`, `tools/product_report.py`, `tests/test_category.py`, `tests/test_export.py` |
| `frontend` | `site/*` (단, `site/data/` 는 생성물. 데이터 형식은 `docs/contract-product-pages.md`) |
| `alerts` | `hotdeal/alerts.py`, `tests/test_alerts.py` |
| `ops` | `.github/workflows/*`, `hotdeal/store.py`, `requirements.txt`, `README.md`, `tools/health.py`, `tests/test_health.py` |
| `reviewer` | 읽기 전용 — 검증 보고만 |
| `critic` | 읽기 전용 + `docs/feedback/rounds/*.md` 작성만 |

새 테스트 파일은 해당 영역 담당이 `tests/test_<영역>.py` 로 만든다.

## 절대 규칙
1. **robots.txt·봇 차단 우회 금지.** 모든 요청은 `hotdeal.http.get`. Cloudflare/CAPTCHA/로그인/서명 우회, UA 위장으로 차단 회피 금지. 막히면 `ENABLED = False` + 사유 주석.
2. **제목·링크·숫자만 수집.** 게시글 본문·이미지 복제 금지 (썸네일 URL 링크는 허용).
3. **완료 기준 = `python tools/check.py` 통과.** 실제 사이트를 건드린 경우 `python tools/check.py --live`.
4. Python 3.12 호환 (Actions 는 3.12, 로컬은 `.venv/Scripts/python`, 3.14).
5. 비밀값(토큰 등)은 코드·로그·커밋에 절대 넣지 않음. GitHub Secret 은 사용자가 직접 입력.
6. 밸런스·수치 튜닝(병합 임계값 등)은 근거 데이터와 전/후 수치를 함께 보고.
7. 커밋·푸시는 사용자가 요청했을 때만. 커밋 메시지는 한국어 한 줄 요약.

## 피드백 루프 (상호보완)
`critic` 비판 → 총괄이 채택/기각 → 소유 에이전트가 개선 → `reviewer` 검증 → 다음 라운드에 `critic` 이 재확인.
자세한 절차·형식: `docs/feedback/README.md`. 한 번에 돌리기: `/improve-cycle`.

## 상품 식별 방침 (사용자 결정)
- 조건부 가격(카드·멤버십·쿠폰·농할 등)은 역대 최저가 계산에서 제외하고 따로 표시.
- 가전은 모델번호로만 같은 상품을 판단. 모델번호가 없는 가전 글은 역대 최저가 기록에서 제외.
