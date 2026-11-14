import os
import re
import time
import socket
import sqlite3
import tempfile
import threading
import logging
import ipaddress
from urllib.parse import urlparse
from pathlib import Path

import requests
from flask import Flask
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or "0")
MAX_FILE_MB = int(os.getenv("MAX_FILE_MB", "45") or "45")
MAX_FILE_BYTES = MAX_FILE_MB * 1024 * 1024
DB_PATH = os.getenv("DB_PATH", "downloads.db")
PORT = int(os.getenv("PORT", "10000") or "10000")

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO
)
log = logging.getLogger("video-link-bot")

app = Flask(__name__)

@app.get("/")
def home():
    return "Telegram Video Link Bot is running.", 200

@app.get("/health")
def health():
    return {"status": "ok"}, 200


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS downloads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            source_url TEXT NOT NULL,
            filename TEXT,
            size_bytes INTEGER,
            status TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    return conn


def log_download(user_id, url, filename="", size=0, status="started"):
    with db() as conn:
        conn.execute(
            "INSERT INTO downloads(user_id, source_url, filename, size_bytes, status) VALUES(?,?,?,?,?)",
            (user_id, url[:2000], filename, size, status)
        )


def is_public_host(hostname):
    if not hostname:
        return False
    try:
        infos = socket.getaddrinfo(hostname, None)
        addresses = {item[4][0] for item in infos}
        if not addresses:
            return False
        for addr in addresses:
            ip = ipaddress.ip_address(addr.split("%")[0])
            if not ip.is_global:
                return False
        return True
    except Exception:
        return False


def validate_url(url):
    if len(url) > 4000:
        raise ValueError("লিংকটি অনেক বড়।")
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("সঠিক http/https Direct Video URL দিন।")
    if parsed.username or parsed.password:
        raise ValueError("Username/password যুক্ত URL গ্রহণযোগ্য নয়।")
    if not is_public_host(parsed.hostname):
        raise ValueError("এই হোস্টটি নিরাপদ পাবলিক URL হিসেবে যাচাই করা যায়নি।")
    return url.strip()


def download_direct_video(url, destination):
    """Fetch only a direct video response; follow a small number of validated redirects."""
    current = validate_url(url)
    headers = {"User-Agent": "TelegramVideoLinkBot/1.0"}
    for _ in range(5):
        with requests.get(current, headers=headers, stream=True, timeout=(15, 45),
                          allow_redirects=False) as response:
            if response.is_redirect or response.is_permanent_redirect:
                location = response.headers.get("Location")
                if not location:
                    raise ValueError("ভিডিও সার্ভারের redirect URL পাওয়া যায়নি।")
                from urllib.parse import urljoin
                current = validate_url(urljoin(current, location))
                continue

            response.raise_for_status()
            content_type = response.headers.get("Content-Type", "").lower()
            path = urlparse(current).path.lower()
            looks_like_video = (
                content_type.startswith("video/") or
                path.endswith((".mp4", ".m4v", ".mov", ".webm"))
            )
            if not looks_like_video:
                raise ValueError(
                    "এটি Direct Video URL নয়। HTML পেজ, playlist, বা protected stream সমর্থিত নয়।"
                )

            length = response.headers.get("Content-Length")
            if length and int(length) > MAX_FILE_BYTES:
                raise ValueError(f"ফাইলটি {MAX_FILE_MB} MB সীমার চেয়ে বড়।")

            total = 0
            with open(destination, "wb") as output:
                for chunk in response.iter_content(chunk_size=1024 * 256):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > MAX_FILE_BYTES:
                        raise ValueError(f"ফাইলটি {MAX_FILE_MB} MB সীমার চেয়ে বড়।")
                    output.write(chunk)

            if total == 0:
                raise ValueError("ভিডিও ফাইলটি খালি।")
            return total, content_type
    raise ValueError("অনেকগুলো redirect পাওয়া গেছে।")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎬 স্বাগতম!\n\n"
        "অনুমোদিত Direct MP4/MOV/WebM ভিডিও লিংক পাঠান।\n"
        f"সর্বোচ্চ ফাইল সাইজ: {MAX_FILE_MB} MB\n\n"
        "⚠️ শুধু আপনার নিজের বা ডাউনলোডের অনুমতি থাকা ভিডিও ব্যবহার করুন।\n"
        "ওয়েবপেজ লিংক, DRM/protected stream বা paid content ডাউনলোড করা হবে না।\n\n"
        "/help — ব্যবহারবিধি\n/status — বটের অবস্থা"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ব্যবহার:\n"
        "1) সরাসরি ভিডিও ফাইলের URL কপি করুন।\n"
        "2) এখানে URL পাঠান।\n"
        "3) বট যাচাই করে ভিডিওটি Telegram-এ পাঠাবে।\n\n"
        "সমর্থিত: সরাসরি MP4, MOV, M4V, WebM URL\n"
        "অসমর্থিত: সাধারণ episode webpage, M3U8/HLS/DASH playlist, DRM বা login/subscription-locked video."
    )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🟢 Bot is running.")


async def handle_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message or not message.text:
        return

    match = re.search(r"https?://\S+", message.text)
    if not match:
        await message.reply_text("একটি Direct Video URL পাঠান।")
        return

    url = match.group(0).rstrip(".,)>]}")
    user_id = update.effective_user.id
    temp_path = None
    log_download(user_id, url, status="started")

    status_msg = await message.reply_text("⏳ লিংক যাচাই করা হচ্ছে...")
    try:
        validate_url(url)
        await status_msg.edit_text("⬇️ অনুমোদিত Direct Video URL ডাউনলোড করা হচ্ছে...")
        with tempfile.NamedTemporaryFile(prefix="video_", suffix=".mp4", delete=False) as temp:
            temp_path = temp.name

        size, content_type = await __import__("asyncio").to_thread(
            download_direct_video, url, temp_path
        )
        filename = Path(urlparse(url).path).name or "video.mp4"
        if not re.search(r"\.(mp4|m4v|mov|webm)$", filename, re.I):
            filename = "video.mp4"

        await context.bot.send_chat_action(chat_id=message.chat_id, action=ChatAction.UPLOAD_VIDEO)
        with open(temp_path, "rb") as video_file:
            await message.reply_video(
                video=video_file,
                filename=filename,
                caption=f"✅ ভিডিও পাঠানো হয়েছে\n📦 Size: {size / (1024*1024):.2f} MB",
                supports_streaming=True,
                read_timeout=120,
                write_timeout=120,
                connect_timeout=30
            )
        log_download(user_id, url, filename, size, "success")
        await status_msg.delete()
    except Exception as exc:
        log.exception("Video processing failed")
        log_download(user_id, url, status="failed")
        safe_error = str(exc)[:700]
        await status_msg.edit_text(f"❌ কাজটি করা যায়নি:\n{safe_error}")
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not ADMIN_ID or update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("এই কমান্ড শুধু Admin-এর জন্য।")
        return
    with db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM downloads").fetchone()[0]
        success = conn.execute("SELECT COUNT(*) FROM downloads WHERE status='success'").fetchone()[0]
        failed = conn.execute("SELECT COUNT(*) FROM downloads WHERE status='failed'").fetchone()[0]
    await update.message.reply_text(
        f"📊 Download Stats\nTotal: {total}\nSuccess: {success}\nFailed: {failed}"
    )


def run_web():
    app.run(host="0.0.0.0", port=PORT)


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is missing. Render Environment-এ BOT_TOKEN দিন.")
    db()
    threading.Thread(target=run_web, daemon=True).start()
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("stats", admin_stats))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_url))
    log.info("Bot polling started")
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
