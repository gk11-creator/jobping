"""
뉴스레터 발송기 v2
"""
import asyncio
import json
import os
from datetime import datetime
from openai import AsyncOpenAI
import resend
from dotenv import load_dotenv
load_dotenv()
import urllib3
urllib3.disable_warnings()

client = AsyncOpenAI()
resend.api_key = os.environ.get("RESEND_API_KEY")
SENDER = os.environ.get("RESEND_SENDER", "onboarding@resend.dev")
SAVE_API_URL = os.environ.get("SAVE_API_URL", "https://jobping-xuwa.onrender.com")

async def generate_email(result: dict) -> dict:
    name = result.get("name", "")
    user_profile = result.get("user_profile", {})
    matched_jobs = result.get("matched_jobs", [])

    if not matched_jobs:
        return None

    return _fallback_template(name, matched_jobs, user_profile)


def _job_card(job: dict, index: int, hidden: bool = False, save_url: str = "", name: str = "") -> str:
    deadline = job.get("deadline") or "상시채용"
    source = job.get("source", "")
    source_url = job.get("source_url", "#")
    title = job.get("title", "")
    company = job.get("company", "")
    location = job.get("location", "")
    job_id = f"job_{index}"

    # 출처 사이트 색상
    source_colors = {
        "잡코리아": "#e8f0fe;color:#1a73e8",
        "링커리어": "#e6f4ea;color:#188038",
        "사람인": "#fce8e6;color:#d93025",
        "인크루트": "#fff3e0;color:#e65100",
        "슈퍼루키": "#f3e8fd;color:#7b1fa2",
        "잡플래닛": "#e8f5e9;color:#2e7d32",
        "피플앤잡": "#e3f2fd;color:#1565c0",
    }
    source_style = source_colors.get(source, "#f1f3f4;color:#5f6368")

    # D-day 계산
    dday_text = ""
    if job.get("deadline"):
        try:
            from datetime import date
            from datetime import datetime as dt
            deadline_date = dt.strptime(job["deadline"], "%Y-%m-%d").date()
            days_left = (deadline_date - date.today()).days
            if days_left < 0:
                dday_text = '<span style="color:#fff;font-size:11px;font-weight:700;background:#ef4444;padding:2px 8px;border-radius:10px;margin-left:6px;">마감</span>'
            elif days_left == 0:
                dday_text = '<span style="color:#fff;font-size:11px;font-weight:700;background:#ef4444;padding:2px 8px;border-radius:10px;margin-left:6px;">D-day</span>'
            elif days_left <= 3:
                dday_text = f'<span style="color:#fff;font-size:11px;font-weight:700;background:#ef4444;padding:2px 8px;border-radius:10px;margin-left:6px;">D-{days_left}</span>'
            elif days_left <= 7:
                dday_text = f'<span style="color:#fff;font-size:11px;font-weight:700;background:#f97316;padding:2px 8px;border-radius:10px;margin-left:6px;">D-{days_left}</span>'
        except:
            pass

    display_style = 'display:none;' if hidden else ''

    import urllib.parse
    save_link = f"{save_url}/save?user={urllib.parse.quote(name)}&title={urllib.parse.quote(title)}&company={urllib.parse.quote(company)}&url={urllib.parse.quote(source_url)}&deadline={deadline}"

    return f"""
    <div id="{job_id}" style="{display_style}border:1px solid #e5e7eb;border-radius:10px;padding:18px;margin:10px 0;background:#fff;">

      <!-- 출처 뱃지 -->
      <div style="margin-bottom:8px;">
        <span style="font-size:11px;font-weight:600;padding:3px 8px;border-radius:10px;background:{source_style};">
          {source}
        </span>
      </div>

      <!-- 제목 + D-day -->
      <div style="margin-bottom:6px;">
        <a href="{source_url}" style="font-size:15px;font-weight:700;color:#111;text-decoration:none;line-height:1.4;display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
          {title}
        </a>
        {dday_text}
      </div>

      <!-- 회사 · 지역 · 마감 -->
      <div style="color:#6b7280;font-size:13px;margin-bottom:14px;">
        <span style="font-weight:600;color:#374151;">{company}</span>
        &nbsp;·&nbsp;{location}
        &nbsp;·&nbsp;마감 {deadline}
      </div>

      <!-- 버튼 -->
      <table width="100%" cellpadding="0" cellspacing="0" style="border-collapse:collapse;">
        <tr>
          <td width="48%" style="padding-right:4px;">
            <a href="{source_url}"
               style="display:block;text-align:center;padding:10px 0;
                      background:#2563eb;color:#fff;border-radius:8px;
                      font-size:13px;font-weight:600;text-decoration:none;">
              🔗 바로가기
            </a>
          </td>
          <td width="4%"></td>
          <td width="48%" style="padding-left:4px;">
            <a href="{save_link}"
               style="display:block;text-align:center;padding:10px 0;
                      background:#fff;color:#2563eb;border-radius:8px;
                      font-size:13px;font-weight:600;text-decoration:none;
                      border:1.5px solid #2563eb;">
              🔖 저장하기
            </a>
          </td>
        </tr>
      </table>

    </div>
    """

