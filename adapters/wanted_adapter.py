"""
원티드(wanted.co.kr) 채용공고 어댑터
"""
import asyncio
import re
from datetime import datetime, date
from adapters.base_adapter import BaseAdapter

BASE_URL = "https://www.wanted.co.kr"

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
    "QA": "518",
    "보안": "518",
    "마케팅": "523",
    "광고": "523",
    "디자인": "521",
    "UI/UX": "521",
    "그래픽": "521",
    "가구": "521",
    "제품": "521",
    "영업": "525",
    "영업관리": "525",
    "기획": "507",
    "PM": "507",
    "금융": "534",
    "회계": "534",
    "인사": "524",
    "HR": "524",
    "QC": "518",
    "제조": "555",
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
        return "518"

    def _get_search_url(self, user_profile: dict, page: int = 1) -> str:
        category_id = self._get_category_id(user_profile)
        employment_type = user_profile.get("employment_type", "")
        career = "0" if ("신입" in employment_type or "인턴" in employment_type) else "1"
        return f"{BASE_URL}/wdlist/{category_id}?job_sort=job.latest_order&years={career}&locations=all&page={page}"

    def _parse_deadline(self, raw: str) -> str:
        """2026.07.05 형태를 2026-07-05로 변환"""
        try:
            raw = raw.strip()
            match = re.match(r"(\d{4})\.(\d{2})\.(\d{2})", raw)
            if match:
                return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
        except:
            pass
        return ""

    async def _fetch_deadline(self, url: str) -> str:
        """공고 상세 페이지에서 마감일 파싱"""
        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=15000)
            await asyncio.sleep(2)

            from bs4 import BeautifulSoup
            html = await self.page.content()
            soup = BeautifulSoup(html, "html.parser")

            # 마감일 컨테이너 찾기 - h2 태그가 "마감일" 텍스트인 article
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

        url = self._get_search_url(user_profile, page)
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
            print(f"[원티드] 아이템 {len(cards)}개 발견")

            # 중복 제거 후 최대 15개만 상세 접속
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

                job_candidates.append({
                    "title": title,
                    "company": company,
                    "location": location or user_profile.get("location", ""),
                    "employment_type": emp_type,
                    "source": self.SOURCE,
                    "source_url": source_url,
                    "rating": None,
                })

            # 상세 페이지에서 마감일 파싱 (최대 15개)
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