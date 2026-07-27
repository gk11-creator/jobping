"""
조현용님 한 명만 대상으로 매칭 파이프라인을 돌리는 디버그용 스크립트.

이 프로필은 이번 수정의 핵심 재현 케이스였음:
- employment_type: work_type("정규직")이 GPT 프롬프트에서 누락돼 "인턴"으로
  잘못 분류되던 문제 (profile_analyzer.py 수정으로 해결됨)
- category("영업/영업관리")가 각 사이트의 카테고리 코드와 "정확히" 일치해서
  버그 있는 duty API/categoryIDs 경로를 그대로 타던 문제 (검색 우선 방식으로
  전환하여 해결됨)
- industries(["IT", "스타트업"])가 검색어에 조합되는지 확인
"""
import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from pipeline.profile_analyzer import run_pipeline

JOHYUNYONG = {
    "email": "winneo77@gmail.com",
    "name": "조현용",
    "profile_url": None,
    "comment_text": "구글 설문 응답",
    "collected_at": "2026-07-14T00:00:00",
    "profile": {
        "name": "조현용",
        "headline": "영업, 사업개발, Product Manager 1-3년차",
        "location": "서울, 경기",
        "summary": "영업, 사업개발, Product Manager 직무 경력 1-3년. 관심 산업: IT, 스타트업.",
        "education": [],
        "experiences": [],
        "skills": ["영업", "사업개발", "Product Manager"],
        "languages": [],
        "certifications": [],
        "employment_type": "1-3년",
        "desired_location": "서울, 경기",
        "work_type": "정규직",
        "industries": ["IT", "스타트업"],
        "extra": "",
    },
}


async def main():
    print("=" * 50)
    print("조현용님 단독 테스트 시작")
    print("=" * 50)

    results = await run_pipeline([JOHYUNYONG])

    output_path = "data/test_johyunyong_result.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 50)
    print(f"완료 — 결과 저장: {output_path}")
    for r in results:
        profile = r.get("user_profile", {})
        print(f"{r.get('name')}: employment_type={profile.get('employment_type')}, "
              f"industries={profile.get('industries')}, "
              f"매칭 {len(r.get('matched_jobs', []))}개")
        for j in r.get("matched_jobs", [])[:10]:
            print(f"  - [{j.get('source')}] {j.get('title')} / {j.get('company')} "
                  f"(match_type={j.get('match_type')})")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())