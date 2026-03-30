"""Mail Reminder CLI
毎日1回実行: メール取得→Gemini分析→下書き保存→ダイジェストメールで通知
"""
import argparse
import logging
from datetime import datetime, timedelta
from html import escape

import config
import db
from mail_client import (
    fetch_todays_emails, send_email, save_draft, check_sent_replies,
)
from gemini_analyzer import analyze_batch
from models import Email

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def build_digest_html(
    emails: list[Email],
    date_str: str,
    overdue: list[dict] | None = None,
) -> str:
    """ダイジェストメールのHTML生成"""
    needs_reply = [e for e in emails if e.needs_reply]
    no_reply = [e for e in emails if not e.needs_reply]

    html = f"""\
<html><body style="font-family: sans-serif; max-width: 600px; margin: 0 auto;">
<h2>Mail Reminder - 本日のダイジェスト</h2>
<p style="color: #666;">
    {escape(date_str)} |
    全{len(emails)}件 |
    <span style="color: #ef4444;">要返信 {len(needs_reply)}件</span>
</p>
<hr style="border: 1px solid #eee;">
"""

    # 未返信アラート（最優先で表示）
    if overdue:
        html += f'<h3 style="color: #dc2626; background: #fef2f2; padding: 8px 12px; border-radius: 4px;">未返信アラート ({len(overdue)}件)</h3>'
        for o in overdue:
            hours_ago = int(
                (datetime.now() - datetime.fromisoformat(o["first_seen"]))
                .total_seconds() / 3600
            )
            html += f"""\
<div style="border-left: 3px solid #dc2626; padding: 8px 16px; margin: 12px 0; background: #fff1f2;">
    <strong>{escape(o["subject"])}</strong><br>
    <span style="color: #666; font-size: 0.9em;">{escape(o["sender"])} &lt;{escape(o["sender_email"])}&gt;</span><br>
    <span style="color: #dc2626; font-size: 0.85em;">{hours_ago}時間経過 | 緊急度: {escape(o.get("urgency") or "不明")}</span>
</div>
"""

    if needs_reply:
        html += '<h3 style="color: #ef4444;">要返信</h3>'
        for e in needs_reply:
            draft_section = ""
            if e.draft_reply:
                draft_section = f'<div style="background: #fff; border: 1px solid #ddd; padding: 10px; margin-top: 8px; font-size: 0.9em; white-space: pre-wrap;">{escape(e.draft_reply)}</div>'
            html += f"""\
<div style="border-left: 3px solid #ef4444; padding: 8px 16px; margin: 12px 0; background: #fef2f2;">
    <strong>{escape(e.subject)}</strong><br>
    <span style="color: #666; font-size: 0.9em;">{escape(e.sender)} &lt;{escape(e.sender_email)}&gt;</span><br>
    <span style="color: #888; font-size: 0.85em;">理由: {escape(e.reply_reason or "")}</span><br>
    <span style="color: #888; font-size: 0.85em;">緊急度: {escape(e.urgency or "")} | 分類: {escape(e.category or "")}</span>
    {draft_section}
</div>
"""

    # カレンダー登録セクション
    events_registered = [e for e in emails if e.event_created_url]
    events_detected = [e for e in emails if e.has_event and e.event_date and not e.event_created_url]
    if events_registered or events_detected:
        html += f'<h3 style="color: #2563eb;">スケジュール ({len(events_registered) + len(events_detected)}件)</h3>'
        for e in events_registered:
            time_str = f"{e.event_start_time}-{e.event_end_time}" if e.event_start_time else "終日"
            html += f"""\
<div style="border-left: 3px solid #2563eb; padding: 8px 16px; margin: 12px 0; background: #eff6ff;">
    <strong>{escape(e.event_title or e.subject)}</strong><br>
    <span style="color: #666; font-size: 0.9em;">{escape(e.event_date)} {escape(time_str)}</span>
    {f' | {escape(e.event_location)}' if e.event_location else ''}<br>
    <a href="{escape(e.event_created_url)}" style="font-size: 0.85em;">Google Calendar で表示</a>
</div>
"""
        for e in events_detected:
            time_str = f"{e.event_start_time}-{e.event_end_time}" if e.event_start_time else "終日"
            html += f"""\
<div style="border-left: 3px solid #93c5fd; padding: 8px 16px; margin: 12px 0; background: #f0f9ff;">
    <strong>{escape(e.event_title or e.subject)}</strong><br>
    <span style="color: #666; font-size: 0.9em;">{escape(e.event_date)} {escape(time_str)}</span>
    {f' | {escape(e.event_location)}' if e.event_location else ''}<br>
    <span style="color: #999; font-size: 0.85em;">未登録（カレンダー未設定）</span>
</div>
"""

    if no_reply:
        html += f'<h3 style="color: #22c55e;">返信不要 ({len(no_reply)}件)</h3>'
        html += '<ul style="color: #666; font-size: 0.9em;">'
        for e in no_reply:
            html += f'<li><strong>{escape(e.subject)}</strong> - {escape(e.sender)} ({escape(e.reply_reason or "")})</li>'
        html += '</ul>'

    html += """\
<hr style="border: 1px solid #eee;">
<p style="color: #999; font-size: 0.8em;">Powered by Gemini + IMAP/SMTP</p>
</body></html>"""
    return html


