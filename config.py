"""設定管理"""
import os
from dotenv import load_dotenv

load_dotenv()

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
DATA_DIR = os.path.expanduser(os.getenv("MAILAPP_DATA_DIR", "~/.mailapp"))
