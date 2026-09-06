import threading
import time
import feedparser
import requests
import telebot
import os
import json
from dotenv import load_dotenv

# --- Environment & Storage Configuration ---
load_dotenv()
TELEGRAM_BOT_TOKEN = os.getenv("BOTTOKEN")
ADMINCHAT_ID = os.getenv("ADMIN_CHAT_ID")  # Authorized Admin Chat ID

# Persistent directory for Railway volumes or local testing
DATA_DIR = os.getenv("DATA_DIR", "data")
os.makedirs(DATA_DIR, exist_ok=True)
DATA_FILE = os.path.join(DATA_DIR, "tracked_users.json")

HEADERS = {"User-Agent": "python:telegram-reddit-monitor:v2.0 (by /u/your_username)"}
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

# --- Multi-User Data Management ---
def load_user_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f:
                raw_data = json.load(f)
                return {
                    str(chat_id): {
                        "subs": set(data.get("subs", ["hardwareswap"])),
                        "keys": set(data.get("keys", []))
                    }
                    for chat_id, data in raw_data.items()
                }
        except Exception as e:
            print(f"Error loading persistent data: {e}")
    return {}

def save_user_data():
    try:
        serializable_data = {
            chat_id: {
                "subs": list(data["subs"]),
                "keys": list(data["keys"])
            }
            for chat_id, data in USER_DATA.items()
        }
        with open(DATA_FILE, "w") as f:
            json.dump(serializable_data, f, indent=2)
    except Exception as e:
        print(f"Error saving user data: {e}")

USER_DATA = load_user_data()
initialized_subs = set()
seen_posts = set()
bot_start_time = time.time()

def get_user_config(chat_id):
    chat_id_str = str(chat_id)
    if chat_id_str not in USER_DATA:
        USER_DATA[chat_id_str] = {
            "subs": {"hardwareswap"},
            "keys": set()
        }
        save_user_data()
    return USER_DATA[chat_id_str]


# --- Admin Command Handlers ---
@bot.message_handler(commands=["removechat"])
def admin_remove_chat(message):
    if str(message.chat.id) != str(ADMIN_CHAT_ID):
        bot.reply_to(message, "⛔ *Unauthorized:* You do not have admin permissions.", parse_mode="Markdown")
        return

    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, "⚠️ *Usage:* `/removechat <chat_id>`", parse_mode="Markdown")
        return

    target_chat_id = parts[1].strip()
    if target_chat_id in USER_DATA:
        del USER_DATA[target_chat_id]
        save_user_data()
        bot.reply_to(message, f"✅ Successfully removed chat ID `{target_chat_id}` from the database.", parse_mode="Markdown")
    else:
        bot.reply_to(message, f"ℹ️ Chat ID `{target_chat_id}` was not found.", parse_mode="Markdown")


@bot.message_handler(commands=["listchats"])
def admin_list_chats(message):
    if str(message.chat.id) != str(ADMIN_CHAT_ID):
        bot.reply_to(message, "⛔ *Unauthorized:* You do not have admin permissions.", parse_mode="Markdown")
        return

    if not USER_DATA:
        bot.reply_to(message, "ℹ️ No registered chats found.", parse_mode="Markdown")
        return

    report = "📋 *Registered Chat IDs:*\n\n"
    for cid, config in USER_DATA.items():
        subs = ", ".join(config['subs']) if config['subs'] else "None"
        keys = ", ".join(config['keys']) if config['keys'] else "All Posts"
        report += f"• `{cid}`\n  └ Subs: {subs}\n  └ Keys: {keys}\n\n"

    bot.reply_to(message, report, parse_mode="Markdown")


# --- Standard User Command Handlers ---
@bot.message_handler(commands=["status"])
def send_status(message):
    user = get_user_config(message.chat.id)

    uptime_seconds = int(time.time() - bot_start_time)
    hours, remainder = divmod(uptime_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    
    subs_list = ", ".join([f"r/{sub}" for sub in user["subs"]]) if user["subs"] else "None"
    keys_list = ", ".join(user["keys"]) if user["keys"] else "None (Alerting on ALL posts)"

    status_text = (
        f"🟢 *Bot Status: ONLINE*\n\n"
        f"⏱️ *Uptime:* {hours}h {minutes}m {seconds}s\n"
        f"👤 *Your Chat ID:* `{message.chat.id}`\n"
        f"📁 *Your Tracked Subs:* {subs_list}\n"
        f"🔑 *Your Tracked Keys:* {keys_list}\n"
    )
    bot.reply_to(message, status_text, parse_mode="Markdown")


@bot.message_handler(commands=["addsub"])
def add_subreddit(message):
    user = get_user_config(message.chat.id)
    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, "⚠️ *Usage:* `/addsub subname`", parse_mode="Markdown")
        return
    
    new_sub = parts[1].strip().lower().replace("r/", "").replace("/", "")
    if new_sub in user["subs"]:
        bot.reply_to(message, f"ℹ️ You are already tracking *r/{new_sub}*", parse_mode="Markdown")
    else:
        user["subs"].add(new_sub)
        save_user_data()
        bot.reply_to(message, f"✅ Successfully added! Now tracking *r/{new_sub}*.", parse_mode="Markdown")


@bot.message_handler(commands=["removesub"])
def remove_subreddit(message):
    user = get_user_config(message.chat.id)
    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, "⚠️ *Usage:* `/removesub subname`", parse_mode="Markdown")
        return
    
    sub_to_remove = parts[1].strip().lower().replace("r/", "").replace("/", "")
    if sub_to_remove in user["subs"]:
        user["subs"].remove(sub_to_remove)
        save_user_data()
        bot.reply_to(message, f"✅ Removed *r/{sub_to_remove}*.", parse_mode="Markdown")
    else:
        bot.reply_to(message, f"ℹ️ You are not currently tracking *r/{sub_to_remove}*.", parse_mode="Markdown")


