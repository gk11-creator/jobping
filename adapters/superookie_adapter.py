"""
슈퍼루키 어댑터 - /jobs/search URL 기반
"""
import asyncio
import re
import urllib.parse
from datetime import datetime, timedelta
from typing import Optional
from adapters.base_adapter import BaseAdapter
from adapters.category_map import get_search_keyword

DUTY_GROUP_MAP = {
    "IT개발 > 프론트엔드": ["661de91a8b129f42ef6c257c"],
    "IT개발 > 서버/백엔드": ["661de91a8b129f42ef6c257b"],
    "IT개발 > 데이터분석": ["661de91a8b129f42ef6c257d"],
    "IT개발 > AI/ML": ["661de91a8b129f42ef6c2581"],
    "IT개발 > iOS": ["661de91a8b129f42ef6c2583"],
    "IT개발 > 안드로이드": ["661de91a8b129f42ef6c2582"],
    "IT개발 > DevOps": ["661de91a8b129f42ef6c2580"],
    "IT개발 > QA": ["661de91a8b129f42ef6c257a"],
    "IT 전 직군": [
        "661de91a8b129f42ef6c257a", "661de91a8b129f42ef6c257b",
        "661de91a8b129f42ef6c257c", "661de91a8b129f42ef6c257d",
        "661de91a8b129f42ef6c257e", "661de91a8b129f42ef6c257f",
        "661de91a8b129f42ef6c2580", "661de91a8b129f42ef6c2581",
        "661de91a8b129f42ef6c2582", "661de91a8b129f42ef6c2583",
    ],
}

JOB_LEVEL_INTERN = "579f18168b129f673b4efebe"
BASE_URL = "https://www.superookie.com"
SEARCH_URL = f"{BASE_URL}/jobs/search"


class SuperookieAdapter(BaseAdapter):

    async def _refresh_session(self):
        print("[슈퍼루키] 세션 재획득 중...")
        try:
            await self.page.goto(BASE_URL, wait_until="domcontentloaded", timeout=15000)
            await asyncio.sleep(2)
        except Exception as e:
            print(f"[슈퍼루키] 세션 재획득 실패: {e}")
        self._session_valid = True
        print("[슈퍼루키] 세션 재획득 완료")

    def _build_search_params(self, user_profile: dict) -> str:
        """
        카테고리가 duty_group에 등록돼 있으면 정밀 필터(duty_group)를 사용하고,
        등록돼 있지 않으면 "IT 전 직군"으로 고정하는 대신 자유 검색어(q=)를 사용한다.
        (예전엔 미등록 카테고리가 전부 IT 전 직군[48개]으로 고정되는 문제가
        있었음 — 비IT 지망자 전원에게 영향을 준 것으로 확인됨)
        """
        category = user_profile.get("category", "")
        duty_groups = DUTY_GROUP_MAP.get(category, [])

        if duty_groups:
            params = f"q=&sort=&status=&job_level%5B%5D={JOB_LEVEL_INTERN}&job_type=job"
            for dg in duty_groups:
                params += f"&duty_group%5B%5D={dg}"
        else:
            keyword = get_search_keyword(category)
            encoded_keyword = urllib.parse.quote(keyword)
            params = f"q={encoded_keyword}&sort=&status=&job_level%5B%5D={JOB_LEVEL_INTERN}&job_type=job"

        return params

    async def fetch_job_list(self, user_profile: dict, page: int = 1) -> list[dict]:
        if not self._session_valid:
            await self._refresh_session()

        params = self._build_search_params(user_profile)
        url = f"{SEARCH_URL}?{params}"
        print(f"[슈퍼루키] 접속: {url[:80]}...")

        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(8)
            await self.page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(3)
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

        items = soup.select(".item-job")
        print(f"[슈퍼루키] 아이템 {len(items)}개 발견")

        for item in items:
                    try:
                        # 링크
                        link_tag = item.select_one("a.job-detail-link")
                        if not link_tag:
                            continue
                        href = link_tag.get("href", "")
                        source_url = href if href.startswith("http") else f"{BASE_URL}{href}"

                        # 제목
                        title_tag = item.select_one(".job-title")
                        title = title_tag.get_text(strip=True) if title_tag else ""
                        if not title:
                            continue

                        # 회사명