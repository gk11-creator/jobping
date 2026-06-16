"""
LinkedIn 크롤러 — 전체 텍스트 추출 + GPT 파싱
"""
import asyncio
import json
import re
import os
from datetime import datetime
from typing import Optional
from playwright.async_api import async_playwright, Page, BrowserContext
from openai import AsyncOpenAI

try:
    from playwright_stealth import stealth_async
    STEALTH_AVAILABLE = True
except ImportError:
    STEALTH_AVAILABLE = False

client = AsyncOpenAI()
COOKIES_FILE = "linkedin_cookies.json"
BASE_URL = "https://www.linkedin.com"
EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")


class LinkedInCrawler:
    def __init__(self):
        self.browser = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self._playwright = None

    async def start(self, headless: bool = False):
        self._playwright = await async_playwright().start()
        self.browser = await self._playwright.chromium.launch(
            headless=headless,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]
        )
        self.context = await self.browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
            locale="ko-KR",
        )
        self.page = await self.context.new_page()
        if STEALTH_AVAILABLE:
            await stealth_async(self.page)

    async def stop(self):
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def login(self):
        if os.path.exists(COOKIES_FILE):
            print("[LinkedIn] 저장된 쿠키로 로그인 시도...")
            cookies = json.load(open(COOKIES_FILE, encoding="utf-8"))
            await self.context.add_cookies(cookies)
            await self.page.goto(f"{BASE_URL}/feed/", wait_until="domcontentloaded")
            await asyncio.sleep(2)
            if "feed" in self.page.url:
                print("[LinkedIn] 자동 로그인 성공")
                return
            print("[LinkedIn] 쿠키 만료 — 수동 로그인 필요")
        await self._manual_login()

    async def _manual_login(self):
        print("[LinkedIn] 브라우저에서 직접 로그인해주세요...")
        await self.page.goto(f"{BASE_URL}/login", wait_until="domcontentloaded")
        print("[LinkedIn] 로그인 완료 후 Enter를 눌러주세요...")
        # 피드 페이지 대기 대신 수동으로 진행
        while True:
            await asyncio.sleep(3)
            if "feed" in self.page.url or "mynetwork" in self.page.url:
                break
            print(f"[LinkedIn] 현재 URL: {self.page.url}")
        await asyncio.sleep(2)
        cookies = await self.context.cookies()
        with open(COOKIES_FILE, "w", encoding="utf-8") as f:
            json.dump(cookies, f, ensure_ascii=False, indent=2)
        print("[LinkedIn] 쿠키 저장 완료")

    async def _extract_page_text(self) -> str:
        text = await self.page.evaluate("""
            () => {
                const main = document.querySelector('main') ||
                              document.querySelector('.scaffold-layout__main') ||
                              document.body;
                const clone = main.cloneNode(true);
                clone.querySelectorAll('script, style, nav, header, footer, [aria-hidden="true"]')
                     .forEach(el => el.remove());
                return clone.innerText
                    .split('\\n')
                    .map(l => l.trim())
                    .filter(l => l.length > 0)
                    .join('\\n');
            }
        """)
        return text

    async def _scroll_and_expand(self):
        for _ in range(10):
            await self.page.keyboard.press("End")
            await asyncio.sleep(0.8)
        await self.page.keyboard.press("Home")
        await asyncio.sleep(1)
        for _ in range(10):
            try:
                btn = await self.page.query_selector(
                    "button.inline-show-more-text__button, "
                    "button[aria-label*='더 보기'], "
                    "button[aria-label*='Show more']"
                )
                if btn:
                    await btn.click()
                    await asyncio.sleep(0.5)
                else:
                    break
            except Exception:
                break

    async def _gpt_parse_profile(self, raw_text: str, profile_url: str) -> dict:
        text = raw_text[:3000]
        prompt = f"""
다음은 LinkedIn 프로필 페이지의 전체 텍스트입니다.
이 텍스트에서 아래 JSON 형식으로 정보를 추출해주세요.
없는 정보는 null 또는 빈 배열로 처리하세요.
반드시 JSON만 출력하고 다른 텍스트는 없애주세요.

[LinkedIn 프로필 텍스트]
{text}

[출력 형식]
{{
  "name": "이름",
  "headline": "헤드라인",
  "location": "위치",
  "summary": "자기소개 요약",
  "education": [{{"school": "학교명", "degree": "전공/학위", "date_range": "기간"}}],
  "experiences": [{{"title": "직함", "company": "회사명", "date_range": "기간", "description": "설명"}}],
  "skills": ["스킬1", "스킬2"],
  "languages": ["언어1", "언어2"],
  "certifications": ["자격증1"]
}}
"""
        try:
            response = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=800,
            )
            raw = response.choices[0].message.content.strip()
            raw = raw.replace("```json", "").replace("```", "").strip()
            profile = json.loads(raw)
            profile["profile_url"] = profile_url
            return profile
        except Exception as e:
            print(f"[LinkedIn] GPT 파싱 오류: {e}")
            return {"name": "", "headline": "", "profile_url": profile_url,
                    "education": [], "experiences": [], "skills": []}

    async def collect_comments(self, post_url: str) -> list[dict]:
        print("[LinkedIn] 포스트 접속 중...")
        await self.page.goto(post_url, wait_until="domcontentloaded")
        await asyncio.sleep(3)

        for _ in range(5):
            await self.page.keyboard.press("End")
            await asyncio.sleep(1)

        for i in range(20):
            try:
                btn = await self.page.query_selector(
                    "button.comments-comments-list__load-more-comments-button, "
                    "button[aria-label*='댓글'], "
                    "button.show-prev-results"
                )
                if btn:
                    await btn.click()
                    await asyncio.sleep(2)
                    print(f"[LinkedIn] 댓글 더 보기 클릭 ({i+1}회)")
                else:
                    break
            except Exception:
                break

        page_text = await self._extract_page_text()

        # 디버깅용 HTML 저장
        html = await self.page.content()
        with open("data/debug_page.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("[LinkedIn] 페이지 HTML 저장 완료 → data/debug_page.html")

        emails = list(set(EMAIL_PATTERN.findall(page_text)))
        print(f"[LinkedIn] 이메일 {len(emails)}개 발견: {emails}")
        comments = await self._map_emails_to_profiles(emails)

        if not comments and emails:
            print("[LinkedIn] DOM 파싱 실패 — 이메일만 저장")
            for email in emails:
                comments.append({
                    "email": email,
                    "name": "",
                    "profile_url": None,
                    "comment_text": "",
                    "collected_at": datetime.now().isoformat(),
                })

        return comments

    async def _map_emails_to_profiles(self, emails: list[str]) -> list[dict]:
        comments = []
        try:
            from bs4 import BeautifulSoup
            html = await self.page.content()
            soup = BeautifulSoup(html, "html.parser")

            for email in emails:
                mailto_tag = soup.find("a", href=f"mailto:{email}")
                if not mailto_tag:
                    continue

                # 상위로 올라가면서 /in/ 링크 찾기
                profile_url = None
                name = ""

                # 충분히 넓게 탐색
                parent = mailto_tag
                for _ in range(10):
                    parent = parent.find_parent()
                    if not parent:
                        break

                    # 프로필 링크 찾기
                    if not profile_url:
                        profile_link = parent.find("a", href=lambda h: h and "/in/" in h and "linkedin.com" in h)
                        if profile_link:
                            href = profile_link.get("href", "")
                            profile_url = href.split("?")[0]
                            if not profile_url.startswith("http"):
                                profile_url = f"{BASE_URL}{profile_url}"

                    # 이름 찾기 - aria-label에서 추출
                    if not name and profile_url:
                        profile_fig = parent.find("figure", attrs={"aria-hidden": None})
                        if not profile_fig:
                            # aria-label에서 이름 추출
                            for tag in parent.find_all(attrs={"aria-label": True}):
                                label = tag.get("aria-label", "")
                                if "님의 프로필" in label:
                                    name = label.replace("님의 프로필 보기", "").replace(",", "").strip()
                                    name = name.split("구직중")[0].strip()
                                    break

                    if profile_url and name:
                        break

                comments.append({
                    "email": email,
                    "name": name,
                    "profile_url": profile_url,
                    "comment_text": email,
                    "collected_at": datetime.now().isoformat(),
                })
                print(f"[LinkedIn] 매핑: {email} → {name} ({profile_url})")

        except Exception as e:
            print(f"[LinkedIn] 매핑 오류: {e}")

        return comments
    
    async def crawl_profile(self, profile_url: str) -> dict:
        print(f"[LinkedIn] 프로필 크롤링: {profile_url}")
        await self.page.goto(profile_url, wait_until="domcontentloaded")
        await asyncio.sleep(3)
        await self._scroll_and_expand()
        raw_text = await self._extract_page_text()
        print(f"[LinkedIn] 텍스트 추출 완료 ({len(raw_text)}자)")
        profile = await self._gpt_parse_profile(raw_text, profile_url)
        print(f"[LinkedIn] 프로필 파싱 완료: {profile.get('name')}")
        await asyncio.sleep(5)
        return profile

    async def collect_subscribers(self, post_url: str) -> list[dict]:
        comments = await self.collect_comments(post_url)
        if not comments:
            print("[LinkedIn] 이메일 댓글 없음")
            return []

        print(f"\n[LinkedIn] 이메일 {len(comments)}개 수집 완료")
        subscribers = []
        for comment in comments:
            subscriber = {
                "email": comment["email"],
                "name": comment["name"],
                "profile_url": comment["profile_url"],
                "comment_text": comment["comment_text"],
                "collected_at": comment["collected_at"],
                "profile": None,
            }
            if comment.get("profile_url"):
                try:
                    profile = await self.crawl_profile(comment["profile_url"])
                    subscriber["profile"] = profile
                    if not subscriber["name"] and profile.get("name"):
                        subscriber["name"] = profile["name"]
                except Exception as e:
                    print(f"[LinkedIn] 프로필 실패 ({comment.get('name')}): {e}")
            subscribers.append(subscriber)
        return subscribers