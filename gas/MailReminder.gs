/**
 * Mail Reminder for Google Apps Script
 *
 * Gmail受信メールをGemini APIで分析し、返信下書き自動生成＆カレンダー仮登録を行う。
 * 認証不要（GASネイティブ権限で動作）。必要なのはGemini APIキーのみ。
 *
 * セットアップ:
 *   1. Google Apps Script エディタで新規プロジェクト作成
 *   2. このファイルの内容を貼り付け
 *   3. setupTrigger() を1回実行（毎朝9時のトリガー設定）
 *   4. スクリプトプロパティに GEMINI_API_KEY を設定
 *      （プロジェクトの設定 → スクリプトプロパティ → 行を追加）
 *   5. （任意）M365エイリアス開通後、スクリプトプロパティに SEND_AS_EMAIL を設定
 *      → 下書きの送信元がM365アドレスになる
 */

// ============================================================
// 設定
// ============================================================
const CONFIG = {
  GEMINI_MODEL: "gemini-3.1-flash-lite-preview",
  TIMEZONE: "Asia/Tokyo",
  MAX_EMAILS: 50,
  REPLY_ALERT_HOURS: 48,
  // 処理対象: 過去N日以内の未読メール（トリガー間隔に合わせて調整）
  SEARCH_DAYS: 1,
  // 処理済みラベル名（重複処理防止）
  PROCESSED_LABEL: "MailReminder/処理済",
  // 仮予定のプレフィックス
  TENTATIVE_PREFIX: "【仮】",
};

// ============================================================
// メインエントリポイント（トリガーから呼ばれる）
// ============================================================
function main() {
  const apiKey = PropertiesService.getScriptProperties().getProperty("GEMINI_API_KEY");
  if (!apiKey) {
    Logger.log("エラー: スクリプトプロパティに GEMINI_API_KEY を設定してください。");
    return;
  }

  const myEmail = Session.getActiveUser().getEmail();
  Logger.log(`実行開始 (${myEmail})`);

  // 1. 未処理メール取得
  const emails = fetchUnprocessedEmails_(myEmail);
  Logger.log(`未処理メール: ${emails.length} 件`);

  if (emails.length === 0) {
    Logger.log("新規メールなし。終了。");
    return;
  }

  // 2. Gemini分析 → 下書き作成 → カレンダー登録
  const results = [];
  for (const emailData of emails) {
    try {
      const result = processEmail_(apiKey, emailData);
      results.push(result);
    } catch (e) {
      Logger.log(`エラー (${emailData.subject}): ${e.message}`);
      results.push({ ...emailData, error: e.message });
    }
  }

  // 3. ダイジェストメール送信
  const needsReply = results.filter(r => r.needs_reply);
  const events = results.filter(r => r.has_event);
  Logger.log(`結果: 要返信 ${needsReply.length} 件, スケジュール ${events.length} 件`);

  if (results.length > 0) {
    sendDigestEmail_(myEmail, results);
  }

  Logger.log("実行完了");
}

// ============================================================
// メール取得
// ============================================================
function fetchUnprocessedEmails_(myEmail) {
  // 処理済みラベルを取得（なければ作成）
  let label = GmailApp.getUserLabelByName(CONFIG.PROCESSED_LABEL);
  if (!label) {
    label = GmailApp.createLabel(CONFIG.PROCESSED_LABEL);
  }

  // 検索クエリ: 受信トレイ、未処理、自分が送ったもの以外
  const afterDate = new Date();
  afterDate.setDate(afterDate.getDate() - CONFIG.SEARCH_DAYS);
  const dateStr = Utilities.formatDate(afterDate, CONFIG.TIMEZONE, "yyyy/MM/dd");

  const query = `in:inbox after:${dateStr} -from:${myEmail} -label:${CONFIG.PROCESSED_LABEL}`;
  const threads = GmailApp.search(query, 0, CONFIG.MAX_EMAILS);

  const emails = [];
  for (const thread of threads) {
    const messages = thread.getMessages();
    // スレッドの最新メッセージを対象
    const msg = messages[messages.length - 1];

    emails.push({
      thread: thread,
      messageId: msg.getId(),
      subject: msg.getSubject() || "(件名なし)",
      sender: extractSenderName_(msg.getFrom()),
      senderEmail: extractSenderEmail_(msg.getFrom()),
      body: msg.getPlainBody() || stripHtml_(msg.getBody()),
      receivedAt: msg.getDate(),
      gmailMessage: msg,
    });

    // 処理済みラベル付与
    thread.addLabel(label);
  }

  return emails;
}