@bot.message_handler(commands=["addkey"])
def add_keyword(message):
    user = get_user_config(message.chat.id)
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, "⚠️ *Usage:* `/addkey ddr5` or `/addkey 3090`", parse_mode="Markdown")
        return
    
    new_key = parts[1].strip().lower()
    if new_key in user["keys"]:
        bot.reply_to(message, f"ℹ️ You are already filtering for *{new_key}*", parse_mode="Markdown")
    else:
        user["keys"].add(new_key)
        save_user_data()
        bot.reply_to(message, f"✅ Added *{new_key}* to your filters.", parse_mode="Markdown")


@bot.message_handler(commands=["remkey"])
def remove_keyword(message):
    user = get_user_config(message.chat.id)
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, "⚠️ *Usage:* `/remkey ddr5`", parse_mode="Markdown")
        return
    
    key_to_remove = parts[1].strip().lower()
    if key_to_remove in user["keys"]:
        user["keys"].remove(key_to_remove)
        save_user_data()
        bot.reply_to(message, f"✅ Removed *{key_to_remove}*.", parse_mode="Markdown")
    else:
        bot.reply_to(message, f"ℹ️ You are not currently tracking *{key_to_remove}*.", parse_mode="Markdown")


# --- Reddit Monitor Engine ---
def send_telegram_alert(chat_id, sub, title, link):
    text = f"🚨 New on r/{sub}\n\n📌 {title}\n🔗 {link}"
    try:
        bot.send_message(chat_id, text, disable_web_page_preview=False, timeout=45)
    except Exception as e:
        print(f"Failed to send alert to chat {chat_id}: {e}")


def monitor_reddit_feed():
    print("Started multi-user Reddit RSS monitor...")
    
    while True:
        active_subs = set()
        for user in USER_DATA.values():
            active_subs.update(user["subs"])

        if not active_subs:
            time.sleep(10)
            continue
            
        for sub in list(active_subs):
            url = f"https://www.reddit.com/r/{sub}/new.rss"
            try:
                response = requests.get(url, headers=HEADERS, timeout=10)
                
                # Handling HTTP 429 Rate Limiting
                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 120))
                    print(f"⚠️ [Rate Limit] HTTP 429 on r/{sub}. Backing off for {retry_after}s...")
                    time.sleep(retry_after)
                    continue

                if response.status_code == 200:
                    feed = feedparser.parse(response.content)
                    is_first_run = sub not in initialized_subs
                    
                    for entry in reversed(feed.entries):
                        post_id = entry.id
                        if post_id not in seen_posts:
                            seen_posts.add(post_id)
                            
                            if not is_first_run:
                                title_lower = entry.title.lower()
                                is_selling_post = True
                                
                                if sub == "hardwareswap":
                                    if "[h]" in title_lower and "[w]" in title_lower:
                                        h_index = title_lower.find("[h]")
                                        w_index = title_lower.find("[w]")
                                        h_section = title_lower[h_index:w_index]
                                        if "paypal" in h_section or "cash" in h_section:
                                            is_selling_post = False
                                
                                if not is_selling_post:
                                    continue

                                for chat_id_str, user_config in USER_DATA.items():
                                    if sub in user_config["subs"]:
                                        user_keys = user_config["keys"]
                                        if user_keys:
                                            if any(k in title_lower for k in user_keys):
                                                send_telegram_alert(chat_id_str, sub, entry.title, entry.link)
                                        else:
                                            send_telegram_alert(chat_id_str, sub, entry.title, entry.link)

                    if is_first_run:
                        initialized_subs.add(sub)
                        print(f"Initialized r/{sub} feed silently.")
                        
                else:
                    print(f"Failed to fetch r/{sub}. HTTP Status: {response.status_code}")
                    
            except Exception as e:
                print(f"Error checking feed for r/{sub}: {e}")

            time.sleep(3) 

        time.sleep(90)


if __name__ == "__main__":
    if TELEGRAM_BOT_TOKEN == "YOUR_TOKEN_HERE" or not TELEGRAM_BOT_TOKEN:
        print("WARNING: Please set your Telegram Bot Token.")
    else:
        monitor_thread = threading.Thread(target=monitor_reddit_feed, daemon=True)
        monitor_thread.start()

        try:
            bot.set_my_commands([
                telebot.types.BotCommand("/status", "Check your status and uptime"),
                telebot.types.BotCommand("/addsub", "Add a subreddit to your list"),
                telebot.types.BotCommand("/removesub", "Remove a subreddit from your list"),
                telebot.types.BotCommand("/addkey", "Add hardware keyword filter"),
                telebot.types.BotCommand("/remkey", "Remove hardware keyword filter")
            ])
        except Exception as e:
            print(f"Failed to set bot commands: {e}")

        print("Bot is listening for commands...")
        
        while True:
            try:
                bot.infinity_polling(interval=1, timeout=20, long_polling_timeout=20)
            except (requests.exceptions.ConnectionError, requests.exceptions.ReadTimeout, ConnectionResetError) as e:
                print(f"\n[Network Notice] Connection dropped or timed out: {e}")
                print("Reconnecting to Telegram in 5 seconds...")
                time.sleep(5)
            except Exception as e:
                print(f"\n[Error] An unexpected polling error occurred: {e}")
                time.sleep(5)