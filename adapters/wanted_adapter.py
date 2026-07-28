"""
원티드(wanted.co.kr) 채용공고 어댑터

[검색 전략 변경 - 검색 최우선]
기존엔 CATEGORY_MAP에 코드가 있으면 wdlist(카테고리 목록) 페이지를 우선 쓰고,
없을 때만 검색페이지(search?query=...)로 폴백했다. 그런데 CATEGORY_MAP은
IT개발 하위 카테고리(서버/백엔드, 데이터분석, iOS, Android 등)를 전부
같은 코드(518)로 뭉뚱그리는 등 정밀도가 낮은 것이 확인됐다 (Sebastian
"데이터분석" 요청에 "Android 개발자", "iOS 개발자"가 섞여 나온 사례).

그래서 순서를 뒤집는다:
1) 사용자의 관심 산업(industries) + 카테고리 키워드를 조합한 검색
   (search?query=...)을 항상 먼저 시도한다 (예: "IT 영업").
2) 검색 결과가 너무 적으면(5개 미만) CATEGORY_MAP의 wdlist 코드로
   보충한다 -- 완전히 버리진 않되 보조 수단으로만 사용.

검색 결과는 match_type="keyword"로 태깅되고, wdlist 보충 결과는
match_type="category"로 태깅해 사전필터에서 검증 여부를 구분한다.
"""
import asyncio
import re
import urllib.parse
from datetime import datetime, date
from adapters.base_adapter import BaseAdapter
from adapters.category_map import get_search_keyword

BASE_URL = "https://www.wanted.co.kr"

# 원티드 직무 카테고리 코드 (실제 URL에서 확인된 값) -- 이제는 검색 결과가
# 부족할 때의 보충용으로만 쓰인다.
# 주의: 매칭은 딕셔너리 순서대로 부분 문자열 검사를 하므로, 짧고 일반적인 키가
# 긴/구체적인 키보다 먼저 있으면 잘못 걸릴 수 있다 (예전에 "제조/QC/QA" 카테고리가
# "제조"에 도달하기 전에 "QA"에 먼저 매칭되던 버그가 있었음).
CATEGORY_MAP = {
    "IT개발": "518",
    "서버/백엔드": "518",
    "프론트엔드": "518",
    "풀스택": "518",
    "AI/ML": "518",
    "데이터분석": "518",
    "DevOps": "518",
    "iOS": "518",
    "Android": "518",
    "보안": "518",
    "마케팅": "523",
    "광고": "523",
    "디자인": "511",
    "UI/UX": "511",
    "그래픽": "511",
    "가구": "511",
    "제품": "511",
    "영업": "530",
    "영업관리": "530",
    "기획": "507",
    "PM": "507",
    "금융": "508",
    "회계": "508",
    "인사": "517",
    "HR": "517",
    "제조": "555",
    "QC": "518",
    "QA": "518",
    "물류": "540",
    "무역": "540",
}

EMPLOYMENT_TYPE_MAP = {
    "regular": "정규직",
    "intern": "인턴",
    "contract": "계약직",
    "parttime": "파트타임",
}

MIN_SEARCH_RESULTS = 5


