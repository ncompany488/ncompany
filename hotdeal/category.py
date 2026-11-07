"""딜 제목·게시판 분류·판매처로 카테고리 하나를 고른다.

categorize(title, source_category, shop) -> CATEGORIES 중 하나 (모르면 "기타")

방식 (점수 합산, 가장 높은 카테고리):
  1) 제목 키워드  — 강한 단어 3점, 보통 단어 2점 (카테고리마다 서로 다른 단어 수만큼)
  2) 원본 게시판 분류 — 사이트 분류 문자열을 후보 카테고리로 바꿔 2점 (애매한 분류는 후보 여럿에 1점)
     · 뽐뿌 '기타'·클리앙 '상품정보' 처럼 정보가 없는 분류는 0점
  3) 판매처·말머리 — [무신사]·[올리브영] 등 2점, 플랫폼 말머리 [스팀]·[닌텐도]·[iOS]·[WearOS] 는 3.5점
  3') 결정적 단어 6점 — 커피머신·냉장고·전기요(가전), 노트북(디지털, PC부품 점수 제거), 강아지·고양이(유아·반려)
  4) 사이트 기본값 — 어미새(패션 게시판) 0.5점
동점이면 CATEGORIES 순서가 앞인 쪽. 점수가 모두 0 이면 "기타".
"""
from __future__ import annotations

import re
from typing import Optional

CATEGORIES = ("식품", "생활", "가전", "디지털", "PC부품", "게임", "패션", "뷰티", "유아·반려",
              "스포츠·레저", "여행·티켓", "상품권·포인트", "기타")

