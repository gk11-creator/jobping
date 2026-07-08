"""
캐치(catch.co.kr) 채용공고 어댑터
"""
import asyncio
import re
from datetime import datetime, date
from adapters.base_adapter import BaseAdapter
from adapters.category_map import get_search_keyword

BASE_URL = "https://www.catch.co.kr"

DUTY_MAP = {
    "IT개발": "2",
    "기획": "3",
    "마케팅": "4",
    "영업": "5",
    "경영": "6",
    "디자인": "7",
    "금융": "8",
    "회계": "8",
    "인사": "6",
    "QC": "4",
    "QA": "4",
    "가구": "6",
}

AD_TITLE_PREFIXES = ("📌", "👏", "✨", "🎯", "🔥", "⭐", "💡", "🎁", "🏆", "📢", "🚀")


class CatchAdapter(BaseAdapter):
    SOURCE = "캐치"

    async def _refresh_session(self):
        print("[캐치] 세션 재획득 중...")
        await self.page.goto(BASE_URL, wait_until="domcontentloaded")
        await asyncio.sleep(2)
        print("[캐치] 세션 재획득 완료")

    def _get_duty(self, user_profile: dict) -> str:
        """
        카테고리를 먼저, 우선적으로 확인한다.
        (예전엔 category와 skills를 합쳐서 한 번에 텍스트 매칭했는데, 다중
        카테고리를 가진 사용자의 경우 스킬 하나가 먼저 매칭되어 두 번째
        카테고리 검색이 첫 번째로 오염되는 버그가 있었음 — 장세욱 케이스로 확인됨)
        매칭 실패시 빈 문자열 반환 (예전처럼 "2"=IT개발로 고정하지 않음).
        """
        category = user_profile.get("category", "")
        for keyword, duty in DUTY_MAP.items():
            if keyword in category:
                return duty
        return ""

    def _get_career(self, user_profile: dict) -> str:
        emp = user_profile.get("employment_type", "")
        if "신입" in emp or "인턴" in emp:
            return "1"
        elif "1-3" in emp:
            return "2"
        return "1"

    def _parse_deadline(self, raw: str) -> str:
        try:
            raw = raw.strip().lstrip("~")
            match = re.match(r"(\d{2})\.(\d{2})", raw)
            if match:
                month, day = int(match.group(1)), int(match.group(2))
                year = date.today().year
                if month < date.today().month:
                    year += 1
                return f"{year}-{month:02d}-{day:02d}"
        except:
            pass
        return ""

    def _get_search_keyword(self, user_profile: dict, duty: str) -> str:
        """
        duty(카테고리 코드)가 매칭됐으면 스킬 키워드를 보조적으로 사용해도 무방하지만,
        duty 매칭에 실패했을 때는 카테고리 자체를 검색 키워드로 사용한다.
        (예전엔 항상 skills[0]을 사용해서 "MS 엑셀" 같은 무관한 검색어가 나가는
        문제가 있었음 — 김태진 케이스로 확인됨)
        """
        category = user_profile.get("category", "")
        if duty:
            skills = user_profile.get("skills", [])
            return skills[0] if skills else ""
        return get_search_keyword(category)

    def _get_search_url(self, user_profile: dict, page: int = 1) -> str:
        duty = self._get_duty(user_profile)
        career = self._get_career(user_profile)
        keyword = self._get_search_keyword(user_profile, duty)
        return f"{BASE_URL}/NCS/RecruitSearch?keyword={keyword}&duty={duty}&career={career}&pageNo={page}"

    async def fetch_job_list(self, user_profile: dict, page: int = 1) -> list[dict]:
        if not self._session_valid:
            await self._refresh_session()
            self._session_valid = True

        url = self._get_search_url(user_profile, page)
        print(f"[캐치] 접속: {url[:80]}...")

        try:
            await self._goto_safe(url)
            await asyncio.sleep(3)

            from bs4 import BeautifulSoup
            html = await self.page.content()
            soup = BeautifulSoup(html, "html.parser")

            rows = soup.select("tr.gg")
            print(f"[캐치] 아이템 {len(rows)}개 발견")

            jobs = []
            for row in rows:
                try:
                    company_tag = row.select_one("td.wd18 a.tdlink")
                    company = company_tag.get_text(strip=True) if company_tag else ""

                    title_tag = row.select_one("td.wdauto a.link")
                    if not title_tag:
                        title_tag = row.select_one("td.wdauto a.tdlink")
                    title = title_tag.get_text(strip=True) if title_tag else ""
                    href = title_tag.get("href", "") if title_tag else ""
                    source_url = f"{BASE_URL}{href}" if href.startswith("/") else href

                    job_tag = row.select_one("td.wd15 a.tdlink")
                    job_type = job_tag.get_text(strip=True) if job_tag else ""

                    date_tag = row.select_one("td.wd9 p.date2")
                    deadline_raw = date_tag.get_text(strip=True) if date_tag else ""
                    deadline = self._parse_deadline(deadline_raw)

                    if not title or not company:
                        continue

                    # 광고 필터링
                    if company.endswith("AD"):
                        continue
                    if title.startswith(AD_TITLE_PREFIXES):
                        continue
                    if "비영리법인" in company or "공공기관" in company:
                        continue

                    jobs.append({
                        "title": title,
                        "company": company,
                        "location": user_profile.get("location", ""),
                        "deadline": deadline,
                        "source": self.SOURCE,
                        "source_url": source_url,
                        "rating": None,
                        "job_type": job_type,
                    })
                except Exception:
                    continue

            print(f"[캐치] {len(jobs)}개 파싱 완료")
            return jobs

        except Exception as e:
            print(f"[캐치] 오류: {e}")
            return []