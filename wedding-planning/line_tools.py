import os
import requests

def send_line_message_to_user(message: str, to_id: str = "") -> str:
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    target_id = to_id or os.environ.get("LINE_TO_ID")

    if not token:
        return "LINE token missing"
    if not target_id:
        return "LINE_TO_ID missing"

    url = "https://api.line.me/v2/bot/message/push"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    payload = {
        "to": target_id,
        "messages": [
            {"type": "text", "text": message}
        ]
    }

    r = requests.post(url, headers=headers, json=payload)

    if r.status_code != 200:
        return f"LINE error: {r.text}"

    return "LINE sent"

def send_line_message(message: str) -> str:
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")

    if not token:
        return "LINE token missing"

    # Changed endpoint to 'broadcast'
    url = "https://api.line.me/v2/bot/message/broadcast"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    payload = {
        "messages": [
            {
                "type": "text",
                "text": message
            }
        ]
    }

    r = requests.post(url, headers=headers, json=payload)

    if r.status_code != 200:
        return f"LINE error: {r.text}"

    return "Broadcast sent to all followers"