// ============================================================
// メール1件の処理パイプライン
// ============================================================
function processEmail_(apiKey, emailData) {
  // 1. Geminiで分類
  const classification = classifyEmail_(apiKey, emailData);
  const result = {
    ...emailData,
    needs_reply: classification.needs_reply || false,
    reply_reason: classification.reason || "",
    category: classification.category || "other",
    urgency: classification.urgency || "low",
    has_event: classification.has_event || false,
    event: classification.event || null,
    draft_created: false,
    event_created: false,
  };

  // 2. 要返信なら下書き生成
  if (result.needs_reply) {
    const draftBody = generateDraftReply_(apiKey, emailData, result.reply_reason);
    if (draftBody) {
      createGmailDraft_(emailData, draftBody);
      result.draft_body = draftBody;
      result.draft_created = true;
      Logger.log(`  下書き作成: ${emailData.subject.substring(0, 40)}`);
    }
  }

  // 3. スケジュール検出時はカレンダー仮登録
  if (result.has_event && result.event && result.event.date) {
    const eventUrl = createTentativeEvent_(result.event, emailData);
    if (eventUrl) {
      result.event_url = eventUrl;
      result.event_created = true;
      Logger.log(`  カレンダー仮登録: ${result.event.title || emailData.subject}`);
    }
  }

  return result;
}

// ============================================================
// Gemini API: メール分類
// ============================================================
function classifyEmail_(apiKey, emailData) {
  const bodyTruncated = (emailData.body || "").substring(0, 2000);

  const prompt = `あなたはメール分析アシスタントです。
以下のメールを分析し、「返信が必要かどうか」を判定してください。

## 判定基準
- 質問・依頼・確認要求 → 返信必要
- ニュースレター・通知・広告・自動送信 → 返信不要
- CC/BCCで参考送付されただけ → 返信不要
- 挨拶・お礼のみで返信不要のもの → 返信不要

## メール情報
- 件名: ${emailData.subject}
- 差出人: ${emailData.sender} <${emailData.senderEmail}>
- 本文:
${bodyTruncated}

## スケジュール検出
- メールに会議・打ち合わせ・イベント・予定・締切の情報が含まれる場合、has_event: true とし event オブジェクトを出力
- 日時が明示されていない場合は has_event: false
- event.date は YYYY-MM-DD 形式、start_time/end_time は HH:MM 形式 (24時間)
- 終了時刻が不明な場合は開始時刻の1時間後をデフォルトとする
- 時刻が不明な場合は終日イベント（start_time/end_time を null に）

## 出力形式（JSON厳守）
\`\`\`json
{
  "needs_reply": true,
  "reason": "判定理由を1-2文で",
  "urgency": "high/medium/low",
  "category": "question/request/confirmation/newsletter/notification/other",
  "has_event": true,
  "event": {
    "title": "イベント名",
    "date": "YYYY-MM-DD",
    "start_time": "HH:MM or null",
    "end_time": "HH:MM or null",
    "location": "場所 or null",
    "description": "概要"
  }
}
\`\`\`

has_event が false の場合、event は null としてください。
JSONのみ出力してください。`;

  const response = callGeminiApi_(apiKey, prompt, 0.1, 500);
  return parseJsonResponse_(response);
}

// ============================================================
// Gemini API: 返信文案生成
// ============================================================
function generateDraftReply_(apiKey, emailData, reason) {
  const bodyTruncated = (emailData.body || "").substring(0, 2000);

  const prompt = `あなたはメール返信アシスタントです。
以下のメールに対する返信文案を日本語で作成してください。

## 方針
- ビジネスメールとして適切な敬語を使用
- 簡潔かつ丁寧に
- 相手の要求に対して具体的に応答
- 署名は不要（ユーザーが後で追加する）

## 元メール
- 件名: ${emailData.subject}
- 差出人: ${emailData.sender}
- 本文:
${bodyTruncated}

## 判定理由
${reason}

返信文案のみを出力してください（件名不要、本文のみ）。`;

  return callGeminiApi_(apiKey, prompt, 0.7, 1000);
}