# ---------- 1) 제목 키워드 ----------
# (강한 단어, 보통 단어). 한글은 부분 일치, 영문(ascii)만으로 된 단어는 단어 경계로 일치.
_KW: dict[str, tuple[str, str]] = {
    "상품권·포인트": (
        r"모바일\s*금액|"
        r"상품권|기프트\s*카드|기프트\s*코드|기프티콘|e\s*쿠폰|모바일\s*쿠폰|금액권|교환권|\d+\s*만\s*원\s*권|"
        r"컬쳐랜드|해피머니|북앤라이프|문화상품권|gift\s*cards?|egift|일일\s*적립|클릭\s*적립|"
        r"네이버\s*페이|네페|토스\s*포인트|페이코\s*포인트|캐시워크|오퀴즈|퀴즈\s*정답|랜덤\s*\d+\s*원|라방",
        r"포인트|적립|캐시백|쿠폰|넾다|할인\s*코드|promo\s*code|savings\s*account|cashback",
    ),
    "여행·티켓": (
        r"항공권|항공|호텔|리조트|숙박|펜션|투어|입장권|티켓|왕복|편도|직항|렌터카|렌트카|워터파크|"
        r"오션월드|에버랜드|롯데월드|movie\s*tickets?|flights?|hotels?|cruise|airfare|"
        r"(?:인천|김포|김해|제주|부산)\s*-\s*[가-힣]{2,}|\b\d{4}\s*-\s*\d{4}\b",
        r"여행|패키지|cgv|메가박스|롯데시네마|롯시|예매|관람|공연|뮤지컬|콘서트|전시|travel|vacation",
    ),
    "게임": (
        r"스트리트\s*파이터|psvr|포르자|게이머즈|p의\s*거짓|포코피아|"
        r"라스트\s*오브\s*어스|툼\s*레이더|tomb\s*raider|balatro|발라트로|"
        r"스팀|steam|ps5|ps4|플스|플레이\s*스테이션|playstation|닌텐도|nintendo|스위치\s*2?|switch|"
        r"엑스박스|xbox|에픽\s*게임즈|epic\s*games|에픽\s*모바일|게임|games?|gaming\s*handheld|dlc|"
        r"젤다|마리오|포켓몬|몬스터\s*헌터|파이널\s*판타지|드래곤\s*퀘스트|스팀\s*덱|steam\s*deck|"
        r"rog\s*(?:xbox\s*)?ally|레전드\s*에디션|디럭스\s*에디션|한정판|에디션|타이틀|"
        r"\(ns2?\)|건담|hguc|프라모델|피규어|레고|lego|보드\s*게임|키캡\s*특전|topps|trading\s*cards?|게임\s*패스|리뎀션",
        r"아미보|amiibo|컨트롤러|듀얼센스|조이콘|패드|toys?|collectibles?",
    ),
    "PC부품": (
        r"미니\s*pc|(?<!\d)\d{4}x3d|"
        r"(?:ddr[45])|(?<!\d)[45]0[6-9]0(?!\d)|igame|"
        r"ssd|nvme|hdd|하드\s*디스크|외장\s*하드|ddr[45]|램\b|ram\b|그래픽\s*카드|그래픽카드|rtx\s*\d|gtx\s*\d|"
        r"라데온|radeon|rx\s*\d{4}|지포스|geforce|인텔\s*아크|arc\s*b\d+|cpu|라이젠|ryzen|코어\s*울트라|core\s*ultra|"
        r"i[579]-\d{4,5}|메인\s*보드|메인보드|파워\s*서플라이|\d{3,4}\s*w\s*(?:80|골드|플래티넘)|"
        r"cpu\s*쿨러|수랭|공랭|쿨러|케이스\s*팬|pc\s*케이스|미들\s*타워|빅\s*타워|"
        r"모니터|monitor|게이밍\s*모니터|키보드|keyboard|기계식|마우스|mouse|트랙볼|마우스\s*패드|"
        r"데스크탑|desktop|완본체|본체|nas|공유기|랜카드|웹캠|\d{2}\s*인치\s*(?:qhd|fhd|uhd)|qhd|"
        r"\d{3}\s*hz|\d{2,3}hz|필라멘트|3d\s*프린터|3d\s*printers?",
        r"usb\s*허브|도킹|독\b|dock|모니터\s*암|폴대|어고트론|ergotron|레이저|razer|로지텍|logitech|"
        r"커세어|corsair|msi|asus|기가바이트|애즈락|asrock|팀그룹|teamgroup|wd\b|씨게이트|seagate|"
        r"마이크론|crucial|하이닉스|조립\s*pc",
    ),
    "디지털": (
        r"(?:skt|kt|lg|u\+|lgu\+)\s*망|평생\s*요금|데이터\s*\d+\s*(?:gb|기가)|통화\s*무제한|빅터스|victus|서피스|surface|"
        r"아이폰|iphone|갤럭시|galaxy|아이패드|ipad|맥북|macbook|맥\s*미니|mac\s*mini|imac|"
        r"노트북|laptop|chromebook|크롬북|태블릿|tablet|갤럭시\s*탭|y700|샤오신|"
        r"에어팟|airpods|버즈|이어폰|이어버드|earbuds|헤드폰|헤드셋|headphones?|headset|"
        r"스피커|speakers?|사운드바|soundbar|블루투스|bluetooth|"
        r"애플\s*워치|apple\s*watch|갤럭시\s*워치|스마트\s*워치|smart\s*watch|워치\s*페이스|watch\s*face|가민|garmin|"
        r"충전기|charger|충전\s*케이블|케이블|cable|보조\s*배터리|power\s*bank|\d+\s*mah|맥세이프|magsafe|"
        r"자급제|폴드\s*\d|플립\s*\d|z\s*fold|z\s*flip|스마트폰|smartphones?|휴대폰|phones?|"
        r"요금제|알뜰폰|유심|esim|esim|5g|lte|"
        r"카메라|camera|디카|액션캠|고프로|gopro|드론|drones?|프로젝터|projectors?|"
        r"마이크로\s*sd|microsd\w*|micro\s*sd|flir|열화상|sd\s*카드|메모리\s*카드|usb\s*메모리|"
        r"복합기|프린터|printer|잉크|토너|전자책|e북|킨들|kindle|이북\s*리더|"
        r"airtag|에어태그|스마트\s*태그|ios|android|wearos|watchos|앱\b|어플|apps?\b",
        r"애플|apple|삼성전자|샤오미|xiaomi|레노버|lenovo|hp\b|dell|델\b|에이서|acer|소니|sony|"
        r"브리츠|britz|보스|bose|마샬|marshall|jbl|젠하이저|에디파이어|edifier|앤커|anker|벨킨|belkin|ugreen|"
        r"c\s*to\s*c|a\s*to\s*c|8핀|라이트닝|usb|tv\s*box|streaming|tablet|vpn|software|소프트웨어|"
        r"오피스|office|windows|윈도우",
    ),
    "가전": (
        r"\btv\b|티비|텔레비전|oled|qled|mini\s*led|냉장고|김치\s*냉장고|세탁기|건조기|워시타워|"
        r"청소기|로봇\s*청소기|vacuum|robot\s*vacuum|에어컨|공기\s*청정기|air\s*purifiers?|가습기|제습기|"
        r"전자\s*레인지|에어\s*프라이어|air\s*fryer|오븐|밥솥|인덕션|하이라이트|전기\s*포트|커피\s*머신|"
        r"캡슐\s*머신|에스프레소\s*머신|식기\s*세척기|식세기|음식물\s*처리기|정수기|(?<!마이)비데|빌트인|컨버터블\s*패키지|"
        r"선풍기|서큘레이터|써큘레이터|히터|온풍기|난로|전기\s*요|전기\s*매트|온수\s*매트|탄소\s*매트|"
        r"드라이기|드라이어|고데기|헤어\s*드라이|전기\s*면도기|전동\s*칫솔|안마\s*의자|안마기|마사지기|massager|"
        r"블렌더|믹서기|착즙기|토스터|appliances?|refrigerator|washer|dryer|microwave|dishwasher|"
        r"오브제|비스포크|bespoke|다이슨|dyson|로보락|roborock|쿠쿠|쿠첸|위닉스|코웨이|캐치웰|"
        r"laundry|무선\s*청소기|스팀\s*다리미|다리미",
        r"가전|lg전자|삼성\s*가전|필립스|브라운|발뮤다|드롱기|돌체\s*구스토|네스프레소\s*머신|smart\s*tv",
    ),
    "뷰티": (
        r"폼\s*클렌|클랜징|포밍\s*워시|쉐이빙\s*폼|휘핑\s*폼|헤어\s*미스트|퍼퓸|"
        r"염색|새치|스팟\s*패치|여드름|듀오덤|속눈썹|눈썹|"
        r"화장품|콘택트\s*렌즈|투명\s*렌즈|컬러\s*렌즈|원데이\s*렌즈|스킨\s*케어|스킨케어|토너|로션|에센스|세럼|앰플|크림|선크림|선\s*스크린|썬크림|"
        r"클렌징|클렌저|폼\s*클렌|클렌징\s*오일|마스크\s*팩|마스크팩|시트\s*마스크|립밤|립스틱|틴트|"
        r"파운데이션|쿠션\s*팩트|팩트|아이\s*섀도|마스카라|네일|향수|perfume|fragrances?|오드\s*퍼퓸|"
        r"샴푸|린스|컨디셔너|트리트먼트|헤어\s*에센스|바디\s*로션|바디\s*워시|바디워시|핸드\s*크림|"
        r"바세린|니베아|설화수|이니스프리|라네즈|아이오페|프리메라|에스트라|토리든|라운드랩|아누아|"
        r"올리브영|탈모\s*샴푸|염색약|헤어\s*오일|데오드란트|skincare|cosmetics?|makeup|lotion",
        r"뷰티|beauty|personal\s*care|피부|보습|미백|주름|기초\s*\d?\s*종|맨\s*기초",
    ),
    "패션": (
        r"워킹화|팔토시|"
        r"슬립온|프로스펙스|리복|reebok|메트로시티|마리떼|로고\s*티|"
        r"순면\s*트렁크|트렁크\s*\d+\s*(?:매|장|개)|슈펜|락포트|슬링\b|아디제로|아디오스|슈즈|"
        r"패딩|다운\s*자켓|다운\s*점퍼|롱\s*다운|롱\s*패딩|구스\s*다운|자켓|재킷|점퍼|코트|블루종|후리스|플리스|"
        r"후드|후디|맨투맨|스웨터|니트|가디건|셔츠|티셔츠|반팔|긴팔|청바지|바지|팬츠|슬랙스|조거|레깅스|"
        r"치마|스커트|원피스|드로즈|런닝(?!\s*(?:화|머신|벨트|조끼))|민소매|속옷|팬티|브라|양말|삭스|내복|히트텍|발열\s*내의|"
        r"신발|운동화|스니커즈|러닝화|런닝화|등산화|트레킹화|방한화|부츠|슬리퍼|샌들|로퍼|구두|클로그|"
        r"가방|백팩|크로스백|토트백|지갑|벨트|모자|비니|와치캡|볼캡|장갑|목도리|머플러|넥워머|"
        r"시계|watches?|선글라스|sunglasses|안경|레이벤|ray-?ban|오클리|oakley|옷\b|옷\.|backpacks?|bags?\b|fanatics|jewelry|목걸이|귀걸이|반지|팔찌|"
        r"나이키|nike|아디다스|adidas|뉴발란스|new\s*balance|푸마|puma|휠라|fila|아식스|asics|호카|hoka|"
        r"크록스|crocs|스케쳐스|컨버스|반스|노스페이스|north\s*face|컬럼비아|columbia|네파|블랙야크|"
        r"k2|아이더|디스커버리|몽벨|파타고니아|patagonia|아크테릭스|유니클로|uniqlo|탑텐|스파오|지오다노|"
        r"무신사|29cm|w컨셉|폴로|polo|ralph\s*lauren|타미|캘빈\s*클라인|calvin\s*klein|리바이스|levi'?s|"
        r"lululemon|룰루레몬|under\s*armour|언더아머|j\.?crew|clothing|apparel|jackets?|coats?|"
        r"hoodies?|sweaters?|jeans|pants|shirts?|t-shirts?|shoes|sneakers?|boots|joggers|shorts|"
        r"cardigan|overcoat|hat|headwear|jerseys?|rrl|스투시|stussy|빔즈|beams|단톤|ma-1",
        r"의류|잡화|남성용|여성용|남녀\s*공용|키즈\s*(?:패딩|점퍼|부츠)|아울렛|outlet",
    ),
    "유아·반려": (
        r"플레이모빌|토이저러스|"
        r"기저귀|분유|이유식|젖병|유모차|카시트|아기띠|아기|유아|영유아|신생아|베이비|baby|babies|"
        r"어린이|키즈\s*(?:프로바이오틱스|유산균|비타민)|장난감|완구|토이|레고\s*듀플로|다마고치|다마고찌|"
        r"세이펜|한글\s*자석|교구|그림책|동화책|playard|bassinet|"
        r"강아지|반려견|애견|고양이|반려묘|애묘|캣|cat\s*(?:feeder|litter|food)|dog\s*food|사료|간식\s*(?:강아지|고양이)|"
        r"츄르|모래\s*(?:고양이|벤토)|배변\s*패드|펫|pets?|petco",
        r"키즈|kids|아동|주니어",
    ),
    "스포츠·레저": (
        r"구명\s*조끼|아쿠아\s*슈즈|물놀이|"
        r"캠핑|텐트|타프|침낭|코펠|버너|랜턴|아이스\s*박스|쿨러\s*백|낚시|골프|golf|자전거|bike|bicycl|"
        r"전기\s*자전거|킥보드|스키|보드복|수영복|수경|요가\s*매트|요가|필라테스|덤벨|바벨|케틀벨|"
        r"헬스|홈트|트레드밀|treadmill|walking\s*pad|런닝\s*머신|러닝\s*머신|실내\s*자전거|"
        r"resistance\s*bands?|exercise|fitness|sporting\s*goods|등산\s*스틱|스포츠|basketball",
        r"아웃도어|outdoor|레저|스노우|러닝\s*(?:벨트|조끼)|sports",
    ),
    "생활": (
        r"시그니앙|베베숲|\d+\s*매\s*\d+\s*팩|"
        r"옷걸이|행주|치실|초극세모|트롤리|해충|포충기|압력솥|옷장|드레스룸|보온대|초퍼|분쇄기|"
        r"리필\s*봉투|매직캔|쓰레기\s*봉투|종량제|세정제|세척제|수저|디너\s*세트|식기\s*세트|포트메리온|빨래|바구니|장바구니|롤링\s*카트|바디\s*필로우|필로우|쿨링\s*시트|휴족시간|파스\b|찜질|쿨\s*패치|혈압계|체온계|우산|엔진\s*오일|\d+w-\d+|지팡이|리스테린|"
        r"화장지|휴지|두루마리|미용\s*티슈|티슈|물티슈|키친\s*타올|키친타올|키친\s*타월|"
        r"세제|캡슐\s*세제|세탁\s*세제|섬유\s*유연제|유연제|주방\s*세제|표백제|락스|배수구|청소포|물걸레|"
        r"수세미|고무장갑|지퍼백|위생\s*(?:장갑|백)|랩\b|호일|종이컵|빨대|"
        r"마이비데|샤프란|피죤|다우니|퍼실|테크|스파크|비트\b|"
        r"치약|칫솔|구강|가글|면도기|면도날|생리대|오버나이트|라이너|탐폰|마스크\b|kf94|"
        r"핫팩|손난로|수면\s*안대|안대|건전지|배터리\s*\d+\s*(?:알|개)|멀티탭|전구|led\s*등|"
        r"체중계|체지방|수건|타월|\d+\s*매\s*캡|평량|gsm|이불|베개|침구|매트리스|토퍼|침대|소파|의자|책상|테이블|선반|수납|행거|"
        r"칼갈이|숫돌|냄비|프라이팬|후라이팬|웍|도마|칼\s*세트|식기|그릇|접시|컵\b|머그|텀블러|보온병|밀폐\s*용기|"
        r"락앤락|글라스락|스탠리|stanley|코렐|해피콜|"
        r"방향제|디퓨저|탈취제|섬유\s*탈취|제습제|살충제|모기|"
        r"도어락|공구|드릴|전동\s*드릴|tools?|hardware|drill|chainsaw|ratchet|work\s*bench|"
        r"차량용|차량\s|자동차|타이어|와이퍼|블랙박스|tire\s*inflator|automotive|obd2|"
        r"클립보드|서류철|문구|볼펜|노트\b|다이어리|달력|calendar|책\b|도서|"
        r"캐리어|여행\s*가방|luggage|duffel|"
        r"furniture|decor|candle|kitchen|home\s*&\s*garden|household|comforter|duvet|bedding|"
        r"핸드\s*워시|핸드워시|손\s*세정제|비누|바디\s*타월|롤\b|\d+\s*롤",
        r"생활|생필품|주방|욕실|청소|세탁|홈|리빙|living|인테리어|조명|커튼|러그|매트\b",
    ),
    "식품": (
        r"스테이크|바베큐|평창수|백산수|아이시스|가자미|생선|필렛|홍차|밀크티|허니|꿀\b|육포|"
        r"진미채|오징어채|후랑크|프랑크|코엔자임|코큐텐|아르기닌|프리바이오틱스|오예스|몰티져스|자유시간|키스틱|에너지바|호올스|갈아만든배|삼다수|더말린|썬키스트|소다\b|나물|곤약|쭈꾸미|주꾸미|돼지|양념|도넛|요구르트|엔요|햄(?=\d)|진저\s*(?:샷|에일|라이저|티)|생강|"
        r"(?:\d\s*kg)\b|[가-힣]{1,3}배\s*(?:선물|\d|가정용|정품)|신고배|나주배|배즙|카프리썬|참마|곱창|전골|샤인\s*머스[캣켓]|꼬막|버팔로\s*스틱|치킨\s*스틱|시래기|[가-힣]국\b|얼박사|핫식스|박카스|비타\s*500|식혜|링티|미에로|레몬수|칸타타|후레쉬베리|양갱|츄러스|크래커|누룽지|쥐포|장어|굴비|조기|삼치|전어|홍어|박대|열기\b|아보카도|베리|파프리카|단호박|호박\b|밤호박|옥수수|햇밤|군밤|족발|순대|떡바|카무트|귀리|콘드로이친|침향|센트룸|오쏘몰|이뮨|뼈국|앞다리|뒷다리|로인립|쫄면|새청무|신동진|추청|고시히카리|경기미|수향미|오향미|라이프밀|쉐이크|선식|콜라|사이다|탄산|에너지\s*드링크|몬스터\s*에너지|레드불|포카리|게토레이|토레타|"
        r"라면|봉지면|컵라면|짜파게티|너구리|신라면|불닭|사발면|국수|냉면|막국수|우동|파스타|스파게티|"
        r"쌀\b|햅쌀|백미|현미|잡곡|햇반|즉석밥|백미밥|떡\b|떡볶이|만두|교자|딤섬|샤오롱바오|"
        r"과자|스낵|칩\b|칩스|쿠키|비스킷|웨이퍼|와플|초콜릿|초코|캔디|사탕|젤리|구미|껌\b|빼빼로|"
        r"아이스크림|파인트|하겐다즈|투게더|빵\b|식빵|소금빵|베이글|케이크|시리얼|그래놀라|오트밀|"
        r"음료|탄산|탄산수|사이다|콜라|제로\s*콜라|펩시|코크|환타|주스|에이드|아이스티|이온\s*음료|"
        r"생수|물\s*\d+\s*(?:l|ml)|하늘\s*보리|수염차|헛개|\d+(?:\.\d+)?\s*l\s*\d+\s*(?:개|병|펫|입)|무침|명태|회\s*무침|커피(?!\s*(?:머신|메이커|스케일|그라인더))|커피믹스|원두|캡슐\s*커피|아메리카노|라떼|차\b|녹차|보리차|티백|"
        r"우유|두유|요거트|요구르트|치즈|버터|생크림|계란|달걀|유정란|무정란|구운란|란\s*\d+\s*구|"
        r"고기|한우|한돈|대패|삼겸살|소고기|돼지고기|삼겹살|목살|오겹살|항정살|갈비|등심|안심|차돌|우삼겹|불고기|제육|"
        r"닭|닭가슴살|치킨|닭갈비|오리|훈제|햄\b|소시지|베이컨|스팸|참치|연어|고등어|갈치|오징어|문어|낙지|"
        r"새우|꽃게|대게|홍게|킹크랩|크랩|전복|굴\b|조개|가리비|홍합|멸치|김\b|김부각|미역|다시마|황태|"
        r"과일|사과|배\s*\d|감귤|귤\b|한라봉|레드향|천혜향|오렌지|포도|샤인\s*머스캣|샤인머스켓|딸기|바나나|"
        r"키위|망고|복숭아|자두|수박|참외|멜론|블루베리|체리|대봉|단감|홍시|곶감|토마토|방울토마토|"
        r"채소|야채|고구마|감자|양파|마늘|대파|오이|배추|절임\s*배추|상추|시금치|버섯|당근|브로콜리|양배추|"
        r"김치|깍두기|반찬|젓갈|된장|고추장|간장|쌈장|고춧가루|케찹|케첩|마요네즈|소스|드레싱|식용유|"
        r"올리브\s*오일|참기름|들기름|설탕|소금|후추|육수|스톡|"
        r"밀키트|도시락|볶음밥|피자|돈까스|돈가스|떡갈비|함박|국밥|해장국|곰탕|육개장|찌개|탕\b|감자탕|"
        r"추어탕|미역국|짜장|짬뽕|카레|(?<!가)죽\b|스프|수프|만두|핫도그|어묵|맛살|"
        r"견과|아몬드|호두|땅콩|캐슈넛|피스타치오|프로틴|단백질|닭가슴살|"
        r"비타민|유산균|락토핏|생유산균|프로바이오틱스|오메가\s*3|마그네슘|아연|철분|루테인|밀크씨슬|홍삼|멜라토닌|콜라겐|"
        r"영양제|건강\s*기능|(?<![a-z\d])\d+\s*정\b|(?<![a-z\d])\d+\s*캡슐(?!\s*세제)|맥주|카스\b|카스\s*(?:올|제로|라이트|레몬)|테라\b|켈리\b|하이네켄|칭따오|소주|와인|위스키|막걸리|증류주|하이볼|"
        r"버거|와퍼|햄버거|맥도날드|버거킹|롯데리아|kfc|bbq|bhc|교촌|굽네|메가\s*커피|메가mgc|스타벅스|"
        r"빽다방|컴포즈|이디야|투썸|배스킨|던킨|파리바게뜨|뚜레쥬르|"
        r"오레오|밀카|뿌셔뿌셔|닥터\s*페퍼|오리온|농심|오뚜기|삼양|팔도|cj제일제당|비비고|풀무원|동원|청정원|대상|롯데웰푸드|빙그레|매일유업|"
        r"남양|서울우유|해태|크라운|동서|맥심|프링글스|도리토스|꼬북칩|새우깡|"
        r"restaurants?|burgers?|pizza|nachos|food|snacks?|coffee|grocery",
        r"식품|먹거리|간식|건강|국내산|산지\s*직송|당도|brix|kg\b|\d+\s*캔\b",
    ),
}