class WantedAdapter(BaseAdapter):
    SOURCE = "원티드"

    async def _refresh_session(self):
        print("[원티드] 세션 재획득 중...")
        await self.page.goto(BASE_URL, wait_until="domcontentloaded")
        await asyncio.sleep(2)
        print("[원티드] 세션 재획득 완료")

    def _get_category_id(self, user_profile: dict) -> str:
        category = user_profile.get("category", "")
        for key, code in CATEGORY_MAP.items():
            if key in category:
                return code
        return ""

    async def _scrape_url(self, url: str, match_type: str, matched_keyword: str, user_profile: dict) -> list[dict]:
        """주어진 URL(검색 또는 카테고리 목록)을 열고 카드 목록만 파싱 (마감일 제외 -- 느린 작업이라 나중에 일괄 처리)"""
        print(f"[원티드] 접속: {url[:80]}...")
        try:
            await self._goto_safe(url)
            await asyncio.sleep(4)

            for _ in range(3):
                await self.page.keyboard.press("End")
                await asyncio.sleep(1)

            from bs4 import BeautifulSoup
            html = await self.page.content()
            soup = BeautifulSoup(html, "html.parser")

            cards = soup.select('a[href^="/wd/"]')
            print(f"[원티드] 아이템 {len(cards)}개 발견 ({match_type})")

            seen_urls = set()
            job_candidates = []
            for card in cards:
                href = card.get("href", "")
                source_url = f"{BASE_URL}{href}"
                if source_url in seen_urls:
                    continue
                seen_urls.add(source_url)

                # 실제 DevTools로 확인한 구조: /search?query= 페이지에서는
                # <a> 태그 자체에 data-position-name/data-company-name이
                # 바로 붙어있음 (예전엔 안쪽 button[data-position-name]을
                # 찾는 방식이었는데, 이건 wdlist 페이지 구조라 검색결과
                # 페이지에서는 안 먹혀서 전부 빈 값으로 스킵되고 있었음).
                title = card.get("data-position-name", "")
                company = card.get("data-company-name", "")
                emp_type_raw = card.get("data-position-employment-type", "")
                emp_type = EMPLOYMENT_TYPE_MAP.get(emp_type_raw, emp_type_raw)

                if not title or not company:
                    # 폴백: 혹시 다른 페이지 변형에서 안쪽 button/class 구조를
                    # 쓰는 경우 대비
                    btn = card.select_one("button[data-position-name]")
                    if btn:
                        title = title or btn.get("data-position-name", "")
                        company = company or btn.get("data-company-name", "")
                        emp_type_raw = emp_type_raw or btn.get("data-position-employment-type", "")
                        emp_type = EMPLOYMENT_TYPE_MAP.get(emp_type_raw, emp_type_raw)
                    else:
                        title_tag = card.select_one("[class*='position']")
                        company_tag = card.select_one("[class*='company']")
                        title = title or (title_tag.get_text(strip=True) if title_tag else "")
                        company = company or (company_tag.get_text(strip=True) if company_tag else "")

                location_tag = card.select_one("[class*='location']")
                location_text = location_tag.get_text(strip=True) if location_tag else ""
                location = location_text.split("·")[0].strip() if "·" in location_text else location_text

                if not title or not company:
                    continue
                if emp_type_raw == "parttime":
                    continue

                candidate = {
                    "title": title,
                    "company": company,
                    "location": location or user_profile.get("location", ""),
                    "employment_type": emp_type,
                    "source": self.SOURCE,
                    "source_url": source_url,
                    "rating": None,
                    "match_type": match_type,
                }
                if matched_keyword:
                    candidate["_matched_keyword"] = matched_keyword
                job_candidates.append(candidate)

            return job_candidates
        except Exception as e:
            print(f"[원티드] 오류 ({match_type}): {e}")
            return []

    def _parse_deadline(self, raw: str) -> str:
        try:
            raw = raw.strip()
            match = re.match(r"(\d{4})\.(\d{2})\.(\d{2})", raw)
            if match:
                return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
        except:
            pass
        return ""

    async def _fetch_deadline(self, url: str) -> str:
        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=15000)
            await asyncio.sleep(2)

            from bs4 import BeautifulSoup
            html = await self.page.content()
            soup = BeautifulSoup(html, "html.parser")

            articles = soup.find_all("article")
            for article in articles:
                h2 = article.find("h2")
                if h2 and "마감일" in h2.get_text():
                    span = article.find("span")
                    if span:
                        return self._parse_deadline(span.get_text(strip=True))
        except:
            pass
        return ""

    async def fetch_job_list(self, user_profile: dict, page: int = 1) -> list[dict]:
        if not self._session_valid:
            await self._refresh_session()
            self._session_valid = True

        category = user_profile.get("category", "")
        industries = user_profile.get("industries", [])
        keyword = get_search_keyword(category, industries)
        encoded_keyword = urllib.parse.quote(keyword)
        search_url = f"{BASE_URL}/search?query={encoded_keyword}&tab=position"

        print(f"[원티드][디버그] 키워드 검색 우선 시도: '{keyword}'")
        candidates = await self._scrape_url(search_url, "keyword", keyword, user_profile)
        print(f"[원티드][디버그] 키워드 검색 결과: {len(candidates)}개")

        if len(candidates) < MIN_SEARCH_RESULTS:
            category_id = self._get_category_id(user_profile)
            if category_id:
                employment_type = user_profile.get("employment_type", "")
                career = "0" if ("신입" in employment_type or "인턴" in employment_type) else "1"
                cat_url = f"{BASE_URL}/wdlist/{category_id}?job_sort=job.latest_order&years={career}&locations=all&page={page}"
                print(f"[원티드][디버그] 결과 부족 -- 카테고리 코드 {category_id}로 보충 시도")

                existing_urls = {c["source_url"] for c in candidates}
                # match_type은 "category"로 유지하되, _matched_keyword는 붙여서
                # 사전필터의 제목 관련성 검증을 반드시 받게 한다. wdlist
                # 카테고리 코드가 정밀하다는 보장이 없다는 것이 이미 여러 번
                # 확인됐으므로, 검증 없이 통과시키면 무관한 결과가 새어 들어간다.
                backup = await self._scrape_url(cat_url, "category", keyword, user_profile)
                for b in backup:
                    if b["source_url"] not in existing_urls:
                        candidates.append(b)
                        existing_urls.add(b["source_url"])
                print(f"[원티드][디버그] 보충 후 총 {len(candidates)}개")

        jobs = []
        for candidate in candidates[:15]:
            print(f"[원티드] 마감일 확인: {candidate['title'][:20]}...")
            deadline = await self._fetch_deadline(candidate["source_url"])
            candidate["deadline"] = deadline
            jobs.append(candidate)
            await asyncio.sleep(1)

        print(f"[원티드] {len(jobs)}개 파싱 완료")
        return jobs