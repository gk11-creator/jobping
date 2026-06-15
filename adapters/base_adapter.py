"""
BaseAdapter — 모든 어댑터의 공통 베이스 클래스
"""
import asyncio
import random
from abc import ABC, abstractmethod
from typing import Optional, Any

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

try:
    from playwright_stealth import stealth_async
    STEALTH_AVAILABLE = True
except ImportError:
    STEALTH_AVAILABLE = False
    print("[BaseAdapter] 경고: playwright-stealth 미설치.")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
]

BLOCK_STATUS_CODES = {429, 403, 503, 502}
DELAY_MIN = 5.0
DELAY_MAX = 15.0
BLOCK_WAIT_MIN = 30.0
BLOCK_WAIT_MAX = 60.0
MAX_RETRIES = 3
BACKOFF_BASE = 2.0


class BlockedError(Exception):
    pass


class BaseAdapter(ABC):

    def __init__(self):
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self._playwright = None
        self._ua = random.choice(USER_AGENTS)
        self._session_valid = False
        self._request_count = 0

    async def start(self, headless: bool = True):
        self._playwright = await async_playwright().start()
        self.browser = await self._playwright.chromium.launch(
            headless=headless,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--disable-dev-shm-usage",
            ]
        )
        await self._new_context()

    async def _new_context(self):
        self._ua = random.choice(USER_AGENTS)
        if self.context:
            await self.context.close()
        self.context = await self.browser.new_context(
            user_agent=self._ua,
            viewport={"width": random.randint(1280, 1920), "height": random.randint(800, 1080)},
            locale="ko-KR",
            timezone_id="Asia/Seoul",
            java_script_enabled=True,
            extra_http_headers={
                "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            }
        )
        self.page = await self.context.new_page()
        if STEALTH_AVAILABLE:
            await stealth_async(self.page)
        else:
            await self.page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
                Object.defineProperty(navigator, 'languages', { get: () => ['ko-KR', 'ko', 'en-US'] });
                window.chrome = { runtime: {} };
            """)
        self._session_valid = False

    async def stop(self):
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def _delay(self, min_sec: float = DELAY_MIN, max_sec: float = DELAY_MAX):
        wait = random.uniform(min_sec, max_sec)
        print(f"[{self.__class__.__name__}] 대기 {wait:.1f}초...")
        await asyncio.sleep(wait)

    async def _block_delay(self):
        wait = random.uniform(BLOCK_WAIT_MIN, BLOCK_WAIT_MAX)
        print(f"[{self.__class__.__name__}] 차단 감지 — {wait:.0f}초 대기...")
        await asyncio.sleep(wait)

    async def _maybe_rotate_ua(self):
        self._request_count += 1
        if self._request_count % 50 == 0:
            await self._new_context()
            await self._refresh_session()

    async def _fetch_with_retry(self, fetch_fn, *args, max_retries: int = MAX_RETRIES, **kwargs) -> Any:
        last_error = None
        for attempt in range(1, max_retries + 1):
            try:
                result = await fetch_fn(*args, **kwargs)
                if isinstance(result, dict):
                    status = result.get("status_code") or result.get("code")
                    if status in BLOCK_STATUS_CODES:
                        raise BlockedError(f"status {status}")
                await self._maybe_rotate_ua()
                return result
            except BlockedError as e:
                print(f"[{self.__class__.__name__}] 차단 감지 (시도 {attempt}/{max_retries}): {e}")
                await self._block_delay()
                await self._new_context()
                await self._refresh_session()
                last_error = e
            except Exception as e:
                error_msg = str(e).lower()
                if any(k in error_msg for k in ["timeout", "net::", "connection", "refused"]):
                    backoff = BACKOFF_BASE ** attempt + random.uniform(0, 2)
                    print(f"[{self.__class__.__name__}] 네트워크 오류 (시도 {attempt}/{max_retries}), {backoff:.1f}초 후 재시도")
                    await asyncio.sleep(backoff)
                elif any(k in error_msg for k in ["403", "429", "503", "blocked", "captcha"]):
                    print(f"[{self.__class__.__name__}] 차단 감지 (시도 {attempt}/{max_retries})")
                    await self._block_delay()
                    await self._new_context()
                    await self._refresh_session()
                else:
                    print(f"[{self.__class__.__name__}] 오류 (시도 {attempt}/{max_retries}): {e}")
                    await asyncio.sleep(BACKOFF_BASE ** attempt)
                last_error = e
        print(f"[{self.__class__.__name__}] 최대 재시도 초과: {last_error}")
        return None

    async def _goto_safe(self, url: str, **kwargs) -> bool:
        async def _goto():
            response = await self.page.goto(url, wait_until="domcontentloaded", timeout=30000, **kwargs)
            if response and response.status in BLOCK_STATUS_CODES:
                raise BlockedError(f"HTTP {response.status}")
            return response
        result = await self._fetch_with_retry(_goto)
        return result is not None

    @abstractmethod
    async def _refresh_session(self):
        pass

    @abstractmethod
    async def fetch_job_list(self, user_profile: dict, page: int = 1) -> list[dict]:
        pass

    async def collect_all_pages(self, user_profile: dict, max_pages: int = 5) -> list[dict]:
        all_jobs = []
        for page_num in range(1, max_pages + 1):
            jobs = await self.fetch_job_list(user_profile, page=page_num)
            if not jobs:
                break
            all_jobs.extend(jobs)
            print(f"[{self.__class__.__name__}] 페이지 {page_num} 완료: {len(jobs)}개 (누적 {len(all_jobs)}개)")
            if len(jobs) < 10:
                break
            await self._delay()
        return all_jobs