_ASCII = re.compile(r"^[\x00-\x7f]+$")


def _split_top(pat: str) -> list[str]:
    """괄호 밖의 '|' 로만 나눔."""
    out, depth, cur, esc = [], 0, [], False
    for ch in pat:
        if esc:
            cur.append(ch)
            esc = False
            continue
        if ch == "\\":
            esc = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "|" and depth == 0:
            out.append("".join(cur))
            cur = []
            continue
        cur.append(ch)
    out.append("".join(cur))
    return out


_META = set("\\()[]{}?*+|.^$")


def _trie(words: list[str]) -> str:
    """글자 그대로인 단어들을 접두 트리 정규식으로 (수백 개 대안을 하나씩 시도하지 않게 — 속도)."""
    root: dict = {}
    for w in words:
        node = root
        for ch in w:
            node = node.setdefault(ch, {})
        node[""] = True

    def build(node: dict) -> str:
        end = "" in node
        branches = [re.escape(ch) + build(sub) for ch, sub in sorted(node.items()) if ch != ""]
        if not branches:
            return ""
        body = branches[0] if len(branches) == 1 else "(?:" + "|".join(branches) + ")"
        if end:   # 이 지점에서 끝나는 단어도 있음 → 더 긴 쪽 먼저, 없으면 여기서 끝
            return "(?:" + body + ")?"
        return body
    return build(root)