def _fallback_template(name: str, jobs: list, user_profile: dict) -> dict:
    # 마감 지난 공고 제거
    from datetime import date, datetime
    today = date.today()
    jobs = [
        j for j in jobs
        if not j.get("deadline") or
        datetime.strptime(j["deadline"], "%Y-%m-%d").date() >= today
    ]

    all_jobs = jobs[:8]

    visible_cards = "".join(_job_card(job, i, hidden=False, save_url=SAVE_API_URL, name=name) for i, job in enumerate(all_jobs))
    hidden_cards = ""
    more_button = ""

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;margin:0;padding:0;background:#f4f4f4;">
  <div style="max-width:600px;margin:0 auto;background:#fff;">

    <!-- 헤더 -->
    <div style="background:#2563eb;padding:32px 24px;text-align:center;">
      <h1 style="color:#fff;font-size:22px;font-weight:700;margin:0;">안녕하세요, {name}님!</h1>
      <p style="color:#bfdbfe;font-size:14px;margin:10px 0 0;">
        {user_profile.get('category')} · {user_profile.get('location')} 기준으로 맞춤 공고를 준비했습니다
      </p>
    </div>

    <!-- 공고 목록 -->
    <div style="padding:24px;">
      <h2 style="font-size:16px;font-weight:700;color:#111;margin:0 0 4px;">추천 채용 공고</h2>
      <p style="font-size:13px;color:#6b7280;margin:0 0 16px;">총 {len(all_jobs)}개 맞춤 공고</p>

      {visible_cards}
    </div>

    <!-- 저장된 공고 보기 -->
    <div style="padding:0 24px 24px;">
      <a href="{SAVE_API_URL}/saved?user={name}"
         style="display:block;text-align:center;padding:12px;
                background:#f9fafb;color:#374151;border:1px solid #e5e7eb;
                border-radius:8px;font-size:14px;font-weight:600;text-decoration:none;">
        📋 저장된 공고 보기
      </a>
    </div>

    <!-- 푸터 -->
    <div style="padding:20px 24px;border-top:1px solid #e5e7eb;text-align:center;">
      <p style="color:#9ca3af;font-size:12px;margin:0;">좋은 소식이 있기를 바랍니다! 화이팅! 🎉</p>
      <p style="color:#d1d5db;font-size:11px;margin:8px 0 0;">구독 취소를 원하시면 회신해주세요.</p>
    </div>

  </div>
