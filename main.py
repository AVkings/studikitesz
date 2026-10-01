from fastapi import FastAPI, Request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler
import logging
import os
import requests
import time

# ==============================================================================
# CONFIGURATION
# ==============================================================================
BOT_VERSION = "v4.0.0-Final"
BOT_TOKEN = os.getenv("BOT_TOKEN", "8780623348:AAFfxePY9dJiWxkbsI8rne9XXWaNIwTdvjA")
BOT_USERNAME = os.getenv("BOT_USERNAME", "Studikitez_bot")
CHANNEL_USERNAME = "@studikitesz"

# Firebase (Studiki) - For saving user login data
FIREBASE_API_KEY = "AIzaSyCG2zFEsE5Fr8Vx-5of_PL0xQeP773MNFM"
FIREBASE_PROJECT_ID = "studiki"

# OTP Gateway Worker
OTP_GATEWAY_URL = "https://otp-gateway-api.avnishrajurkar6.workers.dev"

# Temporary storage for OTP sessions (In production, use Redis or Firestore)
# Format: { telegram_user_id: {"session_id": "...", "mobile": "..."} }
PENDING_OTP = {}

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger("studikitez")

app = FastAPI()
application = Application.builder().token(BOT_TOKEN).build()

# ==============================================================================
# FIREBASE HELPERS
# ==============================================================================
def get_firebase_user(telegram_id: int) -> dict:
    url = f"https://firestore.googleapis.com/v1/projects/{FIREBASE_PROJECT_ID}/databases/(default)/documents/users/{telegram_id}?key={FIREBASE_API_KEY}"
    try:
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            data = res.json()
            fields = data.get("fields", {})
            return {
                "mobile": fields.get("mobile", {}).get("stringValue", ""),
                "verified": fields.get("verified", {}).get("booleanValue", False),
                "token": fields.get("token", {}).get("stringValue", "")
            }
    except Exception as e:
        logger.error(f"Firebase GET error: {e}")
    return None

def save_firebase_user(telegram_id: int, mobile: str, token: str):
    url = f"https://firestore.googleapis.com/v1/projects/{FIREBASE_PROJECT_ID}/databases/(default)/documents/users/{telegram_id}?key={FIREBASE_API_KEY}"
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
        if res.status_code in [200, 204]:
            logger.info(f"Successfully saved user {telegram_id} to Firebase")
            return True
        logger.error(f"Firebase PATCH failed: {res.status_code} - {res.text}")
    except Exception as e:
        logger.error(f"Firebase PATCH error: {e}")
    return False

