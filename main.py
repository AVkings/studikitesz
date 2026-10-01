import logging
import random
import string
import time
import urllib.parse
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# ==============================================================================
# CONFIGURATION
# ==============================================================================
BOT_TOKEN = "8780623348:AAFfxePY9dJiWxkbsI8rne9XXWaNIwTdvjA"
CHANNEL_USERNAME = "@studikitesz"

# Firebase: Studiki (User Profiles)
STUDIKI_API_KEY = "AIzaSyCG2zFEsE5Fr8Vx-5of_PL0xQeP773MNFM"
STUDIKI_PROJECT = "studiki"

# Firebase: Smexgod (Key Minting)
SMEXGOD_API_KEY = "AIzaSyAzxBCRdwK4NIyGwkzBrV9ev_53MJIfsOM"
SMEXGOD_PROJECT = "smexgod"

# Workers
OTP_WORKER = "https://otp-gateway-api.avnishrajurkar6.workers.dev"
PROXY_WORKER = "https://studi-proxy.avnishrajurkar6.workers.dev"
BATCHES_URL = "https://studikitesz.pages.dev/batches.json"

# In-memory OTP session store
PENDING_OTP = {}

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ==============================================================================
# FIREBASE HELPERS
# ==============================================================================
def get_firebase_user(telegram_id: int) -> dict:
    url = f"https://firestore.googleapis.com/v1/projects/{STUDIKI_PROJECT}/databases/(default)/documents/users/{telegram_id}?key={STUDIKI_API_KEY}"
    try:
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            fields = res.json().get("fields", {})
            return {
                "mobile": fields.get("mobile", {}).get("stringValue", ""),
                "verified": fields.get("verified", {}).get("booleanValue", False),
                "token": fields.get("token", {}).get("stringValue", "")
            }
    except Exception as e:
        logger.error(f"Firebase GET error: {e}")
    return None

def save_firebase_user(telegram_id: int, mobile: str, token: str):
    url = f"https://firestore.googleapis.com/v1/projects/{STUDIKI_PROJECT}/databases/(default)/documents/users/{telegram_id}?key={STUDIKI_API_KEY}"
    payload = {
        "fields": {
            "telegramId": {"integerValue": str(telegram_id)},
            "mobile": {"stringValue": mobile},
            "verified": {"booleanValue": True},
            "token": {"stringValue": token},
            "updatedAt": {"integerValue": str(int(time.time() * 1000))}
        }
    }
    try:
        res = requests.patch(url, json=payload, timeout=5)
        return res.status_code in [200, 204]
    except Exception as e:
        logger.error(f"Firebase PATCH error: {e}")
    return False

def mint_play_key() -> tuple:
    key = f"SB-{''.join(random.choices(string.digits + string.ascii_lowercase, k=4)).upper()}-{''.join(random.choices(string.digits + string.ascii_lowercase, k=4)).upper()}"
    device_id = f"dev_{''.join(random.choices(string.digits + string.ascii_lowercase, k=6))}"
    now_ms = int(time.time() * 1000)
    payload = {
        "fields": {
            "createdAt": {"integerValue": str(now_ms)},
            "expiresAt": {"integerValue": str(now_ms + 2 * 24 * 60 * 60 * 1000)},
            "status": {"stringValue": "active"},
            "maxDevices": {"integerValue": "1"},
            "registeredDevices": {"arrayValue": {"values": [{"stringValue": device_id}]}}
        }
    }
    url = f"https://firestore.googleapis.com/v1/projects/{SMEXGOD_PROJECT}/databases/(default)/documents/valid_keys?key={SMEXGOD_API_KEY}&documentId={key}"
    try:
        res = requests.post(url, json=payload, timeout=5)
        if res.status_code in [200, 201]:
            return key, device_id
    except Exception as e:
        logger.error(f"Key minting error: {e}")
    return None, None

# ==============================================================================
# ACCESS CONTROL
# ==============================================================================
async def check_access(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user_id = update.effective_user.id
    target = update.callback_query if update.callback_query else update.message

    # 1. Check Community
    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        if member.status not in ["member", "administrator", "creator"]:
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("📢 Join Channel", url="https://t.me/studikitesz"),
                InlineKeyboardButton("✅ I Joined", callback_data="retry_access")
            ]])
            text = "🔒 <b>Community Access Required</b>\n\nYou must be a member of @studikitesz to use this bot."
            if update.callback_query:
                await target.edit_message_text(text, reply_markup=kb, parse_mode="HTML")
            else:
                await target.reply_text(text, reply_markup=kb, parse_mode="HTML")
            return False
    except Exception:
        await target.reply_text("⚠️ Bot cannot verify channel. Ensure the bot is an Admin in @studikitesz.")
        return False

    # 2. Check Login
    user_data = get_firebase_user(user_id)
    if not user_data or not user_data.get("verified"):
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🌐 Open Web Login", url="https://studikitesz.pages.dev/login.html")]])
        text = "🔑 <b>Login Required</b>\n\nYou are a community member, but you must log in.\n\nUse <code>/login &lt;phone&gt;</code> or click below."
        if update.callback_query:
            await target.edit_message_text(text, reply_markup=kb, parse_mode="HTML")
        else:
            await target.reply_text(text, reply_markup=kb, parse_mode="HTML")
        return False

    return True

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📚 Browse Batches", callback_data="menu_batches")],
        [InlineKeyboardButton("👤 My Profile", callback_data="menu_profile")]
    ])
    text = "🎉 <b>Welcome to StudiKitEZ!</b>\n\nYou are verified and logged in. Choose an option:"
    if update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")
    else:
        await update.message.reply_text(text, reply_markup=kb, parse_mode="HTML")

