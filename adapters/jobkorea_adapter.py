"""
잡코리아 어댑터
"""
import asyncio
import re
import urllib.parse
from datetime import datetime, timedelta
from typing import Optional
from adapters.base_adapter import BaseAdapter
from adapters.category_map import get_search_keyword

DUTY_MAP = {
    "IT개발 > 서버/백엔드": ["1000229"], "IT개발 > 프론트엔드": ["1000230"],
    "IT개발 > 풀스택": ["1000229","1000230"], "IT개발 > 안드로이드": ["1000232"],
    "IT개발 > iOS": ["1000233"], "IT개발 > AI/ML": ["1000238"],
    "IT개발 > 데이터분석": ["1000237"], "IT개발 > 데브옵스/인프라": ["1000236"],
    "IT개발 > 보안": ["1000234"], "IT개발 > QA": ["1000235"],
    "IT개발 > 게임": ["1000231"], "기획/전략": ["1000101"],
    "마케팅/광고": ["1000103"], "디자인": ["1000201"], "영업": ["1000301"],
    "법무/컴플라이언스": ["1000065"], "경영지원/총무": ["1000065"],
    "영업/영업관리": ["1000301"],
    "IT개발 > Android": ["1000232"],
    "IT개발 > DevOps": ["1000236"],
}
LOCAL_MAP = {
    "서울":"I000","경기":"I001","인천":"I002","부산":"I003","대구":"I004",
    "광주":"I005","대전":"I006","울산":"I007","세종":"I008","강원":"I009",
    "경남":"I010","경북":"I011","전남":"I012","전북":"I013","충남":"I015",
    "충북":"I016","제주":"I017","해외":"I018","전국":"I019",
}
JOBTYPE_MAP = {"정규직":"1","계약직":"2","인턴":"3","파견직":"4","아르바이트":"5"}
BASE_URL = "https://www.jobkorea.co.kr"
API_URL = f"{BASE_URL}/Recruit/Home/_GI_List/"
SEARCH_URL = f"{BASE_URL}/Search"

JOB_LINK_PATTERN = re.compile(r"/Recruit/GI_Read/(\d+)")

DEADLINE_TEXT_PATTERN = re.compile(
    r"(오늘\s*마감|내일\s*마감|모레\s*마감|상시\s*채용|채용\s*시\s*마감|"
    r"~\s*\d{1,2}\s*/\s*\d{1,2}\s*(?:\([가-힣]\))?|D-\d+)"
)


