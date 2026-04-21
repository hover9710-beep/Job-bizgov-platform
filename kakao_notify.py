import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()

def send_kakao_message(message):

    access_token = os.getenv("KAKAO_ACCESS_TOKEN")

    if not access_token:
        raise Exception("KAKAO_ACCESS_TOKEN 없음")

    url = "https://kapi.kakao.com/v2/api/talk/memo/default/send"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/x-www-form-urlencoded"
    }

    template = {
        "object_type": "text",
        "text": message,
        "link": {
            "web_url": "https://example.com"
        }
    }

    data = {
        "template_object": json.dumps(template, ensure_ascii=False)
    }

    print("[KAKAO] 요청 시작")

    response = requests.post(url, headers=headers, data=data)

    print("[KAKAO] status_code =", response.status_code)
    print("[KAKAO] response_text =", response.text)

    if response.status_code != 200:
        raise Exception("카카오 전송 실패")

    print("[KAKAO] 전송 성공")


if __name__ == "__main__":
    send_kakao_message("카카오 테스트 메시지")


def send_kakao_memo(text: str, web_url: str = "", mobile_web_url: str = "") -> None:
    send_kakao_message(text)


def build_recommend_kakao_text(company_name: str, company_id: str, items: list) -> str:
    lines = [f"[맞춤 추천] {company_name} 기준 상위 {len(items)}건"]
    for i, item in enumerate(items[:5], 1):
        title = item.get("title") or item.get("공고제목") or ""
        lines.append(f"{i}. {title[:30]}")
    return "\n".join(lines)