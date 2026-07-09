"""
자소설닷컴(jasoseol.com) 채용공고 어댑터
"""
import asyncio
import re
from datetime import datetime, date
from adapters.base_adapter import BaseAdapter
from adapters.category_map import get_search_keyword

BASE_URL = "https://jasoseol.com"

CATEGORY_KEYWORD_MAP = {
    "IT개발": "개발",
    "마케팅": "마케팅",
    "영업": "영업",
    "기획": "기획",
    "디자인": "디자인",
    "금융": "금융",
    "회계": "회계",
    "인사": "인사",
    "QC": "QC",
    "QA": "QA",
    "가구": "가구",
}


class JasoseolAdapter(BaseAdapter):
    SOURCE = "자소설닷컴"

    async def _refresh_session(self):
        print("[자소설닷컴] 세션 재획득 중...")
        await self.page.goto(BASE_URL, wait_until="domcontentloaded")
        await asyncio.sleep(2)
        print("[자소설닷컴] 세션 재획득 완료")

    def _get_keyword_and_type(self, user_profile: dict) -> tuple[str, str]:
        """
        등록된 카테고리 키워드가 있으면 (키워드, "category")를 반환하고,
        없으면 (공용 검색 키워드, "keyword")를 반환한다.
        (예전엔 스킬 목록[0]로 폴백해서 "MS 엑셀" 같은 무관한 검색어가
        나가는 문제가 있었음 — 김태진 케이스로 확인됨)
        """
        category = user_profile.get("category", "")
        for key, keyword in CATEGORY_KEYWORD_MAP.items():
            if key in category:
                return keyword, "category"
        return get_search_keyword(category), "keyword"

    def _parse_deadline(self, raw: str) -> str:
        """26/07/09 형태를 2026-07-09로 변환"""
        try:
            raw = raw.strip()
            match = re.match(r"(\d{2})/(\d{2})/(\d{2})", raw)
            if match:
                year = int("20" + match.group(1))
                month = int(match.group(2))
                day = int(match.group(3))
                return f"{year}-{month:02d}-{day:02d}"
        except:
            pass
        return ""

    def _get_search_url(self, user_profile: dict, page: int = 1) -> str:
        keyword, _ = self._get_keyword_and_type(user_profile)
        return f"{BASE_URL}/search?q={keyword}&page={page}"

    async def fetch_job_list(self, user_profile: dict, page: int = 1) -> list[dict]:
        if not self._session_valid:
            await self._refresh_session()
            self._session_valid = True

        url = self._get_search_url(user_profile, page)
        print(f"[자소설닷컴] 접속: {url[:80]}...")

        keyword, match_type = self._get_keyword_and_type(user_profile)
        matched_keyword = keyword if match_type == "keyword" else None

        try:
            await self._goto_safe(url)
            await asyncio.sleep(3)

            try:
                await self.page.wait_for_selector('[data-sentry-component="EmploymentCompanyCard"]', timeout=8000)
            except:
                print("[자소설닷컴] 공고 아이템 없음")
                return []

            cards = await self.page.query_selector_all('[data-sentry-component="EmploymentCompanyCard"]')
            print(f"[자소설닷컴] 아이템 {len(cards)}개 발견")

            jobs = []
            for card in cards:
                try:
                    # URL
                    href = await card.get_attribute("href") or ""
                    source_url = f"{BASE_URL}{href}" if href.startswith("/") else href

                    # 회사명
                    h5 = await card.query_selector("h5")
                    company = await h5.inner_text() if h5 else ""
                    company = company.strip()

                    # 공고명
                    h4 = await card.query_selector("h4")
                    title = await h4.inner_text() if h4 else ""
                    title = title.strip()

                    # 마감일 — span 두 개 중 두 번째가 마감일 (26/07/09)
                    spans = await card.query_selector_all("div.body6 span")
                    deadline = ""
                    if len(spans) >= 3:
                        # "26/06/30 - 26/07/09" 형태에서 마지막 날짜
                        deadline_raw = await spans[2].inner_text()
                        deadline = self._parse_deadline(deadline_raw)
                    elif len(spans) >= 1:
                        deadline_raw = await spans[0].inner_text()
                        deadline = self._parse_deadline(deadline_raw)

                    if not title:
                        continue

                    job = {
                        "title": title,
                        "company": company,
                        "category": user_profile.get("category", ""),
                        "location": user_profile.get("location", ""),
                        "deadline": deadline,
                        "source": self.SOURCE,
                        "source_url": source_url,
                        "rating": None,
                        "match_type": match_type,
                    }
                    if matched_keyword:
                        job["_matched_keyword"] = matched_keyword
                    jobs.append(job)
                except Exception:
                    continue

            print(f"[자소설닷컴] {len(jobs)}개 파싱 완료")
            return jobs

        except Exception as e:
            print(f"[자소설닷컴] 오류: {e}")
            return []