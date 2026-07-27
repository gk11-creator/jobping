"""
카테고리 -> 검색 키워드 공용 매핑
─────────────────────────────────────────
profile_analyzer.py의 GPT 프롬프트가 정의하는 26개 마스터 카테고리 기준.

[검색 전략 변경]
기존엔 각 사이트 어댑터가 자체 duty/카테고리 코드로 먼저 시도하고,
실패했을 때만 이 키워드로 자유 검색하는 "폴백" 역할이었다. 그런데
실사용 데이터에서 사이트별 카테고리 코드 필터가 반복적으로 무시/오작동
하는 것이 확인되어 (잡코리아 condition[duty], 사람인 cat_kewd 등),
이제 이 키워드 기반 검색을 모든 어댑터의 "최우선" 검색 방식으로 삼는다.

추가로, 카테고리 키워드 단독 검색(예: "영업")은 너무 광범위해서 무관한
결과가 섞이기 쉬우므로, 사용자의 관심 산업(industries, 예: "IT", "스타트업")
이 있으면 이를 카테고리 키워드와 조합해 더 구체적인 검색어를 만든다
(예: industries=["IT"] + category="영업/영업관리" -> "IT 영업").
관심 산업이 여러 개면 첫 번째 값만 사용해 검색어가 과도하게 길어지는
것을 막는다 (여러 산업을 다 반영하고 싶으면 호출부에서 산업별로 여러 번
검색을 돌리는 방식을 고려할 것).
"""

MASTER_CATEGORIES = [
    "IT개발 > 서버/백엔드", "IT개발 > 프론트엔드", "IT개발 > 풀스택",
    "IT개발 > AI/ML", "IT개발 > 데이터분석", "IT개발 > DevOps",
    "IT개발 > iOS", "IT개발 > Android", "IT개발 > QA", "IT개발 > 보안",
    "IT기획/PM", "기획/전략", "마케팅/광고", "디자인", "영업/영업관리",
    "제조/QC/QA", "금융/회계", "인사/HR", "법무/컴플라이언스",
    "디자인 > 제품/가구디자인", "디자인 > 그래픽", "디자인 > UI/UX",
    "무역/유통", "서비스/고객지원", "물류/구매", "경영지원/총무",
]

CATEGORY_SEARCH_KEYWORD = {
    "IT개발 > 서버/백엔드": "백엔드",
    "IT개발 > 프론트엔드": "프론트엔드",
    "IT개발 > 풀스택": "풀스택 개발자",
    "IT개발 > AI/ML": "AI 개발자",
    "IT개발 > 데이터분석": "데이터 분석",
    "IT개발 > DevOps": "데브옵스",
    "IT개발 > iOS": "iOS 개발자",
    "IT개발 > Android": "안드로이드 개발자",
    "IT개발 > QA": "QA",
    "IT개발 > 보안": "보안",
    "IT기획/PM": "IT 기획",
    "기획/전략": "기획",
    "마케팅/광고": "마케팅",
    "디자인": "디자인",
    "영업/영업관리": "영업",
    "제조/QC/QA": "품질관리",
    "금융/회계": "회계",
    "인사/HR": "인사",
    "법무/컴플라이언스": "법무",
    "디자인 > 제품/가구디자인": "가구디자인",
    "디자인 > 그래픽": "그래픽디자인",
    "디자인 > UI/UX": "UI UX 디자인",
    "무역/유통": "무역",
    "서비스/고객지원": "고객지원",
    "물류/구매": "물류",
    "경영지원/총무": "총무",
}


def _base_keyword(category: str) -> str:
    """카테고리 문자열 -> 산업 조합 없는 순수 직무 키워드."""
    if not category:
        return ""

    if category in CATEGORY_SEARCH_KEYWORD:
        return CATEGORY_SEARCH_KEYWORD[category]

    for key, keyword in CATEGORY_SEARCH_KEYWORD.items():
        if key in category or category in key:
            return keyword

    return category


def get_search_keyword(category: str, industries: list | None = None) -> str:
    """
    카테고리(+선택적으로 관심 산업)를 받아 검색용 키워드를 반환.

    industries가 주어지면 "산업 직무" 형태로 조합한다 (예: "IT 영업").
    이러면 카테고리 키워드 단독 검색보다 결과가 좁혀져서 무관한 공고가
    섞일 확률이 낮아진다. industries가 여러 개면 첫 번째 값만 사용한다.

    industries가 없거나 빈 리스트면 기존처럼 카테고리 키워드만 반환한다
    (하위 호환 -- 기존 호출부(get_search_keyword(category))도 그대로 동작).
    """
    keyword = _base_keyword(category)
    if not keyword:
        return ""

    if industries:
        primary_industry = industries[0].strip()
        if primary_industry:
            existing_tokens = {t.lower() for t in keyword.split()}
            if primary_industry.lower() not in existing_tokens:
                return f"{primary_industry} {keyword}"

    return keyword