// ============================================================
// Gemini API 共通呼び出し
// ============================================================
function callGeminiApi_(apiKey, prompt, temperature, maxTokens) {
  const url = `https://generativelanguage.googleapis.com/v1beta/models/${CONFIG.GEMINI_MODEL}:generateContent?key=${apiKey}`;

  const payload = {
    contents: [{ parts: [{ text: prompt }] }],
    generationConfig: {
      temperature: temperature,
      maxOutputTokens: maxTokens,
    },
  };

  const options = {
    method: "post",
    contentType: "application/json",
    payload: JSON.stringify(payload),
    muteHttpExceptions: true,
  };

  const response = UrlFetchApp.fetch(url, options);
  const json = JSON.parse(response.getContentText());

  if (json.error) {
    throw new Error(`Gemini API: ${json.error.message}`);
  }

  return json.candidates[0].content.parts[0].text.trim();
}

// ============================================================
// Gmail下書き作成（スレッドに紐づく返信下書き）
// ============================================================
function createGmailDraft_(emailData, draftBody) {
  let subject = emailData.subject;
  if (!/^Re:\s*/i.test(subject)) {
    subject = `Re: ${subject}`;
  }

  // エイリアス設定があれば送信元をM365アドレスにする
  const sendAsEmail = PropertiesService.getScriptProperties().getProperty("SEND_AS_EMAIL");

  const options = {
    replyTo: emailData.senderEmail,
    ...(emailData.gmailMessage ? { inReplyTo: emailData.messageId } : {}),
    ...(sendAsEmail ? { from: sendAsEmail } : {}),
  };

  GmailApp.createDraft(emailData.senderEmail, subject, draftBody, options);
}

// ============================================================
// カレンダー仮登録
// ============================================================
function createTentativeEvent_(eventInfo, emailData) {
  const calendar = CalendarApp.getDefaultCalendar();
  const title = `${CONFIG.TENTATIVE_PREFIX}${eventInfo.title || emailData.subject}`;

  const description =
    `${eventInfo.description || ""}\n\n` +
    `--- 元メール ---\n` +
    `件名: ${emailData.subject}\n` +
    `差出人: ${emailData.sender} <${emailData.senderEmail}>`;

  let event;

  if (eventInfo.start_time && eventInfo.date) {
    // 時刻付きイベント
    const startDt = new Date(`${eventInfo.date}T${eventInfo.start_time}:00`);
    let endDt;
    if (eventInfo.end_time) {
      endDt = new Date(`${eventInfo.date}T${eventInfo.end_time}:00`);
    } else {
      endDt = new Date(startDt.getTime() + 60 * 60 * 1000); // +1時間
    }
    event = calendar.createEvent(title, startDt, endDt, {
      description: description.trim(),
      location: eventInfo.location || "",
    });
  } else if (eventInfo.date) {
    // 終日イベント
    const dateDt = new Date(`${eventInfo.date}T00:00:00`);
    event = calendar.createAllDayEvent(title, dateDt, {
      description: description.trim(),
      location: eventInfo.location || "",
    });
  } else {
    return null;
  }

  // 仮予定の色を設定（黄色 = "5" → 仮であることを視覚的に示す）
  event.setColor("5");

  return event.getId();
}

