"""
오케스트레이터 — 6개 어댑터 동시 실행
"""
import asyncio
import json
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime
from typing import Optional

from adapters.base_adapter import BaseAdapter
# from adapters.saramin_adapter import SaraminAdapter
from adapters.jobkorea_adapter import JobKoreaAdapter
from adapters.linkareer_adapter import LinkareerAdapter
# from adapters.incruit_adapter import IncruitAdapter
from adapters.superookie_adapter import SuperookieAdapter
# from adapters.jobplanet_adapter import JobplanetAdapter

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

    def _sort(self, jobs: list[dict]) -> list[dict]:
        today = datetime.now().date()

        def sort_key(job):
            deadline = job.get("deadline")
            rating = job.get("rating") or 0.0
            if deadline:
                try:
                    d = datetime.strptime(deadline, "%Y-%m-%d").date()
                    days_left = (d - today).days
                    if days_left < 0:
                        return (2, 9999, -rating)
                    return (0, days_left, -rating)
                except ValueError:
                    return (1, 9999, -rating)
            return (1, 9999, -rating)

        return sorted(jobs, key=sort_key)