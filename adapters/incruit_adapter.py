"""
인크루트 어댑터
"""
import asyncio
import re
from datetime import datetime, timedelta
from typing import Optional
from adapters.base_adapter import BaseAdapter

OCC_MAP = {
    "IT개발 > 전체": {"occ1": 150},
    "IT개발 > 서버/백엔드": {"occ1": 150, "occ2": 152},
    "IT개발 > 프론트엔드": {"occ1": 150, "occ2": 153},
    "IT개발 > 안드로이드": {"occ1": 150, "occ2": 155},
    "IT개발 > iOS": {"occ1": 150, "occ2": 156},
    "IT개발 > AI/ML": {"occ1": 150, "occ2": 158},
    "IT개발 > 데이터분석": {"occ1": 150, "occ2": 159},
    "IT개발 > DevOps": {"occ1": 150, "occ2": 160},
    "IT개발 > 보안": {"occ1": 150, "occ2": 163},
    "IT개발 > QA": {"occ1": 150, "occ2": 164},
    "기획/전략": {"occ1": 2},
    "마케팅/광고": {"occ1": 7},
    "디자인": {"occ1": 104},
    "영업": {"occ1": 5},
}
REGION_MAP = {
    "서울": 11, "경기": 12, "인천": 13, "부산": 21, "대구": 22,
    "광주": 23, "대전": 24, "울산": 25, "세종": 26, "강원": 31,
    "경남": 41, "경북": 42, "전남": 43, "전북": 44,
    "충남": 45, "충북": 46, "제주": 51, "해외": 61,
}
ETYPE_MAP = {"정규직": 1, "계약직": 2, "인턴": 3, "파견직": 4, "아르바이트": 5}

SKIP_KEYWORDS = [
    "교육", "훈련", "과정", "수료", "강의", "캠퍼스", "아카데미", "부트캠프", "국비",
    "장애인", "협력단", "공무직", "공제", "체육회", "협력단", "재단", "공단",
    "신입사원 공개채용", "수시채용"
]

BASE_URL = "https://job.incruit.com"
SEARCH_URL = f"{BASE_URL}/jobdb_list/searchjob.asp"


class IncruitAdapter(BaseAdapter):

    async def _refresh_session(self):
        print("[인크루트] 세션 재획득 중...")
        try:
            await self.page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
            await asyncio.sleep(2)
        except Exception as e:
            print(f"[인크루트] 메인 접속 실패: {e}")
        self._session_valid = True
        print("[인크루트] 세션 재획득 완료")

    async def fetch_job_list(self, user_profile: dict, page: int = 1) -> list[dict]:
        if not self._session_valid:
            await self._refresh_session()

        occ = OCC_MAP.get(user_profile.get("category", "IT개발 > 전체"), {"occ1": 150})
        rgn = REGION_MAP.get(user_profile.get("location", "서울"), 11)
        etype = ETYPE_MAP.get(user_profile.get("employment_type", "인턴"), 3)

        params = {
            "occ1": occ["occ1"],
            "rgn2": rgn,
            "etype": etype,
            "pno": page,
            "col": 1,
            "sortby": 2,
        }
        if "occ2" in occ:
            params["occ2"] = occ["occ2"]

        param_str = "&".join(f"{k}={v}" for k, v in params.items())
        url = f"{SEARCH_URL}?{param_str}"
        print(f"[인크루트] 접속: {url}")

        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(10)
        except Exception as e:
            print(f"[인크루트] 페이지 이동 실패: {e}")
            return []

        try:
            html = await self.page.content()
        except Exception as e:
            print(f"[인크루트] 콘텐츠 추출 실패: {e}")
            return []

        if "recaptcha" in html.lower() and "로봇" in html:
            print("[인크루트] 차단 감지")
            return []

        jobs = self._parse_html(html, user_profile)
        print(f"[인크루트] {len(jobs)}개 파싱 완료")
        await asyncio.sleep(3)
        return jobs

    def _parse_html(self, html: str, user_profile: dict) -> list[dict]:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        jobs = []

        items = soup.select(".cPrdlists_box_pos")
        print(f"[인크루트] 아이템 {len(items)}개 발견")

        for item in items:
            try:
                title_tag = item.select_one(".cTitle strong")
                if not title_tag:
                    continue
                title = title_tag.get_text(strip=True)
                if not title:
                    continue

                # 교육/훈련 과정 필터링
                if any(kw in title for kw in SKIP_KEYWORDS):
                    continue

                link_tag = item.select_one("a[href*='jobpost.asp']")
                href = link_tag.get("href", "") if link_tag else ""
                source_url = href if href.startswith("http") else f"{BASE_URL}{href}"

                company_tag = item.select_one(".cCpName")
                company = company_tag.get_text(strip=True) if company_tag else ""

                deadline_tag = item.select_one(".cDate")
                deadline_raw = deadline_tag.get_text(strip=True) if deadline_tag else ""

                jobs.append({
                    "title": title,
                    "company": company,
                    "category": user_profile.get("category", ""),
                    "employment_type": user_profile.get("employment_type", "인턴"),
                    "location": user_profile.get("location", "서울"),
                    "deadline": self._parse_deadline(deadline_raw),
                    "source": "인크루트",
                    "source_url": source_url,
                    "rating": None,
                    "competition_ratio": None,
                    "_raw": {"deadline_raw": deadline_raw}
                })
            except Exception as e:
                print(f"[인크루트] 파싱 오류: {e}")

        return jobs

    def _parse_deadline(self, raw: str) -> Optional[str]:
        today = datetime.now()
        if not raw or "상시" in raw:
            return None
        if "오늘마감" in raw:
            return today.strftime("%Y-%m-%d")
        m = re.search(r"(\d{2,4})[./](\d{2})[./](\d{2})", raw)
        if m:
            y = m.group(1)
            year = int(y) if len(y) == 4 else today.year
            return f"{year}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        m2 = re.search(r"D-(\d+)", raw)
        if m2:
            return (today + timedelta(days=int(m2.group(1)))).strftime("%Y-%m-%d")
        return None