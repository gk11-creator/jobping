"""
박지훈님 한 명만 대상으로 매칭 파이프라인을 돌리는 디버그용 스크립트.

이 프로필의 특이점:
- industries가 5개("IT", "게임", "헬스케어", "제조", "바이오")나 있음
  -> get_search_keyword는 industries[0]("IT")만 사용하므로, 검색어가
     "IT 마케팅", "IT 품질관리" 등으로 나갈 것으로 예상됨. 나머지 4개
     산업은 검색어에 반영 안 되는데, 이게 실사용에 문제가 되는지 확인 필요.
- employment_type이 다른 사람들과 다르게 이미 "신입"으로 직접 들어있고,
  work_type은 "상관없음" -- work_type이 구체적 값이 아닌 경우
  profile_analyzer가 employment_type을 "신입"으로 잘 유지하는지 확인.
- categories가 "마케팅/광고", "제조/QC/QA", "서비스/고객지원" 등 여러 개일
  가능성이 높음 (원본 스킬: 마케팅, QC, QA) -- 다중 카테고리 라운드로빈이
  잘 동작하는지 확인.
- extra: "축구관련 업무도 부탁드립니다" -- 특이 요청사항이 매칭에 어떻게
  반영되는지(또는 무시되는지) 참고용.
"""
import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from pipeline.profile_analyzer import run_pipeline

PARKJIHOON = {
    "email": "anwndkdl33@naver.com",
    "name": "박지훈",
    "profile_url": None,
    "comment_text": "구글 설문 응답",
    "collected_at": "2026-06-30T00:00:00",
    "profile": {
        "name": "박지훈",
        "headline": "마케팅, QC, QA 신입",
        "location": "전국",
        "summary": "마케팅, QC, QA 직무에 관심 있는 신입 구직자. 관심 산업: IT, 게임, 헬스케어, 제조, 바이오.",
        "education": [],
        "experiences": [],
        "skills": ["마케팅", "QC", "QA"],
        "languages": [],
        "certifications": [],
        "employment_type": "신입",
        "desired_location": "전국",
        "work_type": "상관없음",
        "industries": ["IT", "게임", "헬스케어", "제조", "바이오"],
        "extra": "축구관련 업무도 부탁드립니다",
    },
}


async def main():
    print("=" * 50)
    print("박지훈님 단독 테스트 시작")
    print("=" * 50)

    results = await run_pipeline([PARKJIHOON])

    output_path = "data/test_parkjihoon_result.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 50)
    print(f"완료 — 결과 저장: {output_path}")
    for r in results:
        profile = r.get("user_profile", {})
        print(f"{r.get('name')}: employment_type={profile.get('employment_type')}, "
              f"categories={profile.get('categories')}, "
              f"industries={profile.get('industries')}, "
              f"매칭 {len(r.get('matched_jobs', []))}개")
        for j in r.get("matched_jobs", [])[:10]:
            print(f"  - [{j.get('source')}] {j.get('title')} / {j.get('company')} "
                  f"(match_type={j.get('match_type')})")
    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())