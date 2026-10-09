# api/services/line_service.py
import os
import requests
import logging
from django.conf import settings

logger = logging.getLogger(__name__)

def get_line_credentials():
    channel_id = getattr(settings, 'LINE_CHANNEL_ID', '') or os.getenv('LINE_CHANNEL_ID', '') or os.getenv('LINE_CLIENT_ID', '')
    channel_secret = getattr(settings, 'LINE_CHANNEL_SECRET', '') or os.getenv('LINE_CHANNEL_SECRET', '') or os.getenv('LINE_CLIENT_SECRET', '')
    access_token = getattr(settings, 'LINE_ACCESS_TOKEN', '') or os.getenv('LINE_ACCESS_TOKEN', '') or os.getenv('LINE_CHANNEL_ACCESS_TOKEN', '')
    callback_url = getattr(settings, 'LINE_CALLBACK_URL', '') or os.getenv('LINE_CALLBACK_URL', 'https://www.trustlabthailand.com/api/auth/line/callback')
    return channel_id, channel_secret, access_token, callback_url


def get_line_user_profile(code: str, redirect_uri: str = None) -> dict:
    """
    Exchanges LINE OAuth code for access token and fetches user profile.
    Returns dict containing line_user_id, display_name, picture_url, status_message
    """
    channel_id, channel_secret, _, default_redirect_uri = get_line_credentials()
    if not redirect_uri:
        redirect_uri = default_redirect_uri

    if not channel_id or not channel_secret:
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
        "client_id": channel_id,
        "client_secret": channel_secret,
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
    _, _, access_token, _ = get_line_credentials()
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
        print(f"📡 Sending LINE Push Message to {to_user_or_group_id}...", flush=True)
        res = requests.post(push_url, json=payload, headers=headers, timeout=10)
        if res.status_code == 200:
            print(f"✅ LINE Push Sent Successfully to {to_user_or_group_id}", flush=True)
            return {"status": "success", "response": res.json() if res.text else {}}
        else:
            msg = f"❌ LINE Push Failed ({res.status_code}): {res.text}"
            logger.error(msg)
            print(msg, flush=True)
            return {"status": "error", "code": res.status_code, "message": res.text}
    except Exception as e:
        logger.exception("Exception in send_line_push_message")
        print(f"❌ Exception in send_line_push_message: {e}", flush=True)
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

    target_id = (
        line_user_id or
        getattr(settings, 'LINE_NOTIFY_TARGET_ID', '') or
        os.getenv('LINE_NOTIFY_TARGET_ID', '') or
        os.getenv('LINE_GROUP_ID', '') or
        os.getenv('LINE_NOTIFY_GROUP_ID', '') or
        os.getenv('LINE_DEFAULT_NOTIFY_USER_ID', '')
    )
    if not target_id:
        logger.info("No target LINE User/Group ID provided for notification.")
        return {"status": "mock", "message": "No target LINE User/Group ID provided."}

    return send_line_push_message(target_id, messages)