def _compile(pat: str) -> re.Pattern:
    """대안을 4묶음으로: 글자 그대로(한글 등) / 정규식 / 영문 단어(앞뒤 경계) / 영문 정규식(앞 경계만).
    제목은 소문자로 바꿔 넣는다 (re.I 보다 빠름)."""
    lit, rx, alit, arx = [], [], [], []
    for alt in _split_top(pat):
        alt = alt.strip()
        if not alt:
            continue
        plain = not (set(alt) & _META)
        # 영문 단어는 단어 경계 — 'ram' 이 'program' 에 걸리지 않게
        if _ASCII.match(alt) and re.match(r"^[a-z0-9]", alt):
            if plain:
                alit.append(alt)
            elif alt.endswith(("?", ")", "+", "*", r"\b")):
                arx.append(alt)
            else:
                arx.append(alt + r"(?![a-z])")
        elif plain:
            lit.append(alt)
        else:
            rx.append(alt)
    parts = []
    if lit:
        parts.append(_trie(lit))
    parts += rx
    if alit:
        parts.append(r"(?<![a-z0-9])" + _trie(alit) + r"(?![a-z])")
    if arx:
        parts.append(r"(?<![a-z0-9])(?:" + "|".join(f"(?:{p})" for p in arx) + ")")
    return re.compile("|".join(f"(?:{p})" for p in parts))


