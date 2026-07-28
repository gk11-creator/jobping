"""
사람인 어댑터만 단독으로, headless=False(실제 브라우저 창)로 실행해보는
테스트 스크립트. page.goto(BASE_URL) 타임아웃이 헤드리스 자동화 탐지
때문인지 확인하기 위한 용도.

프로젝트 루트에서 실행:
    python scripts/test_saramin_only.py
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adapters.saramin_adapter import SaraminAdapter

TEST_PROFILE = {
    "category": "디자인 > 제품/가구디자인",
    "location": "서울",
    "employment_type": "정규직",
}


async def main():
    print("=" * 50)
    print("사람인 단독 테스트 (headless=False — 실제 브라우저 창이 뜹니다)")
    print("=" * 50)

    adapter = SaraminAdapter()
    try:
        await adapter.start(headless=True)

        # navigator.webdriver 값 확인 — stealth가 실제로 먹혔는지 체크
        try:
            webdriver_flag = await adapter.page.evaluate("() => navigator.webdriver")
            print(f"[진단] navigator.webdriver = {webdriver_flag} "
                  f"({'자동화 탐지될 수 있음' if webdriver_flag else '정상 은닉됨'})")
        except Exception as e:
            print(f"[진단] navigator.webdriver 확인 실패: {e}")

        jobs = await adapter.collect_all_pages(TEST_PROFILE, max_pages=1)
        print(f"\n결과: {len(jobs)}개 파싱됨")
        for j in jobs[:5]:
            print(f"  - {j.get('title')} / {j.get('company')}")

        print("\n브라우저 창을 눈으로 확인해보세요:")
        print("  - 정상적으로 사람인 메인/검색 페이지가 보이나요?")
        print("  - 캡차, '비정상적인 접근입니다' 같은 차단 화면이 뜨나요?")
        print("  - 흰 화면으로 계속 멈춰있나요?")
        await asyncio.sleep(15)  # 눈으로 확인할 시간

    finally:
        await adapter.stop()


if __name__ == "__main__":
    asyncio.run(main())