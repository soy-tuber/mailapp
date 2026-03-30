"""IMAP/SMTP メールクライアント"""
import imaplib
import email
import email.header
import email.utils
import logging
import re
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from typing import Optional

import config
from models import Email

logger = logging.getLogger(__name__)


def _decode_header(raw: str) -> str:
    """メールヘッダーのデコード"""
    if not raw:
        return ""
    parts = email.header.decode_header(raw)
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(part)
    return "".join(decoded)


def _extract_sender(from_header: str) -> tuple[str, str]:
    """From ヘッダーから名前とメールアドレスを抽出"""
    decoded = _decode_header(from_header)
    match = re.match(r'^"?(.+?)"?\s*<(.+?)>$', decoded)
    if match:
        return match.group(1).strip('" '), match.group(2)
    email_match = re.search(r'[\w.+-]+@[\w.-]+', decoded)
    if email_match:
        return decoded, email_match.group(0)
    return decoded, decoded


def _extract_body(msg: email.message.Message) -> str:
    """メール本文をプレーンテキストで抽出"""
    if msg.is_multipart():
        # text/plain を優先
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace")
        # text/html フォールバック
        for part in msg.walk():
            ct = part.get_content_type()
            if ct == "text/html":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    html = payload.decode(charset, errors="replace")
                    text = re.sub(r'<[^>]+>', '', html)
                    text = re.sub(r'\s+', ' ', text).strip()
                    return text[:5000]
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            return payload.decode(charset, errors="replace")
    return ""


def _get_folder_by_attr(conn: imaplib.IMAP4_SSL, attr: str) -> str:
    """IMAPフォルダを特殊属性(\\Drafts, \\Sent等)で検索"""
    _, folders = conn.list()
    for folder_line in folders:
        if folder_line is None:
            continue
        decoded = folder_line.decode("utf-8", errors="replace")
        if attr in decoded:
            # フォルダ名を抽出: '(\\HasNoChildren \\Drafts) "/" "[Gmail]/Drafts"'
            match = re.search(r'"([^"]+)"$', decoded)
            if match:
                return match.group(1)
            # スペース区切りの場合
            parts = decoded.rsplit(" ", 1)
            if len(parts) == 2:
                return parts[1].strip('"')
    # フォールバック
    fallbacks = {
        "\\Drafts": "[Gmail]/Drafts",
        "\\Sent": "[Gmail]/Sent Mail",
    }
    return fallbacks.get(attr, attr)


def save_draft(original: Email, draft_body: str) -> None:
    """返信下書きをGmailの下書きフォルダにIMAP APPENDで保存"""
    # 件名の Re: 処理
    subject = original.subject
    if not re.match(r'^Re:\s*', subject, re.IGNORECASE):
        subject = f"Re: {subject}"

    msg = MIMEText(draft_body, "plain", "utf-8")
    msg["From"] = config.EMAIL_ADDRESS
    msg["To"] = original.sender_email
    msg["Subject"] = subject
    msg["In-Reply-To"] = original.message_id
    msg["References"] = original.message_id
    msg["Date"] = email.utils.formatdate(localtime=True)

    conn = imaplib.IMAP4_SSL(config.IMAP_SERVER)
    try:
        conn.login(config.EMAIL_ADDRESS, config.EMAIL_APP_PASSWORD)
        drafts_folder = _get_folder_by_attr(conn, "\\Drafts")
        conn.append(f'"{drafts_folder}"', "\\Draft", None, msg.as_bytes())
        logger.info(f"  下書き保存: {subject[:50]}")
    finally:
        conn.logout()


def check_sent_replies(message_ids: list[str], since_date: str) -> set[str]:
    """Sentフォルダを検索し、返信済みの message_id を返す"""
    if not message_ids:
        return set()

    conn = imaplib.IMAP4_SSL(config.IMAP_SERVER)
    replied = set()
    try:
        conn.login(config.EMAIL_ADDRESS, config.EMAIL_APP_PASSWORD)
        sent_folder = _get_folder_by_attr(conn, "\\Sent")
        conn.select(f'"{sent_folder}"', readonly=True)

        # SINCE で検索範囲を限定
        target = datetime.strptime(since_date, "%Y-%m-%d")
        imap_date = target.strftime("%d-%b-%Y")

        for mid in message_ids:
            # In-Reply-To ヘッダーで返信を検索
            # message_id から角括弧を除去してクエリを構築
            clean_mid = mid.strip("<>")
            try:
                _, msg_ids = conn.search(None, "SINCE", imap_date, "HEADER", "In-Reply-To", clean_mid)
                if msg_ids[0].strip():
                    replied.add(mid)
            except imaplib.IMAP4.error:
                logger.debug(f"IMAP SEARCH failed for {mid}, skipping")
    finally:
        conn.logout()
    return replied


def fetch_todays_emails(date_str: Optional[str] = None) -> list[Email]:
    """IMAPで今日の受信メールを取得"""
    if date_str is None:
        target = datetime.now()
    else:
        target = datetime.strptime(date_str, "%Y-%m-%d")

    # IMAP日付フォーマット: 26-Mar-2026
    imap_date = target.strftime("%d-%b-%Y")

    conn = imaplib.IMAP4_SSL(config.IMAP_SERVER)
    conn.login(config.EMAIL_ADDRESS, config.EMAIL_APP_PASSWORD)
    conn.select("INBOX")

    # 今日の日付で検索（自分が送ったメールは除外）
    search_criteria = f'(ON {imap_date} NOT FROM "{config.EMAIL_ADDRESS}")'
    _, msg_ids = conn.search(None, search_criteria)

    emails = []
    ids = msg_ids[0].split()

    # 最新からMAX_EMAILS件
    for mid in ids[-config.MAX_EMAILS:]:
        _, msg_data = conn.fetch(mid, "(RFC822)")
        raw = msg_data[0][1]
        msg = email.message_from_bytes(raw)

        sender_name, sender_email = _extract_sender(msg.get("From", ""))
        subject = _decode_header(msg.get("Subject", "(件名なし)"))
        date_header = msg.get("Date", target.isoformat())
        message_id = msg.get("Message-ID", mid.decode())

        body = _extract_body(msg)
        if len(body) > 3000:
            body = body[:3000] + "\n...(以下省略)"

        emails.append(Email(
            message_id=message_id,
            subject=subject,
            sender=sender_name,
            sender_email=sender_email,
            body_text=body,
            received_at=date_header,
        ))

    conn.logout()
    return emails


def send_email(to: str, subject: str, body_html: str):
    """SMTPでメール送信"""
    msg = MIMEText(body_html, "html", "utf-8")
    msg["From"] = config.EMAIL_ADDRESS
    msg["To"] = to
    msg["Subject"] = subject

    with smtplib.SMTP(config.SMTP_SERVER, config.SMTP_PORT) as server:
        server.starttls()
        server.login(config.EMAIL_ADDRESS, config.EMAIL_APP_PASSWORD)
        server.send_message(msg)