// ============================================================
// ダイジェストメール送信
// ============================================================
function sendDigestEmail_(toEmail, results) {
  const today = Utilities.formatDate(new Date(), CONFIG.TIMEZONE, "yyyy-MM-dd");
  const needsReply = results.filter(r => r.needs_reply);
  const noReply = results.filter(r => !r.needs_reply && !r.error);
  const events = results.filter(r => r.event_created);

  let html = `
<div style="font-family: sans-serif; max-width: 600px; margin: 0 auto;">
<h2>Mail Reminder - 本日のダイジェスト</h2>
<p style="color: #666;">
  ${escapeHtml_(today)} |
  全${results.length}件 |
  <span style="color: #ef4444;">要返信 ${needsReply.length}件</span>
</p>
<hr style="border: 1px solid #eee;">`;

  // 要返信セクション
  if (needsReply.length > 0) {
    html += `<h3 style="color: #ef4444;">要返信</h3>`;
    for (const r of needsReply) {
      let draftSection = "";
      if (r.draft_body) {
        draftSection = `
<div style="background: #fff; border: 1px solid #ddd; padding: 10px; margin-top: 8px; font-size: 0.9em; white-space: pre-wrap;">${escapeHtml_(r.draft_body)}</div>
<p style="font-size: 0.85em; color: #2563eb;">↑ Gmailの下書きに保存済み。確認して送信してください。</p>`;
      }
      html += `
<div style="border-left: 3px solid #ef4444; padding: 8px 16px; margin: 12px 0; background: #fef2f2;">
  <strong>${escapeHtml_(r.subject)}</strong><br>
  <span style="color: #666; font-size: 0.9em;">${escapeHtml_(r.sender)} &lt;${escapeHtml_(r.senderEmail)}&gt;</span><br>
  <span style="color: #888; font-size: 0.85em;">理由: ${escapeHtml_(r.reply_reason)}</span><br>
  <span style="color: #888; font-size: 0.85em;">緊急度: ${escapeHtml_(r.urgency)} | 分類: ${escapeHtml_(r.category)}</span>
  ${draftSection}
</div>`;
    }
  }

  // スケジュールセクション
  if (events.length > 0) {
    html += `<h3 style="color: #2563eb;">スケジュール仮登録 (${events.length}件)</h3>`;
    for (const r of events) {
      const ev = r.event;
      const timeStr = ev.start_time ? `${ev.start_time}-${ev.end_time || ""}` : "終日";
      html += `
<div style="border-left: 3px solid #eab308; padding: 8px 16px; margin: 12px 0; background: #fefce8;">
  <strong>${CONFIG.TENTATIVE_PREFIX}${escapeHtml_(ev.title || r.subject)}</strong><br>
  <span style="color: #666; font-size: 0.9em;">${escapeHtml_(ev.date)} ${escapeHtml_(timeStr)}</span>
  ${ev.location ? ` | ${escapeHtml_(ev.location)}` : ""}<br>
  <span style="color: #999; font-size: 0.85em;">Googleカレンダーに仮登録済み（黄色）。確定したらタイトルの【仮】を削除してください。</span>
</div>`;
    }
  }

  // 返信不要セクション
  if (noReply.length > 0) {
    html += `<h3 style="color: #22c55e;">返信不要 (${noReply.length}件)</h3>`;
    html += `<ul style="color: #666; font-size: 0.9em;">`;
    for (const r of noReply) {
      html += `<li><strong>${escapeHtml_(r.subject)}</strong> - ${escapeHtml_(r.sender)} (${escapeHtml_(r.reply_reason)})</li>`;
    }
    html += `</ul>`;
  }

  html += `
<hr style="border: 1px solid #eee;">
<p style="color: #999; font-size: 0.8em;">Powered by Gemini + Google Apps Script</p>
</div>`;

  const subject = `Mail Reminder: 要返信${needsReply.length}件 / スケジュール${events.length}件 (${today})`;
  GmailApp.sendEmail(toEmail, subject, "", { htmlBody: html });
  Logger.log(`ダイジェストメール送信完了 → ${toEmail}`);
}

// ============================================================
// トリガー設定（初回1回だけ実行）
// ============================================================
function setupTrigger() {
  // 既存トリガー削除
  const triggers = ScriptApp.getProjectTriggers();
  for (const trigger of triggers) {
    if (trigger.getHandlerFunction() === "main") {
      ScriptApp.deleteTrigger(trigger);
    }
  }

  // 毎日朝9時に実行
  ScriptApp.newTrigger("main")
    .timeBased()
    .atHour(9)
    .everyDays(1)
    .inTimezone(CONFIG.TIMEZONE)
    .create();

  Logger.log("トリガー設定完了: 毎日 9:00 (Asia/Tokyo)");
}

// ============================================================
// ユーティリティ
// ============================================================
function extractSenderName_(fromHeader) {
  const match = fromHeader.match(/^"?(.+?)"?\s*<.+>$/);
  return match ? match[1].trim().replace(/^"|"$/g, "") : fromHeader;
}

function extractSenderEmail_(fromHeader) {
  const match = fromHeader.match(/<(.+?)>/);
  return match ? match[1] : fromHeader;
}

function stripHtml_(html) {
  return (html || "")
    .replace(/<[^>]+>/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .substring(0, 5000);
}

function escapeHtml_(text) {
  return (text || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function parseJsonResponse_(text) {
  // コードブロック除去
  let cleaned = text.trim();
  if (cleaned.startsWith("```")) {
    const lines = cleaned.split("\n");
    cleaned = lines
      .filter(l => !l.trim().startsWith("```"))
      .join("\n");
  }

  try {
    return JSON.parse(cleaned);
  } catch (e) {
    // JSON部分を抽出
    const match = cleaned.match(/\{[\s\S]*\}/);
    if (match) {
      try {
        return JSON.parse(match[0]);
      } catch (e2) {
        // パース失敗時のフォールバック
      }
    }
    Logger.log(`JSON parse failed: ${cleaned.substring(0, 200)}`);
    return {
      needs_reply: false,
      reason: "解析エラー",
      urgency: "low",
      category: "other",
      has_event: false,
    };
  }
}