class JobKoreaAdapter(BaseAdapter):

    async def _refresh_session(self):
        print("[잡코리아] 세션 재획득 중...")
        await self._goto_safe(BASE_URL)
        await asyncio.sleep(2)
        self._session_valid = True
        print("[잡코리아] 세션 재획득 완료")

    def _build_payload(self, user_profile: dict, page: int = 1) -> dict:
        category = user_profile.get("category", "")
        duty_codes = DUTY_MAP.get(category, [])

        payload = {
            "condition[duty]": ",".join(duty_codes),
            "condition[local]": LOCAL_MAP.get(user_profile.get("location", "서울"), "I000"),
            "condition[jobtype]": JOBTYPE_MAP.get(user_profile.get("employment_type", ""), ""),
            "condition[menucode]": "",
            "page": str(page), "pagesize": "40",
            "order": "20", "direct": "0", "onePick": "0", "confirm": "0",
            "tabindex": "0", "profile": "0",
        }
        return {k: v for k, v in payload.items() if v != ""}

    async def fetch_job_list(self, user_profile: dict, page: int = 1) -> list[dict]:
        if not self._session_valid:
            await self._refresh_session()

        category = user_profile.get("category", "")
        duty_codes = DUTY_MAP.get(category, [])

        if duty_codes:
            jobs = await self._fetch_by_duty(user_profile, page, duty_codes)
            for j in jobs:
                j["match_type"] = "category"
            return jobs
        else:
            keyword = get_search_keyword(category)
            jobs = await self._fetch_by_search_page(keyword, page, user_profile)
            for j in jobs:
                j["match_type"] = "keyword"
                j["_matched_keyword"] = keyword
            return jobs

    async def _fetch_by_duty(self, user_profile: dict, page: int, duty_codes: list) -> list[dict]:
        payload = self._build_payload(user_profile, page)
        payload_str = "&".join(f"{k}={v}" for k, v in payload.items())

        async def _call():
            result = await self.page.evaluate(f"""
                async () => {{
                    const res = await fetch('{API_URL}', {{
                        method: 'POST',
                        headers: {{
                            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                            'X-Requested-With': 'XMLHttpRequest',
                            'Referer': '{BASE_URL}/recruit/joblist',
                        }},
                        body: '{payload_str}'
                    }});
                    if (!res.ok) throw new Error(`HTTP ${{res.status}}`);
                    return await res.text();
                }}
            """)
            return result

        html = await self._fetch_with_retry(_call)
        if not html:
            return []

        jobs = self._parse_duty_html(html, user_profile)
        await self._delay()
        return jobs

    async def _fetch_by_search_page(self, keyword: str, page: int, user_profile: dict) -> list[dict]:
        encoded_keyword = urllib.parse.quote(keyword)
        url = f"{SEARCH_URL}?stext={encoded_keyword}&tabType=recruit&Page_No={page}"
        print(f"[잡코리아][디버그] 검색페이지 접속: {url}")

        try:
            await self._goto_safe(url)
            await asyncio.sleep(3)
            html = await self.page.content()
        except Exception as e:
            print(f"[잡코리아] 검색페이지 접속 실패: {e}")
            return []

        jobs = self._parse_search_html(html, user_profile, keyword)
        await self._delay()
        return jobs

    def _parse_duty_html(self, html: str, user_profile: dict) -> list[dict]:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        jobs = []
        for row in soup.select("tr.devloopArea"):
            try:
                gno = row.get("data-gno", "")
                if not gno:
                    continue
                company_tag = row.select_one("td.tplCo a.link")
                company = company_tag.get_text(strip=True) if company_tag else ""
                title_tag = row.select_one("td.tplTit strong a.link")
                title = title_tag.get_text(strip=True) if title_tag else ""
                href = title_tag.get("href", "") if title_tag else ""
                source_url = href if href.startswith("http") else f"{BASE_URL}{href}"
                etc_spans = row.select("td.tplTit .etc span.cell")
                etc_texts = [s.get_text(strip=True) for s in etc_spans]
                location, employment_type = "", ""
                for text in etc_texts:
                    if re.search(r"(서울|경기|인천|부산|대구|광주|대전|울산|강원|경남|경북|전남|전북|충남|충북|제주|세종)", text):
                        location = text
                    elif any(k in text for k in ["정규직","계약직","인턴","파견","아르바이트","프리랜서"]):
                        employment_type = text
                date_tag = row.select_one("td.odd .date")
                deadline_raw = date_tag.get_text(strip=True) if date_tag else ""
                jobs.append({
                    "title": title, "company": company,
                    "category": user_profile.get("category", ""),
                    "employment_type": employment_type or user_profile.get("employment_type", "정규직"),
                    "location": location or user_profile.get("location", ""),
                    "deadline": self._parse_deadline(deadline_raw),
                    "source": "잡코리아", "source_url": source_url,
                    "rating": None, "competition_ratio": None,
                    "_raw": {"gno": gno, "deadline_raw": deadline_raw, "etc": etc_texts}
                })
            except Exception as e:
                print(f"[잡코리아] 파싱 오류: {e}")
        return jobs

    def _extract_deadline_near(self, anchor, own_gno: str, debug: bool = False) -> str:
        """
        마감일이 정확히 어느 태그/클래스에 있는지 확인이 안 돼서, 앵커(공고
        제목 링크)의 조상 요소를 최대 6단계까지 올라가며 텍스트에서 마감일
        패턴을 찾는다.

        중요: 컨테이너 안에 이 공고(own_gno)가 아닌 다른 공고의 링크가 섞여
        있으면, 그 단계는 여러 공고 정보를 뭉쳐서 담고 있다는 뜻이라 신뢰하지
        않고 탐색을 중단한다 (실측 결과 조상 4단계에서 서로 다른 두 공고가
        동일한 마감일을 반환하는 오염 사례가 확인됨). 잘못된 마감일을 주는
        것보다는 마감일을 비워두는 게 안전하다.
        """
        container = anchor
        for level in range(6):
            if container.parent is None:
                break
            container = container.parent

            inner_links = container.find_all("a", href=JOB_LINK_PATTERN)
            inner_gnos = set()
            for a in inner_links:
                m = JOB_LINK_PATTERN.search(a.get("href", ""))
                if m:
                    inner_gnos.add(m.group(1))

            if inner_gnos - {own_gno}:
                if debug:
                    print(f"[잡코리아][디버그] 조상 {level+1}단계에서 다른 공고 혼입 감지 "
                          f"({inner_gnos - {own_gno}}) — 탐색 중단, 마감일 비움")
                return ""

            text = container.get_text(" ", strip=True)
            m = DEADLINE_TEXT_PATTERN.search(text)
            if m:
                if debug:
                    print(f"[잡코리아][디버그] 마감일 패턴 '{m.group(0)}' 발견 "
                          f"(조상 {level+1}단계, 컨테이너 길이 {len(text)}자, 다른 공고 혼입 없음)")
                return m.group(0)
        return ""

    def _parse_search_html(self, html: str, user_profile: dict, keyword: str) -> list[dict]:
        """
        실제 검색 페이지(/Search?stext=...) 파싱.
        """
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")

        job_links = soup.select('a[href*="/Recruit/GI_Read/"]')

        if not job_links:
            print(f"[잡코리아][디버그] 검색결과 링크 0개 — HTML 응답 길이: {len(html)}자")
            return []

        groups: dict = {}
        for a in job_links:
            href = a.get("href", "")
            m = JOB_LINK_PATTERN.search(href)
            if not m:
                continue
            gno = m.group(1)
            groups.setdefault(gno, []).append(a)

        jobs = []
        debug_count = 0
        for gno, anchors in groups.items():
            try:
                text_anchors = [a for a in anchors if a.get_text(strip=True)]
                if not text_anchors:
                    continue
                text_anchors.sort(key=lambda a: len(a.get_text(strip=True)), reverse=True)
                title = text_anchors[0].get_text(strip=True)
                company = ""
                for a in text_anchors[1:]:
                    t = a.get_text(strip=True)
                    if t and t != title:
                        company = t
                        break

                href = text_anchors[0].get("href", "")
                source_url = href if href.startswith("http") else f"{BASE_URL}{href}"

                if not title:
                    continue

                show_debug = debug_count < 3
                deadline_raw = self._extract_deadline_near(text_anchors[0], gno, debug=show_debug)
                deadline = self._parse_deadline(deadline_raw)
                if show_debug:
                    print(f"[잡코리아][디버그] '{title[:20]}' → 마감일 원문: '{deadline_raw}' → 파싱: {deadline}")
                    debug_count += 1

                jobs.append({
                    "title": title,
                    "company": company,
                    "category": user_profile.get("category", ""),
                    "employment_type": user_profile.get("employment_type", ""),
                    "location": user_profile.get("location", ""),
                    "deadline": deadline,
                    "source": "잡코리아",
                    "source_url": source_url,
                    "rating": None, "competition_ratio": None,
                    "_raw": {"gno": gno, "deadline_raw": deadline_raw},
                })
            except Exception as e:
                print(f"[잡코리아] 검색결과 파싱 오류: {e}")

        print(f"[잡코리아][디버그] 검색페이지에서 파싱된 공고 {len(jobs)}개 (제목 샘플): "
              f"{[j['title'][:30] for j in jobs[:10]]}")

        return jobs

    def _parse_deadline(self, raw: str) -> Optional[str]:
        if not raw:
            return None
        today = datetime.now()
        if "상시" in raw or "채용시" in raw:
            return None
        if "모레" in raw:
            return (today + timedelta(days=2)).strftime("%Y-%m-%d")
        if "내일" in raw:
            return (today + timedelta(days=1)).strftime("%Y-%m-%d")
        if "오늘" in raw:
            return today.strftime("%Y-%m-%d")
        m = re.search(r"~\s*(\d{1,2})\s*/\s*(\d{1,2})", raw)
        if m:
            month, day = int(m.group(1)), int(m.group(2))
            year = today.year if month >= today.month else today.year + 1
            return f"{year}-{month:02d}-{day:02d}"
        m2 = re.search(r"D-(\d+)", raw)
        if m2:
            return (today + timedelta(days=int(m2.group(1)))).strftime("%Y-%m-%d")
        return None