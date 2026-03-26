# 📬 Mail Reminder - メールリマインダーアプリ

返信が必要なメールをGeminiが自動判定し、返信文案まで提案するアプリ。

## アーキテクチャ

```
Gmail API → メール取得 → Gemini Flash判定（要返信？）→ 返信文案生成 → ダッシュボード表示
```

**Human-in-the-loop**: 自動送信なし。最終送信は必ず人間が行う。

## セットアップ

### 1. Google Cloud Console
1. https://console.cloud.google.com/ でプロジェクト作成
2. Gmail API を有効化
3. OAuth 2.0 クライアントID作成（デスクトップアプリ）
4. `credentials.json` をダウンロードしてプロジェクトルートに配置

### 2. Gemini API Key
1. https://ai.google.dev/ でAPIキー取得

### 3. 環境変数

```bash
cp .env.example .env
# .env を編集:
# GEMINI_API_KEY=your_key_here
```

### 4. インストール・起動

```bash
uv pip install -r requirements.txt
python app.py
# → http://localhost:8501
```

初回起動時にブラウザが開き、Gmail OAuth認証を求められる。

### 5. テスト

エイリアス機能でテスト可能:
```bash
# 自分から自分へテストメール送信
python test_send.py
```

## 機能

- 📥 当日の受信メール一括取得
- 🤖 Gemini Flashによる「要返信/不要」判定
- ✍️ 要返信メールへの返信文案自動生成
- 📊 ダッシュボードで一覧表示
- 📋 ワンクリックで返信文案コピー
- 🔄 手動リフレッシュ / systemdタイマーで定時実行可

## ファイル構成

```
mail-reminder/
├── app.py              # FastAPI メインアプリ
├── gmail_client.py     # Gmail API クライアント
├── gemini_analyzer.py  # Gemini 判定・文案生成
├── models.py           # データモデル (SQLite)
├── config.py           # 設定管理
├── test_send.py        # テストメール送信
├── requirements.txt
├── .env.example
├── templates/
│   └── dashboard.html  # ダッシュボードUI
└── static/
    └── style.css
```