# ==============================================================================
# ACCESS CONTROL (The Core Logic You Requested)
# ==============================================================================
async def check_access(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Returns True if user is in channel AND logged in. Sends prompts and returns False otherwise."""
    user_id = update.effective_user.id
    target = update.callback_query if update.callback_query else update.message

    # 1. Check Community Membership
    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        if member.status not in ["member", "administrator", "creator"]:
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{CHANNEL_USERNAME.replace('@', '')}"),
                InlineKeyboardButton("✅ I Have Joined", callback_data="retry_access")
            ]])
            await target.edit_message_text(
                "🔒 <b>Community Access Required</b>\n\nYou must be a member of @studikitesz to use this bot.",
                reply_markup=kb, parse_mode="HTML"
            ) if update.callback_query else await target.reply_text(
                "🔒 <b>Community Access Required</b>\n\nYou must be a member of @studikitesz to use this bot.",
                reply_markup=kb, parse_mode="HTML"
            )
            return False
    except Exception as e:
        logger.error(f"Channel check failed: {e}")
        await target.edit_message_text("⚠️ Bot cannot verify channel. Ensure the bot is an Admin in @studikitesz.") if update.callback_query else await target.reply_text("⚠️ Bot cannot verify channel. Ensure the bot is an Admin in @studikitesz.")
        return False

    # 2. Check Firebase Login Status
    user_data = get_firebase_user(user_id)
    if not user_data or not user_data.get("verified"):
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("🌐 Open Web Login", url="https://studikitesz.pages.dev/login.html")
        ]])
        msg = "🔑 <b>Login Required</b>\n\nYou are a community member, but you must log in to access content.\n\nUse <code>/login &lt;phone&gt;</code> or click below."
        await target.edit_message_text(msg, reply_markup=kb, parse_mode="HTML") if update.callback_query else await target.reply_text(msg, reply_markup=kb, parse_mode="HTML")
        return False

    return True

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📚 Browse Batches", callback_data="menu_batches")],
        [InlineKeyboardButton("👤 My Profile", callback_data="menu_profile")],
        [InlineKeyboardButton("💎 Premium", callback_data="menu_premium")]
    ])
    msg = "🎉 <b>Welcome to StudiKitEZ!</b>\n\nYou are verified and logged in. Choose an option below:"
    if update.callback_query:
        await update.callback_query.edit_message_text(msg, reply_markup=kb, parse_mode="HTML")
    else:
        await update.message.reply_text(msg, reply_markup=kb, parse_mode="HTML")

# ==============================================================================
# COMMANDS
# ==============================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await check_access(update, context):
        await show_main_menu(update, context)

async def vme_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Explicitly verifies community membership, then checks login."""
    user_id = update.effective_user.id
    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        if member.status in ["member", "administrator", "creator"]:
            await update.message.reply_text("✅ <b>Verified!</b> You are a member of @studikitesz.", parse_mode="HTML")
            # Now check login
            user_data = get_firebase_user(user_id)
            if user_data and user_data.get("verified"):
                await update.message.reply_text("✅ You are also logged in. Opening main menu...")
                await show_main_menu(update, context)
            else:
                kb = InlineKeyboardMarkup([[InlineKeyboardButton("🌐 Open Web Login", url="https://studikitesz.pages.dev/login.html")]])
                await update.message.reply_text("🔑 Now, please log in to access content:\nUse <code>/login &lt;phone&gt;</code> or click below.", reply_markup=kb, parse_mode="HTML")
        else:
            await update.message.reply_text(f"❌ You are not a member of {CHANNEL_USERNAME}. Please join first.")
    except Exception:
        await update.message.reply_text("⚠️ Cannot verify. Make sure the bot is an admin in the channel.")

async def login_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_access(update, context):
        return
    if not context.args:
        await update.message.reply_text("Usage: <code>/login &lt;10-digit-phone-number&gt;</code>", parse_mode="HTML")
        return
    
    mobile = context.args[0].strip()
    if len(mobile) != 10 or not mobile.isdigit():
        await update.message.reply_text("❌ Invalid phone number. Must be exactly 10 digits.")
        return

    user_id = update.effective_user.id
    await update.message.reply_text("⏳ Requesting OTP...")
    
    payload = {"mobile": mobile, "provider": "nexttoppers", "channel": "sms"}
    try:
        res = requests.post(f"{OTP_GATEWAY_URL}/api/otp/send", json=payload, timeout=10)
        data = res.json()
        if data.get("success"):
            PENDING_OTP[user_id] = {"session_id": data["session_id"], "mobile": mobile}
            await update.message.reply_text(f"✅ OTP sent to {mobile}!\n\nReply with the 6-digit OTP or use <code>/verify &lt;otp&gt;</code> to complete login.", parse_mode="HTML")
        else:
            await update.message.reply_text(f"❌ Failed: {data.get('error', 'Unknown error')}")
    except Exception as e:
        await update.message.reply_text(f"❌ Network error: {e}")

async def verify_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not await check_access(update, context):
        return
    if user_id not in PENDING_OTP:
        await update.message.reply_text("❌ No pending OTP request. Use <code>/login &lt;phone&gt;</code> first.", parse_mode="HTML")
        return
        
    if not context.args:
        await update.message.reply_text("Usage: <code>/verify &lt;6-digit-otp&gt;</code>", parse_mode="HTML")
        return
        
    otp = context.args[0].strip()
    session = PENDING_OTP.pop(user_id)
    
    payload = {"session_id": session["session_id"], "otp": otp}
    await update.message.reply_text("⏳ Verifying OTP...")
    try:
        res = requests.post(f"{OTP_GATEWAY_URL}/api/otp/verify", json=payload, timeout=10)
        data = res.json()
        if data.get("success"):
            token = data.get("data", {}).get("token") or data.get("token") or "verified"
            # SAVE TO FIREBASE
            if save_firebase_user(user_id, session["mobile"], token):
                await update.message.reply_text(f"🎉 <b>Login Successful!</b>\n\nYour account is now linked and saved. Opening main menu...", parse_mode="HTML")
                await show_main_menu(update, context)
            else:
                await update.message.reply_text("⚠️ OTP verified, but failed to save to database. Please try again.")
        else:
            await update.message.reply_text(f"❌ Verification failed: {data.get('error', 'Invalid OTP')}")
    except Exception as e:
        await update.message.reply_text(f"❌ Network error: {e}")

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "retry_access":
        # Re-run access check
        await query.edit_message_text("⏳ Checking...")
        if await check_access(update, context):
            await show_main_menu(update, context)
        return

    if not await check_access(update, context):
        return

    if query.data == "menu_batches":
        await query.edit_message_text("📚 <b>Batches</b>\n\nFetching available courses...", parse_mode="HTML")
        # Add your batch fetching logic here
        await query.edit_message_text("📚 <b>Batches</b>\n\n(Example) 1. Class 12th Foundation\n2. NEET Booster", parse_mode="HTML")
    elif query.data == "menu_profile":
        user_data = get_firebase_user(query.from_user.id)
        mobile = user_data.get("mobile", "Unknown") if user_data else "Unknown"
        await query.edit_message_text(f"👤 <b>My Profile</b>\n\nTelegram ID: <code>{query.from_user.id}</code>\nMobile: <code>{mobile}</code>\nStatus: ✅ Verified & Logged In", parse_mode="HTML")
    elif query.data == "menu_premium":
        await query.edit_message_text("💎 <b>Premium</b>\n\nPremium features coming soon!", parse_mode="HTML")

async def ver_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"🤖 <b>StudiKitEZ Bot</b>\n📦 Version: <code>{BOT_VERSION}</code>\n✅ Platform: Vercel (FastAPI Webhook)\n🔒 Auth: Firebase + OTP Gateway", parse_mode="HTML")

