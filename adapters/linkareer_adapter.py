"""
링커리어 어댑터

[검색 전략 변경 - 검색 최우선]
기존엔 CATEGORY_MAP에 등록된 카테고리면 categoryIDs 정밀 필터를 우선 쓰고,
등록 안 된 카테고리만 키워드 검색으로 폴백했다. 그런데 categoryIDs 필터가
"IT기획/PM"[114] 요청에 마케팅/그로스/영업 성격의 공고를 반환하는 등
카테고리 코드 자체의 신뢰도가 낮은 것이 확인되어, 이제 순서를 뒤집는다:

1) 사용자의 관심 산업(industries) + 카테고리 키워드를 조합한 자유 검색을
   항상 먼저 시도한다 (예: "IT 영업").
2) 검색 결과가 너무 적으면(5개 미만) categoryIDs 정밀 필터(CATEGORY_QUERY_HASH)
   결과로 보충한다 -- 완전히 버리진 않되 보조 수단으로만 사용.

검색은 GraphQL persistedQuery 해시 추측 방식이 항상 0개를 반환하는 것이
확인되어(조현용 "IT 영업" 케이스), 실제 검색 결과 페이지(/search?q=...)를
직접 스크래핑하는 방식으로 교체했다. DevTools로 확인한 실제 구조:

    <div data-activityid="333202" class="large ActivityListItem-ua...">
      <div>...<img alt="[신원] 수출부문 KNIT 해외영업... 경력 채용" .../></div>
      <div>
        <a class="link" href="/activity/333202">
          <p class="title">"[신원] 수출부문 KN" <b class="highlight">IT</b> " 해외"
            <b class="highlight">영업</b> "(Old Navy/Active) 경력 채용"</p>
        </a>
        <p class="short-info-typo">경력직</p>
        <p class="category">영업/CS</p>
        <p class="short-info-typo">~ 07.31</p>
      </div>
    </div>

제목은 검색어가 <b class="highlight">로 하이라이트되어 조각나 있지만,
get_text()로 이어붙이면 원래 문장이 복원된다. href가 실제 상세페이지
경로를 바로 제공하므로 activity_id 추정이 필요 없다.

검색 결과는 match_type="keyword"로 태깅되어 사전필터(prefilter_by_category)의
제목 관련성 검증을 반드시 거치고, categoryIDs 보충 결과도 동일하게 검증받도록
_matched_keyword를 붙인다.
"""
import asyncio
import json
import re
import urllib.parse
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

CATEGORY_QUERY_HASH = "f674e1f77d004204d63b94f4b8bb49fd91138ee4cce1c62c1096876d49f201a2"

RECRUIT_ACTIVITY_TYPE_ID = 5
MIN_SEARCH_RESULTS = 5

DEADLINE_PATTERN = re.compile(r"~?\s*(\d{1,2})\s*\.\s*(\d{1,2})|상시|마감|D-\d+")


