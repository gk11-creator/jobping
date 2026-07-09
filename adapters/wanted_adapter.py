"""
원티드(wanted.co.kr) 채용공고 어댑터
"""
import asyncio
import re
import urllib.parse
from datetime import datetime, date
from adapters.base_adapter import BaseAdapter
from adapters.category_map import get_search_keyword

BASE_URL = "https://www.wanted.co.kr"

# 원티드 직무 카테고리 코드 (실제 URL에서 확인된 값)
# 주의: 매칭은 딕셔너리 순서대로 부분 문자열 검사를 하므로, 짧고 일반적인 키가
# 긴/구체적인 키보다 먼저 있으면 잘못 걸릴 수 있다 (예전에 "제조/QC/QA" 카테고리가
# "제조"에 도달하기 전에 "QA"에 먼저 매칭되던 버그가 있었음).
# 그래서 "제조"를 "QC"/"QA"보다 앞에 배치했다.
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
    "제조": "555",  # QC/QA보다 먼저 와야 "제조/QC/QA" 카테고리가 올바르게 매칭됨
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
        return ""  # 매칭 실패시 빈 값 (예전처럼 "518"=IT개발로 고정하지 않음)

    def _get_search_url_and_type(self, user_profile: dict, page: int = 1) -> tuple[str, str, str]:
        """
        카테고리가 CATEGORY_MAP에 등록돼 있으면 정밀 필터(wdlist)를 사용하고,
        등록돼 있지 않으면 원티드의 실제 검색 페이지(search?query=...&tab=position)로
        폴백한다. (예전엔 미등록 카테고리가 전부 IT개발[518]로 고정되는 문제가 있었음
        — 김태진(법무/경영지원) 케이스로 확인됨)

        반환값: (URL, match_type, matched_keyword)
        """
        category_id = self._get_category_id(user_profile)
        employment_type = user_profile.get("employment_type", "")
        career = "0" if ("신입" in employment_type or "인턴" in employment_type) else "1"

        if category_id:
            url = f"{BASE_URL}/wdlist/{category_id}?job_sort=job.latest_order&years={career}&locations=all&page={page}"
            return url, "category", ""

        keyword = get_search_keyword(user_profile.get("category", ""))
        encoded_keyword = urllib.parse.quote(keyword)
        url = f"{BASE_URL}/search?query={encoded_keyword}&tab=position"
        return url, "keyword", keyword

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

        url, match_type, matched_keyword = self._get_search_url_and_type(user_profile, page)
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

            # 카테고리 리스트(wdlist)와 검색결과(search) 페이지 모두 공고 링크는
            # 사이트 공통 URL 패턴(/wd/{id})을 쓰므로 동일 셀렉터로 파싱 가능
            cards = soup.select('a[href^="/wd/"]')
            print(f"[원티드] 아이템 {len(cards)}개 발견")

            seen_urls = set()
            job_candidates = []
            for card in cards:
                href = card.get("href", "")
                source_url = f"{BASE_URL}{href}"
                if source_url in seen_urls:
                    continue
                seen_urls.add(source_url)

                btn = card.select_one("button[data-position-name]")
                if btn:
                    title = btn.get("data-position-name", "")
                    company = btn.get("data-company-name", "")
                    emp_type_raw = btn.get("data-position-employment-type", "")
                    emp_type = EMPLOYMENT_TYPE_MAP.get(emp_type_raw, emp_type_raw)
                else:
                    title_tag = card.select_one("[class*='position']")
                    company_tag = card.select_one("[class*='company']")
                    title = title_tag.get_text(strip=True) if title_tag else ""
                    company = company_tag.get_text(strip=True) if company_tag else ""
                    emp_type_raw = ""
                    emp_type = ""

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

            jobs = []
            for candidate in job_candidates[:15]:
                print(f"[원티드] 마감일 확인: {candidate['title'][:20]}...")
                deadline = await self._fetch_deadline(candidate["source_url"])
                candidate["deadline"] = deadline
                jobs.append(candidate)
                await asyncio.sleep(1)

            print(f"[원티드] {len(jobs)}개 파싱 완료")
            return jobs

        except Exception as e:
            print(f"[원티드] 오류: {e}")
            return []