# ==============================================================================
# REGISTER HANDLERS
# ==============================================================================
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("vme", vme_command))
application.add_handler(CommandHandler("login", login_command))
application.add_handler(CommandHandler("verify", verify_command))
application.add_handler(CommandHandler("ver", ver_command))
application.add_handler(CallbackQueryHandler(button_click))

# ==============================================================================
# VERCEL WEBHOOK ROUTES
# ==============================================================================
@app.on_event("startup")
async def startup_event():
    await application.initialize()
    await application.start()
    vercel_url = os.getenv("VERCEL_URL", "")
    if vercel_url:
        webhook_url = f"https://{vercel_url}/api/webhook"
        await application.bot.set_webhook(webhook_url)
        logger.info(f"✅ Webhook set to: {webhook_url}")
    else:
        logger.warning("⚠️ VERCEL_URL not set. Webhook not configured.")

@app.on_event("shutdown")
async def shutdown_event():
    await application.stop()
    await application.shutdown()

@app.post("/api/webhook")
async def webhook(request: Request):
    try:
        data = await request.json()
        update = Update.de_json(data, application.bot)
        await application.process_update(update)
        return {"ok": True}
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return {"ok": False, "error": str(e)}

@app.get("/api/setwebhook")
async def set_webhook_manual():
    vercel_url = os.getenv("VERCEL_URL", "")
    if not vercel_url:
        return {"error": "VERCEL_URL environment variable not set in Vercel Dashboard"}
    webhook_url = f"https://{vercel_url}/api/webhook"
    try:
        res = await application.bot.set_webhook(webhook_url)
        return {"ok": True, "webhook": webhook_url, "result": res}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.get("/")
def health():
    return {"status": "alive", "version": BOT_VERSION}