_RULES = [(cat, _compile(strong), _compile(weak)) for cat, (strong, weak) in _KW.items()]

# ---------- 2) 원본 게시판 분류 ----------
# 소문자·공백 제거한 분류 문자열 → 후보 (첫 번째가 기본)
_SRC: dict[str, tuple[str, ...]] = {
    # 뽐뿌 / 딜바다
    "식품/건강": ("식품",), "의류/잡화": ("패션",), "가전/가구": ("가전", "생활"), "디지털": ("디지털", "PC부품"),
    "컴퓨터": ("PC부품", "디지털"), "화장품": ("뷰티",), "가전": ("가전",), "육아": ("유아·반려",),
    "상품권": ("상품권·포인트",), "여행": ("여행·티켓",), "여행/티켓": ("여행·티켓",), "등산/캠핑": ("스포츠·레저",),
    "스포츠": ("스포츠·레저",), "게임": ("게임",), "서적": ("생활",), "pc관련": ("PC부품", "디지털"),
    "생활/육아": ("생활", "유아·반려"), "인터넷/전화": ("디지털",), "모바일/상품권": ("상품권·포인트", "디지털"),
    "해외": (), "기타": (), "일반": (), "이벤트": (),
    # 아카 라이브
    "식품": ("식품",), "전자제품": ("디지털", "가전", "PC부품"), "생활용품": ("생활",), "상품권/쿠폰": ("상품권·포인트",),
    "의류": ("패션",), "pc/하드웨어": ("PC부품",), "sw/게임": ("게임", "디지털"), "도서": ("생활",),
    # 루리웹
    "게임s/w": ("게임",), "게임h/w": ("게임", "PC부품"), "음식": ("식품",), "pc/가전": ("PC부품", "가전", "디지털"),
    "휴대폰": ("디지털",), "a/v": ("디지털",), "취미용품": ("게임",), "패션/의류": ("패션",), "의류/패션": ("패션",),
    "도서/음반": ("생활",), "보드게임": ("게임",), "프라모델": ("게임",),
    # 어미새 (판매처 구분이라 정보 없음)
    "국내": (), "네이버": (), "상품정보": (), "이벤트정보": (),
}
# dealnews 영문 분류 (부분 일치, 위에서부터)
_SRC_EN: list[tuple[str, tuple[str, ...]]] = [
    (r"gift\s*card", ("상품권·포인트",)), (r"financial|bank", ()),
    (r"luggage", ("생활",)), (r"musical|dvd|movie\s*rental|books?|music", ()),
    (r"movie\s*ticket|travel|flight|hotel|cruise|vacation", ("여행·티켓",)),
    (r"sports\s*souvenir", ("스포츠·레저", "패션")),
    (r"video\s*game|gaming|toys|hobbies|comics|collectibles|board\s*game", ("게임",)),
    (r"tool|hardware|drill|automotive", ("생활",)),
    (r"baby|babies|kids|pet", ("유아·반려",)),
    (r"monitor|desktop|computer\s*part|hard\s*drive|ssd|memory|graphics|keyboard|mice|trackball|3d\s*printer|"
     r"networking|router|processor|cpu", ("PC부품",)),
    (r"phone|iphone|tablet|ipad|laptop|macbook|apple\s*computer|headphone|speaker|soundbar|camera|drone|"
     r"projector|smart\s*watch|streaming|software|electronics|tv\s*accessor|audio|wearable", ("디지털",)),
    (r"\btvs?\b|appliance|vacuum|air\s*purifier|laundry|kitchen\s*appliance|refrigerator|heater|"
     r"smart\s*home", ("가전",)),
    (r"fragrance|beauty|skin|makeup|cosmetic|personal\s*care|hair\s*care|shaving", ("뷰티",)),
    (r"clothing|accessor|shoe|coat|jacket|jean|pant|shirt|short|sweater|activewear|watch|jewelry|glasses|"
     r"handbag|apparel|underwear|sock|hat", ("패션",)),
    (r"sport|fitness|exercise|bicycl|camping|outdoor\s*gear|golf|fishing", ("스포츠·레저",)),
    (r"restaurant|food|grocer|drink|beverage|coffee|snack", ("식품",)),
    (r"home|garden|furniture|tool|hardware|automotive|decor|kitchen|table|chair|supplies|party|seasonal|"
     r"holiday|household|cleaning|storage|drill|power|health|medicine|medical", ("생활",)),
]
_SRC_EN_RE = [(re.compile(p, re.I), c) for p, c in _SRC_EN]

