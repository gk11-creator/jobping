"""
메인 실행 파일
- python main.py          전체 파이프라인 실행
- python main.py crawl    LinkedIn 수집만
- python main.py match    공고 매칭만
- python main.py send     이메일 발송만
- python main.py preview  이메일 미리보기
"""
import asyncio
import json
import sys
import os
from datetime import datetime
from dotenv import load_dotenv
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
load_dotenv()

from pipeline.linkedin_crawler import LinkedInCrawler
from pipeline.profile_analyzer import run_pipeline
from pipeline.newsletter_sender import run as send_newsletter, preview as preview_newsletter

POST_URL = os.environ.get("LINKEDIN_POST_URL", "")
SUBSCRIBERS_FILE  = "data/subscribers.json"
FORM_SUBSCRIBERS_FILE = "data/form_subscribers.json"
RESULTS_FILE      = "data/matched_results.json"


def load_all_subscribers() -> list[dict]:
    """LinkedIn 구독자 + 설문 응답자 합치기"""
    subscribers = []

    # LinkedIn 구독자
    try:
        linkedin = json.load(open(SUBSCRIBERS_FILE, encoding="utf-8"))
        subscribers.extend(linkedin)
        print(f"LinkedIn 구독자: {len(linkedin)}명")
    except FileNotFoundError:
        print(f"{SUBSCRIBERS_FILE} 없음")

    # 설문 응답자
    try:
        form = json.load(open(FORM_SUBSCRIBERS_FILE, encoding="utf-8"))
        subscribers.extend(form)
        print(f"설문 응답자: {len(form)}명")
    except FileNotFoundError:
        print(f"{FORM_SUBSCRIBERS_FILE} 없음 — 설문 응답자 없이 진행")

    print(f"총 구독자: {len(subscribers)}명")
    return subscribers


async def step1_crawl() -> list[dict]:
    print("\n" + "="*50)
    print("1단계: LinkedIn 수집")
    print("="*50)

    crawler = LinkedInCrawler()
    await crawler.start(headless=False)
    try:
        await crawler.login()
        subscribers = await crawler.collect_subscribers(POST_URL)
    finally:
        await crawler.stop()

    os.makedirs("data", exist_ok=True)
    with open(SUBSCRIBERS_FILE, "w", encoding="utf-8") as f:
        json.dump(subscribers, f, ensure_ascii=False, indent=2)

    print(f"\n1단계 완료: {len(subscribers)}명 수집 → {SUBSCRIBERS_FILE}")
    return subscribers


async def step2_match(subscribers: list[dict]) -> list[dict]:
    print("\n" + "="*50)
    print("2단계: 프로필 분석 + 공고 매칭")
    print("="*50)

    results = await run_pipeline(subscribers)

    os.makedirs("data", exist_ok=True)
    with open(RESULTS_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n2단계 완료: {len(results)}명 매칭 → {RESULTS_FILE}")
    return results


async def step3_send():
    print("\n" + "="*50)
    print("3단계: 이메일 발송")
    print("="*50)
    await send_newsletter(RESULTS_FILE)
    print("\n3단계 완료")


async def main(mode: str = "all"):
    start = datetime.now()
    print(f"\n취준 뉴스레터 파이프라인 시작 [{mode}] — {start.strftime('%Y-%m-%d %H:%M')}")

    if mode == "all":
        subscribers = await step1_crawl()
        # 설문 응답자 합치기
        all_subscribers = load_all_subscribers()
        if not all_subscribers:
            print("수집된 구독자 없음 — 종료")
            return
        results = await step2_match(all_subscribers)
        if not results:
            print("매칭 결과 없음 — 종료")
            return
        await step3_send()

    elif mode == "crawl":
        await step1_crawl()

    elif mode == "match":
        all_subscribers = load_all_subscribers()
        if not all_subscribers:
            print("구독자 없음 — 먼저 crawl 실행")
            return
        await step2_match(all_subscribers)

    elif mode == "send":
        await step3_send()

    elif mode == "preview":
        await preview_newsletter(RESULTS_FILE)

    elapsed = (datetime.now() - start).seconds
    print(f"\n전체 소요 시간: {elapsed}초")


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    asyncio.run(main(mode))