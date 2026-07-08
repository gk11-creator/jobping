"""
링커리어 어댑터
"""
import asyncio
import json
from datetime import datetime
from typing import Optional
from adapters.base_adapter import BaseAdapter
from adapters.category_map import get_search_keyword

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

# 카테고리 ID 기반 목록 조회 (직무 대분류/상세 필터 클릭 시 나가는 쿼리)
CATEGORY_QUERY_HASH = "f674e1f77d004204d63b94f4b8bb49fd91138ee4cce1c62c1096876d49f201a2"
# 자유 텍스트 키워드 검색 (사이트 검색창 직접 입력 시 나가는 쿼리) — DevTools로 직접 확인함
SEARCH_QUERY_HASH = "766eb8eb6e4365ccb326a8168ad86dffaa86a1b138dcd2450faa3c3af883a0e6"

# 채용공고(인턴/신입/경력 공고)의 activityTypeID. 공모전/이벤트 등 다른 액티비티
# 타입과 섞이지 않도록 검색시에도 반드시 이 값으로 필터링해야 함
# (검색 API로 "법무" 검색시 "법무부 OO 공모전" 같은 무관한 결과가 섞이는 것을 확인함)
RECRUIT_ACTIVITY_TYPE_ID = 5


class LinkareerAdapter(BaseAdapter):

    async def _refresh_session(self):
        print("[링커리어] 세션 재획득 중...")
        await self._goto_safe(BASE_URL)
        await asyncio.sleep(2)
        self._session_valid = True
        print("[링커리어] 세션 재획득 완료")

    def _build_variables(self, user_profile: dict, page: int = 1) -> dict:
        # 카테고리가 CATEGORY_MAP에 등록돼 있지 않으면 categoryIDs 필터 자체를
        # 생략한다 (예전엔 "IT/인터넷"[58]으로 고정돼서 무관한 카테고리로 새는
        # 문제가 있었음). 실제 검색 폴백은 fetch_job_list에서 별도 쿼리로 처리.
        category_ids = CATEGORY_MAP.get(user_profile.get("category", ""), [])
        region_ids = REGION_MAP.get(user_profile.get("location", "서울"), [2])
        job_types = JOBTYPE_MAP.get(user_profile.get("employment_type", "인턴"), ["INTERN"])
        variables = {
            "filterBy": {"status": "OPEN", "activityTypeID": RECRUIT_ACTIVITY_TYPE_ID},
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

    async def _graphql_call(self, operation_name: str, query_hash: str, variables: dict):
        variables_str = json.dumps(variables, ensure_ascii=False)
        extensions = json.dumps({
            "persistedQuery": {"version": 1, "sha256Hash": query_hash}
        })
        variables_js = json.dumps(variables_str)
        extensions_js = json.dumps(extensions)

        async def _call():
            return await self.page.evaluate(f"""
                async () => {{
                    const url = new URL('{GRAPHQL_URL}');
                    url.searchParams.set('operationName', '{operation_name}');
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

        return await self._fetch_with_retry(_call)

    async def fetch_job_list(self, user_profile: dict, page: int = 1) -> list[dict]:
        if not self._session_valid:
            await self._refresh_session()

        category = user_profile.get("category", "")
        category_ids = CATEGORY_MAP.get(category, [])

        if category_ids:
            # 등록된 카테고리 — 정밀 필터(categoryIDs) 사용
            variables = self._build_variables(user_profile, page)
            response_data = await self._graphql_call("RecruitList", CATEGORY_QUERY_HASH, variables)
            if not response_data:
                return []
            nodes = response_data.get("data", {}).get("activities", {}).get("nodes", [])
            jobs = [self._normalize(node, user_profile) for node in nodes]
        else:
            # 미등록 카테고리 — 자유 텍스트 키워드 검색으로 폴백
            # (예전엔 IT/인터넷[58]으로 고정되던 문제 — 구재정(디자인) 케이스로 확인됨)
            keyword = get_search_keyword(category)
            search_variables = {
                "filterBy": {
                    "query": keyword,
                    "isClosed": False,
                    "activityTypeID": RECRUIT_ACTIVITY_TYPE_ID,
                },
                "page": page,
                "pageSize": 20,
                "activityOrder": {"field": "RELEVANCE", "direction": "DESC"},
            }
            response_data = await self._graphql_call(
                "gqlActivitySearchResult", SEARCH_QUERY_HASH, search_variables
            )
            if not response_data:
                return []
            nodes = response_data.get("data", {}).get("activitySearch", {}).get("nodes", [])
            jobs = [self._normalize_search(node, user_profile) for node in nodes]

        jobs = [j for j in jobs if j]
        await self._delay()
        return jobs

    def _normalize(self, node: dict, user_profile: dict) -> Optional[dict]:
        """카테고리 목록(RecruitList) 응답 파싱"""
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
                "category": user_profile.get("category", ""),
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

    def _normalize_search(self, node: dict, user_profile: dict) -> Optional[dict]:
        """
        키워드 검색(gqlActivitySearchResult) 응답 파싱.
        RecruitList와 달리 실제 공고 데이터가 node["source"] 안에 한 겹 더 감싸져 있음.
        """
        try:
            source = node.get("source", {})
            activity_id = source.get("id", "")
            close_at_ms = source.get("recruitCloseAt")
            deadline = datetime.fromtimestamp(close_at_ms / 1000).strftime("%Y-%m-%d") if close_at_ms else None

            region_districts = source.get("regionDistricts", [])
            regions = source.get("regions", [])
            if region_districts:
                location = ", ".join(rd.get("name", "") for rd in region_districts[:2])
            elif regions:
                location = ", ".join(r.get("name", "") for r in regions[:2])
            else:
                location = ""

            job_types = source.get("jobTypes", [])
            recruit_infos = source.get("recruitInformations", [])
            emp_type = self._parse_emp_type(job_types, recruit_infos)

            return {
                "title": source.get("title", ""),
                "company": source.get("organizationName", ""),
                "category": user_profile.get("category", ""),
                "employment_type": emp_type,
                "location": location, "deadline": deadline,
                "source": "링커리어",
                "source_url": f"{BASE_URL}/activity/{activity_id}",
                "rating": None, "competition_ratio": None,
                "_raw": {
                    "id": activity_id, "job_types": job_types,
                    "scrap_count": source.get("scrapCount", 0),
                    "score": node.get("score"),
                }
            }
        except Exception as e:
            print(f"[링커리어] 검색결과 파싱 오류: {e}")
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