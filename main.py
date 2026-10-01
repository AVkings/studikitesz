#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
StudiKitEZ Bot - Production Ready
Version: v2.2.0
"""

from __future__ import annotations
import html as html_lib
import json
import logging
import random
import re
import string
import time
import urllib.parse
import os
import threading
from pathlib import Path

import requests
from flask import Flask
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Update,
    WebAppInfo,
)
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    PreCheckoutQueryHandler,
    filters,
)

# ==============================================================================
# CONFIGURATION
# ==============================================================================
BOT_VERSION = "v2.2.0"  # <-- Updated Version
BASE_DIR = Path(__file__).resolve().parent

BOT_TOKEN = "8780623348:AAFfxePY9dJiWxkbsI8rne9XXWaNIwTdvjA"
BOT_USERNAME = "Studikitez_bot"

# ✅ YOUR CUSTOM WORKERS
PROXY_BASE = "https://studi-proxy.avnishrajurkar6.workers.dev"
PROXY_READY = True
FOLDER_PATH = "/nt/nig"
PLAY_PATH = "/nt/play"

DIRECT_BASE = "https://nt.studybeepro.site"
LEGACY_FOLDER_BASES = ["https://nts.khatikgaurav38.workers.dev"]
BATCHES_URL = "https://studikitesz.pages.dev/batches.json" 
WEB_APP_URL = "https://studiot.site.je/unlock.html"

OTP_GATEWAY_URL = "https://otp-gateway-api.avnishrajurkar6.workers.dev"

FIREBASE_API_KEY = "AIzaSyCG2zFEsE5Fr8Vx-5of_PL0xQeP773MNFM"
FIREBASE_PROJECT_ID = "studiki"
MASTER_API_KEY = "" 

ADMIN_ID = 8989013840
SECRET_CODE = "FRIENDS4EVER"
CRYPTO_WALLET = "TXYZ1234567890abcdef1234567890abcdef"
UPI_ID = "yourname@upi"
PAYMENT_AMOUNT = "$5 / Rs.1400"

STARS_ENABLED = True
PREMIUM_STARS_PRICE = 99
PREMIUM_TITLE = "StudiKitEZ Premium — Lifetime"
PREMIUM_DESCRIPTION = "Lifetime ad-free access to every batch, folder and file in this bot."

USER_DATA_FILE = BASE_DIR / "user_data.json"
REQUESTS_FILE = BASE_DIR / "premium_requests.json"

pending_proofs: dict[int, bool] = {}
pending_ads: dict[int, dict] = {}
pending_otps: dict[int, dict] = {}
AD_TIMEOUT_SEC = 15 * 60
admin_waiting: dict[int, str] = {}
admin_dm_target: dict[int, int] = {}
admin_draft: dict[int, dict] = {}

logging.basicConfig(format="%(asctime)s | %(levelname)-8s | %(message)s", level=logging.INFO)
logger = logging.getLogger("studikitez")
for _noisy in ("httpx", "httpcore", "telegram.vendor.ptb_urllib3", "werkzeug"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

# ==============================================================================
# API ROUTING & HELPERS
# ==============================================================================
def _q(**params) -> str: return "?" + urllib.parse.urlencode(params)

def folder_urls(course_id, folder_id="0") -> list[str]:
    q = _q(content=course_id, folder=folder_id)
    urls = [f"{PROXY_BASE}{FOLDER_PATH}{q}"]
    for base in LEGACY_FOLDER_BASES: urls.append(f"{base}/{q}")
    urls.append(f"{DIRECT_BASE}/api/nig{q}")
    return list(dict.fromkeys(urls))

def play_urls(content_id, course_id, creds) -> list[str]:
    urls = []
    for key, device_id in creds:
        q = _q(content_id=content_id, course_id=course_id, key=key, device_id=device_id)
        urls.append(f"{PROXY_BASE}{PLAY_PATH}{q}")
        urls.append(f"{DIRECT_BASE}/api/play{q}")
    return list(dict.fromkeys(urls))

def batches_urls() -> list[str]:
    return [BATCHES_URL]

def _get_json(url: str, timeout: int = 12):
    try:
        res = requests.get(url, timeout=timeout, headers={"Accept": "application/json", "User-Agent": "StudiKitEZ-bot/2.0"})
        if res.status_code == 200 and res.text.strip(): return res.status_code, res.json()
        return res.status_code, None
    except Exception as exc:
        logger.warning("Network error for %s: %s", url, exc)
        return 0, None

def fetch_first_json(urls: list[str], validator=None):
    last_status = 0
    for url in urls:
        status, data = _get_json(url)
        last_status = status or last_status
        if data and (validator is None or validator(data)):
            logger.info("API hit via %s", url)
            return data, status
    return None, last_status

def _api_ok(data) -> bool: return isinstance(data, dict) and bool(data.get("success"))
def _batches_ok(data) -> bool: return isinstance(data, dict) and bool(data.get("new") or data.get("old"))

# ==============================================================================
# PLAYBACK KEY MINTING (Firebase)
# ==============================================================================
_KEY_ALPHABET = string.digits + string.ascii_lowercase
def _rand_seg(n: int) -> str: return "".join(random.choices(_KEY_ALPHABET, k=n)).upper()

def mint_play_key():
    api_key, project = FIREBASE_API_KEY, FIREBASE_PROJECT_ID
    key = f"SB-{_rand_seg(4)}-{_rand_seg(4)}"
    device_id = "dev_" + "".join(random.choices(_KEY_ALPHABET, k=6))
    now_ms = int(time.time() * 1000)
    body = {
        "fields": {
            "createdAt": {"integerValue": str(now_ms)},
            "expiresAt": {"integerValue": str(now_ms + 2 * 24 * 60 * 60 * 1000)},
            "status": {"stringValue": "active"},
            "maxDevices": {"integerValue": "1"},
            "registeredDevices": {"arrayValue": {"values": [{"stringValue": device_id}]}},
        }
    }
    url = f"https://firestore.googleapis.com/v1/projects/{project}/databases/(default)/documents/valid_keys"
    try:
        res = requests.post(url, params={"documentId": key, "key": api_key}, json=body, timeout=12)
        if res.status_code in (200, 201): 
            logger.info(f"Successfully minted key: {key}")
            return key, device_id
    except Exception as exc:
        logger.warning("Key minting error: %s", exc)
    return None

# ==============================================================================
# LOCAL STORAGE & UTILS
# ==============================================================================
def load_local_json(path: Path) -> dict:
    if not path.exists(): return {}
    try:
        raw = path.read_text(encoding="utf-8").strip()
        return json.loads(raw) if raw else {}
    except Exception:
        path.write_text("{}", encoding="utf-8")
        return {}

def save_local_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

def load_user_data() -> dict: return load_local_json(USER_DATA_FILE)

def save_user_data(user_id, key, device_id, unlocked_content_id=None, is_permanent=False) -> None:
    data = load_user_data()
    uid = str(user_id)
    data.setdefault(uid, {"key": "", "device_id": "", "unlocked": [], "is_permanent": False})
    if key: data[uid]["key"] = str(key).strip()
    if device_id: data[uid]["device_id"] = str(device_id).strip()
    if is_permanent: data[uid]["is_permanent"] = True
    if unlocked_content_id is not None:
        cid = str(unlocked_content_id)
        if cid not in data[uid]["unlocked"]: data[uid]["unlocked"].append(cid)
    save_local_json(USER_DATA_FILE, data)

def grant_premium(user_id, key: str = "STARS_PREMIUM", device_id: str = "") -> None:
    save_user_data(user_id, key, device_id or f"tg_bot_{user_id}", is_permanent=True)

def is_content_unlocked(user_id, content_id) -> bool:
    entry = load_user_data().get(str(user_id), {})
    return bool(entry.get("is_permanent")) or str(content_id) in entry.get("unlocked", [])

def is_premium(user_id) -> bool: return bool(load_user_data().get(str(user_id), {}).get("is_permanent"))
def revoke_premium(user_id) -> bool:
    data = load_user_data()
    uid = str(user_id)
    if uid not in data: return False
    data[uid]["is_permanent"] = False
    save_local_json(USER_DATA_FILE, data)
    return True

def is_admin(user_id: int) -> bool:
    try:
        if int(user_id) == int(ADMIN_ID): return True
    except (TypeError, ValueError): pass
    return False

def set_request_status(user_id, status: str) -> None:
    try:
        req = load_local_json(REQUESTS_FILE)
        uid = str(user_id)
        if uid in req and isinstance(req[uid], dict): req[uid]["status"] = status
        else: req[uid] = {"username": "", "first_name": "", "status": status}
        save_local_json(REQUESTS_FILE, req)
    except Exception: pass

def pending_requests() -> dict:
    return {uid: r for uid, r in load_local_json(REQUESTS_FILE).items() if isinstance(r, dict) and r.get("status") == "pending"}

def admin_overview() -> tuple[int, int, int, int]:
    users = load_user_data()
    total = len(users)
    prem = sum(1 for u in users.values() if isinstance(u, dict) and u.get("is_permanent"))
    unlocks = sum(len(u.get("unlocked", [])) for u in users.values() if isinstance(u, dict))
    return total, prem, len(pending_requests()), unlocks

def user_stats(user_id) -> tuple[bool, int]:
    entry = load_user_data().get(str(user_id), {})
    return bool(entry.get("is_permanent")), len(entry.get("unlocked", []))

def e(value) -> str: return html_lib.escape(str(value), quote=False)
def is_unlock_code(text: str) -> bool:
    parts = str(text).strip().upper().split("-")
    return len(parts) >= 4 and parts[0] == "SB"

def mini_app_url(course_id, content_id, title: str = "") -> str:
    params = {"course": course_id, "content": content_id}
    if title: params["title"] = title
    if BOT_USERNAME: params["bot"] = BOT_USERNAME
    sep = "&" if "?" in WEB_APP_URL else "?"
    return f"{WEB_APP_URL}{sep}{urllib.parse.urlencode(params)}"

def web_app_url_valid() -> bool:
    raw = (WEB_APP_URL or "").strip()
    if not raw.lower().startswith("https://"): return False
    try:
        host = (urllib.parse.urlparse(raw).hostname or "").lower()
    except Exception: return False
    if not host or "." not in host: return False
    if "replace-with" in host or host.endswith(".example") or host == "example.com": return False
    return True

# ==============================================================================
# UI & COMMANDS
# ==============================================================================
def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📚 Browse Batches", callback_data="browse_batches")],
        [InlineKeyboardButton("💎 Go Premium / Unlock All", callback_data="nexttoper")],
        [InlineKeyboardButton("📊 My Status", callback_data="my_status"), InlineKeyboardButton("❓ Help", callback_data="help_menu")],
    ])

def main_menu_text(first_name: str = "") -> str:
    greeting = f"Hey {e(first_name)}! 👋\n\n" if first_name else ""
    return f"{greeting}🌟 <b>Welcome to StudiKitEZ</b> 🌟\n━━━━━━━━━━━━━━━\n📖 Batches, lectures & PDFs — unlocked with a short ad, or go <b>Premium</b> for instant lifetime access.\n━━━━━━━━━━━━━━━\n\n👇 <b>Choose where to go:</b>"

def batches_keyboard(batches: list[dict]) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(f"📦 {b.get('title', 'Unknown')}", callback_data=f"course:{b.get('id')}")] for b in batches[:10]]
    rows.append([InlineKeyboardButton("💎 Go Premium (no ads)", callback_data="nexttoper")])
    rows.append([InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")])
    return InlineKeyboardMarkup(rows)

def nexttoper_text(is_prem: bool, unlocked_count: int) -> str:
    if is_prem: return f"💎 <b>StudiKitEZ Premium — ACTIVE</b> ✅\n━━━━━━━━━━━━━━━\nYou already have <b>lifetime, ad-free access</b> to everything.\n🎬 Items unlocked via ads so far: <b>{unlocked_count}</b>\n\nEnjoy learning! Tap below to keep browsing. 👇"
    return f"💎 <b>Unlock StudiKitEZ Premium</b> 💎\n━━━━━━━━━━━━━━━\nTired of watching an ad for <i>every</i> lecture? 😩\n\n✨ <b>Premium gives you:</b>\n  ✅ <b>Lifetime</b> access to ALL batches\n  🚀 Instant open — <b>zero ads, zero codes</b>\n  📥 PDFs + videos, full quality\n  👑 Priority support\n━━━━━━━━━━━━━━━\n💫 <b>Today only: {PREMIUM_STARS_PRICE} ⭐ Telegram Stars</b>\n<i>(also available via crypto/UPI — {e(PAYMENT_AMOUNT)})</i>\n\n👇 <b>Tap below to upgrade instantly:</b>"

def nexttoper_keyboard(is_prem: bool) -> InlineKeyboardMarkup:
    if is_prem: return InlineKeyboardMarkup([[InlineKeyboardButton("📚 Browse Batches", callback_data="browse_batches")], [InlineKeyboardButton("📊 My Status", callback_data="my_status")], [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
    rows = []
    if STARS_ENABLED: rows.append([InlineKeyboardButton(f"⭐ Unlock All — {PREMIUM_STARS_PRICE} Stars", callback_data="buy_stars")])
    rows.append([InlineKeyboardButton("🎬 Unlock ONE item free (watch ad)", callback_data="browse_batches")])
    rows.append([InlineKeyboardButton("🎁 Request free access", callback_data="create_premium_req"), InlineKeyboardButton("💳 Crypto / UPI", callback_data="buy_crypto_info")])
    rows.append([InlineKeyboardButton("📊 My Status", callback_data="my_status"), InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")])
    return InlineKeyboardMarkup(rows)

def locked_text(title: str, is_waiting: bool = False) -> str:
    waiting = "\n⏳ <i>We are still waiting for your ad result — finish it and the file opens automatically.</i>\n" if is_waiting else ""
    return f"🔒 <b>Locked content</b>\n━━━━━━━━━━━━━━━\n📄 <b>{e(title or 'This item')}</b>\n{waiting}<b>Option 1 — Free (30 sec):</b>\n  1️⃣ Tap <b>🎬 Watch Ad &amp; Unlock</b>\n  2️⃣ Watch the ad <b>to the very end</b>\n  3️⃣ Come back — the bot sends the file <b>automatically</b> ✨\n\n<b>Option 2 — Instant:</b>\n  💎 <b>Premium</b> opens everything with zero ads ({PREMIUM_STARS_PRICE} ⭐). No codes, ever.\n\n👇 <b>Choose:</b>"

def locked_keyboard(course_id, content_id, title: str = "") -> InlineKeyboardMarkup:
    rows = []
    url = mini_app_url(course_id, content_id, title)
    if web_app_url_valid():
        try: rows.append([InlineKeyboardButton("🎬 Watch Ad & Unlock", web_app=WebAppInfo(url=url))])
        except Exception: rows.append([InlineKeyboardButton("🎬 Open unlock page", url=url)])
    else: rows.append([InlineKeyboardButton("🎬 How to unlock (setup needed)", callback_data="help_menu")])
    if STARS_ENABLED: rows.append([InlineKeyboardButton(f"⭐ Skip ads — {PREMIUM_STARS_PRICE} Stars", callback_data="buy_stars")])
    rows.append([InlineKeyboardButton("🔄 I watched it — Retry", callback_data=f"watch_ad:{course_id}:{content_id}"), InlineKeyboardButton("🏠 Menu", callback_data="main_menu")])
    return InlineKeyboardMarkup(rows)

def help_text() -> str:
    return f"❓ <b>How StudiKitEZ works</b>\n━━━━━━━━━━━━━━━\n📚 <b>/start</b> — open the main menu\n💎 <b>/nexttoper</b> — premium / unlock options\n🔑 <b>/key SB-…</b> — redeem a code manually\n📊 <b>/status</b> — check your access\n🆔 <b>/myid</b> — show your Telegram id\n📱 <b>/otp</b> — login via NextToppers OTP\n🔢 <b>/ver</b> — check bot code version\n\n<b>Free flow:</b> open a file → <b>Watch Ad</b> → finish it → the Mini App sends the code back → bot delivers the file. 🎉"

def status_text(is_prem: bool, unlocked_count: int) -> str:
    if is_prem: return f"📊 <b>My Status</b>\n━━━━━━━━━━━━━━━\n💎 Plan: <b>PREMIUM — Lifetime</b> ✅\n🚀 Ads: <b>disabled</b>\n🎬 Items unlocked via ads: <b>{unlocked_count}</b>\n\nEnjoy unlimited access! 🎉"
    return f"📊 <b>My Status</b>\n━━━━━━━━━━━━━━━\n📦 Plan: <b>Free</b>\n🎬 Items unlocked via ads: <b>{unlocked_count}</b>\n💎 Premium: <b>{PREMIUM_STARS_PRICE} ⭐</b> for lifetime, ad-free access.\n\nTap below to upgrade 👇"

# ==============================================================================
# VERSION COMMAND
# ==============================================================================
async def ver_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        f"🤖 <b>StudiKitEZ Bot</b>\n"
        f"📦 Current Code Version: <code>{BOT_VERSION}</code>\n"
        f"✅ Status: Running & Polling", 
        parse_mode="HTML"
    )

# ==============================================================================
# OTP COMMANDS
# ==============================================================================
async def send_otp(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("Usage: <code>/otp &lt;10-digit-phone-number&gt;</code>", parse_mode="HTML")
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
            pending_otps[user_id] = {"session_id": data["session_id"], "mobile": mobile}
            await update.message.reply_text(f"✅ OTP sent to {mobile}!\n\nReply with the 6-digit OTP or use <code>/verify &lt;otp&gt;</code> to complete login.", parse_mode="HTML")
        else:
            await update.message.reply_text(f"❌ Failed: {data.get('error', 'Unknown error')}")
    except Exception as e:
        await update.message.reply_text(f"❌ Network error: {e}")

async def verify_otp(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id not in pending_otps:
        await update.message.reply_text("❌ No pending OTP request. Use <code>/otp &lt;phone&gt;</code> first.", parse_mode="HTML")
        return
        
    if not context.args:
        await update.message.reply_text("Usage: <code>/verify &lt;6-digit-otp&gt;</code>", parse_mode="HTML")
        return
        
    otp = context.args[0].strip()
    session = pending_otps.pop(user_id)
    
    payload = {"session_id": session["session_id"], "otp": otp}
    await update.message.reply_text("⏳ Verifying OTP...")
    try:
        res = requests.post(f"{OTP_GATEWAY_URL}/api/otp/verify", json=payload, timeout=10)
        data = res.json()
        if data.get("success"):
            token = data.get("data", {}).get("token") or data.get("token")
            await update.message.reply_text(f"🎉 Login Successful!\n\nToken: <code>{token}</code>", parse_mode="HTML")
        else:
            await update.message.reply_text(f"❌ Verification failed: {data.get('error', 'Invalid OTP')}")
    except Exception as e:
        await update.message.reply_text(f"❌ Network error: {e}")

# ==============================================================================
# STANDARD HANDLERS
# ==============================================================================
async def get_my_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(f"Your Telegram user id is <code>{update.effective_user.id}</code>", parse_mode="HTML")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.args:
        payload = str(context.args[0]).strip()
        if is_unlock_code(payload) or payload.upper() == SECRET_CODE.upper():
            await redeem_code(update, payload)
            return
    first = update.effective_user.first_name or ""
    await update.message.reply_text(main_menu_text(first), reply_markup=main_menu_keyboard(), parse_mode="HTML")

async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(main_menu_text(update.effective_user.first_name or ""), reply_markup=main_menu_keyboard(), parse_mode="HTML")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("📚 Browse Batches", callback_data="browse_batches")], [InlineKeyboardButton("💎 Go Premium", callback_data="nexttoper")], [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(help_text(), reply_markup=kb, parse_mode="HTML")
    else:
        await update.message.reply_text(help_text(), reply_markup=kb, parse_mode="HTML")

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    prem, count = user_stats(user_id)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("📚 Browse Batches", callback_data="browse_batches")], [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]]) if prem else InlineKeyboardMarkup([[InlineKeyboardButton(f"⭐ Upgrade — {PREMIUM_STARS_PRICE} Stars", callback_data="buy_stars")], [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
    text = status_text(prem, count)
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")
    else:
        await update.message.reply_text(text, reply_markup=kb, parse_mode="HTML")

async def nexttoper_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    prem, count = user_stats(user_id)
    text = nexttoper_text(prem, count)
    kb = nexttoper_keyboard(prem)
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")
    else:
        await update.message.reply_text(text, reply_markup=kb, parse_mode="HTML")

async def redeem_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text("🔑 <b>Have a code?</b>\n\nUsage: <code>/key SB-XXXX-XXXX</code>", parse_mode="HTML")
        return
    await redeem_code(update, str(context.args[0]))

async def redeem_code(update: Update, code: str) -> None:
    message = update.effective_message
    user_id = update.effective_user.id
    key = str(code).strip().upper()
    if key == SECRET_CODE.upper():
        save_user_data(user_id, "PERMANENT_SECRET", "secret_device", is_permanent=True)
        pending_ads.pop(user_id, None)
        await message.reply_text("🎉 <b>Secret code accepted!</b>\nYou now have <b>permanent, ad-free access</b> to all content. 👑", parse_mode="HTML")
        return
    if not is_unlock_code(key):
        await message.reply_text("❌ <b>Invalid code format.</b>", parse_mode="HTML")
        return
    parts = key.split("-")
    course_id, content_id = parts[1], parts[2]
    device_id = f"tg_bot_{user_id}"
    save_user_data(user_id, key, device_id, unlocked_content_id=content_id)
    waited = pending_ads.pop(user_id, None)
    if waited:
        await message.reply_text("🎉 <b>Ad reward claimed!</b> Fetching it right now… ⏳", parse_mode="HTML")
    else:
        await message.reply_text("✅ <b>Unlocked!</b> Fetching your content… ⏳", parse_mode="HTML")
    await fetch_and_send_content_directly(message, user_id, course_id, content_id, key, device_id)

async def handle_web_app_data(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    raw = ((msg.web_app_data.data if msg.web_app_data else "") or "").strip()
    user_id = update.effective_user.id
    if not raw:
        await msg.reply_text("👀 <b>No code received.</b> Tap the file again and finish the ad.", parse_mode="HTML")
        return
    payload = raw
    if payload.startswith("{"):
        try: payload = str(json.loads(payload).get("code", "")).strip()
        except Exception: pass
    if payload:
        await redeem_code(update, payload)
    else:
        await msg.reply_text("⚠️ <b>Got an empty unlock code.</b> Please tap <b>Retry</b>.", parse_mode="HTML")

async def premium_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await nexttoper_command(update, context)

async def create_premium_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user = query.from_user
    req_data = load_local_json(REQUESTS_FILE)
    req_data[str(user.id)] = {"username": user.username or "Unknown", "first_name": user.first_name or "User", "status": "pending"}
    save_local_json(REQUESTS_FILE, req_data)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("💎 Or unlock instantly with Stars ⭐", callback_data="buy_stars")], [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
    await query.edit_message_text("📩 <b>Request sent!</b> Waiting for admin approval… ⏳", reply_markup=kb, parse_mode="HTML")
    admin_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Approve", callback_data=f"approve_req:{user.id}"), InlineKeyboardButton("Deny", callback_data=f"deny_req:{user.id}")]])
    try:
        await context.bot.send_message(chat_id=ADMIN_ID, text=f"<b>New premium request</b>\nName: {e(user.first_name)}\nUsername: @{e(user.username)}\nUser id: <code>{user.id}</code>", reply_markup=admin_keyboard, parse_mode="HTML")
    except Exception: pass

async def show_payment_details(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    pending_proofs[query.from_user.id] = True
    kb = InlineKeyboardMarkup([[InlineKeyboardButton(f"⭐ Pay with Stars instead", callback_data="buy_stars")], [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
    text = f"💳 <b>Permanent premium — {e(PAYMENT_AMOUNT)}</b>\n\n<b>USDT (TRC20)</b>\n<code>{e(CRYPTO_WALLET)}</code>\n\n<b>UPI id</b>\n<code>{e(UPI_ID)}</code>\n\nSend TXID or screenshot here."
    await query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")

def stars_payload(user_id: int) -> str: return f"premium_lifetime:{user_id}:{int(time.time())}"

async def buy_with_stars(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    if is_premium(user_id):
        await query.edit_message_text("💎 <b>You are already Premium!</b> ✅", reply_markup=nexttoper_keyboard(True), parse_mode="HTML")
        return
    if not STARS_ENABLED:
        await query.edit_message_text("⭐ Stars payments are temporarily disabled.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💳 Crypto / UPI", callback_data="buy_crypto_info")]]), parse_mode="HTML")
        return
    try:
        await context.bot.send_invoice(chat_id=query.message.chat_id, title=PREMIUM_TITLE, description=PREMIUM_DESCRIPTION, payload=stars_payload(user_id), provider_token="", currency="XTR", prices=[LabeledPrice("Lifetime Premium", PREMIUM_STARS_PRICE)], start_parameter="premium_lifetime")
        await query.message.reply_text(f"⭐ <b>Invoice sent!</b> Complete the {PREMIUM_STARS_PRICE} ⭐ payment above.", parse_mode="HTML")
    except BadRequest as exc:
        logger.error("Stars invoice failed: %s", exc)
        await query.message.reply_text("⚠️ Could not create the Stars invoice.", parse_mode="HTML")

async def precheckout_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.pre_checkout_query
    user_id = query.from_user.id
    if not str(query.invoice_payload or "").startswith("premium_lifetime:"):
        await query.answer(ok=False, error_message="Invalid payment payload.")
        return
    if is_premium(user_id):
        await query.answer(ok=False, error_message="You are already Premium!")
        return
    await query.answer(ok=True)

async def successful_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    user_id = update.effective_user.id
    pay = msg.successful_payment
    stars_paid = getattr(pay, "total_amount", 0)
    grant_premium(user_id, key="STARS_PREMIUM", device_id=f"tg_bot_{user_id}")
    pending_ads.pop(user_id, None)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("📚 Browse Batches", callback_data="browse_batches")], [InlineKeyboardButton("📊 My Status", callback_data="my_status")]])
    await msg.reply_text(f"🎉 <b>PAYMENT SUCCESSFUL!</b>\n⭐ Paid: <b>{stars_paid} Stars</b>\n💎 Status: <b>PREMIUM — Lifetime ✅</b>", reply_markup=kb, parse_mode="HTML")
    try:
        await context.bot.send_message(chat_id=ADMIN_ID, text=f"⭐ <b>New Stars sale</b>\nUser: @{e(update.effective_user.username or 'Unknown')} (<code>{user_id}</code>)\nStars: <b>{stars_paid}</b>", parse_mode="HTML")
    except Exception: pass

async def handle_admin_decision(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if not is_admin(query.from_user.id):
        await query.answer("Admins only.", show_alert=True)
        return
    action, _, raw_id = query.data.partition(":")
    target_user_id = int(raw_id)
    if action == "approve_req":
        grant_premium(target_user_id, key="ADMIN_APPROVED", device_id=f"tg_bot_{target_user_id}")
        set_request_status(target_user_id, "approved")
        try:
            await context.bot.send_message(chat_id=target_user_id, text="🎉 <b>Congratulations!</b> Your premium request was approved.", parse_mode="HTML")
            await query.edit_message_text(f"Approved and notified. User <code>{target_user_id}</code> has permanent access.", parse_mode="HTML")
        except Exception:
            await query.edit_message_text(f"Access granted for <code>{target_user_id}</code>, but DM failed.", parse_mode="HTML")
    else:
        set_request_status(target_user_id, "denied")
        try:
            await context.bot.send_message(chat_id=target_user_id, text="Your premium request was denied.")
            await query.edit_message_text("Denied and notified.", parse_mode="HTML")
        except Exception:
            await query.edit_message_text("Denied. (User has not started the bot)", parse_mode="HTML")

async def handle_payment_proof(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id in admin_waiting or user_id not in pending_proofs: return
    if update.message.text and update.message.text.lower() == "/cancel":
        pending_proofs.pop(user_id, None)
        await update.message.reply_text("Payment cancelled.")
        return
    admin_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Payment verified", callback_data=f"approve_req:{user_id}"), InlineKeyboardButton("Reject", callback_data=f"deny_req:{user_id}")]])
    admin_msg = f"<b>New payment proof</b>\nUser: @{e(update.effective_user.username or 'Unknown')}\nId: <code>{user_id}</code>"
    try:
        if update.message.photo:
            await context.bot.send_photo(chat_id=ADMIN_ID, photo=update.message.photo[-1].file_id, caption=admin_msg, reply_markup=admin_keyboard, parse_mode="HTML")
        elif update.message.text:
            await context.bot.send_message(chat_id=ADMIN_ID, text=f"{admin_msg}\nTXID: <code>{e(update.message.text)}</code>", reply_markup=admin_keyboard, parse_mode="HTML")
        await update.message.reply_text("Proof sent to the admin.")
        pending_proofs.pop(user_id, None)
    except Exception:
        await update.message.reply_text("Could not send the proof.")

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("⛔ <b>Admins only.</b>", parse_mode="HTML")
        return
    total, prem, pend, unlocks = admin_overview()
    text = f"🛡️ <b>Admin Panel</b>\n👥 Users: <b>{total}</b> | 👑 Premium: <b>{prem}</b>\n📥 Pending: <b>{pend}</b> | 🎬 Unlocks: <b>{unlocks}</b>"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("📥 Requests", callback_data="adm:req"), InlineKeyboardButton("📊 Stats", callback_data="adm:stats")], [InlineKeyboardButton("👑 Premium users", callback_data="adm:prem"), InlineKeyboardButton("📢 Announce", callback_data="adm:bc")]])
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode="HTML")
    else:
        await update.message.reply_text(text, reply_markup=kb, parse_mode="HTML")

async def admin_stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id): return
    total, prem, pend, unlocks = admin_overview()
    await update.message.reply_text(f"📊 <b>Stats</b>\n👥 Total: <b>{total}</b>\n👑 Premium: <b>{prem}</b>\n📥 Pending: <b>{pend}</b>\n🎬 Unlocks: <b>{unlocks}</b>", parse_mode="HTML")

async def admin_requests_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_admin(update.effective_user.id): return
    pend = pending_requests()
    ids = sorted(pend.keys())
    if not ids:
        await update.message.reply_text("📥 <b>Requests</b>\n✅ No pending requests.", parse_mode="HTML")
        return
    lines = ["📥 <b>Pending requests</b>"]
    rows = []
    for uid in ids[:8]:
        r = pend[uid] if isinstance(pend[uid], dict) else {}
        lines.append(f"• {e(r.get('first_name', '?'))} (@{e(r.get('username', '?'))}) — <code>{e(uid)}</code>")
        rows.append([InlineKeyboardButton(f"👤 {uid}", callback_data=f"adm:user:{uid}"), InlineKeyboardButton("✅", callback_data=f"approve_req:{uid}"), InlineKeyboardButton("❌", callback_data=f"deny_req:{uid}")])
    await update.message.reply_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(rows), parse_mode="HTML")

async def admin_panel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not is_admin(query.from_user.id): await query.answer("Admins only.", show_alert=True); return
    await query.answer()
    data = query.data
    if data == "adm:home":
        await admin_command(update, context)
    elif data == "adm:stats":
        await admin_stats_cmd(update, context)
    elif data == "adm:req":
        await admin_requests_cmd(update, context)
    elif data.startswith("adm:user:"):
        uid = data.split(":", 2)[2]
        users = load_user_data()
        u = users.get(str(uid), {})
        prem = bool(u.get("is_permanent")) if isinstance(u, dict) else False
        text = f"👤 <b>User <code>{e(uid)}</code></b>\nPremium: <b>{'✅ YES' if prem else '❌ no'}</b>"
        rows = [[InlineKeyboardButton("✅ Grant", callback_data=f"adm:grant:{uid}"), InlineKeyboardButton("🚫 Revoke", callback_data=f"adm:revoke:{uid}")], [InlineKeyboardButton("⬅️ Panel", callback_data="adm:home")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(rows), parse_mode="HTML")
    elif data.startswith("adm:grant:"):
        uid = data.split(":", 2)[2]
        grant_premium(uid, key="ADMIN_APPROVED", device_id=f"tg_bot_{uid}")
        set_request_status(uid, "approved")
        try: await context.bot.send_message(chat_id=int(uid), text="🎉 <b>Good news!</b> The admin granted you <b>permanent, ad-free access</b>. 👑", parse_mode="HTML")
        except Exception: pass
        await query.edit_message_text(f"Granted to <code>{uid}</code>.", parse_mode="HTML")
    elif data.startswith("adm:revoke:"):
        uid = data.split(":", 2)[2]
        revoke_premium(uid)
        set_request_status(uid, "revoked")
        try: await context.bot.send_message(chat_id=int(uid), text="⚠️ <b>Your premium access was revoked</b>.", parse_mode="HTML")
        except Exception: pass
        await query.edit_message_text(f"Revoked <code>{uid}</code>.", parse_mode="HTML")
    elif data == "adm:bc":
        await query.edit_message_text("📢 <b>Announcement mode</b>\nSend the announcement text now. Type <code>/cancel</code> to abort.", parse_mode="HTML")
        admin_waiting[query.from_user.id] = "broadcast"
    elif data == "adm:cancel":
        admin_waiting.pop(query.from_user.id, None)
        await admin_command(update, context)
    elif data == "adm:sendbc":
        await query.edit_message_text("Broadcast sent! (Simplified for stability)", parse_mode="HTML")

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uid = update.effective_user.id
    if pending_proofs.pop(uid, None) is not None: await update.message.reply_text("Payment cancelled.")
    if admin_waiting.pop(uid, None) is not None: await update.message.reply_text("Admin input cancelled.")
    pending_otps.pop(uid, None)

async def admin_input_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    if not msg or update.effective_user is None: return
    admin_id = update.effective_user.id
    if not is_admin(admin_id) or admin_id not in admin_waiting: return
    mode = admin_waiting.get(admin_id)
    if mode == "broadcast":
        admin_waiting.pop(admin_id, None)
        users = load_user_data()
        ok, fail = 0, 0
        await msg.reply_text(f"📤 Sending to <b>{len(users)}</b> users… ⏳", parse_mode="HTML")
        import asyncio as _asyncio
        for i, uid in enumerate(list(users.keys())):
            try:
                await context.bot.send_message(chat_id=int(uid), text=f"📢 <b>Announcement</b>\n\n{msg.text}", parse_mode="HTML")
                ok += 1
            except Exception: fail += 1
            if i and i % 25 == 0: await _asyncio.sleep(0.3)
        await msg.reply_text(f"✅ Delivered: <b>{ok}</b>\n❌ Failed: <b>{fail}</b>", parse_mode="HTML")

async def send_batches_list(query, context: ContextTypes.DEFAULT_TYPE | None = None) -> None:
    await query.edit_message_text("⏳ <b>Fetching batches…</b>", parse_mode="HTML")
    data, _status = fetch_first_json(batches_urls(), _batches_ok)
    if not data:
        await query.edit_message_text("😞 <b>Could not reach the batch server.</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Retry", callback_data="browse_batches")], [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]]), parse_mode="HTML")
        return
    batches = list(data.get("new", [])) + list(data.get("old", []))
    if not batches:
        await query.edit_message_text("No batches found.")
        return
    await query.edit_message_text("📚 <b>Select a batch:</b> 👇", reply_markup=batches_keyboard(batches), parse_mode="HTML")

async def show_locked_content(query, course_id: str, content_id: str, title: str = "") -> None:
    user_id = query.from_user.id
    now = time.time()
    prev = pending_ads.get(user_id)
    is_waiting = False
    expired = False
    if prev and prev.get("content") == str(content_id) and prev.get("course") == str(course_id):
        if now - float(prev.get("ts", 0)) < AD_TIMEOUT_SEC: is_waiting = True
        else: expired = True
    pending_ads[user_id] = {"course": str(course_id), "content": str(content_id), "title": title, "ts": now}
    if not web_app_url_valid():
        await query.edit_message_text("🔒 <b>Locked content</b>\n\nThe ad-unlock page is not configured yet.", parse_mode="HTML")
        return
    text = locked_text(title, is_waiting=is_waiting)
    if expired: text += "\n\n⌛ <i>Your last unlock attempt expired (15 min). No worries — just watch once more.</i>"
    try:
        await query.edit_message_text(text, reply_markup=locked_keyboard(course_id, content_id, title), parse_mode="HTML")
    except BadRequest:
        url = mini_app_url(course_id, content_id, title)
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🎬 Open unlock page", url=url)]]), parse_mode="HTML")

async def button_click(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query.data.startswith(("adm:", "approve_req:", "deny_req:")): return
    await query.answer()
    user_id = query.from_user.id
    parts = query.data.split(":", 2)
    action = parts[0]
    if action == "main_menu": await query.edit_message_text(main_menu_text(query.from_user.first_name or ""), reply_markup=main_menu_keyboard(), parse_mode="HTML")
    elif action == "browse_batches": await send_batches_list(query, context)
    elif action == "help_menu": await help_command(update, context)
    elif action == "my_status":
        prem, count = user_stats(user_id)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("📚 Browse Batches", callback_data="browse_batches")], [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]]) if prem else InlineKeyboardMarkup([[InlineKeyboardButton(f"⭐ Upgrade — {PREMIUM_STARS_PRICE} Stars", callback_data="buy_stars")], [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]])
        await query.edit_message_text(status_text(prem, count), reply_markup=kb, parse_mode="HTML")
    elif action in ("nexttoper", "premium_menu"):
        prem, count = user_stats(user_id)
        await query.edit_message_text(nexttoper_text(prem, count), reply_markup=nexttoper_keyboard(prem), parse_mode="HTML")
    elif action == "buy_stars": await buy_with_stars(update, context)
    elif action == "watch_ad": await show_locked_content(query, parts[1], parts[2])
    elif action == "course":
        await query.edit_message_text("⏳ <b>Loading folders…</b>", parse_mode="HTML")
        data, _status = fetch_first_json(folder_urls(parts[1], 0), _api_ok)
        if not data:
            await query.edit_message_text("😞 <b>Could not load folders.</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Retry", callback_data=f"course:{parts[1]}")], [InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")]]), parse_mode="HTML")
            return
        keyboard = [[InlineKeyboardButton(f"📁 {item.get('title', 'Folder')}", callback_data=f"folder:{parts[1]}:{item.get('entity_id')}")] for item in data.get("data", []) if item.get("type") == "folder"]
        keyboard.append([InlineKeyboardButton("⬅️ Back to Batches", callback_data="browse_batches")])
        keyboard.append([InlineKeyboardButton("🏠 Main Menu", callback_data="main_menu")])
        await query.edit_message_text(f"📦 <b>Course content</b>\n<code>{e(parts[1])}</code>\n\n👇 Pick a folder:", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
    elif action == "folder":
        await query.edit_message_text("⏳ <b>Loading contents…</b>", parse_mode="HTML")
        data, _status = fetch_first_json(folder_urls(parts[1], parts[2]), _api_ok)
        if not data:
            await query.edit_message_text("😞 <b>Could not load folder contents.</b>", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data=f"course:{parts[1]}")]]), parse_mode="HTML")
            return
        keyboard = []
        for item in data.get("data", []):
            title = item.get("title", "Item")
            if item.get("type") == "folder": keyboard.append([InlineKeyboardButton(f"📁 {title}", callback_data=f"folder:{parts[1]}:{item.get('entity_id')}")])
            elif item.get("type") == "file":
                icon = "🎬" if item.get("data", {}).get("file_type") == 2 else "📄"
                keyboard.append([InlineKeyboardButton(f"{icon} {title}", callback_data=f"file:{parts[1]}:{item.get('entity_id')}")])
        keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data=f"course:{parts[1]}")])
        await query.edit_message_text("📂 <b>Folder contents</b> 👇", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
    elif action == "file":
        entry = load_user_data().get(str(user_id), {})
        if entry.get("is_permanent") or is_content_unlocked(user_id, parts[2]):
            await fetch_and_send_content(query, user_id, parts[1], parts[2], entry.get("key", "SECRET"), entry.get("device_id", "secret"))
            return
        await show_locked_content(query, parts[1], parts[2])
    elif action == "back_to_start": await query.edit_message_text(main_menu_text(query.from_user.first_name or ""), reply_markup=main_menu_keyboard(), parse_mode="HTML")
    elif action == "buy_crypto_info": await show_payment_details(update, context)

async def fetch_and_send_content(query, user_id, course_id, content_id, key, device_id):
    await query.edit_message_text("⏳ <b>Fetching your resource…</b>", parse_mode="HTML")
    await _do_fetch(query.message, user_id, course_id, content_id, key, device_id)

async def fetch_and_send_content_directly(message, user_id, course_id, content_id, key, device_id):
    await _do_fetch(message, user_id, course_id, content_id, key, device_id)

async def _do_fetch(target, user_id, course_id, content_id, key, device_id):
    creds: list[tuple[str, str]] = []
    minted = mint_play_key()
    if minted:
        creds.append(minted)
        logger.info("minted playback key for content %s", content_id)
    stored_key, stored_device = str(key).strip(), str(device_id).strip()
    if stored_key and (stored_key, stored_device) not in creds: creds.append((stored_key, stored_device))
    master = MASTER_API_KEY.strip()
    if master and (master, stored_device) not in creds: creds.append((master, stored_device))
    if not creds:
        await target.reply_text("No playback key available for this request.")
        return
    data, status = fetch_first_json(play_urls(content_id, course_id, creds), lambda d: isinstance(d, dict) and bool(d.get("decryptedData")))
    if not data:
        if status in (401, 403): await target.reply_text(f"<b>Playback key rejected by the API</b> (HTTP {status}).\n\nThe server is reachable - the key was not accepted.", parse_mode="HTML")
        else: await target.reply_text(f"🎉 <b>Unlock saved!</b> But the file server did not respond (last status: {status or 'no response'}).", parse_mode="HTML")
        return
    payload = data.get("decryptedData") or {}
    file_url = payload.get("file_url")
    title = payload.get("title", "Resource")
    file_type = payload.get("file_type")
    if not file_url:
        await target.reply_text("The API returned no file url for this item.")
        return
    header = "🎉 <b>Here is your file — enjoy!</b>\n\n"
    if file_type == 1 or ".pdf" in str(file_url).lower():
        await target.reply_text(f"{header}<b>{e(title)}</b>\n\n<a href=\"{e(file_url)}\">📄 Open PDF</a>", parse_mode="HTML", disable_web_page_preview=True)
    else:
        await target.reply_text(f"{header}<b>{e(title)}</b>\n\n<a href=\"{e(file_url)}\">🎬 Open video</a>\n\n<i>Tip: this is an .m3u8 stream - open it in VLC or MX Player.</i>", parse_mode="HTML", disable_web_page_preview=True)

# ==============================================================================
# FLASK PORT BINDER (Fixes Render "No open ports" warning)
# ==============================================================================
def run_flask_server():
    app = Flask(__name__)
    @app.route('/')
    def home():
        return f"StudiKitEZ Bot is alive! Version: {BOT_VERSION}", 200
    @app.route('/health')
    def health():
        return "OK", 200
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

# ==============================================================================
# MAIN EXECUTION
# ==============================================================================
def main():
    # 1. Start Flask in the background to satisfy Render's port check
    threading.Thread(target=run_flask_server, daemon=True).start()
    logger.info("Flask web server started on Render port.")

    logger.info(f"Starting StudiKitEZ Bot {BOT_VERSION}...")
    app = Application.builder().token(BOT_TOKEN).build()

    # Register all handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("menu", menu_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("mystatus", status_command))
    app.add_handler(CommandHandler("nexttoper", nexttoper_command))
    app.add_handler(CommandHandler("key", redeem_key))
    app.add_handler(CommandHandler("myid", get_my_id))
    app.add_handler(CommandHandler("premium", premium_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(CommandHandler("admin", admin_command))
    app.add_handler(CommandHandler("stats", admin_stats_cmd))
    app.add_handler(CommandHandler("requests", admin_requests_cmd))
    
    # ✅ VERSION & OTP COMMANDS
    app.add_handler(CommandHandler("ver", ver_command))
    app.add_handler(CommandHandler("otp", send_otp))
    app.add_handler(CommandHandler("verify", verify_otp))
    
    app.add_handler(PreCheckoutQueryHandler(precheckout_handler))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment_handler))
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_web_app_data))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, admin_input_handler))
    app.add_handler(MessageHandler(filters.PHOTO, admin_input_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_payment_proof))
    app.add_handler(MessageHandler(filters.PHOTO, handle_payment_proof))
    
    app.add_handler(CallbackQueryHandler(handle_admin_decision, pattern=r"^(approve_req|deny_req):"))
    app.add_handler(CallbackQueryHandler(admin_panel_callback, pattern=r"^adm:"))
    app.add_handler(CallbackQueryHandler(button_click))

    logger.info("✅ Bot is running and polling for updates!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
