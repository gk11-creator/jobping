"""
슈퍼루키 어댑터 - /jobs/search URL 기반
"""
import asyncio
import re
from datetime import datetime, timedelta
from typing import Optional
from adapters.base_adapter import BaseAdapter

DUTY_GROUP_MAP = {
    "IT개발 > 프론트엔드": ["661de91a8b129f42ef6c257c"],
    "IT개발 > 서버/백엔드": ["661de91a8b129f42ef6c257b"],
    "IT개발 > 데이터분석": ["661de91a8b129f42ef6c257d"],
    "IT개발 > AI/ML": ["661de91a8b129f42ef6c2581"],
    "IT개발 > iOS": ["661de91a8b129f42ef6c2583"],
    "IT개발 > 안드로이드": ["661de91a8b129f42ef6c2582"],
    "IT개발 > DevOps": ["661de91a8b129f42ef6c2580"],
    "IT개발 > QA": ["661de91a8b129f42ef6c257a"],
    "IT 전 직군": [
        "661de91a8b129f42ef6c257a", "661de91a8b129f42ef6c257b",
        "661de91a8b129f42ef6c257c", "661de91a8b129f42ef6c257d",
        "661de91a8b129f42ef6c257e", "661de91a8b129f42ef6c257f",
        "661de91a8b129f42ef6c2580", "661de91a8b129f42ef6c2581",
        "661de91a8b129f42ef6c2582", "661de91a8b129f42ef6c2583",
    ],
}

JOB_LEVEL_INTERN = "579f18168b129f673b4efebe"
BASE_URL = "https://www.superookie.com"
SEARCH_URL = f"{BASE_URL}/jobs/search"


class SuperookieAdapter(BaseAdapter):

    async def _refresh_session(self):
        print("[슈퍼루키] 세션 재획득 중...")
        try:
            await self.page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
            await asyncio.sleep(2)
        except Exception as e:
            print(f"[슈퍼루키] 세션 재획득 실패: {e}")
        self._session_valid = True
        print("[슈퍼루키] 세션 재획득 완료")

    async def fetch_job_list(self, user_profile: dict, page: int = 1) -> list[dict]:
        if not self._session_valid:
            await self._refresh_session()

        duty_groups = DUTY_GROUP_MAP.get(
            user_profile.get("category", ""),
            DUTY_GROUP_MAP["IT 전 직군"]
        )

        params = f"q=&sort=&status=&job_level%5B%5D={JOB_LEVEL_INTERN}&job_type=job"
        for dg in duty_groups:
            params += f"&duty_group%5B%5D={dg}"

        url = f"{SEARCH_URL}?{params}"
        print(f"[슈퍼루키] 접속: {url[:80]}...")

        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(8)
            await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(3)
        except Exception as e:
            print(f"[슈퍼루키] 페이지 이동 실패: {e}")
            return []

        try:
            html = await self.page.content()
        except Exception as e:
            print(f"[슈퍼루키] 콘텐츠 추출 실패: {e}")
            return []

        jobs = self._parse_html(html, user_profile)
        print(f"[슈퍼루키] {len(jobs)}개 파싱 완료")
        await asyncio.sleep(3)
        return jobs

    def _parse_html(self, html: str, user_profile: dict) -> list[dict]:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        jobs = []

        items = soup.select(".item-job")
        print(f"[슈퍼루키] 아이템 {len(items)}개 발견")

        for item in items:
                    try:
                        # 링크
                        link_tag = item.select_one("a.job-detail-link")
                        if not link_tag:
                            continue
                        href = link_tag.get("href", "")
                        source_url = href if href.startswith("http") else f"{BASE_URL}{href}"

                        # 제목
                        title_tag = item.select_one(".job-title")
                        title = title_tag.get_text(strip=True) if title_tag else ""
                        if not title:
                            continue

                        # 회사명
                        company_tag = item.select_one("h5")
                        company = company_tag.get_text(strip=True) if company_tag else ""

                        # 마감일
                        deadline_tag = item.select_one(".color-gray.mobile-text-12")
                        deadline_raw = deadline_tag.get_text(strip=True) if deadline_tag else ""

                        jobs.append({
                            "title": title,
                            "company": company,
                            "category": user_profile.get("category", ""),
                            "employment_type": "인턴",
                            "location": user_profile.get("location", "서울"),
                            "deadline": self._parse_deadline(deadline_raw),
                            "source": "슈퍼루키",
                            "source_url": source_url,
                            "rating": None,
                            "competition_ratio": None,
                            "_raw": {"deadline_raw": deadline_raw}
                        })
                    except Exception as e:
                        print(f"[슈퍼루키] 파싱 오류: {e}")
        return jobs

    def _parse_deadline(self, raw: str) -> Optional[str]:
        today = datetime.now()
        if not raw or "상시" in raw or "채용시" in raw:
            return None
        m = re.search(r"(\d{4})[.\-/](\d{2})[.\-/](\d{2})", raw)
        if m:
            return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
        m2 = re.search(r"(\d{2})[.\-/](\d{2})", raw)
        if m2:
            month, day = int(m2.group(1)), int(m2.group(2))
            year = today.year if month >= today.month else today.year + 1
            return f"{year}-{month:02d}-{day:02d}"
        m3 = re.search(r"D-(\d+)", raw)
        if m3:
            return (today + timedelta(days=int(m3.group(1)))).strftime("%Y-%m-%d")
        return None