</body></html>"""

    return {
        "subject": f"[취준 뉴스레터] {name}님 맞춤 공고 {len(all_jobs)}개",
        "html": html,
        "preview_text": f"{user_profile.get('category')} 공고 {len(all_jobs)}개가 도착했어요",
    }

def send_email(to_email: str, subject: str, html: str) -> bool:
    try:
        import requests
        response = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {resend.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "from": SENDER,
                "to": [to_email],
                "subject": subject,
                "html": html,
            },
            verify=False
        )
        result = response.json()
        if response.status_code == 200 or response.status_code == 201:
            print(f"[발송] {to_email} → 성공 (id: {result.get('id')})")
            return True
        else:
            print(f"[발송] {to_email} → 실패: {result}")
            return False
    except Exception as e:
        print(f"[발송] {to_email} → 실패: {e}")
        return False


async def run(matched_results_path: str = "data/matched_results.json"):
    try:
        results = json.load(open(matched_results_path, encoding="utf-8"))
    except FileNotFoundError:
        print(f"[발송기] {matched_results_path} 없음")
        return

    print(f"[발송기] {len(results)}명에게 뉴스레터 발송 시작")
    sent, failed = 0, 0

    for result in results:
        email = result.get("email")
        name = result.get("name", "")
        if not email or not result.get("matched_jobs"):
            continue

        print(f"\n[발송기] 처리 중: {name} ({email})")
        email_data = await generate_email(result)
        if not email_data:
            failed += 1
            continue

        success = send_email(
            to_email=email,
            subject=email_data["subject"],
            html=email_data["html"],
        )
        if success:
            sent += 1
        else:
            failed += 1
        await asyncio.sleep(1)

    print(f"\n[발송기] 완료 — 성공: {sent}명 / 실패: {failed}명")
    log = {"sent_at": datetime.now().isoformat(), "total": len(results), "sent": sent, "failed": failed}
    with open("data/send_log.json", "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


async def preview(matched_results_path: str = "data/matched_results.json"):
    try:
        results = json.load(open(matched_results_path, encoding="utf-8"))
    except FileNotFoundError:
        results = [{
            "email": "test@example.com",
            "name": "테스트",
            "user_profile": {
                "category": "IT개발 > 서버/백엔드",
                "employment_type": "인턴",
                "location": "서울",
                "skills": ["Python", "React", "FastAPI"],
                "summary": "풀스택 개발에 관심 있는 IU 재학생"
            },
            "matched_jobs": [
                {
                    "title": "백엔드 개발 인턴",
                    "company": "카카오",
                    "location": "서울",
                    "deadline": "2026-06-15",
                    "source": "잡플래닛",
                    "source_url": "https://jobplanet.co.kr",
                    "rating": 4.2,
                    "match_score": 92,
                    "match_reason": "Python/FastAPI 스킬이 백엔드 포지션과 직접 일치하며, IU 인포매틱스 전공이 서비스 개발 업무에 적합"
                },
                {
                    "title": "프론트엔드 개발 인턴",
                    "company": "네이버",
                    "location": "서울",
                    "deadline": "2026-06-20",
                    "source": "링커리어",
                    "source_url": "https://linkareer.com",
                    "rating": 4.5,
                    "match_score": 88,
                    "match_reason": "React 경험이 프론트엔드 포지션과 일치"
                },
                {
                    "title": "데이터 분석 인턴",
                    "company": "카카오페이",
                    "location": "서울",
                    "deadline": "2026-06-25",
                    "source": "사람인",
                    "source_url": "https://saramin.co.kr",
                    "rating": None,
                    "match_score": 85,
                    "match_reason": "데이터 분석 경험이 포지션과 일치"
                },
                {
                    "title": "AI 엔지니어 인턴",
                    "company": "뤼튼",
                    "location": "서울",
                    "deadline": "2026-07-01",
                    "source": "잡코리아",
                    "source_url": "https://jobkorea.co.kr",
                    "rating": None,
                    "match_score": 82,
                    "match_reason": "AI 관심사와 포지션 일치"
                },
                {
                    "title": "풀스택 개발 인턴",
                    "company": "토스",
                    "location": "서울",
                    "deadline": "2026-07-05",
                    "source": "링커리어",
                    "source_url": "https://linkareer.com",
                    "rating": 4.8,
                    "match_score": 80,
                    "match_reason": "풀스택 경험과 포지션 일치"
                },
                {
                    "title": "DevOps 인턴",
                    "company": "쿠팡",
                    "location": "서울",
                    "deadline": "2026-07-10",
                    "source": "잡코리아",
                    "source_url": "https://jobkorea.co.kr",
                    "rating": None,
                    "match_score": 78,
                    "match_reason": "인프라 관심사와 포지션 일치"
                },
            ]
        }]

    for result in results[:1]:
        email_data = await generate_email(result)
        if email_data:
            with open("data/email_preview.html", "w", encoding="utf-8") as f:
                f.write(email_data["html"])
            print(f"제목: {email_data['subject']}")
            print("data/email_preview.html 저장 완료 — 브라우저로 열어서 확인하세요")