"""
잡코리아 어댑터
"""
import asyncio
import re
from datetime import datetime, timedelta
from typing import Optional
from adapters.base_adapter import BaseAdapter

DUTY_MAP = {
    "IT개발 > 서버/백엔드": ["1000229"], "IT개발 > 프론트엔드": ["1000230"],
    "IT개발 > 풀스택": ["1000229","1000230"], "IT개발 > 안드로이드": ["1000232"],
    "IT개발 > iOS": ["1000233"], "IT개발 > AI/ML": ["1000238"],
    "IT개발 > 데이터분석": ["1000237"], "IT개발 > 데브옵스/인프라": ["1000236"],
    "IT개발 > 보안": ["1000234"], "IT개발 > QA": ["1000235"],
    "IT개발 > 게임": ["1000231"], "기획/전략": ["1000101"],
    "마케팅/광고": ["1000103"], "디자인": ["1000201"], "영업": ["1000301"],
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


class JobKoreaAdapter(BaseAdapter):

    async def _refresh_session(self):
        print("[잡코리아] 세션 재획득 중...")
        await self._goto_safe(BASE_URL)
        await asyncio.sleep(2)
        self._session_valid = True
        print("[잡코리아] 세션 재획득 완료")

    def _build_payload(self, user_profile: dict, page: int = 1) -> dict:
        duty_codes = DUTY_MAP.get(user_profile.get("category", ""), [])
        payload = {
            "condition[duty]": ",".join(duty_codes),
            "condition[local]": LOCAL_MAP.get(user_profile.get("location", "서울"), "I000"),
            "condition[jobtype]": JOBTYPE_MAP.get(user_profile.get("employment_type", ""), ""),
            "condition[menucode]": "", "page": str(page), "pagesize": "40",
            "order": "20", "direct": "0", "onePick": "0", "confirm": "0",
            "tabindex": "0", "profile": "0",
        }
        return {k: v for k, v in payload.items() if v != ""}

    async def fetch_job_list(self, user_profile: dict, page: int = 1) -> list[dict]:
        if not self._session_valid:
            await self._refresh_session()

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

        jobs = self._parse_html(html, user_profile)
        await self._delay()
        return jobs

    def _parse_html(self, html: str, user_profile: dict) -> list[dict]:
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

    def _parse_deadline(self, raw: str) -> Optional[str]:
        today = datetime.now()
        if "상시" in raw or "채용시" in raw:
            return None
        if "모레" in raw:
            return (today + timedelta(days=2)).strftime("%Y-%m-%d")
        if "내일" in raw:
            return (today + timedelta(days=1)).strftime("%Y-%m-%d")
        m = re.search(r"~(\d{2})\/(\d{2})", raw)
        if m:
            month, day = int(m.group(1)), int(m.group(2))
            year = today.year if month >= today.month else today.year + 1
            return f"{year}-{month:02d}-{day:02d}"
        return None