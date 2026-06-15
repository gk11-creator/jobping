"""
슈퍼루키 어댑터 - HTML 직접 파싱 방식
"""
import asyncio
import re
from datetime import datetime
from typing import Optional
from adapters.base_adapter import BaseAdapter

CATEGORY_MAP = {
    "IT개발 > 서버/백엔드": "백엔드",
    "IT개발 > 프론트엔드": "프론트엔드",
    "IT개발 > 풀스택": "풀스택",
    "IT개발 > AI/ML": "AI",
    "IT개발 > 데이터분석": "데이터",
    "IT개발 > DevOps": "DevOps",
    "IT개발 > iOS": "iOS",
    "IT개발 > 안드로이드": "Android",
    "IT개발 > QA": "QA",
    "IT개발 > 보안": "보안",
    "기획/전략": "기획",
    "마케팅/광고": "마케팅",
    "디자인": "디자인",
}

BASE_URL = "https://www.superookie.com"
LIST_URL = f"{BASE_URL}/list/intern"


class SuperookieAdapter(BaseAdapter):

    async def _refresh_session(self):
        print("[슈퍼루키] 세션 재획득 중...")
        try:
            await self.page.goto(LIST_URL, wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(3)
        except Exception as e:
            print(f"[슈퍼루키] 세션 재획득 실패: {e}")
        self._session_valid = True
        print("[슈퍼루키] 세션 재획득 완료")

    async def fetch_job_list(self, user_profile: dict, page: int = 1) -> list[dict]:
        if not self._session_valid:
            await self._refresh_session()

        keyword = CATEGORY_MAP.get(user_profile.get("category", ""), "")
        search_url = f"{LIST_URL}?q={keyword}&page={page}" if keyword else f"{LIST_URL}?page={page}"

        print(f"[슈퍼루키] 접속: {search_url}")
        try:
            await self.page.goto(search_url, wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(3)

            # 스크롤해서 더 많은 공고 로드
            await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(2)
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

        # 셀렉터 1: .job-card 또는 .activity-card
        items = (
            soup.select(".job-card") or
            soup.select(".activity-card") or
            soup.select(".intern-card") or
            soup.select("li.item") or
            soup.select(".list-item") or
            soup.select("article.job") or
            soup.select(".card-item")
        )

        print(f"[슈퍼루키] 아이템 {len(items)}개 발견")

        for item in items:
            try:
                # 제목
                title_tag = (
                    item.select_one("h3") or
                    item.select_one("h2") or
                    item.select_one(".title") or
                    item.select_one(".job-title") or
                    item.select_one("a.name") or
                    item.select_one("strong")
                )
                if not title_tag:
                    continue
                title = title_tag.get_text(strip=True)
                if not title or len(title) < 2:
                    continue

                # 링크
                link_tag = item.select_one("a[href]") or item.find_parent("a")
                href = link_tag.get("href", "") if link_tag else ""
                source_url = href if href.startswith("http") else f"{BASE_URL}{href}"

                # 회사명
                company_tag = (
                    item.select_one(".company") or
                    item.select_one(".corp-name") or
                    item.select_one(".organization") or
                    item.select_one("p.company")
                )
                company = company_tag.get_text(strip=True) if company_tag else ""

                # 마감일
                deadline_tag = (
                    item.select_one(".deadline") or
                    item.select_one(".date") or
                    item.select_one("time")
                )
                deadline_raw = deadline_tag.get_text(strip=True) if deadline_tag else ""
                deadline = self._parse_deadline(deadline_raw)

                if title:
                    jobs.append({
                        "title": title,
                        "company": company,
                        "category": user_profile.get("category", ""),
                        "employment_type": "인턴",
                        "location": user_profile.get("location", "서울"),
                        "deadline": deadline,
                        "source": "슈퍼루키",
                        "source_url": source_url or LIST_URL,
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
            from datetime import timedelta
            return (today + timedelta(days=int(m3.group(1)))).strftime("%Y-%m-%d")
        return None