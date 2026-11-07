"""딜 제목에서 '같은 상품'을 알아보기 위한 정보 추출.

결과 ProductInfo:
  name      정리된 상품명 (판매처·가격·배송·홍보 문구·수량·용량 제거)
  key       같은 상품 판정용 키 = 이름 토큰만. **용량(g·ml)·개수는 키에 넣지 않는다**
            → '신라면 5개' = '신라면 120g x 20입' = '신라면 600g' 이 한 상품.
            변형어(블랙·투움바·컵·제로…)·원산지(국내산/미국산)·번들·PB(곰곰…)·스펙(256gb·27인치·3구)은
            이름에 남으므로 '신라면' ≠ '신라면 블랙', '아이폰 256GB' ≠ '512GB'.
  alt_key   띄어쓰기·어순 차이 흡수용 보조 키 (단어 정렬)
  count     포장 개수 (5개·20봉·24입·120g x 20·1+1 …)
  label     개수 단위 표시어 ("개","캔","봉","병","팩"…)
  usize     개당 용량 (g/ml, 소수 허용) ─ 120g x 20 의 120
  size      개당 용량 표기 ("120g") 또는 개당 내용물 ("80캡슐")
  size_g    무게·부피 총량 (g/ml 정수) ─ 개당 용량 × 개수, 또는 '2kg' 처럼 총량만 있을 때
  base      size_g 의 단위 "g" | "ml"
  content   내용물 총수 (180정·40매·50포…) 와 그 단위 content_unit
  cond      조건부 가격 (카드 할인·멤버십·와우·신규/미구매·쿠폰 필수·앱 전용 …)
  unit      이 글 하나만 볼 때의 기본 비교 단위 "개" | "100g" | "100ml" | None(총액)

비교 규칙 (history.py 가 사용):
  · '개당' 비교는 개당 용량이 같거나 (양쪽 다) 모를 때만.
  · 개당 용량이 다르거나 한쪽이 무게로만 팔리면 '100g(ml)당' 으로 비교 (총량을 아는 글끼리).
  · 내용물(캡슐·정·매…)이 있으면 '캡슐당' 비교도 가능.
  · GB·TB·인치 같은 스펙은 이름(키)에 남으므로 아예 다른 상품.

비교 불가능한 글(여러 상품 묶음, 택1, 상품권·교환권, 포인트 적립, 항공권, 요금제 등)은 None.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

from .category import _DECISIVE as _CAT_DECISIVE, _RULES as _CAT_RULES, categorize

PARSER_VERSION = 8  # 키 규칙이 바뀌면 올린다 → History.load 가 모든 기록을 다시 분류
# 5 (R3): 숫자로 시작하는 모델명·저장용량·5G·GHz·가전 용량은 무게가 아님(R-5), 조건부 새 표기(C-2-4),
#         요금제·결제 이벤트 제외(C-2-6), 잔여어(임박·선물용·정상화…) 정리(P-007)
# 6 (R3 후속): 가격오류·정상화 글 제외, 증정품 문구는 가전 문맥 판단에서 뺌, 모델번호가 있으면 가전 용량을 키에서 뺌
# 7 (R4): 가전은 모델번호로만 식별 (모델번호 없는 가전 글은 기록 안 함), '증정외 다양'·'경품 이벤트(가격 있음)' 통과
# 8 (R4 후속): TV 는 'TV' 단어 없이도 가전 (모델 모양·Crystal UHD·Neo QLED…), 모니터·노트북은 디지털 고정,
#   부속품 단어(리모컨·물걸레·전용…)는 모델번호가 없을 때만 일반 규칙, category 의 '인버터→버터' 오분류 수정

# ---------- 비교 대상이 아닌 글 ----------
_SKIP = re.compile(
    r"기프트\s*카드|기프트\s*코드|상품권|금액권|교환권|\d+\s*만\s*원?\s*권|\d[\d,]*\s*원\s*권|모바일\s*쿠폰|"
    r"요금제|이용권|구독|리딤|일시\s*무료|무료\s*배포|할인\s*코드|쿠폰\s*(?:팩|북|받기|발급|배포|모음|이벤트)|"
    r"택\s*1|골라\s*담기|(?<!증정)(?<!증정\s)외\s*다양|모음|종합|외\s*\d*\s*종|\d+\s*종\s*(?:세트|중)|전\s*모델|전\s*품목|라이브|live|"
    r"예고|안내|추천|후기|질문|아시는\s*분|세일|패키지|숙박|항공|티켓|입장권|왕복|편도|직항|경유|노선|"
    r"\b외\b|\s외\s|\s외$|중\s*택|"
    r"라방|랜덤\s*\d|클릭\s*적립|일일\s*적립|적립\s*\d|알림\s*(?:받기|신청)|팔로우|출석|(?<![가-힣])퀴즈|만보기|"
    r"\d+\s*원\s*딜|판매\s*예정|출시\s*예정|발매\s*예정|인하\s*예정|예약\s*(?:시작|오픈|예정|안내)|"
    # F-001 여러 상품 나열 신호: '(다양/무료)', '상품별상이', '1,683,300원~' (가격 범위 = 여러 옵션)
    r"[(\[]\s*다양\s*/|상품별\s*상이|\d\s*원\s*~(?!\s*\d)|"
    # C-1-5 네이버페이 N원 적립 (현장결제·이벤트 적립)
    r"(?:네이버\s*페이|네페)[^()]{0,40}?\d[\d,]*\s*원?\s*적립|"
    # C-2-6 휴대폰 요금제 ('요금제' 단어 없이 '통화 500분, 데이터 10GB (990원/평생)')
    r"통화\s*:?\s*(?:\d|무제한|자유)|데이터\s*:?\s*\d+(?:\.\d+)?\s*g|\d+(?:\.\d+)?\s*gb\s*[/,]?\s*\d+\s*분|\d+\s*g\s*/\s*\d+\s*분|"
    r"\d+\s*분\s*[/,]?\s*\d+\s*건|(?<![a-z])(?:skt|kt|lg|u\+|lgu\+?|유플러스)\s*망|알뜰\s*(?:폰|통신|요금)|"
    r"(?<![a-z])(?:skt|kt|lg)\s*알뜰|평생\s*요금|\d\s*mbps|유심|usim|데이터\s*쿠폰|"
    # C-2-6 결제수단·카드사 이벤트 ('1만원 이상 결제시 4000원 할인', '5만원당 5,000원 청구할인')
    r"이상\s*결제\s*시?\s*[\d,]+\s*(?:만\s*)?[천원]|결제\s*시\s*[\d,]+\s*원\s*(?:할인|청구)|"
    r"콘텐츠\s*페이|컨텐츠\s*페이|휴대폰\s*결제|\d\s*만?\s*원\s*당\s*[\d,]+\s*[천만원]|"
    # R3 후속: 가격 오류·이미 정상화 글 = 실제로 살 수 없던 가격 → 기록하지 않음 (역대최저 오염 방지)
    r"정상화|가격\s*오류|오류\s*\?|응모|가입\s*이벤트|착한\s*가격\s*업소",
    re.I,
)
# 포인트 적립 게시판성 말머리 → 통째로 제외
_SKIP_TAG = re.compile(r"네이버\s*페이|네페|페이코\s*포인트|토스\s*포인트|캐시워크|신한\s*sol|오퀴즈", re.I)
_AIRPORTS = (r"인천|김포|김해|부산|제주|청주|대구|무안|양양|나리타|하네다|간사이|오사카|도쿄|후쿠오카|요나고|"
             r"삿포로|오키나와|나고야|타이베이|타이페이|방콕|다낭|세부|괌|사이판|홍콩|상하이|싱가포르|마닐라|"
             r"하노이|호치민|나트랑|발리|시드니|파리|런던|뉴욕|la|마쓰야마|시즈오카|기타큐슈|구마모토|가고시마")
_ROUTE = re.compile(rf"(?:{_AIRPORTS})\s*(?:-|→|->|~)\s*(?:{_AIRPORTS})|\b\d{{4}}\s*-\s*\d{{4}}\b", re.I)
# 가격 %만 있는 세일 공지 (카드·쿠폰 % 할인은 조건부로 처리하고 남김)
_PCT = re.compile(r"\d+\s*%")
_PCT_OK = re.compile(r"(?:카드|쿠폰|적립|페이|청구|즉시|멤버십|중복)[^%]{0,12}\d+\s*%|\d+\s*%\s*(?:카드|쿠폰|적립|청구|즉시|중복)", re.I)

# ---------- 조건부 가격 ----------
_COND = re.compile(
    r"카드\s*(?:할인|결제|청구|즉할|즉시|사용|적용|혜택|다양|\d)|(?:kb|신한|삼성|현대|롯데|하나|우리|bc|nh|농협|국민|씨티|"
    r"스마일|토스|카카오|네이버)\s*(?:페이\s*)?(?:신용|체크)?\s*카드|카드\s*\d+\s*%|체감|"
    r"멤버십|맴버쉽|멤버쉽|네멤(?!\s*무)|티멤|와우(?!\s*무)|외우(?!\s*무)|유니버스|유클(?!\s*무)|스마일\s*클럽|"
    r"신규|첫\s*구매|첫\s*주문|미\s*구매|재구매\s*제외|쿠폰\s*(?:필수|적용|사용|다운)|앱\s*(?:전용|결제|구매)|"
    r"페이코|토스\s*페이|월렛|네이버\s*페이\s*(?:결제|구매)|(?:회원|vip|멤버십?|고객|구매)\s*등급|등급\s*(?:할인|쿠폰|혜택|별|회원)|임직원|학생\s*인증|"
    # 검증에서 놓친 표기: T멤, 토스 15,450원, 스카 15,990원(스마일카드), 특정 결제수단, 모니모, 빅스 10%
    r"t\s*멤(?!\s*무)|토스\s*[\d,]+\s*원|스카\s*[\d,]+|특정\s*결제|모니모|빅스\s*\d+\s*%|"
    r"u\s*클럽|카할가|카드\s*할인가|"
    # R3 C-2-4: 카카오14,940원·카카오페이 머니·페이26,890원·퀵계좌이체·쿠폰가·적용가·쿠폰 2종 모두 적용·카드사 줄임말
    r"카카오\s*(?:페이\s*)?(?:머니\s*)?[\d,]+\s*원|카카오\s*페이\s*머니|(?<![가-힣a-z])페이\s*[\d,]+\s*원|"
    r"네이버\s*페이\s*[\d,]+\s*원|네페\s*[\d,]+|스마일\s*페이|퀵\s*계좌|계좌\s*이체|쿠폰\s*가|적용\s*가|"
    r"쿠폰[^()]{0,12}적용|(?<![가-힣a-z])(?:삼|현|신|국|롯|농|하나|우리)카(?=[\s\d,/)]|시|결제|할인|추가|$)|"
    r"비씨\s*[\d,]+|혜택\s*가|농할|카할|"
    # P-007: 유통기한 임박 상품은 정상가와 비교하지 않음 (임박·소비기한임박·반임박)
    r"임박",
    re.I,
)
# 조건부 표기 바로 뒤 금액 앞의 결제수단 단어 → 상품명에서 지움 ('카카오14,940원' 의 '카카오')
_COND_PAY_WORD = re.compile(
    r"(?:카카오\s*페이\s*머니|카카오\s*페이|카카오|네이버\s*페이|네페|페이|머니|비씨|(?<![가-힣a-z])(?:삼|현|신|국|롯|농|하나|우리)카|"
    r"퀵\s*계좌\s*이체|퀵\s*계좌|계좌\s*이체|카할)\s*(?=[\d,]+\s*원|적용)", re.I)

# ---------- 제목 정리 ----------
_LEAD_TAG = re.compile(r"^\s*([\[【(<]([^\]】)>]{0,30})[\]】)>])\s*")
_LEAD_PAREN_TAG = re.compile(r"^\s*([^\s()\[\]]{1,8})\)\s*")       # gs25) 티) 10시)
# 판매처(쇼핑몰·스토어) 말머리 → 지움. 그 외(브랜드·매장: [메가MGC커피] [스타벅스])는 이름에 남김
_SHOPS = {
    "쿠팡", "쿠팡와우", "로켓프레시", "로켓직구", "네이버", "네이버쇼핑", "네이버스토어", "네이버멤버십", "스마트스토어",
    "지마켓", "g마켓", "gmarket", "옥션", "11번가", "11마존", "ssg", "신세계쇼핑", "이마트", "이마트앱", "이마트24",
    "롯데온", "롯데on", "롯데마트", "롯데마트제타", "롯데백화점", "롯데홈쇼핑", "카카오", "카카오톡", "카카오톡딜",
    "카톡딜", "카톡선물하기", "카카오선물하기", "카카오 톡딜", "톡딜", "토스", "토스쇼핑", "오늘의집", "하이마트",
    "홈플러스", "알리", "알리익스프레스", "테무", "컬리", "마켓컬리", "올리브영", "무신사", "위메프", "티몬", "인터파크",
    "gs25", "gs샵", "gs", "cu", "세븐일레븐", "다이소", "코스트코", "트레이더스", "아마존", "amazon", "amazon.jp",
    "amazonjp", "일마존", "ebay", "이베이", "woot", "큐텐", "스팀", "steam", "psn", "ps스토어", "플레이스테이션스토어",
    "xbox", "ms스토어", "마소스토어", "에픽", "에픽게임즈", "epic", "gog", "그린맨게이밍", "gmg", "gamersgate", "스토브",
    "인벤게임즈", "한국닌텐도", "닌텐도", "닌텐도스토어", "닌텐도 스토어", "닌텐도이샵", "닌텐도e숍", "닌텐도e샵",
    "겜우리", "게임몰", "플레이샵", "playshop", "소프라노", "소프라노몰", "예판런", "반다이몰", "반다이", "게임터치몰",
    "컴퓨존", "아싸컴", "다나와", "테크라인", "크림", "w컨셉", "ns몰", "ns홈쇼핑", "sk스토아", "cj온스타일",
    "현대hmall", "hmall", "우체국쇼핑", "온누리쇼핑", "삼다수몰", "동원몰", "하림몰", "농심몰", "종근당건강몰",
    "자사몰", "공식몰", "공홈", "애플tv스토어", "앱스토어", "ios", "android", "플레이스토어", "구글플레이", "wearos",
    "갤럭시 스토어", "갤럭시스토어", "리디북스", "요기요", "배민", "쿠팡이츠", "페이코", "카카오페이", "티플러스",
    "아이즈모바일", "시월모바일", "인더마켓", "레일플래닛", "블리자드샵", "탁탁몰", "일렉트로마트", "딜릭", "루트바",
    "우리동네gs", "우리동네gs앱", "미니맵", "토이저러스", "kkst", "ts공식몰", "레디홈",
    # R2 C-1-9: 말머리 변형
    "쿠팡 로켓직구", "쿠팡로켓", "쿠팡로켓직구", "쿠팡 로켓", "쿠팡 로켓프레시", "로켓배송", "로켓와우", "29cm", "temu",
    "위시", "wish", "lotte on", "lotteon", "전자랜드", "kream", "팔도감", "공식", "공식홈", "공식수입사", "공식인증점",
    "끌올", "재업", "다이렉트게임즈", "그립",
    "품절", "종료", "예판", "예약", "재입고", "특가", "핫딜", "임박특가", "판매중", "전기종", "매장", "국내", "해외",
    "직구", "기타", "공구", "단독", "한정", "티", "지", "삼", "옥", "쿠", "네", "11", "ns", "gs",
}
_CATEGORIES = {"pc", "가전", "식품", "생활", "게임", "의류", "패션", "디지털", "육아", "화장품", "뷰티", "도서",
               "모바일", "음료", "먹거리", "생필품", "끌올", "엑박", "엑스박스"}
_SHOP_PAT = re.compile(r"(?:몰|샵|숍|스토어|마켓|쇼핑|마트|닷컴|store|shop|mall|마존|홈쇼핑|백화점|\d+시)$", re.I)

_PAREN = re.compile(r"[\[(（【]([^\[\](（）)【】]*)[\])）】]")
_PRICE_TXT = re.compile(r"\$\s*\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d{1,3}(?:,\d{3})+\s*원?~?|\d+\s*원~?|\d+(?:\.\d+)?\s*만\s*원?|\$\s*\d+(?:\.\d+)?|\d+(?:\.\d+)?\s*\$")
_PRICEISH_PAREN = re.compile(r"원|무료|무배|배송|/|구매|발송|증정|택|당\s*\d|랜덤|카드|멤버|네멤|와우|유클|체감|쿠폰|일분|\d+\s*일\s*분|개월\s*분", re.I)
# '+ 증정2개' 처럼 증정 뒤 수량도 증정품 (R3: 포스트 620g 3봉 + 증정2개 → 3봉)
_FREEBIE = re.compile(r"\+\s*[^+]*?(?:증정|사은품|서비스|덤)\s*(?:\d+\s*(?:개입|개|입|봉|팩|병|캔|ea|p)(?![a-z가-힣]))?\)?", re.I)
_PROMO = re.compile(
    r"적립금\s*반영|\d{2,4}\s*년\s*형|카할(?:\s*가)?|"          # R3: '적립' '25년' 보다 먼저 (잔여 '금 반영'·'형' 방지)
    r"무료\s*배송|무배|무료|특가|핫딜|초특가|역대가|최저가|역대급|체감가?\s*[\d.]*\s*만?|카드\s*할인|카드\s*다양|할인|적립|"
    r"와우|외우|로켓\s*배송|로켓\s*설치|로켓\s*직구|로켓|정품|국내\s*정발|haccp\s*인증|haccp|해썹|인증|당일\s*발송|"
    r"오늘\s*출발|단독|한정판매|증정|사은품|이벤트|선착순|타임\s*딜|오늘의\s*딜|빅스마일데이|"
    r"슈퍼\s*딜|쓱\s*데이|티멤버십|티멤|네이버\s*멤버십|멤버십|맴버쉽|멤버쉽|네멤|유니버스\s*클럽|유니버스|유클|"
    r"스마일\s*클럽|톡딜|대용량|멀티팩|본품|기획|신상|new|자급제|직수입|"
    r"예약\s*판매|예약\s*구매|사전\s*예약|예약|예판|재입고|재판매|품절|종료|매장\s*방문|단품|종류\s*무관|"
    r"네이버\s*페이|카카오\s*페이|토스\s*페이|\S*결제\s*시|신규|첫\s*구매|미\s*구매|배송비|배송료|택배비|유배|조건부|"
    r"\d{2,4}\s*년\s*산?|\S*당\s*\d+(?:\.\d+)?\s*[a-z가-힣]*|_?\d{1,2}/\d{1,2}\s*\d*\s*차|\d+\s*차\b|"
    # R2 C-1-9 잔여어: 끌올·재업·정가·카할가·쿠폰 조건·공식(몰/스토어)·N개월분
    r"끌올|재업|(?<![가-힣])정가(?![가-힣])|카할가|카드\s*할인가|u\s*클럽\s*전용|u\s*클럽|\S*쿠폰\s*적용\s*시?|쿠폰\s*적용가|"
    r"적용\s*시|적용가|(?<![가-힣])공식(?:인증점|스토어|몰|홈|수입사|판매처|대리점)?(?![가-힣])|총?\s*\d+\s*개월\s*분|"
    # R3 C-2-4 조건어 잔여: 쿠폰가·시크릿쿠폰가·쿠폰 2종 모두 적용·카드사 줄임말·혜택가·스마일페이시
    r"\S*쿠폰\s*가|쿠폰\s*\d*\s*종?\s*(?:모두\s*)?적용(?:\s*시)?|(?<![가-힣a-z])(?:삼|현|신|국|롯|농|하나|우리)카(?:시|결제\s*시?)?(?![가-힣])|"
    r"(?:최대\s*)?혜택\s*(?:가|시)|스마일\s*페이\s*시?|카카오\s*페이\s*머니|퀵\s*계좌\s*이체|퀵\s*계좌|계좌\s*이체|농할\s*쿠폰|농할|"
    # R3 P-007 잔여어: 유통기한·임박·선물용·정상화·산지직송·코인딜·체험딜·한정수량·N대 한정·가격오류·적립금 반영·'~21시까지'
    r"(?:소비|유통)\s*기한\s*(?:임박|(?:\d{2,4}\s*년\s*)?\d{1,2}\s*월(?:\s*\d{1,2}\s*일)?\s*(?:까지)?|[\d./]+\s*(?:까지)?)?|"
    r"(?<![\d.])\d{2}\.\d{1,2}\.\d{1,2}(?![\d.])|"                  # 소비기한 날짜 '26.11.26'
    r"(?:\d{2,4}\s*년\s*)?\d{1,2}\s*월\s*\d{1,2}\s*일\s*까지|[~\s]\d{1,2}(?:[./]\d{1,2})?\s*(?:시|일)?\s*까지|"
    r"\S*임박|\S*선물용|이미\s*정상화|가격\s*정상화|정상화|산지\s*직송|코인\s*딜|체험\s*딜|한정\s*수량|\d+\s*대\s*한정|"
    r"오늘만|가격\s*오류\??|오류\s*\?|적립금\s*반영|모니모|\S*쿠폰(?![가-힣])",
    re.I,
)
_STOP_TOKENS = {"x", "×", "*", "or", "등", "및", "외", "토스", "페이코", "kb", "카드", "가격", "딜", "구매", "판매", "중",
                "개당", "할인가", "최종", "특전포함", "can", "ea", "pet", "페트", "box", "캔", "병", "봉",
                # R2: 잔여어 (판매처 이름이 본문에 섞인 경우 포함)
                "박스", "한박스", "29cm", "내외", "내", "이내", "다양", "쿠팡", "지마켓", "g마켓", "11번가", "옥션", "롯데온",
                "ssg", "컬리", "테무", "temu", "알리", "위시", "추가", "맛선택", "묶음", "이상", "네맴", "넾다", "당일도정",
                # F-003 영어 불용어
                "for", "with", "the", "and", "of", "by",
                # R3 P-007 단독 잔여어 ('4봉 총 12인분' 의 총, '개당 500원꼴' 의 꼴, '증정포함' 의 포함, '(마감)')
                "총", "꼴", "포함", "이미", "마감", "행사", "페이", "머니", "비씨", "쿠폰", "적용", "적용시", "경품"}
# 이름에서 빼도 상품이 같은 '제조사' (이름이 일반명사뿐이면 남김: '오뚜기 피자' ≠ '피자')
# PB·상품 라인(곰곰·비비고·노브랜드·피코크…)과 원재료 업체(동원·사조·하림·풀무원)는 상품을 가르므로 넣지 않음
_BRANDS = {
    "농심", "오뚜기", "삼양", "삼양식품", "팔도", "오리온", "롯데", "롯데웰푸드", "롯데제과", "롯데칠성",
    "롯데칠성음료", "해태", "해태제과", "크라운", "빙그레", "맥심", "동서", "동서식품", "종근당", "종근당건강",
    "cj", "씨제이", "cj제일제당", "코카콜라사", "삼성전자", "애플", "apple", "크리스피크림", "질레트",
}
_GENERIC = {
    "피자", "만두", "교자", "왕교자", "물만두", "계란", "달걀", "우유", "두부", "참치", "햄", "소시지", "라면", "우동",
    "생수", "물", "김치", "김", "쌀", "햅쌀", "커피", "과자", "아이스크림", "콜라", "사이다", "주스", "맥주", "치킨",
    "닭가슴살", "삼겹살", "목살", "고등어", "갈비", "갈비탕", "육개장", "짜장", "짬뽕", "떡볶이", "볶음밥", "휴지",
    "물티슈", "세제", "샴푸", "치약", "기저귀", "마스크", "모니터", "마우스", "키보드", "이어폰", "충전기", "케이블",
    "두유", "요거트", "커피믹스", "믹스커피", "스틱", "캔디", "젤리", "초콜릿", "비타민", "오메가3", "유산균", "면도기",
    "칫솔", "화장지", "키친타월", "선물세트", "세트", "컵", "제로",
}
_SYNONYM = {"오리지널": "오리지날", "컵라면": "컵", "봉지라면": "", "사발면": "사발", "툼바": "투움바",
            "제로슈거": "제로", "제로슈가": "제로", "zero": "제로", "프로": "pro", "울트라": "ultra", "맥스": "max",
            "아이스": "iced", "ice": "iced", "핫": "hot", "닌텐도스위치": "스위치", "switch": "스위치",
            "플레이스테이션5": "ps5", "플스5": "ps5", "엑스박스": "xbox", "리터": "l",
            "제주삼다수": "삼다수", "메가mgc커피": "메가커피", "refurbished": "refurb"}
_PLATFORM = r"ps[45]|ns[12]?|nsw|스위치2?|xbox|xsx|pc|스팀|1|2"

# ---------- 수량·용량 ----------
# 포장 단위 (개수). 'ea'·'p'·'t' 는 숫자 바로 뒤, 앞이 영문자가 아닐 때만 (PS5 EA SPORTS 오인식 방지)
_PACK_UNITS = r"개입|개|입|봉지|봉|팩|병|캔|can|페트|pet|박스|box|세트|set|통|컵|족|켤레|마리|판|구|스틱|ea|p|t"
_CONTENT_UNITS = r"캡슐|정|포|매|롤|알|장|티백|환|겹"
_SIZE_UNITS = r"kg|g|ml|l|리터|cc"
_LABEL = {"개입": "개", "입": "개", "ea": "개", "p": "개", "봉지": "봉", "can": "캔", "페트": "병", "pet": "병",
          "box": "박스", "set": "세트", "t": "스틱"}
_CONTENT_LABEL = {"정": "알", "환": "알", "장": "매", "티백": "티백"}   # 정당 → '알당' (정당=political party 오독 방지)
_BOXY = {"박스", "세트"}                                         # 개당 비교 시 낱개와 섞지 않음
_NB = r"(?<![a-z\d.,~\-])"                                       # 앞이 영문/숫자가 아님

_PLUS_N = re.compile(rf"(?<![\d+])(\d{{1,2}})\s*\+\s*(\d{{1,2}})(?![\d+])(?:\s*({_PACK_UNITS})(?![a-z가-힣]))?", re.I)
_SAME_PLUS = re.compile(rf"(\d+(?:\.\d+)?)\s*({_SIZE_UNITS})\s*\+\s*\1\s*\2(?:\s*\+\s*\1\s*\2)*(?![a-z])", re.I)
_TOTAL = re.compile(rf"총\s*(\d+)\s*({_PACK_UNITS}|{_CONTENT_UNITS})(?![a-z]|월)", re.I)   # '총 2개월분' 은 개수 아님
_TOTAL_SIZE = re.compile(rf"총\s*(\d+(?:\.\d+)?)\s*({_SIZE_UNITS})(?![a-z])", re.I)
_MUL = re.compile(
    # 앞이 영문자면 모델명 (272F900 X24 의 900 X24 는 곱셈 아님)
    rf"(?<![\d.a-z])(\d+(?:\.\d+)?)\s*({_SIZE_UNITS}|{_CONTENT_UNITS}|{_PACK_UNITS})?\s*[x×*]\s*(\d+)\s*({_PACK_UNITS}|{_CONTENT_UNITS})?(?![a-z\d])",
    re.I,
)
_MUL_BARE = re.compile(rf"(?:^|\s)[x×*](\s*)(\d+)\s*({_PACK_UNITS}|{_CONTENT_UNITS})?(?![a-z\d])", re.I)
_COUNT = re.compile(rf"{_NB}(\d+)\s*({_PACK_UNITS})(?![a-z가-힣])", re.I)
_CONTENT = re.compile(rf"{_NB}(\d+)\s*({_CONTENT_UNITS})(?![a-z가-힣])", re.I)
# 앞이 영문자면 모델명 (MP273L·OLED65G6·LS32FG500 의 273L·65G 는 용량 아님). 'x3kg' 의 x 는 곱셈이라 허용
# 뒤에 숫자가 바로 붙으면 숫자로 시작하는 모델명 (R-5: 27G810A·32G620B·25G523B 의 27G 는 27g 아님)
_SIZE = re.compile(rf"(?<![\d.,a-wyz])(\d+(?:\.\d+)?)\s*({_SIZE_UNITS})(?![a-z\d])", re.I)
_RANGE = re.compile(r"(?<![a-z\d])\d+\s*[-~]\s*\d+\s*[가-힣a-z]*", re.I)            # 3~4인분 (등급 범위는 _GRADE 로 먼저 보존)
# 수산·과일 크기 등급 '9~10미'·'11-12과'·'6미~7미' → '9_10미' 토큰으로 키에 남김 (~ 와 - 는 같게)
_GRADE = re.compile(r"(?<![\d.])(\d{1,3})\s*(?:미|과|수)?\s*[-~]\s*(\d{1,3})\s*(미|번과|과|수)(?:(?![가-힣a-z])|(?=내외|이내|내))", re.I)
# 하이픈 모델번호 (HV9272-001, E14-700, DDR5-5200, LTP-V007L-7B1DF): 영문자+숫자 조각이 있으면 하이픈을 지우고 한 토큰으로
_HYPHEN_MODEL = re.compile(r"(?<![a-z\d])[a-z\d]+(?:-[a-z\d]+)+(?![a-z\d])", re.I)
# 크기 '40x60'·'65X50'·'1,800x800' (단위 없는 두 수가 모두 20 이상) → 개수 아님, '40_x_60' 토큰으로 보존
_DIMS = re.compile(r"(?<![\d.,a-z])(\d{1,3}(?:,\d{3})+|\d{2,4})\s*[x×*]\s*(\d{1,3}(?:,\d{3})+|\d{2,4})(?![\d,.]|\s*(?:mm|cm|m)?\s*(?:개|입|팩|봉|캔|병|ea|p|매|롤|포|정|캡슐|구|g|ml|kg|l|can|박스|통|세트|장|t)(?![a-z]))", re.I)
_GLUED_COUNT = re.compile(rf"(\d(?:\.\d+)?(?:kg|g|ml|l))(?=\d+\s*(?:{_PACK_UNITS}|{_CONTENT_UNITS})(?![a-z가-힣]))", re.I)   # '2L30병' → '2L 30병', '2g200포'
# 함께 묶어 파는 일이 드문 개별 라면 이름: 2개 이상 나오면 여러 상품 나열 (신라면 너구리 짜파게티)
_RAMEN = ("신라면", "너구리", "짜파게티", "안성탕면", "새우탕", "육개장사발면", "삼양라면", "진라면", "열라면", "짜왕",
          "사리곰탕", "무파마", "오징어짬뽕", "비빔면", "불닭볶음면")
_EGG = re.compile(r"란|계란|달걀|egg", re.I)
# R-5 스펙 문맥
_MARK = "zq"                                                     # 스펙 토큰 표시 (영문자라 _SIZE 앞 검사에 걸림)
_DIGITAL = re.compile(r"\d\s*[gt]b|ssd|hdd|nvme|(?<![a-z])ram|램|메모리|갤럭시|아이폰|iphone|galaxy|스마트폰|휴대폰|핸드폰|"
                      r"아이패드|ipad|태블릿|갤럭시\s*탭|노트북|조립\s*pc|(?<![a-z])pc(?![a-z방])|자급제|usb|micro\s*sd|sd\s*카드|"
                      r"\d+\s*g\s+\d{3,4}\s*g(?![a-z\d])|외장\s*하드|라이젠|ryzen|인텔|intel|rtx|gtx|그래픽|공기계|맥북|맥\s*미니|스위치|ps5|xbox|스팀\s*덱", re.I)
_MOBILE = re.compile(r"갤럭시|아이폰|iphone|galaxy|스마트폰|휴대폰|핸드폰|폴드|플립|자급제|공기계|요금|알뜰|유심|lte|"
                     r"(?<![a-z])(?:skt|kt|lg\s*u\+?)(?![a-z])|태블릿|갤럭시\s*탭|아이패드|라우터|모뎀|에그|데이터", re.I)
_APPLIANCE = re.compile(r"(?:냉장고|냉동고|제습기|가습기|에어\s*프라이어|에프라이어|세탁기|건조기|오븐|음식물\s*처리기|분쇄기|"
                        r"전기\s*포트|커피\s*포트|블렌더|믹서기?|밥솥|정수기|청소기|백팩|배낭|가방|캐리어|쿨러백|보냉백|"
                        r"아이스\s*박스|쿨러|김치통|텐트|에어컨|전기\s*레인지|전자\s*레인지|식기\s*세척기|비데|온수기|보온병|텀블러|"
                        r"쿠커|라면\s*포트|저압\s*냄비|압력\s*냄비|블랜더|쌀통|김치\s*톡톡|워시\s*콤보|워시\s*타워)(?!\s*용)", re.I)
# 가전 이름이 있어도 소모품이면 무게·부피 비교가 맞음 ('식기세척기용 세제 550g', '건조기 시트')
_APPLIANCE_NOT = re.compile(r"세제|세정제|세척제|클리너|필터|탈취제|섬유\s*유연제|시트|봉투|리필|원두|캡슐|방향제|"
                            r"정리\s*용기|소금|린스|코팅제", re.I)
_RESOLUTION = {"720", "1080", "1440", "2160", "4320"}
# 증정품 문구 (문맥 판단에서 뺌): '(쿨러백 증정)', '쿨러백1개 증정', '+ 텀블러 증정'
_GIFT_CTX = re.compile(r"[(\[][^()\[\]]*(?:증정|사은품)[^()\[\]]*[)\]]|\S+\s*(?:\d+\s*개\s*)?(?:증정|사은품)", re.I)
# 모델번호 후보: 영문·숫자가 섞이고 숫자가 2개 이상인 4글자 이상 토큰 (단위 표기는 제외)
_MODEL_TOKEN = re.compile(r"(?<![a-z\d.])(?=[a-z\d]*[a-z])(?=(?:[a-z]*\d){2})[a-z\d]{4,}(?![a-z\d])", re.I)
_UNIT_TOKEN = re.compile(r"\d+(?:kg|ml|l|g|gb|tb|hz|w|mah|cm|mm|v|p|k|in1|x\d+)|x\d+|\d+x\d+", re.I)


@dataclass
class ProductInfo:
    name: str
    key: str
    alt_key: str
    count: Optional[int] = None
    size: Optional[str] = None
    size_g: Optional[int] = None
    unit: Optional[str] = None
    label: str = "개"
    usize: Optional[float] = None
    base: Optional[str] = None
    content: Optional[int] = None
    content_unit: Optional[str] = None
    cond: bool = False

    def unit_price(self, price: Optional[int]) -> Optional[int]:
        """이 글 하나만 볼 때의 기본 단가 (unit 기준)."""
        if price is None or self.unit is None:
            return None
        if self.unit == "개":
            n = self.count or self.content
            return round(price / n) if n else None
        return round(price * 100 / self.size_g) if self.size_g else None

    @property
    def unit_label(self) -> str:
        if self.count:
            return self.label
        if self.content:
            return self.content_unit or "개"
        return "개"


def _to_g(num: str, unit: str) -> tuple[float, str]:
    """용량을 g 또는 ml 수치(소수 유지)와 그 단위로."""
    v, u = float(num), unit.lower()
    if u == "kg":
        return v * 1000, "g"
    if u in ("l", "리터"):
        return v * 1000, "ml"
    return v, ("g" if u == "g" else "ml")


def _fmt_size(amount: float, base: str) -> str:
    if amount >= 1000 and amount % 100 == 0:
        return f"{amount / 1000:g}{'kg' if base == 'g' else 'L'}"
    return f"{amount:g}{base}"


def _label(u: str) -> str:
    u = u.lower()
    return _LABEL.get(u, u)


def _clabel(u: str) -> str:
    return _CONTENT_LABEL.get(u, u)


def _is_shop(tag: str) -> bool:
    parts = [p.strip().lower() for p in re.split(r"[/,·]", tag) if p.strip()]
    if not parts:
        return True
    if parts[0] in _SHOPS or _SHOP_PAT.search(parts[0]):
        return True                                  # [쿠팡/와우회원] [마소스토어/엑박] → 앞이 판매처면 통째로
    return all(p in _SHOPS or p in _CATEGORIES or _SHOP_PAT.search(p) or _COND.search(p) or "회원" in p
               or re.fullmatch(r"\d+시|[\d/~\-. ]+", p) for p in parts)


def _clean_truncated(title: str) -> str:
    """루리웹 등 잘린 제목: 끝의 '...' 과 닫히지 않은 괄호 뒤 조각을 버림."""
    t = title.rstrip()
    trunc = bool(re.search(r"(?:\.{2,}|…)$", t))
    t = re.sub(r"(?:\.{2,}|…)$", "", t).rstrip()
    depth, last_open = 0, -1
    for i, ch in enumerate(t):
        if ch in "([【（":
            if depth == 0:
                last_open = i
            depth += 1
        elif ch in ")]】）":
            depth = max(0, depth - 1)
    if depth > 0 and last_open >= 0:
        t = t[:last_open]
    elif trunc:
        # 괄호 없이 잘렸으면 마지막 (잘린) 조각이 가격·배송 잔여물일 때만 버림
        t = re.sub(r"[\s/]+[\d,./원만]*$", "", t) if re.search(r"[\s/][\d,./원만]+$", t) else t
    return t


# 게임 스토어 말머리는 플랫폼 정보 → 제목에 플랫폼 단어가 없으면 토큰으로 남김 ([스팀] FC26 ≠ [닌텐도e숍] FC26)
_STOREFRONT = {"스팀": "pc", "steam": "pc", "에픽": "pc", "에픽게임즈": "pc", "epic": "pc", "gog": "pc", "gmg": "pc",
               "그린맨게이밍": "pc", "gamersgate": "pc", "스토브": "pc", "인벤게임즈": "pc", "다이렉트게임즈": "pc",
               "psn": "ps", "ps스토어": "ps", "플레이스테이션스토어": "ps", "xbox": "xbox", "ms스토어": "xbox",
               "마소스토어": "xbox", "닌텐도e숍": "ns", "닌텐도e샵": "ns", "닌텐도이샵": "ns", "닌텐도스토어": "ns",
               "닌텐도 스토어": "ns", "한국닌텐도": "ns", "ios": "ios", "앱스토어": "ios", "android": "android",
               "플레이스토어": "android", "구글플레이": "android"}
_HAS_PLATFORM = re.compile(r"ps[45]|(?<![a-z])ns[12]?(?![a-z])|스위치|switch|xbox|엑박|(?<![a-z])pc(?![a-z])|ios|android|플스", re.I)


def _strip_lead(t: str) -> tuple[str, list[str]]:
    """맨 앞 말머리 처리. 판매처면 지우고, 그 외(브랜드·매장)는 이름 토큰으로 돌려줌."""
    kept: list[str] = []
    platform = None
    for _ in range(4):
        m = _LEAD_TAG.match(t) or _LEAD_PAREN_TAG.match(t)
        if not m:
            break
        tag = m.group(2) if m.re is _LEAD_TAG else m.group(1)
        if _SKIP_TAG.search(tag):
            return "", ["__skip__"]
        first = re.split(r"[/,·]", tag)[0].strip().lower()
        if first in _STOREFRONT and platform is None:
            platform = _STOREFRONT[first]
        if not _is_shop(tag):
            kept.append(tag)
        t = t[m.end():]
    if platform and not _HAS_PLATFORM.search(t) and not any(_HAS_PLATFORM.search(k) for k in kept):
        kept.insert(0, platform)
    return t, kept


# ---------- 영어 제목 (dealnews 등) ----------
_EN_SALE = re.compile(
    r"\b(?:sale|deals?|clearance|doorbusters?|savings|specials|event|promo\s*code|coupon|offer|sitewide|"
    r"up\s*to|at\s*least|off\s*everything|buy\s*more|bogo|buy\s*(?:one|\d+)\s*,?\s*get|gift\s*cards?|egift|"
    r"membership|account|apy|subscription|bundles?|items)\b|\$\s*[\d,]+s\b|\d+\s*%\s*off", re.I)
_EN_TAIL = re.compile(
    r"\s*\+\s*(?:free\s+)?(?:shipping|delivery|same\s*day|pickup|email|delivered|in-store)[^+]*$|"
    r"\s*\+\s*free\s+(?:shipping|delivery|gifts?)[^+]*|"
    r"\s*\bw/\s*(?:prime|plus|trade-?in|\$\s*[\d,.]+)\b|\s*\bon\s+orders?\s+(?:over\s+)?\$[\d,.]+\+?|"
    r"\s*\bfor\s+(?:from\s+)?\$\s*[\d,]+(?:\.\d+)?|\s*\bfrom\s+\$\s*[\d,]+(?:\.\d+)?", re.I)


def _english(t: str) -> Optional[str]:
    """한글이 없는 영어 제목: 배송·가격 꼬리를 지우고, 세일 공지면 None."""
    if _EN_SALE.search(t):
        return None
    prev = None
    while prev != t:
        prev, t = t, _EN_TAIL.sub(" ", t)
    t = re.sub(r"\bw/\s*", " with ", t, flags=re.I)
    t = re.sub(r"(\w)'s\b", r"\1s", t)
    t = re.sub(r"(\d+)\s*-?\s*packs?\b", r" \1개 ", t, flags=re.I)       # 3-Pack → 3개
    t = re.sub(r"\b(\d+(?:\.\d+)?)\s*-?\s*(?:inch|in\.|\")", r" \1인치 ", t, flags=re.I)
    return t


def _normalize(t: str) -> str:
    """키 규칙 정규화 (R2): 같은 상품의 다른 표기를 하나로."""
    t = re.sub(r"(?<![가-힣])코크(?=\s|제로|라이트|$|[^가-힣])", "코카콜라 ", t)   # 코크제로=코카콜라 제로 (피코크·초코크림 제외)
    t = re.sub(r"제주\s*삼다수", "삼다수", t)
    t = re.sub(r"메가\s*mgc\s*커피", "메가커피", t, flags=re.I)
    t = re.sub(r"난각\s*(?:번호)?\s*(\d)\s*번", r"난각\1번", t)
    t = _GLUED_COUNT.sub(r"\1 ", t)
    t = re.sub(r"([a-z]\d{0,3})\+(?=\s|$|[^\d\s+])", r"\1plus", t, flags=re.I)   # 갤럭시탭 S10+·FE+ (묶음 아님)
    return t


def _model_sub(m) -> str:
    tok = m.group(0)
    if re.search(r"[a-z]\d", tok, re.I) or re.match(r"[a-z]{2,}-\d", tok, re.I):
        return tok.replace("-", "")                   # 모델번호는 한 토큰 (키에 남음). 'SL-1000G'(파워)도 모델명 → 1000g 아님 (R-5)
    return tok


def _dims_sub(m) -> str:
    a, b = m.group(1).replace(",", ""), m.group(2).replace(",", "")
    if int(a) >= 30 and int(b) >= 30:
        return f" {a}_x_{b} "
    return m.group(0)


def _specs(t: str) -> str:
    """R-5: 무게·부피처럼 보이지만 스펙인 숫자를 이름 토큰으로 바꿈 (키에 남아 다른 스펙은 다른 상품).
    · 디지털 문맥의 저장용량 '512g'·'16G' → '512gb', '1T' → '1tb'
    · 휴대폰·요금 문맥의 '5G'·'LTE 4G' → 통신 규격 토큰 '5g'
    · '2.4G'·'5.8G' 무선 → '2.4ghz'
    · 가전·가방 용량 '832L 냉장고'·'20L 제습기'·'21kg 세탁기'·'34L 백팩' → '20l' 스펙 (100ml당 비교 안 함)
    _MARK 를 앞에 붙인 토큰은 _SIZE 가 용량으로 읽지 않고, 이름 만들 때 _MARK 를 뗀다."""
    t = re.sub(r"(?<![\d.,a-z])(2\.4|5\.8)\s*g(?![a-z\d])", lambda m: f" {m.group(1)}ghz ", t, flags=re.I)
    # 문맥 판단은 증정품 문구를 뺀 글로 ('카스 330ml 24캔 +쿨러백1개 증정' 의 쿨러백은 상품이 아님)
    ctx = _GIFT_CTX.sub(" ", _FREEBIE.sub(" ", t))
    if _DIGITAL.search(ctx):
        t = re.sub(r"(?<![\d.,a-z])(8|16|32|64|128|256|512)\s*g(?![a-z\d])", lambda m: f" {m.group(1)}gb ", t, flags=re.I)
        t = re.sub(r"(?<![\d.,a-z])([1248])\s*t(?![a-z\d])", lambda m: f" {m.group(1)}tb ", t, flags=re.I)
    if _MOBILE.search(ctx):
        t = re.sub(r"(?<![\d.,a-z])([345])\s*g(?![a-z\d])", lambda m: f" {_MARK}{m.group(1)}g ", t, flags=re.I)
    if _APPLIANCE.search(ctx) and not _APPLIANCE_NOT.search(ctx):
        # 모델번호(DQ205PBBC·WF21T6000KW·E310)가 있으면 용량은 모델이 이미 정함 → 키에서 뺌
        # ('LG 제습기 DQ205PBBC' = 'LG 제습기 20L DQ205PBBC'). 모델이 없을 때만 용량이 상품을 가름 (13L ≠ 20L)
        has_model = any(not _UNIT_TOKEN.fullmatch(x) for x in _MODEL_TOKEN.findall(t))

        def cap(m):
            if has_model:
                return " "
            u = m.group(2).lower()
            return f" {_MARK}{m.group(1)}{'kg' if u == 'kg' else 'ml' if u == 'ml' else 'l'} "
        t = re.sub(r"(?<![\d.,a-wyz])(\d+(?:\.\d+)?)\s*(kg|ml|l|리터)(?![a-z\d])", cap, t, flags=re.I)
        # '21kg+21kg'·'3.8L / 1.4L' 처럼 스펙끼리 잇는 + / 는 묶음·옵션 나열이 아님
        t = re.sub(rf"(?<=[a-z])\s*[+/]\s*(?={_MARK})", " ", t)
    return t


def _protect(t: str) -> str:
    """수량 해석 전에 숫자가 든 '이름' 조각을 보호: 등급 범위·하이픈 모델번호·크기·스펙(R-5)."""
    t = _GRADE.sub(lambda m: f" {m.group(1)}_{m.group(2)}{m.group(3)} ", t)
    t = _HYPHEN_MODEL.sub(_model_sub, t)
    t = _DIMS.sub(_dims_sub, t)
    t = _specs(t)
    return t


def _too_many(t: str) -> bool:
    """여러 상품 나열 글인가 (F-001)."""
    if sum(1 for r in _RAMEN if r in t) >= 2:
        return True
    if re.search(r"\d\s*원\s*,\s*[\d,]+\s*원", t):
        return True                                   # '(… 22,590원, 22,450원/무료)' 옵션별 가격
    # 가격이 2번 이상, 그 사이(쉼표·슬래시·마침표 뒤)에 다른 상품명
    prices = list(re.finditer(r"\d{1,3}(?:,\d{3})+\s*원|\d{3,}\s*원|\$\s*\d[\d,.]*|\d[\d,.]*\s*(?:\$|달러)", t))
    if len(prices) >= 2:
        for a, b in zip(prices, prices[1:]):
            mid = t[a.end():b.start()]
            if "(" in mid or ")" in mid:
                outside = re.search(r"\)(.*)\(", mid)      # '모니터($81), ZSUS 휴대용모니터($28)' → 괄호 사이 바깥 글자
                if not outside:
                    continue                              # 한쪽 가격만 괄호 안 ('(15,900원/무료) 쿠폰가 3,900원')
                mid = outside.group(1)
            words = re.sub(r"일반|카드사?|하나|국민|신한|삼성|현대|롯데|우리|농협|nh|kb|bc|씨티|토스|카카오|페이코|네이버|스마일|온누리|페이|쿠폰|와우|멤버십?|네멤|t멤|유클|스카|체감|최종|할인가?|정가|판매가|기존|원래|"
                           r"적용가?|결제|무료|무배|배송료|배송비?|택배비|우편비|추가|개당|프라임|→|->|에서|부터|시|가", " ", mid, flags=re.I)
            if re.search(r"[가-힣a-z]{2,}|[가-힣]", words, re.I):
                return True
    # '… 등' (괄호 밖) · '1,600원 등' → 여러 상품 ('한우 국거리, 불고기, 차돌박이 등', '뿌셔뿌셔 24개 등')
    body = re.sub(r"[(\[][^)\]]*[)\]]", " ", t)
    if re.search(r"(?<![가-힣\d])등(?=\s|$|[(\[/,])", body) or re.search(r"원\s*등(?![가-힣])", t):
        return True
    return False


# R3-2: '경품 이벤트' 는 상품 가격이 없을 때만 이벤트 글 ('GTA6 예약구매 경품 이벤트 (89,800원)' 은 상품)
_EVENT_ONLY = re.compile(r"경품\s*이벤트|경품\s*증정\s*이벤트", re.I)

# ---------- R4 가전: 모델번호로만 식별 ----------
# 가전(category.py 기준)이라도 소모품·부속품은 일반 규칙 (필터·세제·리필·거치대·케이블…)
_APPL_PART = re.compile(
    r"필터|세제|세정제|세척제|탈취제|클리너|코팅제|리필|거치대|케이블|봉투|브러시|브러쉬|소모품|부품|호환|교체용|"
    r"패드|더스트\s*백|먼지\s*봉투|커버|받침|선반|트레이|정리\s*용기|용기|리모컨|어댑터|배터리|호스|노즐|칫솔모|"
    r"면도날|(?<![가-힣])날(?![가-힣])|원두|캡슐(?!\s*(?:커피\s*)?머신)|시트|걸레|라이너|물통|전용(?!\s*(?:가전|모델))",
    re.I)
# 디지털·PC 성격이면 기존 규칙 (category 가 가전으로 봐도: 스마트모니터·노트북·폰 등)
_APPL_DIGITAL = re.compile(r"모니터|노트북|태블릿|스마트폰|휴대폰|(?<![가-힣])폰(?![가-힣])|이어폰|헤드폰|키보드|마우스|"
                           r"그래픽\s*카드|ssd|(?<![a-z])pc(?![a-z])|(?<![a-z])msi(?![a-z])|qd\s*-?\s*oled|wqhd|(?<![a-z])qhd|게이밍|"
                           r"(?:16[5-9]|1[7-9]\d|[2-9]\d\d)\s*hz|울트라\s*기어|ultragear|오디세이|odyssey|알파스캔|(?<![a-z])dell(?![a-z])|"
                           r"(?<![가-힣])델(?![가-힣])|그램|프리\s*도스|freedos|맥북|갤럭시\s*북|스탠바이미|"
                           # 모니터 모델 모양: LG 32GX870B·27GR95QE·27UP850N, 삼성 LS32FG500
                           r"(?<![a-z\d])\d{2}(?:g[a-z]|up|ul|mr|ba|bk|sr|ml|mp|uq)\d{2,3}[a-z]{0,3}(?![a-z\d])|(?<![a-z\d])ls\d{2}[a-z]", re.I)
# TV 신호: 'TV' 단어(한글 붙어도), Crystal UHD·Neo QLED·QNED·OLED evo, TV 모델 모양 (삼성 KU/KQ/QN/UN/LH##, LG OLED##·##UR/UT/QNED##)
_TV_WORD = re.compile(r"(?<![a-z])tv(?![a-z])|티비|텔레비전|crystal\s*uhd|크리스탈\s*uhd|neo\s*qled|네오\s*qled|(?<![a-z])qned|"
                      r"oled\s*evo|미니\s*엘이디|더\s*세리프|더\s*프레임|사이니지", re.I)
_TV_MODEL = re.compile(r"(?<![a-z\d])(?:(?:ku|kq|qn|un|lh|kq)\d{2}[a-z]{1,4}\d{2,4}[a-z]*|oled\d{2}[a-z]\d[a-z]*|"
                       r"\d{2}(?:ur|ut|uq|nano|qned|qn)\d{2,4}[a-z]*)(?![a-z\d])", re.I)
_TV_BRAND = re.compile(r"삼성|samsung|(?<![a-z])lg(?![a-z])|엘지|tcl|하이센스|hisense|소니|sony|샤오미|xiaomi|필립스|이노스|더함|프리즘", re.I)
# 모델번호 후보 (영문+숫자, 하이픈·점 허용). 최소 모양: 4글자 이상·영문 1개 이상·숫자 2개 이상 (E310·T17DX3),
# 또는 6글자 이상·숫자 1개 (DUE4BGE). 단위·스펙 표기(21kg·852L·280W·163cm·2in1·144Hz·30000Pa·IPX7)는 제외.
# 7글자 미만 모델은 다른 회사 같은 번호와 섞이지 않게 '브랜드:모델' 로 키를 만든다
_MODEL_CAND = re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9]+(?:[-.][A-Za-z0-9]+)*(?![A-Za-z0-9])")
_NOT_MODEL = re.compile(r"\d+(?:\.\d+)?(?:kg|g|ml|l|cm|mm|m|w|kw|wh|pa|rpm|hz|khz|v|mah|db|in1|p|k|cc|ea|t|gb|tb|"
                        r"lm|mhz|ghz|x\d+)|\d+(?:x|in)\d+|x\d+|\d{4}(?:년)?|[a-z]?\d+(?:/\d+)+.*|ipx?\d+|usb\d*|wifi\d*|pm\d+", re.I)
_BRAND_SKIP = {"mini", "new", "ai", "the", "neo", "led", "oled", "qled", "tv", "pro", "max", "ultra", "plus", "신형", "신제품",
               "비스포크", "bespoke", "오브제", "오브제컬렉션", "디오스", "트롬", "휘센", "그랑데", "본사직영", "공식", "원격"}


# 빠른 1차 거름: category.py 의 가전 단어가 하나도 없으면 가전일 수 없음 (categorize 전체 계산을 아낌)
_APPL_WORDS = [rx for cat, strong, weak in _CAT_RULES if cat == "가전" for rx in (strong, weak)] +               [rx for rx, cat in _CAT_DECISIVE if cat == "가전"]


def _is_tv(title: str) -> bool:
    if _TV_WORD.search(title) or _TV_MODEL.search(title):
        return True
    # '인치' + TV 브랜드 + 긴 모델번호 ('하이센스 85인치 85Q6N…' 처럼 TV 단어 없는 글)
    return bool(re.search(r"\d\s*인치", title) and _TV_BRAND.search(title)
                and any(len(re.sub(r"[-.]", "", m.group(0))) >= 5 and re.search(r"\d.*[a-z]|[a-z].*\d", m.group(0), re.I)
                        for m in _MODEL_CAND.finditer(title)))


def _is_appliance(title: str) -> bool:
    """가전 판단 (부속품 여부는 parse_product 에서 모델번호와 함께 봄). 모니터·노트북 등 디지털 신호가 있으면 가전 아님."""
    if _APPL_DIGITAL.search(title):
        return False
    if _is_tv(title):
        return True                                   # TV 는 'TV' 단어 없이도 가전 (Crystal UHD·KU65MH75AFXKR)
    low = title.lower()
    if not any(rx.search(low) for rx in _APPL_WORDS):
        return False
    body = title
    for _ in range(4):                               # 판매처 말머리([하이마트몰] → 디지털 점수)는 빼고 제목만으로 판단
        m = _LEAD_TAG.match(body)
        if not m:
            break
        body = body[m.end():]
    return categorize(body) == "가전"


def _norm_model(tok: str) -> str:
    tok = tok.split(".")[0] if re.search(r"\.[A-Za-z]{2,}$", tok) else tok   # 'B502S53.AKOR' → 지역 꼬리 제거
    parts = tok.split("-")
    if len(parts) > 1 and re.fullmatch(r"[A-Za-z]{1,3}", parts[-1]) and re.search(r"\d", "".join(parts[:-1])):
        parts = parts[:-1]                                                    # 'DQ205PBBC-B' 같은 색상 꼬리
    return "".join(parts).replace(".", "").upper()


def _appliance_model(raw: str, toks: list[str]) -> Optional[str]:
    """가전 제목의 모델번호 → 키 'M:<모델>' (짧은 모델은 'M:<브랜드>:<모델>'). 없거나 여러 모델이 섞였으면 None."""
    body = re.sub(r"[(\[][^()\[\]]*(?:\d\s*원|\$|무료|무배|카드)[^()\[\]]*[)\]]", " ", raw)   # 가격·배송 괄호
    body = re.sub(r"\d[\d,]*\s*원|\$\s*[\d,.]+", " ", body)
    found: list[str] = []
    for m in _MODEL_CAND.finditer(body):
        tok = m.group(0).strip(".-")
        flat = re.sub(r"[-.]", "", tok)
        nd = sum(ch.isdigit() for ch in flat)
        if len(flat) < 4 or not re.search(r"[A-Za-z]", flat) or nd == 0 or (nd == 1 and len(flat) < 6):
            continue
        if _NOT_MODEL.fullmatch(flat) or _NOT_MODEL.fullmatch(tok):
            continue
        norm = _norm_model(tok)
        if norm not in found:
            found.append(norm)
    if not found:
        return None
    found.sort(key=len, reverse=True)
    best = found[0]
    for other in found[1:]:
        # 시리즈명(MH80·Q9000)은 긴 모델번호에 묻힘. 길이가 비슷한 다른 모델이 또 있으면 묶음/택1 → 애매
        if other not in best and len(other) >= 6 and len(other) >= 0.7 * len(best):
            return None
    if len(best) >= 7:
        return f"M:{best}"
    brand = next((w for w in toks if re.search(r"[가-힣a-z]", w) and w not in _BRAND_SKIP
                  and _norm_model(w) != best and not re.search(r"\d", w)), "")
    brand = {"엘지": "lg", "삼성전자": "삼성", "lg전자": "lg"}.get(brand, re.sub(r"전자$", "", brand))
    if not brand:
        return None
    return f"M:{brand}:{best}"                       # 짧은 모델(T17DX3·W21WAM)은 브랜드와 함께 (다른 회사 같은 번호 방지)


def parse_product(title: str) -> Optional[ProductInfo]:
    if not title:
        return None
    raw = _clean_truncated(title)
    if _ROUTE.search(raw):
        return None
    english = not re.search(r"[가-힣]", raw)
    if english:
        raw = _english(raw)
        if raw is None:
            return None
    t, lead = _strip_lead(raw)
    if lead == ["__skip__"] or _SKIP_TAG.search(t[:12]):
        return None                                   # 말머리 뒤 본문 첫머리의 '네이버페이' 등 (C-1-5)
    # 브랜드 말머리가 본문 첫머리와 같으면 한 번만 ('[스파클] 스파클 생수', '[제주삼다수]삼다수')
    squash = lambda x: re.sub(r"\s+", "", _normalize(x)).lower()
    lead = [k for k in lead if not squash(t).startswith(squash(k))]
    t = " ".join(lead + [t])
    cond = bool(_COND.search(title))
    if _SKIP.search(t) or _too_many(raw):
        return None
    if _EVENT_ONLY.search(t) and not re.search(r"\d[\d,]*\s*원|\$\s*\d|\d+(?:\.\d+)?\s*만\s*원?", raw):
        return None
    t = _normalize(t)
    t = _protect(t)
    pct_free = _PCT_OK.sub(" ", t)
    if _PCT.search(pct_free):
        return None
    t = _PCT_OK.sub(" ", t)
    t = _FREEBIE.sub(" ", t)                        # '+ 텀블러 증정' 은 증정품 → 버림
    t = _SAME_PLUS.sub(lambda m: f" {m.group(1)}{m.group(2)} x {m.group(0).count('+') + 1} ", t)
    # 괄호: 가격·배송·조건 괄호는 버리고, 나머지(65인치·120g X 20개·2박스)는 따로 모아 보조로 사용
    parens: list[str] = []

    def _paren(m):
        inner = m.group(1)
        if _PRICEISH_PAREN.search(inner) and not re.search(rf"\d\s*(?:{_SIZE_UNITS}|{_PACK_UNITS})\s*[x×*]", inner, re.I):
            return " "
        parens.append(inner)
        return " \x00 "
    t = _PAREN.sub(_paren, t)
    t = re.sub(r"[\[\]()【】（）]", " ", t)
    t = re.sub(r"/\s*[\d,]+(?=\s|$)", " ", t)          # '/3000' (배송비 잔여)
    t = _COND_PAY_WORD.sub(" ", t)                  # '카카오14,940원' → 금액과 함께 결제수단 단어도 지움 (C-2-4)
    t = re.sub(r"/*\s*(?:" + _PRICE_TXT.pattern + r")\s*/*", " ", t)
    t = re.sub(r"판에", "판 ", t)
    # 플랫폼 나열 'PS4/NS', 'NS2/1', '스위치, PS5' → 한 상품
    t = re.sub(rf"(?<![a-z])({_PLATFORM})\s*[/,]\s*({_PLATFORM})(?![a-z\d])", r"\1 \2", t, flags=re.I)
    t = re.sub(r"\s/\s*$|^\s*/\s|\s/\s(?=[^가-힣a-z]*$)", " ", t)   # 가격 지운 뒤 남은 '/'
    plus_free = _PLUS_N.sub(" ", t)
    if "+" in plus_free or re.search(r"[가-힣a-z]\s*/\s*[가-힣a-z]", plus_free, re.I):
        return None

    main = t.lower()
    paren_txt = [p.lower() for p in parens]
    egg = bool(_EGG.search(main) or any(_EGG.search(p) for p in paren_txt))
    q = _quantities(main, egg)
    work = q.pop("rest")
    for ptxt in paren_txt:                          # 괄호 안 수량은 바깥에 없는 정보만 보충
        pq = _quantities(ptxt, egg)
        prest = pq.pop("rest")
        if "+" in ptxt:
            pq["count"] = None                        # '(2개입+1개입)'·'(밀크18입+초코18입)' 은 구성 설명 → 곱하지 않음
        if pq.get("total_fixed"):                     # '(총 4팩)'·'(총4병)' → 바깥 개수·N+M 보다 우선
            q["total_fixed"] = True
            if pq.get("count"):
                q["count"], q["label"], q["count_fixed"] = pq["count"], pq["label"], True
                pq["count"] = None
        if q.get("count") and pq.get("count") and pq.get("count_is_inner") and not q.get("count_is_inner") \
                and not q.get("count_fixed") and not (q.get("count_from_mul") and q.get("usize")):
            # (단 '(10입) 415g x 2개' 처럼 바깥이 '용량 x 개수' 면 괄호 개입수는 곱하지 않음)
            q["count"] *= pq["count"]                 # '멀티팩(5개입) 4팩' → 20개
            pq["count"] = None
        for k in ("count", "usize", "total", "content", "ucontent"):
            if k == "count" and (q.get("content") or q.get("ucontent")):
                continue                            # '400매(200X2)' → 괄호의 200x2 는 내용물 설명
            if q.get(k) is None and pq.get(k) is not None:
                q[k] = pq[k]
                if k == "count":
                    q["label"] = pq["label"]
                    q["count_inner"] = pq.get("count_inner")
                if k in ("usize", "total"):
                    q["base"] = pq["base"]
                if k == "total":
                    q["total_is_unit"] = pq.get("total_is_unit")
                if k in ("content", "ucontent"):
                    q["cunit"] = pq["cunit"]
        work = work.replace("\x00", " " + prest + " ", 1)
    work = work.replace("\x00", " ")

    count = q.get("count")
    usize, total, base = q.get("usize"), q.get("total"), q.get("base")
    content, ucontent, cunit = q.get("content"), q.get("ucontent"), q.get("cunit")
    mult = q.get("mult", 1)
    size_after_inner = q.get("size_after_inner", False)

    # N+M: 개수가 있으면 배수, 없으면 N+M 개
    if mult > 1 and not q.get("total_fixed"):
        if count:
            if count != mult:                       # '20+20, 40PET'·'1+1 2개'·'5개 4+1' → 적힌 수가 이미 총수
                count *= mult
        else:
            count = mult
            if usize is None and total is not None:
                usize, total = total, None
    # 개당 용량 ↔ 총량
    if count and usize is None and total is not None and q.get("total_is_unit"):
        usize, total = total, None
    if count and usize is not None:
        if size_after_inner:                        # '24개입, 960g, 1개' → 960g 은 바깥 1개의 용량
            outer = q.get("outer") or 1
            total = total or usize * outer
            usize = total / count
        elif total is None:
            total = usize * count
    if count is None and usize is not None and total is None:
        total, usize = usize, None
    if ucontent and count:
        content = content or ucontent * count
    elif ucontent and not count:
        content = content or ucontent
    if count is not None and (count <= 0 or count > 5000):
        count = None
    if content is not None and (content <= 0 or content > 100000):
        content = None

    # ── 상품명
    work = _PROMO.sub(" ", work)
    toks = []
    for w in re.sub(r"[^\w가-힣.]+", " ", work).split():
        w = w.strip("._").replace("_x_", "x").replace("_", "~")
        if w.startswith(_MARK):
            w = w[len(_MARK):]                        # _specs 가 보호한 스펙 토큰 ('20l', '5g')
        w = _SYNONYM.get(w, w)
        if not w or w in _STOP_TOKENS:
            continue
        toks.append(w)
    all_toks = list(toks)                             # 브랜드 포함 (가전 짧은 모델 키용)
    brandless = [w for w in toks if w not in _BRANDS]
    core = [w for w in brandless if not re.fullmatch(r"[\d.]+", w)]
    if brandless and core and not all(w in _GENERIC for w in core) and len("".join(core)) >= 2:
        toks = brandless
    if not toks or len("".join(toks)) < 2 or not re.search(r"[가-힣a-z]", "".join(toks)):
        return None
    name = " ".join(toks)

    size_txt = None
    if usize is not None:
        size_txt = _fmt_size(round(usize, 2), base or "g")
    elif ucontent and count:
        size_txt = f"{ucontent}{_clabel(cunit)}"
    if count:
        unit = "개"
    elif total:
        unit = "100ml" if base == "ml" else "100g"
    elif content:
        unit = "개"
    else:
        unit = None
    key = "".join(toks)
    alt_key = " ".join(sorted(toks))
    if _is_appliance(title):
        # R4 (사용자 결정, CLAUDE.md '상품 식별 방침'): 가전은 모델번호로만 같은 상품. 모델번호가 없으면 기록 안 함
        model = _appliance_model(raw, all_toks)
        part = _APPL_PART.search(_GIFT_CTX.sub(" ", title))
        if part and model is None:
            pass                                      # 모델 없는 소모품·부속품 (필터·세제…) → 일반 규칙
        elif model is None or (count or 0) > 1:
            return None                               # 모델 없음·여러 모델 묶음·여러 대 묶음 → 비교 불가
        else:
            return ProductInfo(name=name, key=model, alt_key=model, cond=cond)
    return ProductInfo(
        name=name, key=key, alt_key=alt_key, count=count, size=size_txt,
        size_g=round(total) if total else None, unit=unit, label=q.get("label") or "개",
        usize=round(usize, 3) if usize is not None else None, base=base if (usize or total) else None,
        content=content, content_unit=_clabel(cunit) if (content and cunit) else None, cond=cond,
    )


def _quantities(work: str, egg: bool) -> dict:
    """문자열에서 수량·용량을 뽑고 지운 나머지(rest)와 함께 돌려줌."""
    out: dict = {"count": None, "label": None, "usize": None, "total": None, "base": None,
                 "content": None, "ucontent": None, "cunit": None, "mult": 1}

    def is_count_unit(u: str) -> bool:
        return bool(re.fullmatch(_PACK_UNITS, u, re.I))

    # N+M
    for m in list(_PLUS_N.finditer(work)):
        a, b, u = int(m.group(1)), int(m.group(2)), m.group(3)
        if u and u.lower() not in ("p", "t") and not (u == "구" and not egg):
            out["count"] = (out["count"] or 1) * (a + b) if out["count"] else a + b
            out["label"] = _label(u)
        else:
            out["mult"] *= a + b
        work = work.replace(m.group(0), " ", 1)
    work = _RANGE.sub(" ", work)

    m = _TOTAL_SIZE.search(work)
    if m:
        out["total"], out["base"] = _to_g(m.group(1), m.group(2))
        work = work.replace(m.group(0), " ", 1)
    m = _TOTAL.search(work)
    if m:
        n, u = int(m.group(1)), m.group(2)
        if re.fullmatch(_CONTENT_UNITS, u, re.I):
            out["content"], out["cunit"] = n, u
        else:
            out["count"], out["label"] = n, _label(u)
            out["count_fixed"] = True
        out["total_fixed"] = True                    # '총 N' 은 이미 1+1 이 반영된 값
        work = work.replace(m.group(0), " ", 1)

    for m in list(_MUL.finditer(work)):
        a, ua, b, ub = m.group(1), m.group(2), int(m.group(3)), m.group(4)
        ua_l = (ua or "").lower()
        if ub and ub.lower() == "구" and not egg:
            continue
        if ua and re.fullmatch(_SIZE_UNITS, ua, re.I):          # 120g x 20 → 용량 120g, 20개
            if out["usize"] is None:
                out["usize"], out["base"] = _to_g(a, ua)
            n = b
        elif ua and re.fullmatch(_CONTENT_UNITS, ua, re.I):     # 40매 x 9팩 → 내용물 40매, 9팩
            out["ucontent"], out["cunit"] = int(float(a)), ua_l
            n = b
        elif ua:                                                 # 4입 x 5 → 20개
            n = int(float(a)) * b
        else:
            if "." in a or float(a) > 5000:
                continue
            n = int(float(a)) * b
        if ub and re.fullmatch(_CONTENT_UNITS, ub, re.I) and not (ua and is_count_unit(ua)):
            if out["ucontent"] is None and out["content"] is None:
                if ua and re.fullmatch(_SIZE_UNITS, ua, re.I):   # 2g x 50포 → 50포, 포당 2g
                    out["count"] = out["count"] or n
                    out["label"] = out["label"] or _clabel(ub.lower())
                else:
                    out["content"], out["cunit"] = n, ub.lower()
            work = work.replace(m.group(0), " ", 1)
            continue
        if out["count"] is None:
            out["count"] = n
            out["label"] = _label(ub) if ub else (_label(ua) if ua and is_count_unit(ua) else "개")
            out["count_from_mul"] = True
        work = work.replace(m.group(0), " ", 1)
    for m in list(_MUL_BARE.finditer(work)):                  # '딸기 * 8개', 'mx30롤'
        gap, n, u = m.group(1), int(m.group(2)), m.group(3)
        prev = work[:m.start()].split()[-1:] or [""]
        nxt = work[m.end():].split()[:1] or [""]
        if not u and ((not gap and (n >= 100 or re.match(r"[a-z]", nxt[0]))) or (re.search(r"[a-z]\d|\d[a-z]", prev[0])
                                                 and not re.fullmatch(rf"[\d.]+(?:{_SIZE_UNITS})", prev[0]))):
            continue                                  # 'X3700'(블랙박스)·'말코닉 X64 SD'·'272F900 X24' → 모델명
        if u and re.fullmatch(_CONTENT_UNITS, u, re.I):
            if out["ucontent"] is None:
                out["ucontent"], out["cunit"] = n, u.lower()
        elif out["count"] is None:
            out["count"], out["label"] = n, _label(u) if u else "개"
        work = work.replace(m.group(0), " ", 1)

    # 남은 개수 표기
    packs = []
    for m in _COUNT.finditer(work):
        n, u = m.group(1), m.group(2).lower()
        if u == "구" and not egg:
            continue                                  # 멀티탭 3구·인덕션 3구 = 스펙
        if u == "p" and (n in _RESOLUTION or int(n) > 500):
            continue
        if u == "t" and int(n) < 10:
            continue                                  # 1T(테라) 등
        if u == "판" and not egg:
            continue
        packs.append((int(n), u, m.start(), m.group(0)))
    # '365스틱 … 100포 2박스' → '365스틱' 은 제품명 (내용물 '포' 와 함께면 스틱을 개수로 쓰지 않음)
    if any(u == "스틱" for _, u, _, _ in packs) and re.search(rf"{_NB}\d+\s*포(?![a-z가-힣])", work):
        packs = [p for p in packs if p[1] != "스틱"]
    # 'Nkg M입' (과일 등) → 총 무게 N kg 에 M개 (개당 N kg 아님)
    if len(packs) == 1 and packs[0][1] == "입" and out["usize"] is None:
        mk = re.search(rf"(?<![\d.,a-wyz])(\d+(?:\.\d+)?)\s*kg\s*,?\s*{packs[0][0]}\s*입", work, re.I)
        if mk:
            out["kg_total"] = True
    # 괄호 밖에서 이미 개수를 알면 '2박스' 같은 겉포장 수는 곱하지 않음 (괄호는 따로 처리)
    if packs and out["count"] is None:
        inner = [p for p in packs if p[1] in ("개입", "입", "p")]
        # '150입, 9팩' → 150 은 내용물(매), 9팩이 개수
        if inner and len(packs) > 1 and inner[0][0] >= 60 and out["ucontent"] is None:
            out["ucontent"], out["cunit"] = inner[0][0], "매"
            packs = [p for p in packs if p is not inner[0]]
            inner = []
        out["count_is_inner"] = all(u in ("개입", "입") for _, u, _, _ in packs)
        cnt, seen_l, seen_n = 1, set(), set()
        for n, u, _, _ in packs:
            lu = "개" if u in ("ea",) else u
            if lu in seen_l or n in seen_n:
                continue                              # '40입 40개'·'200개 / 15개' → 같은 수·같은 단위는 한 번만
            seen_l.add(lu)
            seen_n.add(n)
            cnt *= n
        out["count"] = cnt
        lab = [u for _, u, _, _ in packs if u not in ("개입", "입", "개", "ea", "p", "박스", "box", "세트", "set", "판")]
        egg_u = [u for _, u, _, _ in packs if u == "구"]
        out["label"] = "구" if egg_u else (_label(lab[0]) if lab else _label(packs[0][1]))
        if len(packs) == 1 and packs[0][1] in _BOXY | {"box", "set"}:
            out["label"] = _label(packs[0][1])
        if inner:
            out["inner_pos"] = inner[0][2]
            outer = [n for n, u, _, _ in packs if u not in ("개입", "입", "p")]
            out["outer"] = 1
            for n in outer:
                out["outer"] *= n
    elif packs and out["count"] is not None and not out.get("count_fixed"):
        # 'x 20' 으로 이미 개수를 얻었고 '5개입 X 3팩' 처럼 겉 개수만 남은 경우는 무시
        pass
    for _, _, _, txt in packs:
        work = work.replace(txt, " ", 1)
    work = _COUNT.sub(lambda m: m.group(0) if (m.group(2) == "구" and not egg) or m.group(2).lower() in ("p", "t") else " ", work)

    # 내용물
    contents = [(int(n), u.lower()) for n, u in _CONTENT.findall(work)]
    work = _CONTENT.sub(" ", work)
    if contents and out["ucontent"] is None and out["content"] is None:
        rolls = [c for c in contents if c[1] == "롤"]
        n, u = rolls[0] if rolls else contents[0]
        if u == "겹":
            pass
        elif out["count"]:
            out["ucontent"], out["cunit"] = n, u
        else:
            out["content"], out["cunit"] = n, u

    # 용량
    sizes = [(m.start(), *_to_g(m.group(1), m.group(2))) for m in _SIZE.finditer(work)]
    work = _SIZE.sub(" ", work)
    if sizes and out["usize"] is None:
        pos, g, base = sizes[0]
        if out["total"] is not None:
            if out["count"]:
                out["usize"] = g
        elif out["count"] and len(sizes) >= 2 and any(
                s2[2] == base and abs(g - s2[1] * out["count"]) <= 0.01 * g for s2 in sizes[1:]):
            # '2kg 500g4팩' → 총 2kg = 500g × 4 (첫 용량이 총량, R3)
            small = next(s2 for s2 in sizes[1:] if s2[2] == base and abs(g - s2[1] * out["count"]) <= 0.01 * g)
            out["usize"], out["total"], out["base"] = small[1], g, base
        elif out["count"] and out.get("kg_total") and base == "g" and g >= 1000:
            out["total"], out["base"] = g, base       # '썬골드키위 5.73kg 41입' → 총 5.73kg
        elif out["count"]:
            out["usize"], out["base"] = g, base
            if out.get("inner_pos") is not None and pos > out["inner_pos"]:
                out["size_after_inner"] = True
        else:
            out["total"], out["base"] = g, base
            out["total_is_unit"] = True
    out["rest"] = work
    return out
