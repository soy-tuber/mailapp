"""Gemini による要返信判定 + 返信文案生成"""
import json
import logging
import re
from datetime import datetime

from google import genai
from google.genai import types

import config
from models import Email

logger = logging.getLogger(__name__)

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


CLASSIFY_PROMPT = """\
あなたはメール分析アシスタントです。
以下のメールを分析し、「返信が必要かどうか」を判定してください。

## 判定基準
- 質問・依頼・確認要求 → 返信必要
- ニュースレター・通知・広告・自動送信 → 返信不要
- CC/BCCで参考送付されただけ → 返信不要
- 挨拶・お礼のみで返信不要のもの → 返信不要

## メール情報
- 件名: {subject}
- 差出人: {sender} <{sender_email}>
- 本文:
{body}

## スケジュール検出
- メールに会議・打ち合わせ・イベント・予定・締切の情報が含まれる場合、has_event: true とし event オブジェクトを出力
- 日時が明示されていない場合は has_event: false
- event.date は YYYY-MM-DD 形式、start_time/end_time は HH:MM 形式 (24時間)
- 終了時刻が不明な場合は開始時刻の1時間後をデフォルトとする
- 時刻が不明な場合は終日イベント（start_time/end_time を null に）

## 出力形式（JSON厳守）
```json
{{
  "needs_reply": true/false,
  "reason": "判定理由を1-2文で",
  "urgency": "high/medium/low",
  "category": "question/request/confirmation/newsletter/notification/other",
  "has_event": true/false,
  "event": {{
    "title": "イベント名",
    "date": "YYYY-MM-DD",
    "start_time": "HH:MM or null",
    "end_time": "HH:MM or null",
    "location": "場所 or null",
    "description": "概要"
  }}
}}
```

has_event が false の場合、event は null としてください。
JSONのみ出力してください。"""

DRAFT_REPLY_PROMPT = """\
あなたはメール返信アシスタントです。
以下のメールに対する返信文案を日本語で作成してください。

## 方針
- ビジネスメールとして適切な敬語を使用
- 簡潔かつ丁寧に
- 相手の要求に対して具体的に応答
- 署名は不要（ユーザーが後で追加する）

## 元メール
- 件名: {subject}
- 差出人: {sender}
- 本文:
{body}

## 判定理由
{reason}

返信文案のみを出力してください（件名不要、本文のみ）。"""


def _parse_json_response(text: str) -> dict:
    """GeminiのレスポンスからJSON抽出"""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        logger.warning(f"JSON parse failed: {text[:200]}")
        return {"needs_reply": False, "reason": "解析エラー", "urgency": "low", "category": "other", "has_event": False}


def classify_email(email_obj: Email) -> dict:
    """メールの要返信判定"""
    client = _get_client()
    prompt = CLASSIFY_PROMPT.format(
        subject=email_obj.subject,
        sender=email_obj.sender,
        sender_email=email_obj.sender_email,
        body=email_obj.body_text[:2000],
    )

    response = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.1,
            max_output_tokens=500,
        ),
    )

    return _parse_json_response(response.text)


def draft_reply(email_obj: Email, reason: str) -> str:
    """返信文案を生成"""
    client = _get_client()
    prompt = DRAFT_REPLY_PROMPT.format(
        subject=email_obj.subject,
        sender=email_obj.sender,
        body=email_obj.body_text[:2000],
        reason=reason,
    )

    response = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.7,
            max_output_tokens=1000,
        ),
    )

    return response.text.strip()


def analyze_email(email_obj: Email) -> Email:
    """メール分析のフルパイプライン: 判定 → 文案生成"""
    logger.info(f"  分析中: {email_obj.subject[:50]}...")

    classification = classify_email(email_obj)
    email_obj.needs_reply = classification.get("needs_reply", False)
    email_obj.reply_reason = classification.get("reason", "")
    email_obj.category = classification.get("category", "other")
    email_obj.urgency = classification.get("urgency", "low")

    if email_obj.needs_reply:
        email_obj.draft_reply = draft_reply(email_obj, email_obj.reply_reason)
    else:
        email_obj.draft_reply = None

    # スケジュール検出
    email_obj.has_event = classification.get("has_event", False)
    if email_obj.has_event and classification.get("event"):
        event = classification["event"]
        email_obj.event_title = event.get("title")
        email_obj.event_date = event.get("date")
        email_obj.event_start_time = event.get("start_time")
        email_obj.event_end_time = event.get("end_time")
        email_obj.event_location = event.get("location")
        email_obj.event_description = event.get("description")

    return email_obj


def analyze_batch(emails: list[Email]) -> list[Email]:
    """バッチ分析"""
    results = []
    for i, em in enumerate(emails):
        try:
            analyzed = analyze_email(em)
            results.append(analyzed)
            status = "要返信" if analyzed.needs_reply else "不要"
            logger.info(f"  [{i+1}/{len(emails)}] {status} | {analyzed.subject[:40]}")
        except Exception as e:
            logger.error(f"  [{i+1}/{len(emails)}] エラー: {e}")
            em.reply_reason = str(e)
            results.append(em)
    return results