def cmd_digest(args):
    """メインのダイジェスト処理"""
    date_str = args.date or datetime.now().strftime("%Y-%m-%d")

    # DB初期化
    db.init_db()

    # メール取得
    logger.info(f"メール取得中... (date={date_str})")
    emails = fetch_todays_emails(date_str)
    logger.info(f"  {len(emails)} 件取得")

    analyzed = []
    if not emails:
        logger.info("新規メールなし。")
    else:
        # Gemini分析
        logger.info("Gemini 分析中...")
        analyzed = analyze_batch(emails)

        needs_reply_count = sum(1 for e in analyzed if e.needs_reply)
        logger.info(f"結果: {len(analyzed)} 件中 {needs_reply_count} 件が要返信")

        # DBにトラッキング登録
        for e in analyzed:
            db.upsert_email(
                message_id=e.message_id,
                subject=e.subject,
                sender=e.sender,
                sender_email=e.sender_email,
                needs_reply=bool(e.needs_reply),
                draft_created=bool(e.draft_reply),
                urgency=e.urgency,
            )

        # 下書き保存
        if not args.dry_run and not args.no_drafts:
            draft_count = 0
            for e in analyzed:
                if e.draft_reply:
                    try:
                        save_draft(e, e.draft_reply)
                        draft_count += 1
                    except Exception as ex:
                        logger.error(f"下書き保存エラー ({e.subject[:30]}): {ex}")
            logger.info(f"下書き保存完了: {draft_count} 件")

        # カレンダー登録
        if not args.dry_run and not args.no_calendar:
            events_with_schedule = [e for e in analyzed if e.has_event and e.event_date]
            if events_with_schedule:
                try:
                    from calendar_client import create_event
                    cal_count = 0
                    for e in events_with_schedule:
                        try:
                            url = create_event(e)
                            if url:
                                e.event_created_url = url
                                cal_count += 1
                        except Exception as ex:
                            logger.error(f"カレンダー登録エラー ({e.subject[:30]}): {ex}")
                    logger.info(f"カレンダー登録完了: {cal_count} 件")
                except ImportError:
                    logger.warning("google-api-python-client 未インストール。カレンダー機能をスキップ。")
        elif args.dry_run:
            events_with_schedule = [e for e in analyzed if e.has_event and e.event_date]
            if events_with_schedule:
                logger.info(f"--- スケジュール検出 ({len(events_with_schedule)}件) ---")
                for e in events_with_schedule:
                    time_str = f"{e.event_start_time}-{e.event_end_time}" if e.event_start_time else "終日"
                    logger.info(f"  {e.event_date} {time_str} | {e.event_title}")

    # 返信チェック（過去の未返信メールも含む）
    logger.info("返信チェック中...")
    unreplied_ids = db.get_tracked_unreplied_ids()
    if unreplied_ids:
        since = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        replied_ids = check_sent_replies(unreplied_ids, since)
        if replied_ids:
            db.mark_replied(replied_ids)
            logger.info(f"  {len(replied_ids)} 件の返信を検出")

    # 未返信アラート取得
    overdue = db.get_unreplied_overdue()
    if overdue:
        logger.info(f"  未返信アラート: {len(overdue)} 件 ({config.REPLY_ALERT_HOURS}時間超)")

    # 古いレコードのクリーンアップ
    cleaned = db.cleanup_old(30)
    if cleaned:
        logger.info(f"  古いレコード削除: {cleaned} 件")

    # ダイジェストメール送信
    if args.dry_run:
        logger.info("dry-run モード: メール送信をスキップ")
        if overdue:
            logger.info("--- 未返信アラート ---")
            for o in overdue:
                logger.info(f"  [{o['urgency']}] {o['subject'][:50]} - {o['sender']}")
    else:
        if not analyzed and not overdue:
            logger.info("送信対象なし。終了します。")
            return

        digest_html = build_digest_html(analyzed, date_str, overdue)
        needs_reply_count = sum(1 for e in analyzed if e.needs_reply)
        alert_part = f" / 未返信{len(overdue)}件" if overdue else ""
        subject = f"Mail Reminder: 要返信{needs_reply_count}件{alert_part} ({date_str})"
        send_email(config.EMAIL_ADDRESS, subject, digest_html)
        logger.info(f"ダイジェストメール送信完了 -> {config.EMAIL_ADDRESS}")


