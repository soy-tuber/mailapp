"""メールデータモデル"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class Email:
    message_id: str
    subject: str
    sender: str
    sender_email: str
    body_text: str
    received_at: str
    needs_reply: Optional[bool] = None
    reply_reason: Optional[str] = None
    draft_reply: Optional[str] = None
    category: Optional[str] = None
    urgency: Optional[str] = None
    # スケジュール関連
    has_event: Optional[bool] = None
    event_title: Optional[str] = None
    event_date: Optional[str] = None
    event_start_time: Optional[str] = None
    event_end_time: Optional[str] = None
    event_location: Optional[str] = None
    event_description: Optional[str] = None
    event_created_url: Optional[str] = None
