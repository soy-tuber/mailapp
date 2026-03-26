"""Google Calendar イベント作成"""
import logging
from datetime import datetime, timedelta

from googleapiclient.discovery import build

from auth import get_calendar_credentials
from models import Email

logger = logging.getLogger(__name__)

TIMEZONE = "Asia/Tokyo"


def create_event(email_obj: Email) -> str | None:
    """メールから抽出されたスケジュール情報でカレンダーイベントを作成。
    成功時はイベントURLを返す。"""
    creds = get_calendar_credentials()
    if not creds:
        logger.warning("カレンダー未認証。`python run.py setup-calendar` を実行してください。")
        return None

    service = build("calendar", "v3", credentials=creds)

    # イベント本文の構築
    event_body = {
        "summary": email_obj.event_title or email_obj.subject,
        "description": (
            f"{email_obj.event_description or ''}\n\n"
            f"--- 元メール ---\n"
            f"件名: {email_obj.subject}\n"
            f"差出人: {email_obj.sender} <{email_obj.sender_email}>"
        ).strip(),
    }

    if email_obj.event_location:
        event_body["location"] = email_obj.event_location

    # 日時設定
    if email_obj.event_start_time and email_obj.event_date:
        # 時刻付きイベント
        start_dt = datetime.strptime(
            f"{email_obj.event_date} {email_obj.event_start_time}",
            "%Y-%m-%d %H:%M",
        )
        if email_obj.event_end_time:
            end_dt = datetime.strptime(
                f"{email_obj.event_date} {email_obj.event_end_time}",
                "%Y-%m-%d %H:%M",
            )
        else:
            end_dt = start_dt + timedelta(hours=1)

        event_body["start"] = {
            "dateTime": start_dt.isoformat(),
            "timeZone": TIMEZONE,
        }
        event_body["end"] = {
            "dateTime": end_dt.isoformat(),
            "timeZone": TIMEZONE,
        }
    elif email_obj.event_date:
        # 終日イベント
        event_body["start"] = {"date": email_obj.event_date}
        end_date = (
            datetime.strptime(email_obj.event_date, "%Y-%m-%d") + timedelta(days=1)
        ).strftime("%Y-%m-%d")
        event_body["end"] = {"date": end_date}
    else:
        logger.warning(f"日付なしのイベントはスキップ: {email_obj.event_title}")
        return None

    event = service.events().insert(calendarId="primary", body=event_body).execute()
    url = event.get("htmlLink", "")
    logger.info(f"  カレンダー登録: {event_body['summary']} ({email_obj.event_date})")
    return url
