"""
오케스트레이터 — 여러 어댑터 동시 실행
"""
import asyncio
import re
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime

from adapters.base_adapter import BaseAdapter
from adapters.jobkorea_adapter import JobKoreaAdapter
from adapters.linkareer_adapter import LinkareerAdapter
from adapters.superookie_adapter import SuperookieAdapter
from adapters.catch_adapter import CatchAdapter
from adapters.jasoseol_adapter import JasoseolAdapter
from adapters.wanted_adapter import WantedAdapter
from adapters.saramin_adapter import SaraminAdapter


def _normalize_for_dedup(text: str) -> str:
    """
    중복 판별용 문자열 정규화.

    다른 소스(예: 링커리어 vs 원티드)에서 같은 공고를 서로 다른 표기로
    내려주는 경우가 있어서 (법인 표기 유무, 대괄호 태그, 공백 차이,
    구두점 차이 등) 단순 strip().lower()만으로는 같은 공고를 다른 공고로
    오인해 둘 다 남기는 문제가 있었다.
    - 조현용 케이스: "에너닷" vs "(주)에너닷" / "[에너닷] DR사업 PM" vs "DR사업 PM"
    - 플레이타임중앙 케이스: 잡코리아는 "대리·과장급"(가운뎃점), 사람인은
      "대리~과장급"(물결표)로 같은 공고를 다르게 표기해서 중복 제거 실패

    - 법인 표기(주식회사/㈜/(주)) 제거
    - 대괄호/괄호로 감싼 부가 태그 제거 (예: "[쿠팡]", "(경력)")
    - 한글/영문/숫자를 제외한 모든 문자(공백, 구두점, 특수기호) 제거
      -- 사이트마다 표기가 미묘하게 다른 구두점(·, ~, /, - 등)까지
      전부 무시하기 위함
    """
    if not text:
        return ""
    text = text.strip().lower()
    text = re.sub(r"주식회사|㈜|\(주\)", "", text)
    text = re.sub(r"[\[\(].*?[\]\)]", "", text)
    text = re.sub(r"[^0-9a-zA-Z가-힣]", "", text)
    return text

class Orchestrator:
    def __init__(self, headless: bool = True):
        self.headless = headless

    async def _run_adapter(self, adapter: BaseAdapter, user_profile: dict, max_pages: int) -> list[dict]:
        name = adapter.__class__.__name__
        try:
            await adapter.start(headless=self.headless)
            jobs = await adapter.collect_all_pages(user_profile, max_pages=max_pages)
            print(f"[오케스트레이터] {name} 완료: {len(jobs)}개")
            return jobs
        except Exception as e:
            print(f"[오케스트레이터] {name} 실패: {e}")
            return []
        finally:
            await adapter.stop()

    async def run(self, user_profile: dict, max_pages: int = 3) -> list[dict]:
        adapters = [
            JobKoreaAdapter(),
            LinkareerAdapter(),
            SuperookieAdapter(),
            CatchAdapter(),
            JasoseolAdapter(),
            WantedAdapter(),
            SaraminAdapter(),
        ]

        print(f"[오케스트레이터] 수집 시작 — {len(adapters)}개 사이트")
        start_time = datetime.now()

        results = await asyncio.gather(
            *[self._run_adapter(a, user_profile, max_pages) for a in adapters],
            return_exceptions=False
        )

        all_jobs = []
        for jobs in results:
            all_jobs.extend(jobs)

        elapsed = (datetime.now() - start_time).seconds
        print(f"[오케스트레이터] 수집 완료: 총 {len(all_jobs)}개 ({elapsed}초)")

        all_jobs = self._deduplicate(all_jobs)
        all_jobs = self._sort(all_jobs)

        print(f"[오케스트레이터] 중복 제거 후: {len(all_jobs)}개")
        return all_jobs

    def _deduplicate(self, jobs: list[dict]) -> list[dict]:
        seen = {}
        for job in jobs:
            key = (
                _normalize_for_dedup(job.get("company", "")),
                _normalize_for_dedup(job.get("title", ""))[:20],
            )
            if key not in seen:
                seen[key] = job
            else:
                # 이미 있는 공고와 중복 — rating(평점) 있는 쪽을 우선 보존
                if job.get("rating") and not seen[key].get("rating"):
                    seen[key] = job
        return list(seen.values())

    def _sort(self, jobs: list[dict]) -> list[dict]:
        """
        정렬 우선순위: match_type(정밀 카테고리 매칭 vs 키워드 검색 폴백) 먼저,
        그다음 마감일 임박도, 그다음 평점.

        예전엔 마감일 임박도만으로 전체를 섞어서 정렬했는데, 이러면 뒤에서
        score_jobs()가 상위 60개만 잘라서 GPT에게 넘길 때 정밀 카테고리로
        찾은 정확한 결과(예: 원티드의 카테고리 코드 기반 검색)가 단순히
        "마감일이 조금 늦다"는 이유만으로 60등 밖으로 밀려나 GPT 눈에 아예
        안 보이는 문제가 있었음 (장세욱/구재정 케이스로 확인됨).
        정밀 매칭 결과를 항상 먼저 배치해 이 문제를 막는다.
        """
        today = datetime.now().date()

        def sort_key(job):
            # match_type 태그가 없는 경우(과거 데이터 호환 등) category로 간주
            match_type = job.get("match_type", "category")
            match_priority = 0 if match_type == "category" else 1

            deadline = job.get("deadline")
            rating = job.get("rating") or 0.0
            if deadline:
                try:
                    d = datetime.strptime(deadline, "%Y-%m-%d").date()
                    days_left = (d - today).days
                    if days_left < 0:
                        return (match_priority, 2, 9999, -rating)
                    return (match_priority, 0, days_left, -rating)
                except ValueError:
                    return (match_priority, 1, 9999, -rating)
            return (match_priority, 1, 9999, -rating)

        return sorted(jobs, key=sort_key)