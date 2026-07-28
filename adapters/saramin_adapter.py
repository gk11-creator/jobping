"""
사람인 어댑터

[아키텍처 변경 이력]
1차: cat_kewd 기반 카테고리 코드 검색 -> 미등록 카테고리 전부 "서버/백엔드"로
    고정되는 버그 확인, 폐기.
2차: get-similar-recruit-list AJAX 엔드포인트를 직접 호출하는 방식으로 시도.
    실제 브라우저 네비게이션에선 정상 접속되나, 이 엔드포인트가 "가구디자인"
    같은 일부 키워드에 대해 resultCode: "empty"를 반환하는 것을 확인 --
    이 API가 전체 검색 결과가 아니라 제한적인 "관련 채용" 위젯일 가능성이
    높음. 폐기.
3차(현재): 실제 검색 페이지(/zf_user/search?searchword=...)로 직접 이동한
    뒤, 사이트 자체 JS가 결과를 채울 시간을 주고, 완성된 DOM을 그대로
    긁는 방식. 엔드포인트를 추측할 필요가 없어 더 안정적이다.

    또한 headless=True(서버 자동화 모드)에서만 page.goto(BASE_URL)이
    15초 타임아웃 나는 현상을 확인 -- headless=False(실제 창)에서는
    정상 로드됨. 구형 헤드리스 크로미움 탐지로 추정되며, BaseAdapter의
    launch 인자에 "--headless=new"(신형 헤드리스)를 추가해 대응함
    (base_adapter.py 참고).

    검색 결과 각 항목 구조(실측):
        <span class="corp_name"><a title="회사명">...</a></span>
        <h2 class="job_tit"><a title="제목" href="...rec_idx=...">...</a></h2>
        <div class="job_condition"><span><a href=".../area/...">지역</a>...</span><span>경력조건</span></div>
        <div class="job_date"><span class="date">~ 08/08(수)</span></div>

[미검증 부분 - 배포 전 반드시 디버그 로그로 확인]
- 검색 결과가 페이지 로드 후 몇 초 만에 다 채워지는지 (지금은 4초 고정 대기 -
  느리면 늘려야 함)
- 페이지네이션 URL 파라미터 (recruitPage= 로 추정, 미검증)
"""
import asyncio
import re
import urllib.parse
from datetime import datetime, timedelta
from typing import Optional
from adapters.base_adapter import BaseAdapter
from adapters.category_map import get_search_keyword

BASE_URL = "https://www.saramin.co.kr"
SEARCH_URL = f"{BASE_URL}/zf_user/search"

JOB_LINK_PATTERN = re.compile(r"rec_idx=(\d+)")

DEADLINE_TEXT_PATTERN = re.compile(
    r"(오늘\s*마감|내일\s*마감|모레\s*마감|상시\s*채용|채용\s*시\s*마감|"
    r"~?\s*\d{1,2}\s*[./]\s*\d{1,2}\s*(?:\([가-힣]\))?|D-\d+)"
)


