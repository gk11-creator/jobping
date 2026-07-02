"""
프로필 분석기 — LinkedIn 프로필 → user_profile 변환 + 공고 매칭
"""
import asyncio
import json
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from openai import AsyncOpenAI
from datetime import datetime

client = AsyncOpenAI()


async def analyze_profile(subscriber: dict) -> dict:
    profile = subscriber.get("profile", {})
    if not profile:
        return _default_profile(subscriber)

    prompt = f"""
다음은 LinkedIn 사용자 프로필입니다. 이 사람에게 맞는 채용 공고를 찾기 위한 검색 조건을 JSON으로 만들어주세요.

[프로필 정보]
이름: {profile.get('name', '')}
헤드라인: {profile.get('headline', '')}
위치: {profile.get('location', '')}
소개: {profile.get('summary', '')}
학력: {json.dumps(profile.get('education', []), ensure_ascii=False)}
경력: {json.dumps(profile.get('experiences', []), ensure_ascii=False)}
스킬: {json.dumps(profile.get('skills', []), ensure_ascii=False)}

[출력 형식 - 반드시 아래 JSON만 출력]
{{
  "categories": ["IT개발 > 서버/백엔드"],
  "employment_type": "인턴",
  "location": "서울",
  "skills": ["Python", "Django"],
  "career_level": "신입",
  "preferred_company_size": "스타트업",
  "min_grade": 3.5,
  "graduation_year": "2027",
  "summary": "이 사람을 한 줄로 요약"
}}

[category 선택지 - categories 배열에 1~3개 선택]
IT개발 > 서버/백엔드, IT개발 > 프론트엔드, IT개발 > 풀스택,
IT개발 > AI/ML, IT개발 > 데이터분석, IT개발 > DevOps,
IT개발 > iOS, IT개발 > Android, IT개발 > QA, IT개발 > 보안,
IT기획/PM, 기획/전략, 마케팅/광고, 디자인, 영업/영업관리,
제조/QC/QA, 금융/회계, 인사/HR, 법무/컴플라이언스,
디자인 > 제품/가구디자인, 디자인 > 그래픽, 디자인 > UI/UX,
무역/유통, 서비스/고객지원, 물류/구매, 경영지원/총무

[규칙]
- 학생이면 employment_type은 "인턴"
- 스킬/경력/소개 기반으로 categories 추론 (최대 3개)
- 여러 직군을 원하는 경우 모두 포함 (예: 법무+경영+HR → 3개)
- 하나의 직군만 원하면 1개만 포함
- 위치 정보 없으면 "서울" 기본값
- min_grade는 3.0~5.0 사이
- graduation_year는 숫자 문자열 또는 null
"""
    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=500,
        )
        raw = response.choices[0].message.content.strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        user_profile = json.loads(raw)
        user_profile["email"] = subscriber.get("email", "")
        user_profile["name"] = subscriber.get("name", "")

        # categories → category 호환성 유지
        categories = user_profile.get("categories", [])
        if categories:
            user_profile["category"] = categories[0]
        
        print(f"[프로필분석] {user_profile.get('name')} → {categories} / {user_profile.get('location')}")
        return user_profile
    except Exception as e:
        print(f"[프로필분석] GPT 오류: {e}")
        return _default_profile(subscriber)


def _default_profile(subscriber: dict) -> dict:
    profile = subscriber.get("profile", {}) or {}
    headline = profile.get("headline", "기타")
    return {
        "email": subscriber.get("email", ""),
        "name": subscriber.get("name", ""),
        "categories": [headline],
        "category": headline,
        "employment_type": profile.get("employment_type", "인턴"),
        "location": profile.get("desired_location") or profile.get("location", "서울"),
        "skills": profile.get("skills", []),
        "career_level": profile.get("employment_type", "신입"),
        "preferred_company_size": "전체",
        "min_grade": 3.0,
        "graduation_year": None,
        "summary": profile.get("summary", ""),
    }