# ==============================================================================
# COMMANDS
# ==============================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_access(update, context):
        await show_main_menu(update, context)

async def vme_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        if member.status in ["member", "administrator", "creator"]:
            await update.message.reply_text("✅ <b>Verified!</b> You are a member of @studikitesz.", parse_mode="HTML")
            user_data = get_firebase_user(user_id)
            if user_data and user_data.get("verified"):
                await update.message.reply_text("✅ You are also logged in. Opening main menu...")
                await show_main_menu(update, context)
            else:
                kb = InlineKeyboardMarkup([[InlineKeyboardButton("🌐 Open Web Login", url="https://studikitesz.pages.dev/login.html")]])
                await update.message.reply_text("🔑 Now, please log in:\nUse <code>/login &lt;phone&gt;</code> or click below.", reply_markup=kb, parse_mode="HTML")
        else:
            await update.message.reply_text(f"❌ You are not a member of {CHANNEL_USERNAME}. Please join first.")
    except Exception:
        await update.message.reply_text("⚠️ Cannot verify. Make sure the bot is an admin in the channel.")

async def login_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context): return
    if not context.args:
        await update.message.reply_text("Usage: <code>/login &lt;10-digit-phone&gt;</code>", parse_mode="HTML"); return
    
    mobile = context.args[0].strip()
    if len(mobile) != 10 or not mobile.isdigit():
        await update.message.reply_text("❌ Invalid phone number. Must be exactly 10 digits."); return

    user_id = update.effective_user.id
    await update.message.reply_text("⏳ Requesting OTP...")
    
    try:
        res = requests.post(f"{OTP_WORKER}/api/otp/send", json={"mobile": mobile, "provider": "nexttoppers", "channel": "sms"}, timeout=10)
        data = res.json()
        if data.get("success"):
            PENDING_OTP[user_id] = {"session_id": data["session_id"], "mobile": mobile}
            await update.message.reply_text(f"✅ OTP sent to {mobile}!\n\nUse <code>/verify &lt;6-digit-otp&gt;</code> to complete.", parse_mode="HTML")
        else:
            await update.message.reply_text(f"❌ Failed: {data.get('error', 'Unknown')}")
    except Exception as e:
        await update.message.reply_text(f"❌ Network error: {e}")

async def verify_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await check_access(update, context): return
    if user_id not in PENDING_OTP:
        await update.message.reply_text("❌ No pending OTP. Use <code>/login &lt;phone&gt;</code> first.", parse_mode="HTML"); return
    if not context.args:
        await update.message.reply_text("Usage: <code>/verify &lt;6-digit-otp&gt;</code>", parse_mode="HTML"); return
        
    otp = context.args[0].strip()
    session = PENDING_OTP.pop(user_id)
    
    await update.message.reply_text("⏳ Verifying OTP...")
    try:
        res = requests.post(f"{OTP_WORKER}/api/otp/verify", json={"session_id": session["session_id"], "otp": otp}, timeout=10)
        data = res.json()
        if data.get("success"):
            token = data.get("data", {}).get("token") or data.get("token") or "verified"
            if save_firebase_user(user_id, session["mobile"], token):
                await update.message.reply_text("🎉 <b>Login Successful!</b> Profile saved to Firebase. Opening menu...", parse_mode="HTML")
                await show_main_menu(update, context)
            else:
                await update.message.reply_text("⚠️ OTP verified, but failed to save to Firebase.")
        else:
            await update.message.reply_text(f"❌ Verification failed: {data.get('error', 'Invalid OTP')}")
    except Exception as e:
        await update.message.reply_text(f"❌ Network error: {e}")

