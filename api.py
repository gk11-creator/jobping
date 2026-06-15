"""
JobSearch API 서버
- /track     : 클릭 추적 + 리다이렉트
- /save      : 공고 저장
- /saved     : 저장된 공고 보기
- /stats     : 클릭 통계
"""
import json
import os
import urllib.parse
from datetime import datetime, date
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

CLICKS_FILE = "data/clicks.json"
SAVED_FILE  = "data/saved_jobs.json"


def _load(path: str) -> list:
    if os.path.exists(path):
        return json.load(open(path, encoding="utf-8"))
    return []


def _save(path: str, data: list):
    os.makedirs("data", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ─────────────────────────────────────────
# 클릭 추적 + 리다이렉트
# ─────────────────────────────────────────
@app.get("/track")
def track_click(
    user: str = Query(""),
    title: str = Query(""),
    company: str = Query(""),
    url: str = Query(""),
    deadline: str = Query(""),
):
    clicks = _load(CLICKS_FILE)
    clicks.append({
        "user": user,
        "title": urllib.parse.unquote(title),
        "company": urllib.parse.unquote(company),
        "url": urllib.parse.unquote(url),
        "deadline": deadline,
        "clicked_at": datetime.now().isoformat(),
    })
    _save(CLICKS_FILE, clicks)
    return RedirectResponse(url=urllib.parse.unquote(url))


# ─────────────────────────────────────────
# 공고 저장
# ─────────────────────────────────────────
@app.get("/save")
def save_job(
    user: str = Query(""),
    title: str = Query(""),
    company: str = Query(""),
    url: str = Query(""),
    deadline: str = Query(""),
):
    saved = _load(SAVED_FILE)

    # 중복 체크
    already = any(
        j.get("url") == urllib.parse.unquote(url) and j.get("user") == user
        for j in saved
    )

    if not already:
        saved.append({
            "user": user,
            "title": urllib.parse.unquote(title),
            "company": urllib.parse.unquote(company),
            "url": urllib.parse.unquote(url),
            "deadline": deadline,
            "saved_at": datetime.now().isoformat(),
        })
        _save(SAVED_FILE, saved)

    # 저장된 공고 페이지로 리다이렉트
    return RedirectResponse(url=f"/saved?user={user}")


# ─────────────────────────────────────────
# 저장된 공고 보기 (D-X 마감 임박 순)
# ─────────────────────────────────────────
@app.get("/saved", response_class=HTMLResponse)
def saved_jobs(user: str = Query("")):
    saved = _load(SAVED_FILE)
    user_jobs = [j for j in saved if j.get("user") == user] if user else saved

    # 마감 임박 순 정렬
    today = date.today()

    def sort_key(job):
        dl = job.get("deadline", "")
        if not dl or dl == "상시채용":
            return 9999
        try:
            return (datetime.strptime(dl, "%Y-%m-%d").date() - today).days
        except:
            return 9999

    user_jobs.sort(key=sort_key)

    # D-X 뱃지 생성
    def dday_badge(deadline: str) -> str:
        if not deadline or deadline == "상시채용":
            return '<span style="color:#6b7280;font-size:12px;">상시채용</span>'
        try:
            days = (datetime.strptime(deadline, "%Y-%m-%d").date() - today).days
            if days < 0:
                return '<span style="background:#fee2e2;color:#ef4444;padding:2px 8px;border-radius:4px;font-size:12px;font-weight:600;">마감</span>'
            elif days == 0:
                return '<span style="background:#fee2e2;color:#ef4444;padding:2px 8px;border-radius:4px;font-size:12px;font-weight:600;">D-day</span>'
            elif days <= 3:
                return f'<span style="background:#fee2e2;color:#ef4444;padding:2px 8px;border-radius:4px;font-size:12px;font-weight:600;">D-{days}</span>'
            elif days <= 7:
                return f'<span style="background:#ffedd5;color:#f97316;padding:2px 8px;border-radius:4px;font-size:12px;font-weight:600;">D-{days}</span>'
            else:
                return f'<span style="background:#f3f4f6;color:#6b7280;padding:2px 8px;border-radius:4px;font-size:12px;">D-{days}</span>'
        except:
            return f'<span style="color:#6b7280;font-size:12px;">{deadline}</span>'

    cards = ""
    for job in user_jobs:
        badge = dday_badge(job.get("deadline", ""))
        cards += f"""
        <div style="border:1px solid #e5e7eb;border-radius:10px;padding:18px;margin:10px 0;background:#fff;">
          <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;">
            <a href="{job.get('url','#')}"
               style="font-size:15px;font-weight:700;color:#1d4ed8;text-decoration:none;flex:1;">
              {job.get('title','')}
            </a>
            {badge}
          </div>
          <div style="color:#6b7280;font-size:13px;margin-top:6px;">
            {job.get('company','')}
          </div>
          <div style="color:#9ca3af;font-size:11px;margin-top:4px;">
            저장일: {job.get('saved_at','')[:10]}
          </div>
        </div>
        """

    if not user_jobs:
        cards = '<p style="color:#9ca3af;text-align:center;padding:40px 0;">저장된 공고가 없습니다</p>'

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>저장된 공고</title>
</head>
<body style="font-family:-apple-system,sans-serif;margin:0;padding:0;background:#f4f4f4;">
  <div style="max-width:600px;margin:0 auto;background:#fff;min-height:100vh;">

    <div style="background:#2563eb;padding:24px;text-align:center;">
      <h1 style="color:#fff;font-size:20px;font-weight:700;margin:0;">📋 저장된 공고</h1>
      <p style="color:#bfdbfe;font-size:13px;margin:6px 0 0;">
        {f"{user}님의 저장 목록 · {len(user_jobs)}개" if user else f"전체 {len(user_jobs)}개"}
      </p>
    </div>

    <div style="padding:20px;">
      {cards}
    </div>

  </div>
</body></html>"""

    return HTMLResponse(content=html)


# ─────────────────────────────────────────
# 클릭 통계
# ─────────────────────────────────────────
@app.get("/stats", response_class=HTMLResponse)
def stats():
    clicks = _load(CLICKS_FILE)
    saved = _load(SAVED_FILE)

    # 공고별 클릭 집계
    from collections import Counter
    click_counts = Counter(c.get("title", "") for c in clicks)
    top_clicks = click_counts.most_common(10)

    rows = "".join(
        f"<tr><td style='padding:8px;border-bottom:1px solid #e5e7eb;'>{title}</td>"
        f"<td style='padding:8px;border-bottom:1px solid #e5e7eb;text-align:center;font-weight:600;color:#2563eb;'>{count}</td></tr>"
        for title, count in top_clicks
    )

    html = f"""<!DOCTYPE html>
<html lang="ko">
<head><meta charset="UTF-8"><title>클릭 통계</title></head>
<body style="font-family:-apple-system,sans-serif;max-width:700px;margin:40px auto;padding:0 20px;">
  <h1 style="font-size:22px;font-weight:700;">📊 클릭 통계</h1>
  <p style="color:#6b7280;">총 클릭: <strong>{len(clicks)}</strong>회 · 저장된 공고: <strong>{len(saved)}</strong>개</p>
  <table style="width:100%;border-collapse:collapse;margin-top:20px;">
    <thead>
      <tr style="background:#f9fafb;">
        <th style="padding:10px;text-align:left;border-bottom:2px solid #e5e7eb;">공고명</th>
        <th style="padding:10px;text-align:center;border-bottom:2px solid #e5e7eb;">클릭수</th>
      </tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
</body></html>"""

    return HTMLResponse(content=html)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)