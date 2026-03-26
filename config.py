"""設定管理（マルチプロファイル対応）"""
import os
import sys
from dotenv import load_dotenv

# --profile 引数を先読み（argparse より前に設定を読む必要がある）
PROFILE = "default"
for i, arg in enumerate(sys.argv):
    if arg == "--profile" and i + 1 < len(sys.argv):
        PROFILE = sys.argv[i + 1]
        break

# プロファイル別の .env を読み込み
_base_dir = os.path.dirname(os.path.abspath(__file__))
if PROFILE != "default":
    _env_path = os.path.join(_base_dir, f".env.{PROFILE}")
else:
    _env_path = os.path.join(_base_dir, ".env")

load_dotenv(_env_path)

# Gemini
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.1-flash-lite-preview")

# Email
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS", "")
EMAIL_APP_PASSWORD = os.getenv("EMAIL_APP_PASSWORD", "")
IMAP_SERVER = os.getenv("IMAP_SERVER", "imap.gmail.com")
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))

# App
MAX_EMAILS = int(os.getenv("MAX_EMAILS", "50"))
REPLY_ALERT_HOURS = int(os.getenv("REPLY_ALERT_HOURS", "48"))

# プロファイル別データディレクトリ
if PROFILE != "default":
    DATA_DIR = os.path.expanduser(
        os.getenv("MAILAPP_DATA_DIR", f"~/.mailapp/{PROFILE}")
    )
else:
    DATA_DIR = os.path.expanduser(
        os.getenv("MAILAPP_DATA_DIR", "~/.mailapp")
    )