# ==============================================================================
# CALLBACKS (Courses & Content)
# ==============================================================================
async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "retry_access":
        await query.edit_message_text("⏳ Checking...")
        if await check_access(update, context):
            await show_main_menu(update, context)
        return

    if not await check_access(update, context): return

    user_id = query.from_user.id

    if query.data == "menu_batches":
        await query.edit_message_text("⏳ Fetching batches...")
        try:
            res = requests.get(BATCHES_URL, timeout=10)
            data = res.json()
            batches = data.get("new", []) + data.get("old", [])
            if not batches:
                await query.edit_message_text("No batches found.")
                return
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"📦 {b.get('title', 'Unknown')}", callback_data=f"course:{b.get('id')}")] for b in batches[:10]
            ])
            kb.inline_keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="menu_main")])
            await query.edit_message_text("📚 <b>Select a batch:</b>", reply_markup=kb, parse_mode="HTML")
        except Exception as e:
            await query.edit_message_text(f"❌ Error: {e}")

    elif query.data.startswith("course:"):
        course_id = query.data.split(":")[1]
        await query.edit_message_text("⏳ Loading folders...")
        try:
            url = f"{PROXY_WORKER}/nt/nig?content={course_id}&folder=0"
            res = requests.get(url, timeout=10)
            data = res.json()
            if data.get("success") and data.get("data"):
                kb = InlineKeyboardMarkup([
                    [InlineKeyboardButton(f"📁 {item.get('title', 'Folder')}", callback_data=f"folder:{course_id}:{item.get('entity_id')}")] 
                    for item in data["data"] if item.get("type") == "folder"
                ])
                kb.inline_keyboard.append([InlineKeyboardButton("🔙 Back", callback_data="menu_batches")])
                await query.edit_message_text(f"📂 <b>Course {course_id}</b>", reply_markup=kb, parse_mode="HTML")
            else:
                await query.edit_message_text("⚠️ No folders found or API error.")
        except Exception as e:
            await query.edit_message_text(f"❌ Error: {e}")

    elif query.data.startswith("folder:"):
        _, course_id, folder_id = query.data.split(":")
        await query.edit_message_text("⏳ Loading files...")
        try:
            url = f"{PROXY_WORKER}/nt/nig?content={course_id}&folder={folder_id}"
            res = requests.get(url, timeout=10)
            data = res.json()
            if data.get("success") and data.get("data"):
                kb = []
                for item in data["data"]:
                    if item.get("type") == "folder":
                        kb.append([InlineKeyboardButton(f"📁 {item.get('title')}", callback_data=f"folder:{course_id}:{item.get('entity_id')}")])
                    elif item.get("type") == "file":
                        kb.append([InlineKeyboardButton(f"🎬 {item.get('title')}", callback_data=f"file:{course_id}:{item.get('entity_id')}")])
                kb.append([InlineKeyboardButton("🔙 Back", callback_data=f"course:{course_id}")])
                await query.edit_message_text("📂 <b>Folder Contents</b>", reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
            else:
                await query.edit_message_text("⚠️ No files found or API error.")
        except Exception as e:
            await query.edit_message_text(f"❌ Error: {e}")

    elif query.data.startswith("file:"):
        _, course_id, content_id = query.data.split(":")
        await query.edit_message_text("⏳ Minting key and fetching content...")
        
        # 1. Mint Key
        key, device_id = mint_play_key()
        if not key:
            await query.edit_message_text("❌ Failed to generate playback key.")
            return

        # 2. Fetch Content
        try:
            url = f"{PROXY_WORKER}/nt/play?content_id={content_id}&course_id={course_id}&key={key}&device_id={device_id}"
            res = requests.get(url, timeout=15)
            data = res.json()
            
            if data.get("decryptedData") and data["decryptedData"].get("file_url"):
                file_url = data["decryptedData"]["file_url"]
                title = data["decryptedData"].get("title", "Content")
                
                # 3. Update Firebase Status (Optional: log that user accessed this)
                # (You can expand this to save progress)
                
                kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Folder", callback_data=f"folder:{course_id}:{content_id}")]]) # Simplified back
                await query.edit_message_text(
                    f"🎉 <b>{title}</b>\n\n<a href='{file_url}'>▶️ Click here to Open/Play</a>\n\n<i>Tip: If it's an .m3u8 link, use VLC Player.</i>",
                    reply_markup=kb, parse_mode="HTML", disable_web_page_preview=True
                )
            else:
                await query.edit_message_text(f"❌ API rejected key or no content found. (Status: {res.status_code})")
        except Exception as e:
            await query.edit_message_text(f"❌ Fetch error: {e}")

    elif query.data == "menu_profile":
        user_data = get_firebase_user(user_id)
        mobile = user_data.get("mobile", "Unknown") if user_data else "Unknown"
        await query.edit_message_text(f"👤 <b>My Profile</b>\n\nTelegram ID: <code>{user_id}</code>\nMobile: <code>{mobile}</code>\nStatus: ✅ Verified & Logged In", parse_mode="HTML")
        
    elif query.data == "menu_main":
        await show_main_menu(update, context)

# ==============================================================================
# MAIN EXECUTION
# ==============================================================================
def main():
    logger.info("Starting StudiKitEZ Bot (Polling Mode)...")
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("vme", vme_command))
    app.add_handler(CommandHandler("login", login_command))
    app.add_handler(CommandHandler("verify", verify_command))
    app.add_handler(CallbackQueryHandler(button_click))

    logger.info("✅ Bot is running and polling for updates!")
    # drop_pending_updates=True prevents spamming old messages on restart
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
