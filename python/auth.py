"""Google Calendar OAuth2 認証"""
import json
import logging
import os

import config

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
TOKEN_PATH = os.path.join(config.DATA_DIR, "calendar_token.json")
CREDENTIALS_PATH = os.path.join(os.path.dirname(__file__), "credentials.json")


def get_calendar_credentials():
    """保存済みトークンをロード。期限切れなら自動リフレッシュ。"""
    from google.oauth2.credentials import Credentials

    if not os.path.exists(TOKEN_PATH):
        return None

    creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if creds and creds.expired and creds.refresh_token:
        from google.auth.transport.requests import Request
        creds.refresh(Request())
        _save_token(creds)

    return creds if creds and creds.valid else None


def setup_calendar_auth():
    """OAuth2 セットアップ（初回のみ、ブラウザ認証）"""
    from google_auth_oauthlib.flow import InstalledAppFlow

    if not os.path.exists(CREDENTIALS_PATH):
        logger.error(
            f"credentials.json が見つかりません: {CREDENTIALS_PATH}\n"
            "Google Cloud Console から OAuth2 クライアント ID をダウンロードし、\n"
            f"{CREDENTIALS_PATH} に配置してください。"
        )
        return False

    os.makedirs(config.DATA_DIR, exist_ok=True)

    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)

    try:
        creds = flow.run_local_server(port=0)
    except Exception:
        logger.info("ブラウザ認証に失敗しました。コンソール認証にフォールバックします。")
        creds = flow.run_console()

    _save_token(creds)
    logger.info(f"認証完了。トークン保存先: {TOKEN_PATH}")
    return True


def _save_token(creds):
    """トークンをファイルに保存"""
    os.makedirs(config.DATA_DIR, exist_ok=True)
    with open(TOKEN_PATH, "w") as f:
        f.write(creds.to_json())
