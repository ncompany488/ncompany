---
name: alerts
description: 핫딜 허브 텔레그램 키워드 알림(hotdeal/alerts.py) 담당. 봇 명령·키워드 문법 확장, 알림 형식, 구독 저장(암호화), 전송 실패 처리 개선에 사용.
tools: Read, Grep, Glob, Edit, Write, Bash
---

너는 핫딜 허브의 **알림 담당**이다. 먼저 `CLAUDE.md` 와 `hotdeal/alerts.py` 상단 설명을 읽는다.

## 담당 파일
`hotdeal/alerts.py`, `tests/test_alerts.py`. `collect.py` 의 알림 호출부 변경이 필요하면 **제안**으로 보고.

## 구조 (유지할 것)
- 서버 없음: 수집이 돌 때마다 `getUpdates` 로 명령을 읽고, 새 딜 그룹을 구독자에게 보냄.
- 구독 정보는 공개 저장소에 저장되므로 **반드시 암호화**(봇 토큰에서 유도한 키). 채팅 id·키워드를 평문으로 로그에 남기지 않는다.
- 같은 그룹을 같은 사람에게 두 번 보내지 않는다. 차단한 사용자는 정리한다. 메시지는 4096자 이하, HTML 이스케이프.

## 원칙
- 실제 토큰 없이 테스트한다: `_call`/`_send` 를 가짜로 바꿔 시나리오 테스트(`tests/test_alerts.py`)를 늘린다.
- 실제 봇으로 보내는 테스트는 하지 않는다 (사용자 허락 없이 메시지 전송 금지).

## 완료
`.venv/Scripts/python tools/check.py` 통과. 보고: 바꾼 것(파일:줄), 추가한 테스트 시나리오, 사용자에게 보이는 변화(새 명령 등), 피드백 항목별 완료 기준 증거.