# ---------- 3) 판매처·말머리 ----------
_SHOP: list[tuple[re.Pattern, str]] = [(re.compile(p, re.I), c) for p, c in [
    (r"스팀|steam|에픽|epic|그린맨|greenman|험블|humble|닌텐도|nintendo|플스|ps\s*스토어|psn|게임몰|겜우리|다이렉트게임즈|루트바|미니맵|"
     r"소프라노몰|아크시스템|xbox|반다이|bandai|디지털터치|전기종|공홈", "게임"),
    (r"^(?:ios|android|wearos|watchos|mac|ms\s*스토어|mac/ms스토어|ios/watchos|구글\s*플레이|google\s*play|"
     r"앱스토어|app\s*store)$|^(?:ios|android|wearos)/", "디지털"),
    (r"아이즈모바일|알뜰폰|모바일$|유심|하이마트|디지털그랩", "디지털"),
    (r"무신사|유니클로|uniqlo|29cm|w컨셉|패션플러스|지그재그|에이블리|무인양품|lululemon|levi|macy|"
     r"j\.?crew|adidas|nike|under\s*armour|anthropologie|nordstrom|fanatics|patagonia", "패션"),
    (r"올리브영|뷰리티|코이공식몰", "뷰티"),
    (r"네이버\s*페이|네페|토스\s*포인트|kfc앱", "상품권·포인트"),
    (r"항공|호텔|여기어때|야놀자|트립|아고다|fandango", "여행·티켓"),
    (r"petco|펫", "유아·반려"),
    (r"dick'?s\s*sporting", "스포츠·레저"),
    (r"best\s*buy|newegg", "디지털"),
]]
_SITE_DEFAULT = {"eomisae": "패션"}
_SHOP_W = {"게임": 3.5, "디지털": 3.5}   # 스팀·닌텐도·iOS 같은 플랫폼 말머리는 거의 확정 (그 외 2점)

