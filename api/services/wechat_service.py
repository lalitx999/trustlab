# api/services/wechat_service.py
import os
import requests
import logging
from django.conf import settings

logger = logging.getLogger(__name__)

WECHAT_WORK_WEBHOOK_URL = getattr(settings, 'WECHAT_WORK_WEBHOOK_URL', os.getenv('WECHAT_WORK_WEBHOOK_URL', ''))
WECHAT_APP_ID = getattr(settings, 'WECHAT_APP_ID', os.getenv('WECHAT_APP_ID', ''))
WECHAT_APP_SECRET = getattr(settings, 'WECHAT_APP_SECRET', os.getenv('WECHAT_APP_SECRET', ''))


def send_wechat_work_alert(title: str, content_markdown: str, job_id: str = None) -> dict:
    """
    Sends Group Bot Webhook alert to Enterprise WeChat / WeChat Work staff group.
    Supports markdown formatting out-of-the-box.
    """
    webhook_url = WECHAT_WORK_WEBHOOK_URL or os.getenv('WECHAT_WORK_WEBHOOK_URL', '')
    if not webhook_url:
        logger.warning("WECHAT_WORK_WEBHOOK_URL is not configured. Webhook alert skipped.")
        return {"status": "mock", "message": "WECHAT_WORK_WEBHOOK_URL is missing. Configured mock response."}

    full_text = f"### 🚨 {title}\n"
    if job_id:
        full_text += f"**Job ID:** `{job_id}`\n\n"
    full_text += content_markdown

    payload = {
        "msgtype": "markdown",
        "markdown": {
            "content": full_text
        }
    }

    try:
        res = requests.post(webhook_url, json=payload, headers={"Content-Type": "application/json"}, timeout=10)
        res_json = res.json() if res.text else {}
        if res.status_code == 200 and res_json.get("errcode") == 0:
            return {"status": "success", "response": res_json}
        else:
            logger.error(f"WeChat Work Webhook Error: {res.status_code} - {res.text}")
            return {"status": "error", "code": res.status_code, "message": res.text}
    except Exception as e:
        logger.exception("Exception in send_wechat_work_alert")
        return {"status": "error", "message": str(e)}


def get_wechat_oa_access_token() -> str:
    """
    Fetches WeChat Official Account Access Token using AppID & AppSecret.
    """
    app_id = WECHAT_APP_ID or os.getenv('WECHAT_APP_ID', '')
    app_secret = WECHAT_APP_SECRET or os.getenv('WECHAT_APP_SECRET', '')

    if not app_id or not app_secret:
        logger.warning("WECHAT_APP_ID or WECHAT_APP_SECRET is not configured.")
        return ""

    url = f"https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid={app_id}&secret={app_secret}"
    try:
        res = requests.get(url, timeout=10)
        data = res.json()
        return data.get("access_token", "")
    except Exception as e:
        logger.exception("Error fetching WeChat OA access token")
        return ""


def send_wechat_oa_template_message(touser_openid: str, template_id: str, data_dict: dict, page_url: str = None) -> dict:
    """
    Sends Official Account Template Message to specific WeChat user OpenID.
    """
    token = get_wechat_oa_access_token()
    if not token:
        return {"status": "mock", "message": "WeChat OA Access Token unavailable. Keys missing."}

    send_url = f"https://api.weixin.qq.com/cgi-bin/message/template/send?access_token={token}"
    payload = {
        "touser": touser_openid,
        "template_id": template_id,
        "url": page_url or "",
        "data": data_dict
    }

    try:
        res = requests.post(send_url, json=payload, timeout=10)
        res_data = res.json()
        if res_data.get("errcode") == 0:
            return {"status": "success", "msgid": res_data.get("msgid")}
        return {"status": "error", "message": res_data.get("errmsg")}
    except Exception as e:
        logger.exception("Error sending WeChat OA template message")
        return {"status": "error", "message": str(e)}
