# Mail Reminder

受信メールの返信要否をGeminiが自動判定し、返信下書き＆カレンダー仮登録を毎朝自動実行。

## アーキテクチャ

```
Gmail受信トレイ → Gemini API分析 → 返信下書き自動作成 / カレンダー仮登録 → ダイジェストメール
```

**Google Apps Script (GAS)** で動作。認証設定不要（Gemini APIキーのみ）。デプロイ不要。

**Human-in-the-loop**: 自動返信なし。下書きを確認して送信ボタンを押すだけ。

## 機能

| 機能 | 説明 |
|------|------|
| 要返信判定 | Geminiがメールを分析し、返信要否・緊急度・分類を判定 |
| 返信文案生成 | 要返信メールに対しビジネス敬語の返信案を自動生成 |
| 下書き保存 | 返信案を元メールのスレッドに紐付けて下書きに保存 |
| スケジュール検出 | メール内の会議・イベント情報をGeminiが抽出 |
| カレンダー仮登録 | 検出したスケジュールを【仮】付き・黄色でGoogleカレンダーに登録 |
| ダイジェストメール | 全結果をHTMLメールで自分宛に送信 |
| 重複防止 | 処理済みメールにラベルを付与し、二重処理を防止 |

## セットアップ（3ステップ）

### 1. GASプロジェクト作成

1. [Google Apps Script](https://script.google.com) を開く
2. 新しいプロジェクトを作成
3. `gas/MailReminder.gs` の内容を貼り付け

### 2. Gemini APIキー設定

1. [Google AI Studio](https://ai.google.dev/) でAPIキーを取得
2. GASエディタ左の **歯車アイコン（プロジェクトの設定）** → **スクリプトプロパティ**
3. 以下を追加:

| プロパティ | 値 |
|---|---|
| `GEMINI_API_KEY` | 取得したAPIキー |
| `SEND_AS_EMAIL` | （任意）M365エイリアスのアドレス |

### 3. トリガー設定

GASエディタ上部で `setupTrigger` を選択 → 実行

毎朝9時に自動実行されます。

## 日常のUX

```
毎朝9時（自動）
  ↓
Gmailの下書きに返信文案が入っている → 確認して送信ボタン
  ↓
カレンダーに黄色の【仮】予定が入っている → 確定したら【仮】を消す
  ↓
ダイジェストメールで全体を把握
```

## M365 Outlookユーザーの場合

Outlookのメールを扱う場合は、以下の構成で対応:

1. **Outlook → Gmail転送**: M365の設定で全メールをGmailに自動転送
2. **Gmailエイリアス**: GmailからM365アドレスとして送信できるように設定
3. GASが転送されたメールを分析・下書き作成

エイリアス設定の詳細は [`gas/M365_ALIAS_SETUP.md`](gas/M365_ALIAS_SETUP.md) を参照。

## Gemini判定基準

| 判定 | 条件 |
|------|------|
| 要返信 | 質問・依頼・確認要求 |
| 不要 | ニュースレター・通知・広告・自動送信・CC参考送付 |

要返信メールには緊急度(high/medium/low)と分類(question/request/confirmation等)を付与。
スケジュール情報(会議・イベント等)が含まれるメールは自動検出し、カレンダーに仮登録。

## 設定値

`gas/MailReminder.gs` 内の `CONFIG` オブジェクトで調整可能:

| 設定 | デフォルト | 説明 |
|------|-----------|------|
| `GEMINI_MODEL` | `gemini-3.1-flash-lite-preview` | 使用するGeminiモデル |
| `SEARCH_DAYS` | `1` | 過去何日分のメールを対象にするか |
| `MAX_EMAILS` | `50` | 1回の実行で処理する最大メール数 |
| `PROCESSED_LABEL` | `MailReminder/処理済` | 重複防止用のGmailラベル名 |
| `TENTATIVE_PREFIX` | `【仮】` | カレンダー仮登録時のタイトルプレフィックス |

## ファイル構成

```
mailapp/
├── README.md
├── gas/
│   ├── MailReminder.gs        # GAS本体（コピペで動く）
│   └── M365_ALIAS_SETUP.md   # M365エイリアス設定ガイド
└── python/                    # 参考: 旧Python CLI版
    ├── run.py
    ├── mail_client.py
    ├── gemini_analyzer.py
    ├── models.py
    ├── config.py
    ├── db.py
    ├── auth.py
    ├── calendar_client.py
    └── requirements.txt
```

## 技術スタック

| コンポーネント | 技術 |
|---|---|
| 実行環境 | Google Apps Script |
| AI分析 | Gemini API (Flash Lite) |
| メール操作 | GmailApp（ネイティブ） |
| カレンダー操作 | CalendarApp（ネイティブ） |
| 定期実行 | GAS時間ベーストリガー |
