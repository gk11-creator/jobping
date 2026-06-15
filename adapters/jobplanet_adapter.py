"""
잡플래닛 어댑터
"""
import asyncio
from typing import Optional
from adapters.base_adapter import BaseAdapter

OCCUPATION_MAP = {
    "IT개발 > 서버/백엔드": {"level1": 1, "level2": 11928},
    "IT개발 > 프론트엔드": {"level1": 1, "level2": 11929},
    "IT개발 > 풀스택": {"level1": 1, "level2": 11930},
    "IT개발 > iOS": {"level1": 1, "level2": 11931},
    "IT개발 > Android": {"level1": 1, "level2": 11932},
    "IT개발 > AI/ML": {"level1": 1, "level2": 11934},
    "IT개발 > 데이터엔지니어": {"level1": 1, "level2": 11935},
    "IT개발 > DevOps": {"level1": 1, "level2": 11936},
    "IT개발 > 보안": {"level1": 1, "level2": 11938},
    "IT개발 > QA": {"level1": 1, "level2": 11939},
    "IT기획/PM": {"level1": 1, "level2": 11940},
    "기획/전략": {"level1": 2, "level2": None},
    "마케팅": {"level1": 4, "level2": None},
    "디자인": {"level1": 6, "level2": None},
    "전체": {"level1": None, "level2": None},
}
BASE_URL = "https://www.jobplanet.co.kr"
API_URL = f"{BASE_URL}/api/v3/job/postings"


class JobplanetAdapter(BaseAdapter):

    async def _refresh_session(self):
        print("[잡플래닛] 세션 재획득 중...")
        await self._goto_safe(f"{BASE_URL}/job")
        await asyncio.sleep(2)
        self._session_valid = True
        print("[잡플래닛] 세션 재획득 완료")

    async def fetch_job_list(self, user_profile: dict, page: int = 1) -> list[dict]:
        if not self._session_valid:
            await self._refresh_session()

        occ = OCCUPATION_MAP.get(
            user_profile.get("category", "IT개발 > 서버/백엔드"),
            {"level1": 1, "level2": 11928}
        )
        params = {
            "occupation_level1": occ["level1"] or "",
            "occupation_level2": occ["level2"] or "",
            "years_of_experience": "",
            "review_score": user_profile.get("min_grade", ""),
            "job_type": user_profile.get("employment_type", ""),
            "city": user_profile.get("location", "서울"),
            "education_level_id": "",
            "order_by": "aggressive",
            "page": page,
            "page_size": 20,
        }
        param_str = "&".join(f"{k}={v}" for k, v in params.items())
        api_url = f"{API_URL}?{param_str}"

        async def _call():
            return await self.page.evaluate(f"""
                async () => {{
                    const res = await fetch('{api_url}', {{
                        headers: {{
                            'Accept': 'application/json',
                            'X-Requested-With': 'XMLHttpRequest',
                            'Referer': '{BASE_URL}/job',
                        }}
                    }});
                    if (!res.ok) throw new Error(`HTTP ${{res.status}}`);
                    return await res.json();
                }}
            """)

        response_data = await self._fetch_with_retry(_call)
        if not response_data or response_data.get("status") != "success":
            return []

        data = response_data.get("data", {})
        if page == 1:
            print(f"[잡플래닛] 총 {data.get('total_count', 0)}개 공고")

        recruits = data.get("recruits", [])
        jobs = [self._normalize(item, user_profile) for item in recruits]
        jobs = [j for j in jobs if j]
        await self._delay()
        return jobs

    def _normalize(self, item: dict, user_profile: dict) -> Optional[dict]:
        try:
            company_obj = item.get("company", {})
            return {
                "title": item.get("title", ""),
                "company": company_obj.get("name", ""),
                "category": user_profile.get("category", ""),
                "employment_type": item.get("job_type", ""),
                "location": company_obj.get("city_name", ""),
                "deadline": item.get("end_at"),
                "source": "잡플래닛",
                "source_url": f"{BASE_URL}/job/postings/{item.get('id','')}",
                "rating": company_obj.get("grade"),
                "competition_ratio": None,
                "_raw": {
                    "id": item.get("id"),
                    "grade": company_obj.get("grade"),
                    "grade_count": company_obj.get("grade_count"),
                    "deadline_message": item.get("deadline_message"),
                    "skills": item.get("skills", []),
                }
            }
        except Exception as e:
            print(f"[잡플래닛] 파싱 오류: {e}")
            return None

    async def fetch_high_rated(self, user_profile: dict, min_grade: float = 4.0, max_pages: int = 3) -> list[dict]:
        return await self.collect_all_pages(
            {**user_profile, "min_grade": min_grade},
            max_pages=max_pages
        )