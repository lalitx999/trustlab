# EP 8 — staff notification outbox (delivery not enabled)

The current implementation records pending notifications only. It does not call
LINE or WeChat, and it does not upload photos to a third party.

## Deployment

Run `python manage.py migrate` before serving the updated application.
Migration 0021 adds StaffNotification. Booking/job/photo writes now use this table.

## Events

- booking_created: LINE; booking database ID.
- job_created: LINE and WeChat; job and booking database IDs.
- job_updated: LINE and WeChat; status/result/expert-source changes through job_update.
- staff_photos_added: WeChat; uploaded photo IDs, not public links or image bytes.

Rows are written in the same transaction as the corresponding business action.
The event_key/channel constraint prevents duplicate rows for the same event.
Status is awaiting_configuration. This is NOT a delivery-success status.
No worker, automatic retries, or dispatch endpoint is enabled yet.
Legacy/direct creation routes are not all connected; review them before enabling delivery.

## Information required to finish

1. LINE OA channel and approved recipient user/group/room IDs.
2. Confirm WeChat product (personal WeChat, Official Account, or WeCom/WeChat Work).
3. Approved target group/account and whether customer photos may be sent there.
4. Choose which events should notify, and which uploaded photos should be included.

After confirmation, implement a dispatcher with recorded provider responses,
timeouts, failure states, and provider-appropriate retry handling. LINE supports
X-Line-Retry-Key for push messages:
https://developers.line.biz/en/docs/messaging-api/retrying-api-request/

Do not automatically deliver the historical waiting backlog when enabling a
channel. Agree a cutoff first so old jobs/photos are not unexpectedly broadcast.
Credentials must remain server-side. Do not log access tokens or webhook URLs.
