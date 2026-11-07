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

PARSER_VERSION = 4  # 키 규칙이 바뀌면 올린다 → History.load 가 모든 기록을 다시 분류

# ---------- 비교 대상이 아닌 글 ----------
_SKIP = re.compile(
    r"기프트\s*카드|기프트\s*코드|상품권|금액권|교환권|\d+\s*만\s*원?\s*권|\d[\d,]*\s*원\s*권|모바일\s*쿠폰|"
    r"요금제|이용권|구독|리딤|일시\s*무료|무료\s*배포|할인\s*코드|쿠폰\s*(?:팩|북|받기|발급|배포|모음|이벤트)|"
    r"택\s*1|골라\s*담기|모음|종합|외\s*\d*\s*종|\d+\s*종\s*(?:세트|중)|전\s*모델|전\s*품목|라이브|live|"
    r"예고|안내|추천|후기|질문|아시는\s*분|세일|패키지|숙박|항공|티켓|입장권|왕복|편도|직항|경유|노선|"
    r"\b외\b|\s외\s|\s외$|중\s*택|"
    r"라방|랜덤\s*\d|클릭\s*적립|일일\s*적립|적립\s*\d|알림\s*(?:받기|신청)|팔로우|출석|(?<![가-힣])퀴즈|만보기|"
    r"\d+\s*원\s*딜|판매\s*예정|출시\s*예정|발매\s*예정|인하\s*예정|예약\s*(?:시작|오픈|예정|안내)|"
    # F-001 여러 상품 나열 신호: '(다양/무료)', '상품별상이', '1,683,300원~' (가격 범위 = 여러 옵션)
    r"[(\[]\s*다양\s*/|상품별\s*상이|\d\s*원\s*~(?!\s*\d)|"
    # C-1-5 네이버페이 N원 적립 (현장결제·이벤트 적립)
    r"(?:네이버\s*페이|네페)[^()]{0,40}?\d[\d,]*\s*원?\s*적립",
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
    r"u\s*클럽|카할가|카드\s*할인가",
    re.I,
)

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
_FREEBIE = re.compile(r"\+\s*[^+]*?(?:증정|사은품|서비스|덤)\)?", re.I)
_PROMO = re.compile(
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
    r"적용\s*시|적용가|(?<![가-힣])공식(?:인증점|스토어|몰|홈|수입사|판매처|대리점)?(?![가-힣])|총?\s*\d+\s*개월\s*분",
    re.I,
)
_STOP_TOKENS = {"x", "×", "*", "or", "등", "및", "외", "토스", "페이코", "kb", "카드", "가격", "딜", "구매", "판매", "중",
                "개당", "할인가", "최종", "특전포함", "can", "ea", "pet", "페트", "box", "캔", "병", "봉",
                # R2: 잔여어 (판매처 이름이 본문에 섞인 경우 포함)
                "박스", "한박스", "29cm", "내외", "내", "이내", "다양", "쿠팡", "지마켓", "g마켓", "11번가", "옥션", "롯데온",
                "ssg", "컬리", "테무", "temu", "알리", "위시", "추가", "맛선택", "묶음", "이상", "네맴", "넾다", "당일도정",
                # F-003 영어 불용어
                "for", "with", "the", "and", "of", "by"}
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
_SIZE = re.compile(rf"(?<![\d.,a-wyz])(\d+(?:\.\d+)?)\s*({_SIZE_UNITS})(?![a-z])", re.I)
_RANGE = re.compile(r"(?<![a-z\d])\d+\s*[-~]\s*\d+\s*[가-힣a-z]*", re.I)            # 3~4인분 (등급 범위는 _GRADE 로 먼저 보존)
# 수산·과일 크기 등급 '9~10미'·'11-12과'·'6미~7미' → '9_10미' 토큰으로 키에 남김 (~ 와 - 는 같게)
_GRADE = re.compile(r"(?<![\d.])(\d{1,3})\s*(?:미|과|수)?\s*[-~]\s*(\d{1,3})\s*(미|번과|과|수)(?:(?![가-힣a-z])|(?=내외|이내|내))", re.I)
# 하이픈 모델번호 (HV9272-001, E14-700, DDR5-5200, LTP-V007L-7B1DF): 영문자+숫자 조각이 있으면 하이픈을 지우고 한 토큰으로
_HYPHEN_MODEL = re.compile(r"(?<![a-z\d])[a-z\d]+(?:-[a-z\d]+)+(?![a-z\d])", re.I)
# 크기 '40x60'·'65X50'·'1,800x800' (단위 없는 두 수가 모두 20 이상) → 개수 아님, '40_x_60' 토큰으로 보존
_DIMS = re.compile(r"(?<![\d.,a-z])(\d{1,3}(?:,\d{3})+|\d{2,4})\s*[x×*]\s*(\d{1,3}(?:,\d{3})+|\d{2,4})(?![\d,.]|\s*(?:mm|cm|m)?\s*(?:개|입|팩|봉|캔|병|ea|p|매|롤|포|정|캡슐|구|g|ml|kg|l|can|박스|통|세트|장|t)(?![a-z]))", re.I)
_GLUED_COUNT = re.compile(rf"(\d(?:\.\d+)?(?:kg|g|ml|l))(?=\d+\s*(?:{_PACK_UNITS})(?![a-z가-힣]))", re.I)   # '2L30병' → '2L 30병'
# 함께 묶어 파는 일이 드문 개별 라면 이름: 2개 이상 나오면 여러 상품 나열 (신라면 너구리 짜파게티)
_RAMEN = ("신라면", "너구리", "짜파게티", "안성탕면", "새우탕", "육개장사발면", "삼양라면", "진라면", "열라면", "짜왕",
          "사리곰탕", "무파마", "오징어짬뽕", "비빔면", "불닭볶음면")
_EGG = re.compile(r"란|계란|달걀|egg", re.I)
_RESOLUTION = {"720", "1080", "1440", "2160", "4320"}


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
    if re.search(r"[a-z]\d", tok, re.I):
        return tok.replace("-", "")                   # 모델번호는 한 토큰 (키에 남음)
    return tok


def _dims_sub(m) -> str:
    a, b = m.group(1).replace(",", ""), m.group(2).replace(",", "")
    if int(a) >= 30 and int(b) >= 30:
        return f" {a}_x_{b} "
    return m.group(0)


def _protect(t: str) -> str:
    """수량 해석 전에 숫자가 든 '이름' 조각을 보호: 등급 범위·하이픈 모델번호·크기."""
    t = _GRADE.sub(lambda m: f" {m.group(1)}_{m.group(2)}{m.group(3)} ", t)
    t = _HYPHEN_MODEL.sub(_model_sub, t)
    t = _DIMS.sub(_dims_sub, t)
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
        w = _SYNONYM.get(w, w)
        if not w or w in _STOP_TOKENS:
            continue
        toks.append(w)
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