def cmd_check_replies(args):
    """未返信チェック（単独実行用）"""
    db.init_db()

    unreplied_ids = db.get_tracked_unreplied_ids()
    if not unreplied_ids:
        logger.info("トラッキング中の未返信メールなし。")
        return

    logger.info(f"未返信メール {len(unreplied_ids)} 件をチェック中...")
    since = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    replied_ids = check_sent_replies(unreplied_ids, since)

    if replied_ids:
        db.mark_replied(replied_ids)
        logger.info(f"  {len(replied_ids)} 件の返信を検出")

    overdue = db.get_unreplied_overdue()
    if overdue:
        logger.info(f"\n--- 未返信アラート ({len(overdue)}件, {config.REPLY_ALERT_HOURS}時間超) ---")
        for o in overdue:
            hours_ago = int(
                (datetime.now() - datetime.fromisoformat(o["first_seen"]))
                .total_seconds() / 3600
            )
            logger.info(f"  [{o['urgency']}] {hours_ago}h経過 | {o['subject'][:50]} - {o['sender']}")
    else:
        logger.info("未返信アラートなし。")


def main():
    parser = argparse.ArgumentParser(description="Mail Reminder CLI")
    parser.add_argument("--profile", default="default", help="ユーザープロファイル名 (.env.{profile} を使用)")
    subparsers = parser.add_subparsers(dest="command")

    # digest (デフォルト)
    p_digest = subparsers.add_parser("digest", help="メール分析→ダイジェスト送信")
    p_digest.add_argument("--date", help="対象日 (YYYY-MM-DD)", default=None)
    p_digest.add_argument("--dry-run", action="store_true", help="分析のみ（メール送信なし）")
    p_digest.add_argument("--no-drafts", action="store_true", help="下書き保存をスキップ")
    p_digest.add_argument("--no-calendar", action="store_true", help="カレンダー登録をスキップ")

    # check-replies
    subparsers.add_parser("check-replies", help="未返信チェック（単独実行）")

    # setup-calendar
    subparsers.add_parser("setup-calendar", help="Google Calendar OAuth2セットアップ")

    args, remaining = parser.parse_known_args()

    if config.PROFILE != "default":
        logger.info(f"プロファイル: {config.PROFILE} ({config.EMAIL_ADDRESS})")

    # サブコマンド省略時は digest 扱い（後方互換性）
    if args.command is None:
        args = p_digest.parse_args(remaining)
        cmd_digest(args)
    elif args.command == "digest":
        cmd_digest(args)
    elif args.command == "check-replies":
        cmd_check_replies(args)
    elif args.command == "setup-calendar":
        try:
            from auth import setup_calendar_auth
        except ImportError as e:
            logger.error(f"依存パッケージ不足: {e}\n  uv pip install -r requirements.txt を実行してください。")
            return
        setup_calendar_auth()


if __name__ == "__main__":
    main()
