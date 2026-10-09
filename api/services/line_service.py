# api/services/line_service.py
import os
import requests
import logging
from django.conf import settings

logger = logging.getLogger(__name__)

LINE_CHANNEL_ID = getattr(settings, 'LINE_CHANNEL_ID', os.getenv('LINE_CHANNEL_ID', ''))
LINE_CHANNEL_SECRET = getattr(settings, 'LINE_CHANNEL_SECRET', os.getenv('LINE_CHANNEL_SECRET', ''))
LINE_ACCESS_TOKEN = getattr(settings, 'LINE_ACCESS_TOKEN', os.getenv('LINE_ACCESS_TOKEN', ''))
LINE_CALLBACK_URL = getattr(settings, 'LINE_CALLBACK_URL', os.getenv('LINE_CALLBACK_URL', 'https://www.trustlabthailand.com/api/auth/line/callback'))


def get_line_user_profile(code: str, redirect_uri: str = None) -> dict:
    """
    Exchanges LINE OAuth code for access token and fetches user profile.
    Returns dict containing line_user_id, display_name, picture_url, status_message
    """
    if not redirect_uri:
        redirect_uri = LINE_CALLBACK_URL

    if not LINE_CHANNEL_ID or not LINE_CHANNEL_SECRET:
        logger.warning("LINE_CHANNEL_ID or LINE_CHANNEL_SECRET not configured.")
        # Return mock payload in development if keys are not set
        return {
            "status": "mock",
            "line_user_id": f"mock_line_{code[:8]}",
            "display_name": "LINE Test User",
            "picture_url": "",
            "message": "LINE Keys not configured yet. Using mock response."
        }

    token_url = "https://api.line.me/oauth2/v2.1/token"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": LINE_CHANNEL_ID,
        "client_secret": LINE_CHANNEL_SECRET,
    }

    try:
        token_res = requests.post(token_url, headers=headers, data=data, timeout=10)
        token_json = token_res.json()

        if token_res.status_code != 200 or "access_token" not in token_json:
            logger.error(f"LINE Token Exchange Error: {token_json}")
            return {"status": "error", "message": token_json.get("error_description", "Failed to exchange LINE code")}

        access_token = token_json["access_token"]
        profile_url = "https://api.line.me/v2/profile"
        profile_headers = {"Authorization": f"Bearer {access_token}"}
        profile_res = requests.get(profile_url, headers=profile_headers, timeout=10)
        profile_json = profile_res.json()

        if profile_res.status_code != 200:
            logger.error(f"LINE Profile Fetch Error: {profile_json}")
            return {"status": "error", "message": "Failed to fetch LINE profile"}

        return {
            "status": "success",
            "line_user_id": profile_json.get("userId"),
            "display_name": profile_json.get("displayName"),
            "picture_url": profile_json.get("pictureUrl"),
            "status_message": profile_json.get("statusMessage", ""),
        }
    except Exception as e:
        logger.exception("Exception in LINE OAuth processing")
        return {"status": "error", "message": str(e)}


def send_line_push_message(to_user_or_group_id: str, messages: list) -> dict:
    """
    Sends push notification via LINE Messaging API (Long-lived Channel Access Token).
    `messages` should be a list of dicts (Text/Flex messages).
    """
    access_token = LINE_ACCESS_TOKEN or os.getenv('LINE_ACCESS_TOKEN', '')
    if not access_token:
        logger.warning("LINE_ACCESS_TOKEN is missing. Notification skipped.")
        return {"status": "mock", "message": "LINE_ACCESS_TOKEN is not configured."}

    push_url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}"
    }
    payload = {
        "to": to_user_or_group_id,
        "messages": messages
    }

    try:
        res = requests.post(push_url, json=payload, headers=headers, timeout=10)
        if res.status_code == 200:
            return {"status": "success", "response": res.json() if res.text else {}}
        else:
            logger.error(f"LINE Push Error: {res.status_code} - {res.text}")
            return {"status": "error", "code": res.status_code, "message": res.text}
    except Exception as e:
        logger.exception("Exception in send_line_push_message")
        return {"status": "error", "message": str(e)}


def send_line_certificate_alert(booking_id: str, cert_code: str, pdf_url: str, line_user_id: str = None) -> dict:
    """
    Helper function to send Certificate Issued notification via LINE OA Flex Message.
    """
    message_text = (
        f"🏆 TRUST LAB Certificate Ready!\n\n"
        f"Booking ID: {booking_id}\n"
        f"Certificate Code: {cert_code}\n"
        f"View & Download PDF: {pdf_url}"
    )

    messages = [
        {
            "type": "text",
            "text": message_text
        }
    ]

    target_id = line_user_id or os.getenv('LINE_DEFAULT_NOTIFY_USER_ID', '')
    if not target_id:
        logger.info("No target LINE User ID provided for notification.")
        return {"status": "mock", "message": "No target LINE User ID provided."}

    return send_line_push_message(target_id, messages)
