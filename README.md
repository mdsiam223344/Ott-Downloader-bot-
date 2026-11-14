# Telegram Video Link Bot (Only Render)

এই বট শুধু অনুমোদিত **Direct Video URL** থেকে ভিডিও নিয়ে Telegram-এ পাঠায়।

## কী কী কাজ করবে
- `/start`, `/help`, `/status`
- Direct MP4/MOV/M4V/WebM URL গ্রহণ
- URL ও public host যাচাই
- সর্বোচ্চ 45 MB পর্যন্ত ভিডিও ডাউনলোড ও Telegram-এ পাঠানো
- SQLite-এ download history
- Admin-এর `/stats` কমান্ড
- Render-এর health endpoint `/health`

## যা করবে না
- `jiocinemaus.com/episodes/...`-এর মতো সাধারণ episode webpage থেকে ভিডিও বের করবে না
- DRM, login/subscription wall, encrypted stream বা paywall bypass করবে না
- M3U8/HLS/DASH playlist download করবে না
- কোনো সাইটের অনুমতি ছাড়া কনটেন্ট কপি করবে না

## Render-এ Deploy
1. ZIP extract করে সব ফাইল GitHub repository-তে upload করুন।
2. Render → New → Blueprint নির্বাচন করে repository connect করুন; অথবা Web Service তৈরি করুন।
3. Runtime: Python
4. Build Command: `pip install -r requirements.txt`
5. Start Command: `python bot.py`
6. Environment Variables দিন:
   - `BOT_TOKEN` = @BotFather থেকে পাওয়া bot token
   - `ADMIN_ID` = আপনার Telegram numeric user ID
   - `MAX_FILE_MB` = `45`
   - `DB_PATH` = `downloads.db`
7. Deploy করুন। Render Logs-এ `Bot polling started` দেখলে বট চালু।

## Bot Token ও Admin ID
- Telegram-এ `@BotFather` খুলে `/newbot` দিয়ে bot তৈরি করে token নিন।
- নিজের numeric Telegram ID জানতে `@userinfobot` ব্যবহার করতে পারেন।
- Token কাউকে দেবেন না এবং GitHub-এ commit করবেন না।

## গুরুত্বপূর্ণ Render Free সীমাবদ্ধতা
- Free instance idle হলে sleep করতে পারে; sleep অবস্থায় bot polling সাময়িক বন্ধ থাকবে।
- Free filesystem স্থায়ী নয়। SQLite database restart/redeploy-এ হারিয়ে যেতে পারে। স্থায়ী history দরকার হলে Render Persistent Disk বা managed PostgreSQL ব্যবহার করুন।
- Telegram Bot API-তে upload limit ও Render memory/time limits থাকতে পারে। এই project-এ নিরাপত্তার জন্য ডিফল্ট 45 MB cap রাখা হয়েছে।
- একই bot token দিয়ে একাধিক polling instance চালাবেন না।

## Local test (ঐচ্ছিক)
`pip install -r requirements.txt` করে environment variables সেট করে `python bot.py` চালান।
