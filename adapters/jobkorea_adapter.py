"""
잡코리아 어댑터

[중요 - 아키텍처 변경 이력]
원래는 카테고리가 DUTY_MAP에 등록돼 있으면 _GI_List 내부 API를
condition[duty] 파라미터로 호출해 정밀 필터링된 결과를 가져오고,
등록 안 된 카테고리만 검색페이지(/Search)로 폴백하는 구조였다.

그런데 실사용 데이터에서 동일 gno(예: 신한투자증권 리서치본부 인턴,
웅진식품 신입/경력 채용 등)가 "법무/컴플라이언스", "제조/QC/QA" 등
서로 무관한 카테고리 요청 양쪽에 그대로 반환되는 것이 반복 확인됐다
(김태진/박지훈/장세욱 케이스). 즉 _GI_List API가 condition[duty]
파라미터를 실제로는 무시하고 있는 것으로 보이며, 필터 없이 최신
전체 공고 피드를 그대로 돌려주고 있었다. 이 결과는 match_type=
"category"로 태깅되어 사전필터(prefilter_by_category)의 제목
관련성 검증도 건너뛰고, GPT 스코어링에서도 "직군 일치"로 오인되어
높은 점수를 받는 악순환이 있었다.

그래서 duty API 경로(condition[duty] 기반 정밀 검색)를 전면 폐기하고,
모든 카테고리에 대해 검색페이지(/Search?stext=...) 스크래핑 +
match_type="keyword" 태깅으로 통일한다. 이러면 사전필터의
_title_matches_keyword() 검증을 반드시 거치게 되어, 최소한
제목에 검색 키워드가 안 들어간 명백한 오탐은 걸러진다.
"""
import asyncio
import re
import urllib.parse
from datetime import datetime, timedelta
from typing import Optional
from adapters.base_adapter import BaseAdapter
from adapters.category_map import get_search_keyword

BASE_URL = "https://www.jobkorea.co.kr"
SEARCH_URL = f"{BASE_URL}/Search"

JOB_LINK_PATTERN = re.compile(r"/Recruit/GI_Read/(\d+)")

DEADLINE_TEXT_PATTERN = re.compile(
    r"(오늘\s*마감|내일\s*마감|모레\s*마감|상시\s*채용|채용\s*시\s*마감|"
    r"~\s*\d{1,2}\s*/\s*\d{1,2}\s*(?:\([가-힣]\))?|D-\d+)"
)

REGION_PATTERN = re.compile(
    r"(서울|경기|인천|부산|대구|광주|대전|울산|강원|경남|경북|"
    r"전남|전북|충남|충북|제주|세종)[가-힣]*"
)

EMPLOYMENT_KEYWORDS = ["정규직", "계약직", "인턴", "파견직", "아르바이트", "프리랜서"]
EMPLOYMENT_PATTERN = re.compile("|".join(EMPLOYMENT_KEYWORDS))


class JobKoreaAdapter(BaseAdapter):

    async def _refresh_session(self):
        print("[잡코리아] 세션 재획득 중...")
        await self._goto_safe(BASE_URL)
        await asyncio.sleep(2)
        self._session_valid = True
        print("[잡코리아] 세션 재획득 완료")

    async def fetch_job_list(self, user_profile: dict, page: int = 1) -> list[dict]:
        if not self._session_valid:
            await self._refresh_session()

        category = user_profile.get("category", "")
        industries = user_profile.get("industries", [])
        keyword = get_search_keyword(category, industries)
        jobs = await self._fetch_by_search_page(keyword, page, user_profile)
        for j in jobs:
            j["match_type"] = "keyword"
            j["_matched_keyword"] = keyword
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

    def _extract_text_near(self, anchor, own_gno: str, pattern: re.Pattern, debug: bool = False, label: str = "") -> str:
        """
        앵커(공고 제목 링크)의 조상 요소를 최대 6단계까지 올라가며 텍스트에서
        주어진 정규식 패턴을 찾는다. 컨테이너 안에 이 공고(own_gno)가 아닌
        다른 공고의 링크가 섞여 있으면 여러 공고 정보가 뭉쳐있다는 뜻이라
        신뢰하지 않고 탐색을 중단한다 (마감일 추출에서 발견된 오염 패턴과 동일
        — 조상 4단계에서 서로 다른 두 공고가 같은 값을 반환하는 사례 확인됨).
        잘못된 값을 주는 것보다는 비워두는 게 안전하다.
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
                    print(f"[잡코리아][디버그][{label}] 조상 {level+1}단계에서 다른 공고 혼입 감지 "
                          f"({inner_gnos - {own_gno}}) — 탐색 중단, {label} 비움")
                return ""

            text = container.get_text(" ", strip=True)
            m = pattern.search(text)
            if m:
                if debug:
                    print(f"[잡코리아][디버그][{label}] 패턴 '{m.group(0)}' 발견 "
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

                deadline_raw = self._extract_text_near(
                    text_anchors[0], gno, DEADLINE_TEXT_PATTERN, debug=show_debug, label="마감일"
                )
                deadline = self._parse_deadline(deadline_raw)

                # 위치/고용형태는 실제 공고 데이터를 최대한 시도하되, 못 찾으면
                # 빈 값으로 남긴다 (사용자 희망값을 실제 공고 정보인 것처럼
                # 잘못 표시하지 않기 위함 — 이전 버전의 문제였음).
                location_raw = self._extract_text_near(
                    text_anchors[0], gno, REGION_PATTERN, debug=show_debug, label="위치"
                )
                employment_raw = self._extract_text_near(
                    text_anchors[0], gno, EMPLOYMENT_PATTERN, debug=show_debug, label="고용형태"
                )

                if show_debug:
                    print(f"[잡코리아][디버그] '{title[:20]}' → 마감일 원문: '{deadline_raw}' → 파싱: {deadline}")
                    debug_count += 1

                jobs.append({
                    "title": title,
                    "company": company,
                    "category": user_profile.get("category", ""),
                    "employment_type": employment_raw or "",
                    "location": location_raw or "",
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