class LinkareerAdapter(BaseAdapter):

    async def _refresh_session(self):
        print("[링커리어] 세션 재획득 중...")
        await self._goto_safe(BASE_URL)
        await asyncio.sleep(2)
        self._session_valid = True
        print("[링커리어] 세션 재획득 완료")

    def _build_category_variables(self, user_profile: dict, page: int, category_ids: list) -> dict:
        region_ids = REGION_MAP.get(user_profile.get("location", "서울"), [2])
        job_types = JOBTYPE_MAP.get(user_profile.get("employment_type", "인턴"), ["INTERN"])
        variables = {
            "filterBy": {"status": "OPEN", "activityTypeID": RECRUIT_ACTIVITY_TYPE_ID, "categoryIDs": category_ids},
            "orderBy": {"field": "RECENT", "direction": "DESC"},
            "page": page, "pageSize": 20,
        }
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

    def _parse_deadline_text(self, raw: str):
        if not raw:
            return None
        if "상시" in raw:
            return None
        today = datetime.now()
        m = re.search(r"(\d{1,2})\s*\.\s*(\d{1,2})", raw)
        if m:
            month, day = int(m.group(1)), int(m.group(2))
            year = today.year if month >= today.month else today.year + 1
            return f"{year}-{month:02d}-{day:02d}"
        m2 = re.search(r"D-(\d+)", raw)
        if m2:
            from datetime import timedelta
            return (today + timedelta(days=int(m2.group(1)))).strftime("%Y-%m-%d")
        return None

    async def _fetch_by_keyword(self, keyword: str, page: int, user_profile: dict) -> list[dict]:
        encoded = urllib.parse.quote(keyword)
        url = f"{BASE_URL}/search?q={encoded}&page={page}"
        print(f"[링커리어][디버그] 검색페이지 접속: {url}")

        try:
            await self._goto_safe(url)
            await asyncio.sleep(3)
            html = await self.page.content()
        except Exception as e:
            print(f"[링커리어] 검색페이지 접속 실패: {e}")
            return []

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")

        items = soup.select("div[data-activityid]")
        seen_ids = set()
        jobs = []
        debug_count = 0

        for item in items:
            activity_id = item.get("data-activityid", "")
            if not activity_id or activity_id in seen_ids:
                continue
            seen_ids.add(activity_id)

            title_tag = item.select_one("p.title")
            if title_tag:
                full_title = title_tag.get_text(strip=True)
                anchor = item.select_one('a[href^="/activity/"]')
                href = anchor.get("href", "") if anchor else f"/activity/{activity_id}"
            else:
                img = item.find("img", alt=True)
                full_title = img.get("alt", "").strip() if img else ""
                href = f"/activity/{activity_id}"

            if not full_title:
                continue

            m = re.match(r"^\[([^\]]+)\]\s*(.*)", full_title)
            if m:
                company = m.group(1)
                title = m.group(2) or full_title
            else:
                company = ""
                title = full_title

            source_url = href if href.startswith("http") else f"{BASE_URL}{href}"

            category_tag = item.select_one("p.category")
            category_text = category_tag.get_text(strip=True) if category_tag else ""

            deadline_raw = ""
            for p in item.select("p.short-info-typo"):
                t = p.get_text(strip=True)
                if DEADLINE_PATTERN.search(t):
                    deadline_raw = t
                    break
            deadline = self._parse_deadline_text(deadline_raw)

            if debug_count < 3:
                print(f"[링커리어][디버그] activityid={activity_id} / 제목:'{title[:30]}' / "
                      f"회사:'{company}' / 실제카테고리:'{category_text}' / 마감:'{deadline_raw}'->{deadline}")
                debug_count += 1

            jobs.append({
                "title": title,
                "company": company,
                "category": user_profile.get("category", ""),
                "employment_type": "",
                "location": "",
                "deadline": deadline,
                "source": "링커리어",
                "source_url": source_url,
                "rating": None, "competition_ratio": None,
                "match_type": "keyword",
                "_matched_keyword": keyword,
                "_raw": {"id": activity_id, "site_category": category_text},
            })

        print(f"[링커리어][디버그] 검색페이지 파싱 결과 {len(jobs)}개")
        return jobs

    async def _fetch_by_category(self, user_profile: dict, page: int, category_ids: list) -> list[dict]:
        variables = self._build_category_variables(user_profile, page, category_ids)
        response_data = await self._graphql_call("RecruitList", CATEGORY_QUERY_HASH, variables)
        if not response_data:
            return []
        nodes = response_data.get("data", {}).get("activities", {}).get("nodes", [])
        return [self._normalize(node, user_profile) for node in nodes]

    async def fetch_job_list(self, user_profile: dict, page: int = 1) -> list[dict]:
        if not self._session_valid:
            await self._refresh_session()

        category = user_profile.get("category", "")
        industries = user_profile.get("industries", [])
        keyword = get_search_keyword(category, industries)

        print(f"[링커리어][디버그] 키워드 검색 우선 시도: '{keyword}'")
        jobs = await self._fetch_by_keyword(keyword, page, user_profile)
        jobs = [j for j in jobs if j]
        print(f"[링커리어][디버그] 키워드 검색 결과: {len(jobs)}개")

        if len(jobs) < MIN_SEARCH_RESULTS:
            category_ids = CATEGORY_MAP.get(category, [])
            if category_ids:
                print(f"[링커리어][디버그] 결과 부족 -- categoryIDs {category_ids}로 보충 시도")
                existing_ids = {j.get("_raw", {}).get("id") for j in jobs}
                backup_jobs = await self._fetch_by_category(user_profile, page, category_ids)
                for bj in backup_jobs:
                    if not bj:
                        continue
                    bid = bj.get("_raw", {}).get("id")
                    if bid not in existing_ids:
                        bj["_matched_keyword"] = keyword
                        jobs.append(bj)
                        existing_ids.add(bid)
                print(f"[링커리어][디버그] 보충 후 총 {len(jobs)}개")

        await self._delay()
        return jobs

    def _normalize(self, node: dict, user_profile: dict):
        """카테고리 목록(RecruitList) 응답 파싱 -- 결과 부족시 보충용"""
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
                "match_type": "category",
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
