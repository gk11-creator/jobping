"""
테스트용: data/matched_results.json 에서 특정 이메일 1명만 골라서 뉴스레터 재발송.
크롤링/매칭 재실행 없이 기존 데이터로 "발송" 단계만 테스트할 때 사용.
(예: /track 리다이렉트 헤더 수정 후 재검증용)

프로젝트 루트에서 실행:
    python scripts/send_single_test.py tonova.seoul@gmail.com
"""
import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.newsletter_sender import generate_email, send_email


async def main():
    if len(sys.argv) < 2:
        print("사용법: python scripts/send_single_test.py <이메일>")
        return

    target_email = sys.argv[1]

    results_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "matched_results.json",
    )

    with open(results_path, encoding="utf-8") as f:
        results = json.load(f)

    target = next((r for r in results if r.get("email") == target_email), None)
    if not target:
        print(f"[테스트발송] {target_email} 을(를) matched_results.json에서 찾을 수 없음")
        return

    if not target.get("matched_jobs"):
        print(f"[테스트발송] {target_email} 은(는) matched_jobs가 비어있음")
        return

    print(f"[테스트발송] {target.get('name')} ({target_email}) 에게만 발송")

    email_data = await generate_email(target)
    if not email_data:
        print("[테스트발송] 이메일 생성 실패")
        return

    success = send_email(
        to_email=target_email,
        subject=email_data["subject"],
        html=email_data["html"],
    )
    print("[테스트발송] 성공" if success else "[테스트발송] 실패")


if __name__ == "__main__":
    asyncio.run(main())