# 결정적 단어: 다른 단어보다 우선 (6점). 커피머신+캡슐 묶음은 가전, 노트북 사양(SSD·램)은 PC부품 아님
_DECISIVE = [(re.compile(p, re.I), c) for p, c in [
    (r"커피\s*머신|에스프레소\s*머신|캡슐\s*머신|김치\s*냉장고|냉장고|세탁기|건조기|식기\s*세척기|전기\s*요|전기\s*매트|탄소\s*매트|온수\s*매트", "가전"),
    (r"노트북(?!\s*(?:용\s*)?(?:램|ram|메모리|ssd|가방|파우치|거치대|스탠드|쿨러|받침))|laptop(?!\s*(?:bag|stand|sleeve|backpack))|elitebook|latitude|thinkpad|씽크패드|맥북|macbook|lg\s*그램|그램\s*(?:ai|\d{2}|프로|pro)|갤럭시\s*북|chromebook", "디지털"),
    (r"강아지|고양이|반려견|반려묘|애견|애묘|댕댕|냥이\s*(?:간식|사료|모래)", "유아·반려"),   # 강아지 육포 ≠ 사람 간식
]]

_LEAD = re.compile(r"^\s*(?:\(?끌올\)?\s*)?[\[【]([^\]】]{1,30})[\]】]")
_PRICE_PAREN = re.compile(r"\([^()]*?(?:\d\s*원|\$|달러|엔|jpy|무료|무배|배송)[^()]*\)\s*$", re.I)
_WS = re.compile(r"\s+")
_GIFT = re.compile(r"\+?\s*(?:사은품\s*)?증정\s*\([^()]*\)|\([^()]*증정[^()]*\)|\+\s*[^+()]{1,20}\s*증정")


