import requests
from ..config import settings
from ..logger import get_logger
log=get_logger(__name__)

def _escape_md(s:str)->str:
    # protège Telegram MarkdownV2
    for ch in r"_*[]()~`>#+-=|{}.!":
        s=s.replace(ch, f"\\{ch}")
    return s

def send_alert(title:str, body:str, emoji:str="🔔"):
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_CHAT_ID:
        return
    text=f"*{_escape_md(emoji+' '+title)}*\n{_escape_md(body)}"
    url=f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        r=requests.post(url,json={"chat_id":settings.TELEGRAM_CHAT_ID,"text":text,"parse_mode":"MarkdownV2"},timeout=10)
        r.raise_for_status()
    except Exception as e:
        log.error("Telegram send failed: %s",e)