def build_booking_flex_message(booking) -> dict:
    """Builds a rich LINE Flex Message card for a new online booking"""
    customer_name = booking.customer.full_name if booking.customer else "ลูกค้าทั่วไป"
    customer_phone = booking.customer.phone_number if booking.customer else "-"
    branch_name = booking.branch.name if booking.branch else "สาขาหลัก"
    booking_id = f"BK-{booking.pk:06d}" if isinstance(booking.pk, int) else str(booking.pk)
    date_str = str(booking.booking_date)
    time_str = str(booking.booking_time)[:5] if booking.booking_time else "-"

    item_desc = f"{booking.brand_name} {booking.model}".strip() or booking.category or "สินค้าตรวจ"
    pkg = booking.service_package or "Physical Inspection"
    price = f"{float(booking.price_snapshot.get('total', 0)):,.2f}" if (isinstance(booking.price_snapshot, dict) and 'total' in booking.price_snapshot) else "0.00"

    pm_method = {
        'shop': 'ชำระหน้าร้าน',
        'promptpay': 'PromptPay',
        'wallet': 'เครดิตสมาชิก',
        'transfer': 'โอนผ่านธนาคาร',
        'cash': 'เงินสด',
        'credit_card': 'บัตรเครดิต'
    }.get(booking.payment_method, booking.payment_method or '-')

    pm_status = {
        'paid': 'ชำระแล้ว',
        'pending_review': 'รอตรวจสลิป',
        'unpaid': 'ยังไม่ชำระ'
    }.get(booking.payment_status, booking.payment_status or '-')

    delivery = "จัดส่งพัสดุ" if booking.delivery_method == 'shipping' else "มารับด้วยตัวเอง"

    flex_json = {
        "type": "flex",
        "altText": f"📋 มีการจองคิวใหม่! {booking_id} ({customer_name})",
        "contents": {
            "type": "bubble",
            "size": "mega",
            "header": {
                "type": "box",
                "layout": "vertical",
                "backgroundColor": "#1E293B",
                "paddingAll": "15px",
                "contents": [
                    {
                        "type": "text",
                        "text": "📋 TRUST LAB • NEW BOOKING",
                        "weight": "bold",
                        "color": "#F59E0B",
                        "size": "xs"
                    },
                    {
                        "type": "text",
                        "text": f"คิวจองใหม่ #{booking_id}",
                        "weight": "bold",
                        "color": "#FFFFFF",
                        "size": "lg",
                        "margin": "xs"
                    }
                ]
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "md",
                "contents": [
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "contents": [
                            {"type": "text", "text": "ลูกค้า", "size": "xs", "color": "#64748B", "flex": 2},
                            {"type": "text", "text": f"{customer_name} ({customer_phone})", "size": "xs", "color": "#1E293B", "weight": "bold", "flex": 5, "wrap": True}
                        ]
                    },
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "contents": [
                            {"type": "text", "text": "นัดหมาย", "size": "xs", "color": "#64748B", "flex": 2},
                            {"type": "text", "text": f"{date_str} เวลา {time_str} น.", "size": "xs", "color": "#2563EB", "weight": "bold", "flex": 5}
                        ]
                    },
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "contents": [
                            {"type": "text", "text": "สาขา", "size": "xs", "color": "#64748B", "flex": 2},
                            {"type": "text", "text": branch_name, "size": "xs", "color": "#1E293B", "flex": 5}
                        ]
                    },
                    {"type": "separator", "margin": "md"},
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "contents": [
                            {"type": "text", "text": "สินค้า", "size": "xs", "color": "#64748B", "flex": 2},
                            {"type": "text", "text": f"[{booking.category}] {item_desc}", "size": "xs", "color": "#1E293B", "weight": "bold", "flex": 5, "wrap": True}
                        ]
                    },
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "contents": [
                            {"type": "text", "text": "แพ็กเกจ", "size": "xs", "color": "#64748B", "flex": 2},
                            {"type": "text", "text": pkg, "size": "xs", "color": "#1E293B", "flex": 5}
                        ]
                    },
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "contents": [
                            {"type": "text", "text": "ยอดรวม", "size": "xs", "color": "#64748B", "flex": 2},
                            {"type": "text", "text": f"฿{price} ({pm_status} / {pm_method})", "size": "xs", "color": "#059669", "weight": "bold", "flex": 5, "wrap": True}
                        ]
                    },
                    {
                        "type": "box",
                        "layout": "horizontal",
                        "contents": [
                            {"type": "text", "text": "การจัดส่ง", "size": "xs", "color": "#64748B", "flex": 2},
                            {"type": "text", "text": delivery, "size": "xs", "color": "#1E293B", "flex": 5}
                        ]
                    }
                ]
            }
        }
    }
    return flex_json


def send_line_booking_notification(booking, target_id: str = None) -> dict:
    """
    Sends Flex Message + preview photos to a LINE Group (or User) whenever a new booking is created.
    `target_id` can be a Group ID (C...) or User ID (U...).
    """
    target = (
        target_id or
        getattr(settings, 'LINE_NOTIFY_TARGET_ID', '') or
        os.getenv('LINE_NOTIFY_TARGET_ID', '') or
        os.getenv('LINE_GROUP_ID', '') or
        os.getenv('LINE_NOTIFY_GROUP_ID', '') or
        os.getenv('LINE_DEFAULT_NOTIFY_USER_ID', '')
    )
    if not target:
        msg = "⚠️ LINE Notification Skipped: No target LINE Group/User ID configured."
        logger.info(msg)
        print(msg, flush=True)
        return {"status": "mock", "message": "LINE_NOTIFY_TARGET_ID is not configured."}

    flex_msg = build_booking_flex_message(booking)
    messages = [flex_msg]

    # Attach customer preview photos (up to 3 photos)
    try:
        photos = booking.photos.filter(photo_type='customer')[:3]
        for p in photos:
            if p.photo:
                img_url = p.photo.url
                if not img_url.startswith('http'):
                    base_domain = os.getenv('BACKEND_BASE_URL', 'https://app2.tanchonhomserverxxx.online').rstrip('/')
                    img_url = f"{base_domain}{img_url}"
                if img_url.startswith('http://'):
                    img_url = img_url.replace('http://', 'https://', 1)

                messages.append({
                    "type": "image",
                    "originalContentUrl": img_url,
                    "previewImageUrl": img_url
                })
    except Exception as e:
        logger.exception("Error formatting photo URL for LINE booking notification")
        print(f"⚠️ Error formatting photo URL for LINE notification: {e}", flush=True)

    print(f"🚀 Triggering LINE Booking Notification for BK-{booking.pk} to Target: {target}", flush=True)
    return send_line_push_message(target, messages)
