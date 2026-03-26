# Mail Reminder

受信メールの返信要否をGeminiが自動判定し、返信文案付きのダイジェストメールを1日1回送信するCLIツール。

## アーキテクチャ

```
IMAP(Gmail) → メール取得 → Gemini分析 → 下書き保存 / カレンダー登録 → ダイジェストメール送信
                                ↓
                          SQLite (未返信トラッキング)
```

**Human-in-the-loop**: 自動返信なし。文案はあくまで参考用。下書きフォルダに保存されるだけ。

## 機能

| 機能 | 説明 |
|------|------|
| 要返信判定 | Geminiがメールを分析し、返信要否・緊急度・分類を判定 |
| 返信文案生成 | 要返信メールに対しビジネス敬語の返信案を自動生成 |
| Gmail下書き保存 | 返信案を元メールのスレッドに紐付けて下書きフォルダに保存 |
| スケジュール検出 | メール内の会議・イベント情報をGeminiが抽出 |
| Google Calendar登録 | 検出したスケジュールをGoogleカレンダーに自動登録 |
| 未返信アラート | 一定時間(デフォルト48h)返信がないメールをダイジェストで警告 |
| ダイジェストメール | 全結果をHTMLメールで自分宛に送信 |

## セットアップ

### 1. Gmailアプリパスワード取得

1. Googleアカウントで2段階認証を有効化
2. https://myaccount.google.com/apppasswords でアプリパスワードを生成

### 2. Gemini APIキー取得

https://ai.google.dev/ でAPIキーを取得

### 3. 環境変数

`.env` を作成して以下を設定:

```
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-3.1-flash-lite-preview
EMAIL_ADDRESS=your_email@gmail.com
EMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
IMAP_SERVER=imap.gmail.com
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
MAX_EMAILS=50
REPLY_ALERT_HOURS=48
```

### 4. インストール・実行

```bash
uv venv && uv pip install -r requirements.txt
source .venv/bin/activate
python run.py
```

### 5. Google Calendar連携（任意）

1. [Google Cloud Console](https://console.cloud.google.com/) でプロジェクトを作成
2. **Google Auth Platform** → 同意画面を構成（テストユーザーに自分を追加）
3. **認証情報** → OAuth クライアント ID → **デスクトップ アプリ** で作成
4. JSONをダウンロード → `mailapp/credentials.json` に配置
5. セットアップ実行:

```bash
python run.py setup-calendar
```

## 使い方

```bash
# 今日のメールを分析してダイジェスト送信（下書き保存+カレンダー登録含む）
python run.py

# サブコマンドを明示
python run.py digest

# 日付を指定して実行
python run.py digest --date 2026-03-25

# 分析のみ（メール送信・下書き保存なし）
python run.py digest --dry-run

# 下書き保存をスキップ
python run.py digest --no-drafts

# カレンダー登録をスキップ
python run.py digest --no-calendar

# 未返信チェック（単独実行）
python run.py check-replies

# Google Calendar OAuth2セットアップ
python run.py setup-calendar
```

## Gemini判定基準

| 判定 | 条件 |
|------|------|
| 要返信 | 質問・依頼・確認要求 |
| 不要 | ニュースレター・通知・広告・自動送信・CC参考送付 |

要返信メールには緊急度(high/medium/low)と分類(question/request/confirmation等)も付与される。
スケジュール情報(会議・イベント等)が含まれるメールは自動検出される。

## ファイル構成

```
mailapp/
├── run.py                # CLIエントリポイント (サブコマンド対応)
├── mail_client.py        # IMAP受信 / SMTP送信 / 下書き保存 / 返信チェック
├── gemini_analyzer.py    # Gemini判定・返信文案・スケジュール検出
├── models.py             # Emailデータクラス
├── config.py             # 設定管理(.env読み込み)
├── db.py                 # SQLite 未返信トラッキング
├── auth.py               # Google Calendar OAuth2認証
├── calendar_client.py    # Google Calendar イベント作成
├── credentials.json      # OAuth2クライアントID (git管理外)
├── requirements.txt
├── .env                  # 環境変数 (git管理外)
├── .gitignore
└── README.md

~/.mailapp/
├── calendar_token.json   # OAuth2トークン (自動生成)
└── mailreminder.db       # SQLiteデータベース (自動生成)
```

## 定期実行(cron)

```bash
# 毎朝9時にダイジェスト送信
0 9 * * * cd /home/soy/mailapp && .venv/bin/python run.py

# 夕方に未返信チェック
0 17 * * * cd /home/soy/mailapp && .venv/bin/python run.py check-replies
```
