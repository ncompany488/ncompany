# 🔥 핫딜 허브

여러 커뮤니티의 핫딜을 15분마다 자동으로 모아 한 페이지에 보여주는 사이트입니다.
같은 딜이 여러 곳에 올라오면 하나로 묶고, 텔레그램으로 키워드 알림도 보냅니다.
서버가 필요 없습니다. GitHub가 무료로 수집하고 사이트를 올려 줍니다.

## 수집 소스

| 소스 | 상태 | 비고 |
|---|---|---|
| 뽐뿌 / 해외뽐뿌 | ✅ | 목록 페이지 |
| 루리웹 핫딜 | ✅ | 목록 페이지 |
| 클리앙 알뜰구매 | ✅ | 첫 페이지만 (robots.txt가 `?` 주소 금지) |
| 아카라이브 핫딜 | ✅ | 목록 페이지 |
| DealNews (해외) | ✅ | 공식 RSS |
| 펨코, 쿨앤조이 | ⛔ | robots.txt가 봇 수집 금지 |
| 퀘이사존, Slickdeals | ⛔ | Cloudflare 봇 차단 |
| 11번가·G마켓·옥션·쿠팡·SSG 등 공식몰 | ⛔ | robots.txt 금지 또는 봇 차단 |

공식몰 특가는 커뮤니티에 올라온 글을 판매처(쿠팡, 11번가 …) 기준으로 모아 **공식몰** 탭에 보여줍니다.
막힌 사이트는 우회하지 않습니다. 각 파일(`hotdeal/sources/*.py`)의 `ENABLED = False`에 이유가 적혀 있습니다.

## 처음 한 번만 하는 설정 (약 10분)

### 1. GitHub에 올리기
1. https://github.com/new 에서 **Public** 저장소를 만듭니다 (예: `hotdeal-hub`). 무료 Pages와 무제한 Actions를 쓰려면 공개 저장소여야 합니다.
2. 이 폴더에서 아래를 실행합니다 (`<아이디>`를 바꿔서):
   ```bash
   git init -b main
   git add .
   git commit -m "init"
   git remote add origin https://github.com/<아이디>/hotdeal-hub.git
   git push -u origin main
   ```
3. 저장소 **Settings → Pages → Build and deployment → Source**를 **GitHub Actions**로 바꿉니다.
4. **Actions** 탭 → `collect` → **Run workflow**를 누르면 첫 수집이 돌고,
   몇 분 뒤 `https://<아이디>.github.io/hotdeal-hub/` 에 사이트가 뜹니다. 이후로는 15분마다 자동으로 갱신됩니다.

### 2. 텔레그램 알림 켜기 (선택)
1. 텔레그램에서 **@BotFather** → `/newbot` → 이름과 아이디(예: `my_hotdeal_bot`)를 정하면 **토큰**이 나옵니다.
2. 저장소 **Settings → Secrets and variables → Actions → New repository secret**:
   이름 `TELEGRAM_BOT_TOKEN`, 값에 토큰을 붙여넣습니다.
3. `site/config.js`의 `telegramBot`에 봇 아이디(@ 없이)를 넣고 커밋하고 푸시합니다.
4. 텔레그램에서 내 봇에 `/start`를 보내고 `/add 에어팟` 처럼 키워드를 등록합니다.
   봇 답장은 다음 수집 때(최대 15분 + GitHub 지연) 옵니다.

키워드 문법: `/add 에어팟 프로`(둘 다 포함) · `/add 모니터 -중고`(제외) · `/add 라면 <15000` 또는 `<1.5만`(가격 상한)

## 내 PC에서 돌려보기
```bash
py -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python collect.py --no-alerts
.venv/Scripts/python -m http.server 8765 --directory site
```
그다음 http://localhost:8765 에 접속합니다.

## 구조
```
collect.py              전체 실행 (수집 → 병합 → 그룹화 → 사이트 데이터 → 알림)
hotdeal/sources/*.py    사이트별 수집기 (새 소스 = 파일 하나 추가)
hotdeal/http.py         robots.txt 준수, 속도 제한, 재시도
hotdeal/dedup.py        같은 딜 묶기
hotdeal/alerts.py       텔레그램 봇 (구독 정보는 암호화해 저장)
site/                   정적 웹사이트 (GitHub Pages)
tools/try_source.py     수집기 하나 테스트: python tools/try_source.py ppomppu
```

## 알아둘 점
- 제목, 링크, 숫자 정보만 모읍니다. 본문과 이미지는 복제하지 않습니다(썸네일은 원본 주소로 표시).
- GitHub 예약 실행은 붐비는 시간에 5~20분씩 늦어질 수 있습니다.
- 사이트 구조가 바뀌면 해당 수집기만 실패하고 나머지는 계속 동작합니다. 실패 여부는 사이트 하단 **수집 상태**에서 확인할 수 있습니다.
