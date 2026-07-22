"""
구재정님 한 명만 대상으로 매칭 파이프라인을 돌리는 디버그용 스크립트.
"""
import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from pipeline.profile_analyzer import run_pipeline

GUJEONGJEONG = {
    "email": "kookoojj0127@naver.com",
    "name": "구재정",
    "profile_url": None,
    "comment_text": "구글 설문 응답",
    "collected_at": "2026-06-30T00:00:00",
    "profile": {
        "name": "구재정",
        "headline": "가구디자인, 가구개발 1-3년차",
        "location": "서울, 경기",
        "summary": "가구디자인 및 가구개발 직무 경력 1-3년. 관심 산업: 가구.",
        "education": [],
        "experiences": [],
        "skills": ["가구디자인", "가구개발"],
        "languages": [],
        "certifications": [],
        "employment_type": "1-3년",
        "desired_location": "서울, 경기",
        "work_type": "정규직",
        "industries": ["가구"],
        "extra": "",
    },
}


async def main():
    print("=" * 50)
    print("구재정님 단독 테스트 시작")
    print("=" * 50)

    results = await run_pipeline([GUJEONGJEONG])

    output_path = "data/test_single_result.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 50)
    print(f"완료 — 결과 저장: {output_path}")
    for r in results:
        print(f"{r.get('name')}: 매칭 {len(r.get('matched_jobs', []))}개")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())