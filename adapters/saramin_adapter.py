"""
사람인 어댑터 - 일반 검색 API 사용
"""
import asyncio
import re
from datetime import datetime, timedelta
from typing import Optional
from adapters.base_adapter import BaseAdapter

CATEGORY_MAP = {
    "IT개발 > 서버/백엔드": 84, "IT개발 > 프론트엔드": 87, "IT개발 > 풀스택": 226,
    "IT개발 > 안드로이드": 88, "IT개발 > iOS": 89, "IT개발 > AI/ML": 400,
    "IT개발 > 데이터분석": 401, "IT개발 > 데브옵스/인프라": 235, "IT개발 > 보안": 93,
    "IT개발 > QA": 94, "IT개발 > 게임": 92, "기획/전략": 16, "마케팅/광고": 2,
    "디자인": 10, "영업": 7, "경영/인사/총무": 11,
}
LOCATION_MAP = {
    "서울": "101000", "경기": "102000", "인천": "108000", "부산": "106000",
    "대구": "104000", "광주": "103000", "대전": "105000", "울산": "107000",
    "세종": "118000", "강원": "109000", "경남": "110000", "경북": "111000",
    "전남": "112000", "전북": "113000", "충남": "115000", "충북": "116000",
    "제주": "117000", "해외": "119000",
}
EMPLOYMENT_MAP = {"정규직": "1", "계약직": "2", "인턴": "4", "파견직": "8", "프리랜서": "32"}
BASE_URL = "https://www.saramin.co.kr"
SEARCH_URL = f"{BASE_URL}/zf_user/jobs/list/job-category"


class SaraminAdapter(BaseAdapter):

    async def _refresh_session(self):
        print("[사람인] 세션 재획득 중...")
        try:
            await self.page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
            await asyncio.sleep(2)
            self._session_valid = True
            print("[사람인] 세션 재획득 완료")
        except Exception as e:
            print(f"[사람인] 세션 재획득 실패: {e}")
            self._session_valid = True  # 실패해도 진행

    async def fetch_job_list(self, user_profile: dict, page: int = 1) -> list[dict]:
        if not self._session_valid:
            await self._refresh_session()

        cat_code = CATEGORY_MAP.get(user_profile.get("category", ""), 84)
        loc_code = LOCATION_MAP.get(user_profile.get("location", "서울"), "101000")
        emp_code = EMPLOYMENT_MAP.get(user_profile.get("employment_type", "인턴"), "4")

        url = (
            f"{SEARCH_URL}"
            f"?cat_kewd={cat_code}"
            f"&loc_mcd={loc_code}"
            f"&job_type={emp_code}"
            f"&page={page}"
            f"&panel_type=&search_optional_item=n&search_done=y&panel_count=y"
        )

        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(2)
        except Exception as e:
            print(f"[사람인] 페이지 이동 실패: {e}")
            return []

        try:
            html = await self.page.content()
        except Exception as e:
            print(f"[사람인] 콘텐츠 추출 실패: {e}")
            return []

        jobs = self._parse_html(html, user_profile)
        print(f"[사람인] {len(jobs)}개 파싱 완료")
        await asyncio.sleep(3)
        return jobs

    def _parse_html(self, html: str, user_profile: dict) -> list[dict]:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        jobs = []

        # 방법 1: 일반 공고 리스트
        for item in soup.select("div.item_recruit"):
            try:
                title_tag = item.select_one("a.str_tit") or item.select_one(".job_tit a")
                if not title_tag:
                    continue
                title = title_tag.get_text(strip=True)
                href = title_tag.get("href", "")
                rec_idx = re.search(r"rec_idx=(\d+)", href)
                rec_idx = rec_idx.group(1) if rec_idx else None
                source_url = f"{BASE_URL}{href}" if href.startswith("/") else href

                company_tag = item.select_one(".corp_name a") or item.select_one(".company_name")
                company = company_tag.get_text(strip=True) if company_tag else ""

                loc_tag = item.select_one(".work_place") or item.select_one(".job_condition span")
                location = loc_tag.get_text(strip=True) if loc_tag else user_profile.get("location", "")

                deadline_tag = item.select_one(".job_date .date") or item.select_one(".deadline")
                deadline_raw = deadline_tag.get_text(strip=True) if deadline_tag else ""

                if title:
                    jobs.append({
                        "title": title,
                        "company": company,
                        "category": user_profile.get("category", ""),
                        "employment_type": user_profile.get("employment_type", "인턴"),
                        "location": location,
                        "deadline": self._parse_deadline(deadline_raw),
                        "source": "사람인",
                        "source_url": source_url if source_url else f"{BASE_URL}/zf_user/jobs/relay/view?rec_idx={rec_idx}",
                        "rating": None,
                        "competition_ratio": None,
                        "_raw": {"rec_idx": rec_idx, "deadline_raw": deadline_raw}
                    })
            except Exception as e:
                print(f"[사람인] 파싱 오류: {e}")

        # 방법 2: 결과 없으면 다른 셀렉터 시도
        if not jobs:
            for item in soup.select("li.list"):
                try:
                    title_tag = item.select_one("a")
                    if not title_tag:
                        continue
                    title = title_tag.get_text(strip=True)
                    href = title_tag.get("href", "")
                    rec_idx = re.search(r"rec_idx=(\d+)", href)
                    rec_idx = rec_idx.group(1) if rec_idx else None

                    company_tag = item.select_one(".corp_name") or item.select_one(".company")
                    company = company_tag.get_text(strip=True) if company_tag else ""

                    deadline_tag = item.select_one(".date")
                    deadline_raw = deadline_tag.get_text(strip=True) if deadline_tag else ""

                    if title and rec_idx:
                        jobs.append({
                            "title": title,
                            "company": company,
                            "category": user_profile.get("category", ""),
                            "employment_type": user_profile.get("employment_type", "인턴"),
                            "location": user_profile.get("location", "서울"),
                            "deadline": self._parse_deadline(deadline_raw),
                            "source": "사람인",
                            "source_url": f"{BASE_URL}/zf_user/jobs/relay/view?rec_idx={rec_idx}",
                            "rating": None,
                            "competition_ratio": None,
                            "_raw": {"rec_idx": rec_idx, "deadline_raw": deadline_raw}
                        })
                except Exception as e:
                    print(f"[사람인] 파싱2 오류: {e}")

        return jobs

    def _parse_deadline(self, raw: str) -> Optional[str]:
        today = datetime.now()
        if not raw:
            return None
        if "상시" in raw or "채용시" in raw:
            return None
        m = re.search(r"(\d{2})[\./](\d{2})", raw)
        if m:
            month, day = int(m.group(1)), int(m.group(2))
            year = today.year if month >= today.month else today.year + 1
            return f"{year}-{month:02d}-{day:02d}"
        m2 = re.search(r"D-(\d+)", raw)
        if m2:
            return (today + timedelta(days=int(m2.group(1)))).strftime("%Y-%m-%d")
        return None