"""
링커리어 어댑터
"""
import asyncio
import json
from datetime import datetime
from typing import Optional
from adapters.base_adapter import BaseAdapter

CATEGORY_MAP = {
    "IT/인터넷": [58], "IT개발 > 서버/백엔드": [291, 293, 312],
    "IT개발 > 프론트엔드": [294, 340], "IT개발 > 안드로이드": [295, 299],
    "IT개발 > iOS": [297], "IT개발 > AI/ML": [298, 319, 320],
    "IT개발 > DevOps": [302], "IT개발 > 보안": [310, 311, 317],
    "IT개발 > QA": [116], "IT개발 > 데이터/DBA": [112],
    "IT기획/PM": [114], "경영/사무": [53],
    "마케팅/광고/홍보": [54], "디자인": [63],
}
REGION_MAP = {
    "서울": [2], "경기": [9], "인천": [10], "부산": [3], "대구": [4],
    "광주": [5], "대전": [6], "울산": [7], "세종": [8], "강원": [11],
    "경남": [26], "경북": [25], "전남": [23], "전북": [22],
    "충남": [20], "충북": [19], "제주": [27], "해외": [28], "전국": [],
}
JOBTYPE_MAP = {
    "인턴": ["INTERN"], "신입": ["NEW"], "경력": ["EXPERIENCED"],
    "정규직": ["NEW","EXPERIENCED"], "전체": [],
}
BASE_URL = "https://linkareer.com"
GRAPHQL_URL = "https://api.linkareer.com/graphql"
PERSISTED_QUERY_HASH = "f674e1f77d004204d63b94f4b8bb49fd91138ee4cce1c62c1096876d49f201a2"


class LinkareerAdapter(BaseAdapter):

    async def _refresh_session(self):
        print("[링커리어] 세션 재획득 중...")
        await self._goto_safe(BASE_URL)
        await asyncio.sleep(2)
        self._session_valid = True
        print("[링커리어] 세션 재획득 완료")

    def _build_variables(self, user_profile: dict, page: int = 1) -> dict:
        category_ids = CATEGORY_MAP.get(user_profile.get("category", "IT/인터넷"), [58])
        region_ids = REGION_MAP.get(user_profile.get("location", "서울"), [2])
        job_types = JOBTYPE_MAP.get(user_profile.get("employment_type", "인턴"), ["INTERN"])
        variables = {
            "filterBy": {"status": "OPEN", "activityTypeID": 5},
            "orderBy": {"field": "RECENT", "direction": "DESC"},
            "page": page, "pageSize": 20,
        }
        if category_ids:
            variables["filterBy"]["categoryIDs"] = category_ids
        if region_ids:
            variables["filterBy"]["regionIDs"] = region_ids
        if job_types:
            variables["filterBy"]["jobTypes"] = job_types
        return variables

    async def fetch_job_list(self, user_profile: dict, page: int = 1) -> list[dict]:
        if not self._session_valid:
            await self._refresh_session()

        variables = self._build_variables(user_profile, page)
        variables_str = json.dumps(variables, ensure_ascii=False)
        extensions = json.dumps({
            "persistedQuery": {"version": 1, "sha256Hash": PERSISTED_QUERY_HASH}
        })
        variables_js = json.dumps(variables_str)
        extensions_js = json.dumps(extensions)

        async def _call():
            return await self.page.evaluate(f"""
                async () => {{
                    const url = new URL('{GRAPHQL_URL}');
                    url.searchParams.set('operationName', 'RecruitList');
                    url.searchParams.set('variables', {variables_js});
                    url.searchParams.set('extensions', {extensions_js});
                    const res = await fetch(url.toString(), {{
                        headers: {{
                            'Accept': 'application/json',
                            'Origin': 'https://linkareer.com',
                            'Referer': 'https://linkareer.com/',
                        }}
                    }});
                    if (!res.ok) throw new Error(`HTTP ${{res.status}}`);
                    return await res.json();
                }}
            """)

        response_data = await self._fetch_with_retry(_call)
        if not response_data:
            return []

        nodes = response_data.get("data", {}).get("activities", {}).get("nodes", [])
        jobs = [self._normalize(node, user_profile) for node in nodes]
        jobs = [j for j in jobs if j]
        await self._delay()
        return jobs

    def _normalize(self, node: dict, user_profile: dict) -> Optional[dict]:
        try:
            activity_id = node.get("id", "")
            close_at_ms = node.get("recruitCloseAt")
            deadline = datetime.fromtimestamp(close_at_ms / 1000).strftime("%Y-%m-%d") if close_at_ms else None
            regions = node.get("regions", [])
            addresses = node.get("addresses", [])
            if addresses:
                addr = addresses[0]
                location = f"{addr.get('sido','')} {addr.get('sigungu','')}".strip()
            elif regions:
                location = ", ".join(r.get("name","") for r in regions[:2])
            else:
                location = ""
            job_types = node.get("jobTypes", [])
            recruit_infos = node.get("recruitInformations", [])
            emp_type = self._parse_emp_type(job_types, recruit_infos)
            return {
                "title": node.get("title", ""),
                "company": node.get("organizationName", ""),
                "category": user_profile.get("category", "IT/인터넷"),
                "employment_type": emp_type,
                "location": location, "deadline": deadline,
                "source": "링커리어",
                "source_url": f"{BASE_URL}/activity/{activity_id}",
                "rating": None, "competition_ratio": None,
                "_raw": {
                    "id": activity_id, "job_types": job_types,
                    "scrap_count": node.get("scrapCount", 0),
                    "view_count": node.get("viewCount", 0),
                }
            }
        except Exception as e:
            print(f"[링커리어] 파싱 오류: {e}")
            return None

    def _parse_emp_type(self, job_types: list, recruit_infos: list) -> str:
        types = set(job_types)
        if "INTERN" in types:
            intern_types = []
            for info in recruit_infos:
                if info.get("jobType") == "INTERN":
                    for it in info.get("internTypes", []):
                        intern_types.append(it.get("name", ""))
            if intern_types:
                unique = list(set(intern_types))
                return f"인턴({unique[0]})" if len(unique) == 1 else "인턴"
            return "인턴"
        if "NEW" in types and "EXPERIENCED" in types:
            return "신입/경력"
        if "NEW" in types:
            return "신입"
        if "EXPERIENCED" in types:
            return "경력"
        return "기타"