class SaraminAdapter(BaseAdapter):

    async def _refresh_session(self):
        print("[사람인] 세션 재획득 중...")
        try:
            await self.page.goto(BASE_URL, wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(2)
            self._session_valid = True
            print("[사람인] 세션 재획득 완료")
        except Exception as e:
            print(f"[사람인] 세션 재획득 실패: {e}")
            self._session_valid = True

    async def fetch_job_list(self, user_profile: dict, page: int = 1) -> list[dict]:
        if not self._session_valid:
            await self._refresh_session()

        category = user_profile.get("category", "")
        industries = user_profile.get("industries", [])
        keyword = get_search_keyword(category, industries)
        encoded_keyword = urllib.parse.quote(keyword)

        url = (
            f"{SEARCH_URL}?search_area=main&search_done=y&search_optional_item=n"
            f"&searchType=search&searchword={encoded_keyword}&recruitPage={page}"
        )
        print(f"[사람인][디버그] 검색페이지 접속: {url}")

        try:
            await self._goto_safe(url)
            # 고정 4초 대기 대신 실제 공고 항목(h2.job_tit)이 DOM에 나타날
            # 때까지 최대 10초 기다린다. 검색 결과 건수가 많을수록(예:
            # "IT 영업" 8천여 건 vs "가구디자인" 소량) 렌더링 시간이 달라져서
            # 고정 대기로는 결과가 많은 검색어에서 항목이 채워지기 전에
            # 읽어버려 0개로 나오는 문제가 있었다.
            try:
                await self.page.wait_for_selector("h2.job_tit", timeout=10000)
            except Exception:
                print("[사람인][디버그] h2.job_tit 10초 대기 후에도 안 나타남 -- "
                      "빈 결과이거나 셀렉터/차단 문제일 수 있음")
            await asyncio.sleep(1)  # 추가 항목들 마저 로드될 여유
            html = await self.page.content()
        except Exception as e:
            print(f"[사람인] 검색페이지 접속 실패: {e}")
            return []

        jobs = self._parse_html(html, user_profile)
        for j in jobs:
            j["match_type"] = "keyword"
            j["_matched_keyword"] = keyword

        print(f"[사람인] {len(jobs)}개 파싱 완료")
        await asyncio.sleep(2)
        return jobs

    def _parse_html(self, html: str, user_profile: dict) -> list[dict]:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")

        # 실제 구조 확인 결과: 공고 항목은 <li>가 아니라
        # <div class="item_recruit" value="54360251" ...> 형태였다.
        # 예전 코드가 무조건 <li> 태그만 뒤져서 h2.job_tit를 찾았는데,
        # h2.job_tit 자체는 페이지에 존재해도 <li> 안에 없어서 항상 0개로
        # 나온 것 -- 대기시간 문제가 아니라 셀렉터 자체가 잘못됐던 것.
        items = soup.select("div.item_recruit")

        if not items:
            print(f"[사람인][디버그] 공고 항목 0개 -- HTML 응답 길이: {len(html)}자 "
                  f"(page.content() 시점에 아직 렌더링 안 됐거나 셀렉터 재확인 필요)")
            return []

        jobs = []
        debug_count = 0

        for item in items:
            try:
                title_tag = item.select_one("h2.job_tit a")
                if not title_tag:
                    continue
                title = title_tag.get("title", "") or title_tag.get_text(strip=True)
                if not title:
                    continue

                href = title_tag.get("href", "")
                m = JOB_LINK_PATTERN.search(href)
                rec_idx = m.group(1) if m else None
                source_url = href if href.startswith("http") else f"{BASE_URL}{href}" if href else ""

                corp_tag = item.select_one("div.area_corp")
                company = ""
                if corp_tag:
                    # area_corp 안에는 회사명 외에 "관심기업 등록", "기업정보",
                    # "공고 모아보기" 같은 UI 버튼 텍스트가 같이 들어있어서
                    # get_text()로 통째로 가져오면 다 붙어버린다. 실제 회사명은
                    # 보통 링크(<a>) 텍스트나 첫 번째 텍스트 노드이므로, 그
                    # 안의 링크 텍스트를 우선 시도하고, 없으면 알려진 버튼
                    # 문구들을 잘라낸다.
                    name_link = corp_tag.select_one("a")
                    if name_link:
                        company = name_link.get_text(strip=True)
                    else:
                        raw_company = corp_tag.get_text(strip=True)
                        for noise in ["관심기업 등록", "기업정보", "공고 모아보기", "+"]:
                            raw_company = raw_company.replace(noise, "")
                        company = raw_company.strip()
                if not company:
                    corp_tag_fallback = item.select_one("span.corp_name a")
                    if corp_tag_fallback:
                        company = corp_tag_fallback.get("title", "") or corp_tag_fallback.get_text(strip=True)

                condition_div = item.select_one("div.job_condition")
                location = ""
                if condition_div:
                    region_links = condition_div.select("a")
                    location = " ".join(a.get_text(strip=True) for a in region_links[:2])

                date_tag = item.select_one("div.job_date span.date")
                deadline_raw = date_tag.get_text(strip=True) if date_tag else ""
                deadline = self._parse_deadline(deadline_raw)

                if debug_count < 3:
                    print(f"[사람인][디버그] '{title[:20]}' / {company} / {location} / "
                          f"마감원문:'{deadline_raw}' -> {deadline} / url:{source_url[:60]}")
                    debug_count += 1

                jobs.append({
                    "title": title,
                    "company": company,
                    "category": "",
                    "employment_type": "",
                    "location": location,
                    "deadline": deadline,
                    "source": "사람인",
                    "source_url": source_url,
                    "rating": None, "competition_ratio": None,
                    "_raw": {"rec_idx": rec_idx, "deadline_raw": deadline_raw},
                })
            except Exception as e:
                print(f"[사람인] 항목 파싱 오류: {e}")

        print(f"[사람인][디버그] 파싱된 공고 {len(jobs)}개 (제목 샘플): "
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
        m = re.search(r"(\d{1,2})\s*[./]\s*(\d{1,2})", raw)
        if m:
            month, day = int(m.group(1)), int(m.group(2))
            year = today.year if month >= today.month else today.year + 1
            return f"{year}-{month:02d}-{day:02d}"
        m2 = re.search(r"D-(\d+)", raw)
        if m2:
            return (today + timedelta(days=int(m2.group(1)))).strftime("%Y-%m-%d")
        return None