async def score_jobs(user_profile: dict, jobs: list[dict], top_n: int = 10) -> list[dict]:
    if not jobs:
        return []

    jobs_summary = []
    for i, job in enumerate(jobs[:60]):
        jobs_summary.append({
            "idx": i,
            "title": job.get("title", ""),
            "company": job.get("company", ""),
            "category": job.get("category", ""),
            "employment_type": job.get("employment_type", ""),
            "location": job.get("location", ""),
            "deadline": job.get("deadline", ""),
            "rating": job.get("rating", ""),
            "source": job.get("source", ""),
        })

    categories = user_profile.get("categories", [user_profile.get("category", "")])
    categories_str = ", ".join(categories)

    prompt = f"""
다음은 구직자 프로필과 채용 공고 목록입니다.
구직자에게 가장 적합한 공고 {top_n}개를 선택하고 점수를 매겨주세요.

[구직자 프로필]
이름: {user_profile.get('name')}
희망직군: {categories_str}
고용형태: {user_profile.get('employment_type')}
희망지역: {user_profile.get('location')}
스킬: {', '.join(user_profile.get('skills', []))}
경력수준: {user_profile.get('career_level')}
한줄요약: {user_profile.get('summary')}

[공고 목록]
{json.dumps(jobs_summary, ensure_ascii=False, indent=2)}

[출력 형식 - 반드시 아래 JSON만 출력]
[
  {{"idx": 0, "score": 95, "reason": "추천 이유"}},
  ...
]

[채점 기준]
- 직군 일치 (희망직군 중 하나라도 일치하면 만점): 40점
- 고용형태 일치: 20점
- 지역 일치: 15점
- 기업 평점 높을수록: 10점
- 마감 여유 D-7 이상: 10점 (마감일 정보 없는 경우 5점 기본 부여)
- 기업 규모 선호 일치: 5점

[절대 제외 조건 - 아무리 점수가 높아도 선택 금지]
- 공고 제목에 "파트", "홀서빙", "세척", "주방", "시급", "알바", "아르바이트" 포함된 경우
- 공고 제목에 "주방", "조리", "기능직" 포함된 경우
- 학원, 과외, 교육생 모집, 수강생 모집 공고
- 희망직군({categories_str})과 전혀 무관한 직군
- "영커리언스", "청년인턴", "산업은행", "기업은행" 관련 공고
위 조건에 해당하면 반드시 제외하고 다른 공고를 선택할 것.

[추천 이유 작성 규칙]
- 반드시 이 사람의 스킬, 전공, 경험을 구체적으로 언급할 것
- 예시: "Python/FastAPI 스킬이 백엔드 포지션과 일치하며, IU 인포매틱스 전공 배경이 데이터 분석 업무에 적합"
- 절대 "직군, 고용형태, 지역 일치" 같은 일반적인 문구 사용 금지
- 공고 제목의 특정 기술/역할과 지원자 프로필을 연결해서 설명할 것
- 2문장 이내로 작성

상위 {top_n}개만 반환, score 내림차순 정렬.
"""
    try:
        response = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=1000,
        )
        raw = response.choices[0].message.content.strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        scored = json.loads(raw)

        result = []
        for s in scored:
            idx = s.get("idx")
            if idx is not None and idx < len(jobs):
                job = jobs[idx].copy()
                job["match_score"] = s.get("score", 0)
                job["match_reason"] = s.get("reason", "")
                result.append(job)

        result.sort(key=lambda x: x.get("match_score", 0), reverse=True)
        print(f"[매칭] {user_profile.get('name')} — 상위 {len(result)}개 공고 선정")
        return result
    except Exception as e:
        print(f"[매칭] GPT 스코어링 오류: {e}")
        return jobs[:top_n]


async def run_pipeline(subscribers: list[dict]) -> list[dict]:
    from pipeline.orchestrator import Orchestrator
    from datetime import date

    results = []
    for subscriber in subscribers:
        print(f"\n{'='*50}")
        print(f"처리 중: {subscriber.get('name')} ({subscriber.get('email')})")

        user_profile = await analyze_profile(subscriber)
        categories = user_profile.get("categories", [user_profile.get("category", "")])

        all_jobs = []
        seen_urls = set()

        for category in categories:
            profile_for_category = {**user_profile, "category": category}
            orchestrator = Orchestrator(headless=True)
            jobs = await orchestrator.run(profile_for_category, max_pages=2)

            # 카테고리별 중복 제거
            for job in jobs:
                url = job.get("source_url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    all_jobs.append(job)

        # 마감 지난 공고 제거
        today = date.today()
        all_jobs = [
            j for j in all_jobs
            if not j.get("deadline") or
            datetime.strptime(j["deadline"], "%Y-%m-%d").date() >= today
        ]

        matched_jobs = await score_jobs(user_profile, all_jobs, top_n=10)

        results.append({
            "email": subscriber.get("email"),
            "name": subscriber.get("name"),
            "user_profile": user_profile,
            "matched_jobs": matched_jobs,
        })
        print(f"완료: {len(matched_jobs)}개 공고 매칭")

    return results