def _norm_src(s: str) -> str:
    return _WS.sub("", s.strip().lower())


def _source_cands(source_category: Optional[str]) -> tuple[str, ...]:
    if not source_category or not source_category.strip():
        return ()
    k = _norm_src(source_category)
    if k in _SRC:
        return _SRC[k]
    for rx, cands in _SRC_EN_RE:
        if rx.search(source_category):
            return cands
    return ()


def _clean(title: str) -> str:
    t = _WS.sub(" ", title or "").strip()
    t = _PRICE_PAREN.sub("", t)   # '(16,940원/무료)' 의 카드·멤버십·포인트 단어가 점수에 섞이지 않게
    t = _GIFT.sub(" ", t)         # '+증정(메가커피)' 사은품은 상품이 아님
    return t


def scores(title: str, source_category: Optional[str] = None, shop: Optional[str] = None,
           source: Optional[str] = None) -> dict[str, float]:
    """카테고리별 점수 (디버그·테스트용)."""
    sc: dict[str, float] = {}
    t = _clean(title)
    m = _LEAD.match(t)
    tag = m.group(1).strip() if m else None
    body = (t[m.end():] if m else t).lower()
    for cat, strong, weak in _RULES:
        s = 3.0 * len({x.group(0) for x in strong.finditer(body)}) \
            + 2.0 * len({x.group(0) for x in weak.finditer(body)})
        if s:
            sc[cat] = sc.get(cat, 0.0) + s
    for rx, cat in _DECISIVE:
        if rx.search(body):
            sc[cat] = sc.get(cat, 0.0) + 6.0
            if cat == "디지털":
                sc.pop("PC부품", None)   # 노트북의 CPU·램·SSD 사양
    cands = _source_cands(source_category)
    if cands:
        if len(cands) == 1:
            sc[cands[0]] = sc.get(cands[0], 0.0) + 2.0
        else:
            # 애매한 분류: 제목이 후보 중 하나를 가리키면 그쪽으로, 아니면 첫 후보
            sc[cands[0]] = sc.get(cands[0], 0.0) + 1.5
            for c in cands[1:]:
                sc[c] = sc.get(c, 0.0) + 1.0
    for hint in {h for h in (shop, tag) if h}:
        for rx, cat in _SHOP:
            if rx.search(hint.strip()):
                sc[cat] = sc.get(cat, 0.0) + _SHOP_W.get(cat, 2.0)
                break
    if source in _SITE_DEFAULT:
        c = _SITE_DEFAULT[source]
        sc[c] = sc.get(c, 0.0) + 0.5
    return sc


_RANK = {c: i for i, c in enumerate(CATEGORIES)}


def categorize(title: str, source_category: Optional[str] = None, shop: Optional[str] = None,
               source: Optional[str] = None) -> str:
    """CATEGORIES 중 하나. source(사이트 key)는 선택 — 사이트 기본값(어미새=패션)에만 쓴다."""
    sc = scores(title, source_category, shop, source)
    if not sc:
        return "기타"
    return min(sc, key=lambda c: (-sc[c], _RANK[c]))


def categorize_many(items) -> str:
    """여러 (title, source_category, shop, source) 의 점수를 합쳐 하나로 (같은 딜의 여러 사이트 글)."""
    total: dict[str, float] = {}
    for title, cat, shop, src in items:
        for c, v in scores(title or "", cat, shop, src).items():
            total[c] = total.get(c, 0.0) + v
    if not total:
        return "기타"
    return min(total, key=lambda c: (-total[c], _RANK[c]))
