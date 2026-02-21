import re
import time
import random
import os

import psycopg
import telebot
from telebot import types

# =========================
# تنظیمات اصلی
# =========================
TOKEN = os.environ.get("TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")

OWNER_ID = 2043594987
DB_CHANNEL_USERNAME = "@hunter_database"  # کانال دیتابیس
VERSION = "HunterBot v13 (Neon/Postgres build)"

if not TOKEN:
    raise RuntimeError("TOKEN env is missing")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL env is missing")

bot = telebot.TeleBot(TOKEN, parse_mode=None)

# =========================
# RARITY / EVENTS
# =========================
RARITIES = {
    "common":       {"emoji": "🔵", "title": "Common"},
    "rare":         {"emoji": "🟠", "title": "Rare"},
    "epic":         {"emoji": "🟣", "title": "Epic"},
    "legendary":    {"emoji": "🟡", "title": "Legendary"},
    "flat":         {"emoji": "🔮", "title": "Flat"},
    "transcendent": {"emoji": "🪞", "title": "Transcendent"},
    "cosmic":       {"emoji": "🌌", "title": "Cosmic"},
    "infinity":     {"emoji": "♾️", "title": "Infinity"},
    "oblivion":     {"emoji": "🩸", "title": "Oblivion"},
}

EVENTS = {
    "post_apocalyptic_survivor": "Post-Apocalyptic Survivor ☢️",
    "space_explorer": "Space Explorer 🚀",
    "festival_fireworks": "Festival Fireworks 🎆",
    "monster_side": "Monster Side🐉",
    "rome": "Rome 🏰",
    "halloween": "Halloween 🎃",
    "valentine": "Valentine 💝",
    "wedding": "Wedding 💍",
    "school": "School 🏫",
    "cosplay": "Cosplay 🎭",
    "winter": "Winter ❄️",
    "christmas": "Christmas 🎄",
    "summer": "Summer 🏖",
    "gamer": "Gamer 🎮",
    "police": "𝗣𝗢𝗟𝗜𝗖𝗘 🚨",
    "doctor": "Doctor 🧬",
    "maid": "Maid 🧹",
    "idol": "Idol 🎤",
    "office_lady": "Office Lady 💼",
    "sports": "sports ⚽️",
    "warrior": "warrior 🛡",
}

NO_EVENT_KEY = "none"
NO_EVENT_TITLE = "None"

# =========================
# Spawn config (قابل تغییر)
# =========================
RARITY_SPAWN_WEIGHTS = {
    "common": 60,
    "rare": 25,
    "epic": 10,
    "legendary": 4,
    "flat": 1,
    "transcendent": 0.4,
    "cosmic": 0.1,
    "infinity": 0,
    "oblivion": 0,
}

DEFAULT_SPAWN_EVERY = 100
DEFAULT_SPAWN_ENABLED = True

# =========================
# DB (Postgres / Neon)
# =========================
def db():
    # Neon/Postgres
    return psycopg.connect(DATABASE_URL, autocommit=False)

def init_db():
    with db() as con:
        with con.cursor() as cur:
            cur.execute("""
            CREATE TABLE IF NOT EXISTS uploaders (
                tg_id BIGINT PRIMARY KEY,
                added_by BIGINT NOT NULL,
                added_at BIGINT NOT NULL
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS characters (
                id BIGSERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                anime TEXT NOT NULL,
                rarity_key TEXT NOT NULL,
                event_key TEXT NOT NULL,
                image_file_id TEXT NOT NULL,
                channel_msg_id BIGINT,
                uploaded_by BIGINT NOT NULL,
                uploaded_at BIGINT NOT NULL
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS chat_settings (
                chat_id BIGINT PRIMARY KEY,
                spawn_enabled BOOLEAN NOT NULL,
                spawn_every INTEGER NOT NULL,
                msg_counter BIGINT NOT NULL
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS active_spawns (
                chat_id BIGINT PRIMARY KEY,
                char_id BIGINT NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
                spawned_msg_id BIGINT NOT NULL,
                spawned_at BIGINT NOT NULL,
                claimed_by BIGINT,
                claimed_at BIGINT
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS inventory (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                chat_id BIGINT NOT NULL,
                char_id BIGINT NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
                obtained_at BIGINT NOT NULL
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS favorites (
                user_id BIGINT PRIMARY KEY,
                char_id BIGINT NOT NULL REFERENCES characters(id) ON DELETE CASCADE
            )
            """)

            # indexes
            cur.execute("CREATE INDEX IF NOT EXISTS idx_inventory_user ON inventory(user_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_inventory_chat_user ON inventory(chat_id, user_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_characters_rarity ON characters(rarity_key)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_characters_name ON characters(name)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_characters_anime ON characters(anime)")

        con.commit()

init_db()

# =========================
# Resolve DB channel chat_id
# =========================
DB_CHAT_ID = None

def resolve_db_chat_id():
    global DB_CHAT_ID
    try:
        chat = bot.get_chat(DB_CHANNEL_USERNAME)
        DB_CHAT_ID = chat.id
        print("DB channel resolved:", DB_CHANNEL_USERNAME, "=>", DB_CHAT_ID)
    except Exception as e:
        print("Failed to resolve DB channel id:", e)
        DB_CHAT_ID = DB_CHANNEL_USERNAME

resolve_db_chat_id()

# =========================
# Helpers
# =========================
def is_owner(uid: int) -> bool:
    return uid == OWNER_ID

def is_uploader(uid: int) -> bool:
    if is_owner(uid):
        return True
    with db() as con:
        with con.cursor() as cur:
            cur.execute("SELECT 1 FROM uploaders WHERE tg_id=%s", (uid,))
            row = cur.fetchone()
    return row is not None

def normalize(s: str) -> str:
    s = (s or "").strip().lower()
    s = s.replace("ي", "ی").replace("ك", "ک")
    s = re.sub(r"\s+", " ", s)
    return s

def parse_rarity(line: str):
    raw = (line or "").strip()
    t = normalize(raw).replace(":", " ")
    t = re.sub(r"\s+", " ", t).strip()

    if t in RARITIES:
        return t
    for key, meta in RARITIES.items():
        if key in t:
            return key
        if normalize(meta["title"]) in t:
            return key
        if meta["emoji"] and meta["emoji"] in raw:
            return key
    return None

def parse_event_optional(line: str):
    raw = (line or "").strip()
    if not raw:
        return NO_EVENT_KEY

    t = normalize(raw)
    t = t.replace("event", "").replace(":", " ")
    t = re.sub(r"\s+", " ", t).strip()

    if t in (NO_EVENT_KEY, "noevent", "no event", "none", "null", "-"):
        return NO_EVENT_KEY
    if t in EVENTS:
        return t
    for key, title in EVENTS.items():
        if normalize(title) in normalize(raw):
            return key
        if key in t:
            return key
    return NO_EVENT_KEY

def event_title(key: str) -> str:
    return NO_EVENT_TITLE if key == NO_EVENT_KEY else EVENTS.get(key, NO_EVENT_TITLE)

def extract_card_from_reply(message):
    if not message.reply_to_message:
        return None, "❌ باید روی پیام عکس ریپلای کنی."
    src = message.reply_to_message
    if not src.photo:
        return None, "❌ پیام ریپلای باید Photo باشه."

    caption = (src.caption or "").strip()
    lines = [ln.strip() for ln in caption.splitlines() if ln.strip()]

    if len(lines) not in (3, 4):
        return None, (
            "❌ کپشن باید ۳ یا ۴ خط باشه:\n"
            "3 lines:\nName\nAnime\nRarity\n\n"
            "4 lines:\nName\nAnime\nRarity\nEvent(optional)"
        )

    if len(lines) == 3:
        name, anime, rarity_line = lines
        event_line = ""
    else:
        name, anime, rarity_line, event_line = lines

    rarity_key = parse_rarity(rarity_line)
    if not rarity_key:
        return None, "❌ Rarity نامعتبره. مثال: 🌌 Cosmic"

    event_key = parse_event_optional(event_line)
    file_id = src.photo[-1].file_id

    return {
        "name": name,
        "anime": anime,
        "rarity_key": rarity_key,
        "event_key": event_key,
        "file_id": file_id
    }, None

def get_character(char_id: int):
    with db() as con:
        with con.cursor() as cur:
            cur.execute("""
                SELECT id, name, anime, rarity_key, event_key, image_file_id, channel_msg_id
                FROM characters WHERE id=%s
            """, (char_id,))
            row = cur.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "name": row[1],
        "anime": row[2],
        "rarity_key": row[3],
        "event_key": row[4],
        "image_file_id": row[5],
        "channel_msg_id": row[6],
    }

def repost_to_channel(char_id: int):
    c = get_character(char_id)
    if not c:
        raise Exception("Character not found in DB")

    if c["channel_msg_id"]:
        try:
            bot.delete_message(DB_CHAT_ID, c["channel_msg_id"])
        except Exception:
            pass

    r = RARITIES[c["rarity_key"]]
    e_title = event_title(c["event_key"])
    channel_caption = (
        "OWO! CHECK OUT THIS CHARACTER!\n\n"
        f"[ ANIME : {c['anime']} ]\n"
        f"[ ID : {c['id']} {c['name']} ]\n"
        f"[ RARITY : {r['emoji']} {r['title']} ]\n"
        f"[ EVENT : {e_title} ]\n\n"
        "➤ UPDATED/ADDED"
    )
    sent = bot.send_photo(DB_CHAT_ID, c["image_file_id"], caption=channel_caption)

    with db() as con:
        with con.cursor() as cur:
            cur.execute("UPDATE characters SET channel_msg_id=%s WHERE id=%s", (sent.message_id, char_id))
        con.commit()

# =========================
# SEARCH HELPERS
# =========================
def search_characters_in_db(query: str):
    q = (query or "").strip()
    if not q:
        return []
    like = f"%{q}%"

    with db() as con:
        with con.cursor() as cur:
            cur.execute("""
                SELECT id, name, anime, rarity_key, event_key, image_file_id
                FROM characters
                WHERE LOWER(name) LIKE LOWER(%s)
                   OR LOWER(anime) LIKE LOWER(%s)
                ORDER BY id ASC
            """, (like, like))
            rows = cur.fetchall()
    return rows

def short_search_preview(rows, limit=12):
    ids = [str(r[0]) for r in rows[:limit]]
    if not ids:
        return "—"
    more = ""
    if len(rows) > limit:
        more = f" (+{len(rows)-limit} more)"
    return ", ".join(ids) + more

# =========================
# Spawn System
# =========================
def get_or_create_chat_settings(chat_id: int):
    with db() as con:
        with con.cursor() as cur:
            cur.execute("SELECT spawn_enabled, spawn_every, msg_counter FROM chat_settings WHERE chat_id=%s", (chat_id,))
            row = cur.fetchone()
            if not row:
                cur.execute("""
                    INSERT INTO chat_settings (chat_id, spawn_enabled, spawn_every, msg_counter)
                    VALUES (%s, %s, %s, %s)
                """, (chat_id, DEFAULT_SPAWN_ENABLED, DEFAULT_SPAWN_EVERY, 0))
                con.commit()
                row = (DEFAULT_SPAWN_ENABLED, DEFAULT_SPAWN_EVERY, 0)
    return {"enabled": bool(row[0]), "every": int(row[1]), "counter": int(row[2])}

def set_chat_settings(chat_id: int, enabled=None, every=None):
    s = get_or_create_chat_settings(chat_id)
    enabled_val = (s["enabled"] if enabled is None else bool(enabled))
    every_val = s["every"] if every is None else int(every)
    if every_val < 1:
        every_val = 1
    with db() as con:
        with con.cursor() as cur:
            cur.execute("""
                UPDATE chat_settings
                SET spawn_enabled=%s, spawn_every=%s
                WHERE chat_id=%s
            """, (enabled_val, every_val, chat_id))
        con.commit()

def increment_counter(chat_id: int):
    s = get_or_create_chat_settings(chat_id)
    new_counter = s["counter"] + 1
    with db() as con:
        with con.cursor() as cur:
            cur.execute("UPDATE chat_settings SET msg_counter=%s WHERE chat_id=%s", (new_counter, chat_id))
        con.commit()
    return new_counter, s["every"], s["enabled"]

def has_active_spawn(chat_id: int):
    with db() as con:
        with con.cursor() as cur:
            cur.execute("SELECT char_id, spawned_msg_id, claimed_by FROM active_spawns WHERE chat_id=%s", (chat_id,))
            row = cur.fetchone()
    return row

def weighted_choice_rarity():
    items = [(k, float(v)) for k, v in RARITY_SPAWN_WEIGHTS.items() if float(v) > 0]
    if not items:
        return "common"
    total = sum(w for _, w in items)
    r = random.random() * total
    upto = 0.0
    for key, w in items:
        upto += w
        if upto >= r:
            return key
    return items[-1][0]

def pick_random_character_by_rarity(rarity_key: str):
    with db() as con:
        with con.cursor() as cur:
            cur.execute("SELECT id FROM characters WHERE rarity_key=%s ORDER BY RANDOM() LIMIT 1", (rarity_key,))
            row = cur.fetchone()
    return row[0] if row else None

def pick_random_character_any():
    with db() as con:
        with con.cursor() as cur:
            cur.execute("SELECT id FROM characters ORDER BY RANDOM() LIMIT 1")
            row = cur.fetchone()
    return row[0] if row else None

def spawn_character_in_chat(chat_id: int):
    active = has_active_spawn(chat_id)
    if active and active[2] is None:
        return None

    rarity_key = weighted_choice_rarity()
    cid = pick_random_character_by_rarity(rarity_key)
    if cid is None:
        cid = pick_random_character_any()
        if cid is None:
            return None

    c = get_character(cid)
    if not c:
        return None

    caption = (
        "✨ A new character has just spawned in the chat!\n"
        "Use /hunt [Name] to hunt them for yourself."
    )
    msg = bot.send_photo(chat_id, c["image_file_id"], caption=caption)

    with db() as con:
        with con.cursor() as cur:
            cur.execute("""
                INSERT INTO active_spawns (chat_id, char_id, spawned_msg_id, spawned_at, claimed_by, claimed_at)
                VALUES (%s, %s, %s, %s, NULL, NULL)
                ON CONFLICT (chat_id) DO UPDATE SET
                    char_id=EXCLUDED.char_id,
                    spawned_msg_id=EXCLUDED.spawned_msg_id,
                    spawned_at=EXCLUDED.spawned_at,
                    claimed_by=NULL,
                    claimed_at=NULL
            """, (chat_id, c["id"], msg.message_id, int(time.time())))
        con.commit()

    return c["id"]

def claim_spawn(chat_id: int, user_id: int):
    with db() as con:
        with con.cursor() as cur:
            cur.execute("SELECT char_id, spawned_msg_id, claimed_by FROM active_spawns WHERE chat_id=%s", (chat_id,))
            row = cur.fetchone()
            if not row:
                return (False, "❌ No active spawn.")
            char_id, spawned_msg_id, claimed_by = row
            if claimed_by is not None:
                return (False, "❌ This spawn is already claimed.")

            now = int(time.time())
            cur.execute("UPDATE active_spawns SET claimed_by=%s, claimed_at=%s WHERE chat_id=%s",
                        (user_id, now, chat_id))
            cur.execute("INSERT INTO inventory (user_id, chat_id, char_id, obtained_at) VALUES (%s, %s, %s, %s)",
                        (user_id, chat_id, char_id, now))
        con.commit()
    return (True, (char_id, spawned_msg_id))

def name_matches(user_text: str, real_name: str) -> bool:
    u = normalize(user_text)
    r = normalize(real_name)
    if not u or len(u) < 2:
        return False
    return (u == r)

# =========================
# HAREM + FAV helpers
# =========================
def get_user_fav_char_id(user_id: int):
    with db() as con:
        with con.cursor() as cur:
            cur.execute("SELECT char_id FROM favorites WHERE user_id=%s", (user_id,))
            row = cur.fetchone()
    return int(row[0]) if row else None

def user_owns_char_in_chat(chat_id: int, user_id: int, char_id: int) -> bool:
    with db() as con:
        with con.cursor() as cur:
            cur.execute("""
                SELECT 1 FROM inventory
                WHERE chat_id=%s AND user_id=%s AND char_id=%s
                LIMIT 1
            """, (chat_id, user_id, char_id))
            ok = cur.fetchone() is not None
    return ok

def get_harem_cover_file_id(chat_id: int, user_id: int):
    fav_id = get_user_fav_char_id(user_id)
    if fav_id and user_owns_char_in_chat(chat_id, user_id, fav_id):
        c = get_character(fav_id)
        if c:
            return c["image_file_id"]

    with db() as con:
        with con.cursor() as cur:
            cur.execute("""
                SELECT c.image_file_id
                FROM inventory i
                JOIN characters c ON c.id=i.char_id
                WHERE i.chat_id=%s AND i.user_id=%s
                ORDER BY i.obtained_at DESC
                LIMIT 1
            """, (chat_id, user_id))
            row = cur.fetchone()
    return row[0] if row else None

def get_user_collection_counts(chat_id: int, user_id: int):
    with db() as con:
        with con.cursor() as cur:
            cur.execute("""
                SELECT c.anime, c.id, c.name, c.rarity_key, c.event_key, COUNT(*) as cnt
                FROM inventory i
                JOIN characters c ON c.id = i.char_id
                WHERE i.chat_id=%s AND i.user_id=%s
                GROUP BY c.anime, c.id, c.name, c.rarity_key, c.event_key
                ORDER BY LOWER(c.anime) ASC, c.id ASC
            """, (chat_id, user_id))
            rows = cur.fetchall()

    if not rows:
        return 0, []

    per = {}
    for anime, cid, name, rk, ek, cnt in rows:
        if anime not in per:
            per[anime] = {"anime": anime, "total_unique": 0, "samples": []}
        per[anime]["total_unique"] += 1
        if len(per[anime]["samples"]) < 6:
            per[anime]["samples"].append((cid, name, rk, ek, cnt))

    per_list = list(per.values())
    total_unique = sum(x["total_unique"] for x in per_list)
    return total_unique, per_list

def render_harem_page(title_name: str, total_unique: int, per_anime: list, page: int, page_size: int = 4):
    total_pages = max(1, (len(per_anime) + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))
    start = (page - 1) * page_size
    chunk = per_anime[start:start + page_size]

    lines = []
    lines.append(f"🗂 {title_name}'s Harem — Page: {page}/{total_pages}")
    lines.append("")
    for block in chunk:
        anime = block["anime"]
        lines.append(f"⚜️ {anime} ({block['total_unique']})")
        lines.append("————————————")
        for (cid, name, rk, ek, cnt) in block["samples"]:
            r = RARITIES.get(rk, {"emoji": "❔", "title": rk})
            extra = f" (x{cnt})" if cnt and cnt > 1 else ""
            lines.append(f"{r['emoji']} [{cid}] | {name}{extra}")
        lines.append("")

    return "\n".join(lines).strip(), total_pages, page

def harem_keyboard(total_unique: int, page: int, total_pages: int, target_user_id: int):
    kb = types.InlineKeyboardMarkup(row_width=3)
    row = []
    if page > 1:
        row.append(types.InlineKeyboardButton("⬅️", callback_data=f"harem:{page-1}:{target_user_id}"))
    row.append(types.InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        row.append(types.InlineKeyboardButton("➡️", callback_data=f"harem:{page+1}:{target_user_id}"))
    kb.row(*row)

    kb.row(types.InlineKeyboardButton(
        f"See Collection ({total_unique})",
        switch_inline_query_current_chat=f"mycards {target_user_id}"
    ))
    return kb

def rarity_deck_stats(user_id: int):
    with db() as con:
        with con.cursor() as cur:
            cur.execute("""
                SELECT rarity_key, COUNT(*)
                FROM characters
                GROUP BY rarity_key
            """)
            total_rows = cur.fetchall()
            total_map = {rk: int(cnt) for rk, cnt in total_rows}

            cur.execute("""
                SELECT c.rarity_key, COUNT(DISTINCT i.char_id)
                FROM inventory i
                JOIN characters c ON c.id = i.char_id
                WHERE i.user_id=%s
                GROUP BY c.rarity_key
            """, (user_id,))
            owned_rows = cur.fetchall()
            owned_map = {rk: int(cnt) for rk, cnt in owned_rows}

    for rk in RARITIES.keys():
        total_map.setdefault(rk, 0)
        owned_map.setdefault(rk, 0)

    return total_map, owned_map

# =========================
# Commands
# =========================
@bot.message_handler(commands=["start"])
def start(message):
    role = "OWNER" if is_owner(message.from_user.id) else ("UPLOADER" if is_uploader(message.from_user.id) else "USER")
    bot.reply_to(
        message,
        f"✅ Bot is online!\n{VERSION}\nRole: {role}\n\n"
        "Player:\n"
        "- /hunt Name   (example: /hunt Rangiku)\n"
        "- /harem (or reply to someone: /harem)\n"
        "- /fav ID   (set harem cover)\n"
        "- /search text (search cards in DB)\n\n"
        "Owner (spawn settings per chat):\n"
        "- /changetime 20\n"
        "- /spawn on | /spawn off\n"
        "- /spawnstatus\n"
        "- /forcespawn\n"
        "- /clearspawn\n"
        "- /reset (reply to user)\n\n"
        "Uploader:\n"
        "- reply /upload\n"
        "- reply /uploadid 25\n\n"
        "Owner edit:\n"
        "- /delete 25\n"
        "- /update 25 name New Name\n"
        "- /update 25 anime New Anime\n"
        "- /update 25 rarity 🌌 Cosmic\n"
        "- /update 25 event none\n"
        "- reply /updatephoto 25\n"
        "- /check 25\n"
        "- /rarity\n"
    )

@bot.message_handler(commands=["ping"])
def ping(message):
    bot.reply_to(message, "🏓 Pong!")

# =========================
# /search
# =========================
@bot.message_handler(regexp=r"^/search(\s+.+)?$")
def search_cmd(message):
    m = re.match(r"^/search\s+(.+)$", (message.text or "").strip(), flags=re.I)
    if not m:
        return bot.reply_to(message, "Usage: /search NameOrAnime\nExample: /search Rangiku")

    q = m.group(1).strip()
    rows = search_characters_in_db(q)

    kb = types.InlineKeyboardMarkup()
    kb.row(types.InlineKeyboardButton("🔍 View results (inline)", switch_inline_query_current_chat=f"search {q}"))

    if not rows:
        return bot.reply_to(message, f"❌ No cards found for: {q}", reply_markup=kb)

    preview = short_search_preview(rows, limit=12)
    bot.reply_to(
        message,
        f"✅ Search results for: {q}\n"
        f"Found: {len(rows)} card(s)\n"
        f"IDs: {preview}",
        reply_markup=kb
    )

# =========================
# Spawn settings (Owner)
# =========================
@bot.message_handler(regexp=r"^/changetime(\s+\d+)?$")
def changetime(message):
    if not is_owner(message.from_user.id):
        return
    if message.chat.type not in ("group", "supergroup"):
        return bot.reply_to(message, "Use in group.")
    m = re.match(r"^/changetime\s+(\d+)$", (message.text or "").strip())
    if not m:
        return bot.reply_to(message, "Usage: /changetime 20")
    n = int(m.group(1))
    if n < 1:
        return bot.reply_to(message, "❌ عدد باید حداقل 1 باشه.")
    set_chat_settings(message.chat.id, every=n)
    bot.reply_to(message, f"✅ Spawn interval set to every {n} messages (this chat).")

@bot.message_handler(regexp=r"^/spawn(\s+(on|off))?$")
def spawn_toggle(message):
    if not is_owner(message.from_user.id):
        return
    if message.chat.type not in ("group", "supergroup"):
        return bot.reply_to(message, "Use in group.")
    m = re.match(r"^/spawn\s+(on|off)$", (message.text or "").strip())
    if not m:
        return bot.reply_to(message, "Usage: /spawn on  OR  /spawn off")
    val = (m.group(1) == "on")
    set_chat_settings(message.chat.id, enabled=val)
    bot.reply_to(message, f"✅ Spawn {'enabled' if val else 'disabled'} for this chat.")

# =========================
# Spawn debug (Owner)
# =========================
@bot.message_handler(commands=["spawnstatus"])
def spawn_status(message):
    if message.chat.type not in ("group", "supergroup"):
        return bot.reply_to(message, "Use in group.")
    s = get_or_create_chat_settings(message.chat.id)
    active = has_active_spawn(message.chat.id)

    txt = (
        f"📊 Spawn Status\n"
        f"- enabled: {s['enabled']}\n"
        f"- every: {s['every']}\n"
        f"- counter: {s['counter']}\n"
    )
    if active:
        txt += f"- active_spawn: YES | char_id={active[0]} | claimed_by={active[2]}\n"
        if active[2] is None:
            txt += "⚠️ Active spawn is UNCLAIMED → new spawns are blocked until hunted.\n"
    else:
        txt += "- active_spawn: NO\n"
    bot.reply_to(message, txt)

@bot.message_handler(commands=["forcespawn"])
def force_spawn(message):
    if not is_owner(message.from_user.id):
        return
    if message.chat.type not in ("group", "supergroup"):
        return bot.reply_to(message, "Use in group.")
    try:
        cid = spawn_character_in_chat(message.chat.id)
        if cid is None:
            bot.reply_to(message, "❌ Force spawn failed (maybe no characters in DB OR active spawn locked).")
        else:
            bot.reply_to(message, f"✅ Forced spawn done. char_id={cid}")
    except Exception as e:
        bot.reply_to(message, f"❌ Force spawn error:\n{e}")

@bot.message_handler(commands=["clearspawn"])
def clear_spawn(message):
    if not is_owner(message.from_user.id):
        return
    if message.chat.type not in ("group", "supergroup"):
        return bot.reply_to(message, "Use in group.")
    with db() as con:
        with con.cursor() as cur:
            cur.execute("DELETE FROM active_spawns WHERE chat_id=%s", (message.chat.id,))
        con.commit()
    bot.reply_to(message, "✅ Active spawn cleared for this chat.")

# =========================
# Hunt (Players)
# =========================
@bot.message_handler(regexp=r"^/hunt(\s+.+)?$")
def hunt_cmd(message):
    if message.chat.type == "private":
        return bot.reply_to(message, "❌ /hunt works only inside groups.")

    m = re.match(r"^/hunt\s+(.+)$", (message.text or "").strip())
    if not m:
        return bot.reply_to(message, "Usage: /hunt Name\nExample: /hunt Rangiku")

    guess = m.group(1).strip()

    with db() as con:
        with con.cursor() as cur:
            cur.execute("SELECT char_id, claimed_by FROM active_spawns WHERE chat_id=%s", (message.chat.id,))
            row = cur.fetchone()

    if not row:
        return bot.reply_to(message, "❌ No active spawn right now.")

    char_id, claimed_by = row
    if claimed_by is not None:
        return bot.reply_to(message, "❌ This character is already claimed.")

    c = get_character(char_id)
    if not c:
        return bot.reply_to(message, "❌ Spawn data not found.")

    if not name_matches(guess, c["name"]):
        return bot.reply_to(message, "❌ Wrong name!")

    # GLOBAL CAPACITY 25
    with db() as con:
        with con.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM inventory WHERE user_id=%s", (message.from_user.id,))
            count = int(cur.fetchone()[0] or 0)

    MAX_CAPACITY = 25
    if count >= MAX_CAPACITY:
        return bot.reply_to(
            message,
            "🚫 Storage Limit Reached!\n\n"
            "Your total collection capacity is full (25/25).\n"
            "You can't hunt more characters until the Owner resets your storage."
        )

    ok, info = claim_spawn(message.chat.id, message.from_user.id)
    if not ok:
        return bot.reply_to(message, info)

    r = RARITIES[c["rarity_key"]]
    e_title = event_title(c["event_key"])

    bot.reply_to(
        message,
        f"🏹 {message.from_user.first_name} claimed!\n"
        f"ID: {c['id']} | {c['name']} ({c['anime']})\n"
        f"{r['emoji']} {r['title']} | Event: {e_title}"
    )

@bot.message_handler(commands=["reset"])
def reset_collection(message):
    if not is_owner(message.from_user.id):
        return bot.reply_to(message, "⛔ Only the Owner can use this command.")

    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
        target_name = message.reply_to_message.from_user.first_name
    else:
        target_id = message.from_user.id
        target_name = message.from_user.first_name

    with db() as con:
        with con.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM inventory WHERE user_id=%s", (target_id,))
            total = int(cur.fetchone()[0] or 0)
            cur.execute("DELETE FROM inventory WHERE user_id=%s", (target_id,))
        con.commit()

    bot.reply_to(
        message,
        f"♻️ {target_name}'s storage has been fully reset.\n"
        f"{total} cards removed.\n"
        f"They can now collect up to 25 new characters again."
    )

# =========================
# /fav
# =========================
@bot.message_handler(regexp=r"^/fav(\s+\d+)?$")
def fav_cmd(message):
    if message.chat.type == "private":
        return bot.reply_to(message, "❌ /fav فقط داخل گروه کار می‌کنه.")
    m = re.match(r"^/fav\s+(\d+)$", (message.text or "").strip())
    if not m:
        return bot.reply_to(message, "Usage: /fav ID (مثال: /fav 25)")
    cid = int(m.group(1))
    if not get_character(cid):
        return bot.reply_to(message, "❌ این ID وجود نداره.")
    if not user_owns_char_in_chat(message.chat.id, message.from_user.id, cid):
        return bot.reply_to(message, "❌ این کارت رو توی همین گروه نداری.")

    with db() as con:
        with con.cursor() as cur:
            cur.execute("""
                INSERT INTO favorites (user_id, char_id)
                VALUES (%s, %s)
                ON CONFLICT (user_id) DO UPDATE SET char_id=EXCLUDED.char_id
            """, (message.from_user.id, cid))
        con.commit()

    bot.reply_to(message, f"✅ Favorite set to #{cid} (for your /harem cover).")

# =========================
# /harem
# =========================
@bot.message_handler(commands=["harem"])
def harem_cmd(message):
    if message.chat.type == "private":
        return bot.reply_to(message, "❌ /harem فقط داخل گروه کار می‌کنه.")

    target_user_id = message.from_user.id
    target_name = message.from_user.first_name

    if message.reply_to_message and message.reply_to_message.from_user:
        target_user_id = message.reply_to_message.from_user.id
        target_name = message.reply_to_message.from_user.first_name

    total_unique, per_anime = get_user_collection_counts(message.chat.id, target_user_id)
    if total_unique == 0:
        return bot.reply_to(message, "You Have Not Hunted any Characters Yet.")

    cover = get_harem_cover_file_id(message.chat.id, target_user_id)
    text, total_pages, page = render_harem_page(target_name, total_unique, per_anime, page=1)
    kb = harem_keyboard(total_unique, page, total_pages, target_user_id)

    if cover:
        bot.send_photo(message.chat.id, cover, caption=text, reply_markup=kb)
    else:
        bot.reply_to(message, text, reply_markup=kb)

@bot.callback_query_handler(func=lambda call: call.data and call.data.startswith("harem:"))
def harem_page_callback(call):
    try:
        _, page_str, target_str = call.data.split(":")
        page = int(page_str)
        target_user_id = int(target_str)
    except:
        return bot.answer_callback_query(call.id)

    chat_id = call.message.chat.id

    total_unique, per_anime = get_user_collection_counts(chat_id, target_user_id)
    if total_unique == 0:
        bot.answer_callback_query(call.id, "No cards.")
        try:
            bot.edit_message_caption("You Have Not Hunted any Characters Yet.", chat_id, call.message.message_id)
        except:
            try:
                bot.edit_message_text("You Have Not Hunted any Characters Yet.", chat_id, call.message.message_id)
            except:
                pass
        return

    title_name = "Harem"
    try:
        u = bot.get_chat(target_user_id)
        title_name = u.first_name or "Player"
    except:
        title_name = "Player"

    text, total_pages, page = render_harem_page(title_name, total_unique, per_anime, page=page)
    kb = harem_keyboard(total_unique, page, total_pages, target_user_id)

    try:
        bot.edit_message_caption(chat_id=chat_id, message_id=call.message.message_id, caption=text, reply_markup=kb)
    except:
        try:
            bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text=text, reply_markup=kb)
        except:
            pass

    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "noop")
def noop(call):
    bot.answer_callback_query(call.id)

# =========================
# Inline Mode: mycards + search
# =========================
@bot.inline_handler(func=lambda inline_query: True)
def inline_handler(inline_query):
    q_raw = (inline_query.query or "").strip()
    q = q_raw.lower()

    # SEARCH MODE
    if q.startswith("search "):
        search_text = q_raw[7:].strip()
        rows = search_characters_in_db(search_text)

        if not rows:
            results = [
                types.InlineQueryResultArticle(
                    id="search_empty",
                    title="No results",
                    input_message_content=types.InputTextMessageContent(f"No cards found for: {search_text}")
                )
            ]
            bot.answer_inline_query(inline_query.id, results, cache_time=1, is_personal=False)
            return

        try:
            offset = int(inline_query.offset or "0")
        except:
            offset = 0

        page_size = 15
        chunk = rows[offset:offset + page_size]
        next_offset = str(offset + page_size) if (offset + page_size) < len(rows) else ""

        results = []
        for idx, (cid, name, anime, rk, ek, file_id) in enumerate(chunk):
            r = RARITIES.get(rk, {"emoji": "❔", "title": rk})
            e_title = event_title(ek)
            caption = f"ID: {cid} | {name} ({anime})\n{r['emoji']} {r['title']} | Event: {e_title}"

            results.append(
                types.InlineQueryResultCachedPhoto(
                    id=f"search_{cid}_{offset}_{idx}",
                    photo_file_id=file_id,
                    caption=caption
                )
            )

        bot.answer_inline_query(
            inline_query.id,
            results,
            cache_time=1,
            is_personal=False,
            next_offset=next_offset
        )
        return

    # MYCARDS MODE
    if not q.startswith("mycards"):
        return

    m = re.match(r"^mycards\s+(\d+)$", q_raw.strip(), flags=re.I)
    if m:
        target_user_id = int(m.group(1))
    else:
        target_user_id = inline_query.from_user.id

    with db() as con:
        with con.cursor() as cur:
            cur.execute("""
                SELECT c.id, c.name, c.anime, c.rarity_key, c.event_key, c.image_file_id, COUNT(*) as cnt
                FROM inventory i
                JOIN characters c ON c.id = i.char_id
                WHERE i.user_id=%s
                GROUP BY c.id, c.name, c.anime, c.rarity_key, c.event_key, c.image_file_id
                ORDER BY c.id ASC
            """, (target_user_id,))
            rows = cur.fetchall()

    if not rows:
        results = [
            types.InlineQueryResultArticle(
                id="empty",
                title="No characters yet",
                input_message_content=types.InputTextMessageContent("No characters yet.")
            )
        ]
        bot.answer_inline_query(inline_query.id, results, cache_time=1, is_personal=True)
        return

    try:
        offset = int(inline_query.offset or "0")
    except:
        offset = 0

    page_size = 15
    chunk = rows[offset:offset + page_size]
    next_offset = str(offset + page_size) if (offset + page_size) < len(rows) else ""

    results = []
    for idx, (cid, name, anime, rk, ek, file_id, cnt) in enumerate(chunk):
        r = RARITIES.get(rk, {"emoji": "❔", "title": rk})
        e_title = event_title(ek)
        extra = f" (x{cnt})" if cnt and cnt > 1 else ""
        caption = f"ID: {cid} | {name}{extra} ({anime})\n{r['emoji']} {r['title']} | Event: {e_title}"

        results.append(
            types.InlineQueryResultCachedPhoto(
                id=f"{cid}_{offset}_{idx}",
                photo_file_id=file_id,
                caption=caption
            )
        )

    bot.answer_inline_query(
        inline_query.id,
        results,
        cache_time=1,
        is_personal=True,
        next_offset=next_offset
    )

# =========================
# Uploader/Admin management
# =========================
@bot.message_handler(commands=["adduploader"])
def add_uploader(message):
    if not is_owner(message.from_user.id):
        return bot.reply_to(message, "⛔ فقط Owner.")
    if not message.reply_to_message:
        return bot.reply_to(message, "❌ روی پیام شخص ریپلای کن بعد /adduploader بزن.")
    target = message.reply_to_message.from_user
    with db() as con:
        with con.cursor() as cur:
            cur.execute("""
                INSERT INTO uploaders (tg_id, added_by, added_at)
                VALUES (%s, %s, %s)
                ON CONFLICT (tg_id) DO NOTHING
            """, (target.id, OWNER_ID, int(time.time())))
        con.commit()
    bot.reply_to(message, f"✅ Uploader added: {target.first_name} (ID: {target.id})")

@bot.message_handler(commands=["deluploader"])
def del_uploader(message):
    if not is_owner(message.from_user.id):
        return bot.reply_to(message, "⛔ فقط Owner.")
    if not message.reply_to_message:
        return bot.reply_to(message, "❌ روی پیام شخص ریپلای کن بعد /deluploader بزن.")
    target = message.reply_to_message.from_user
    with db() as con:
        with con.cursor() as cur:
            cur.execute("DELETE FROM uploaders WHERE tg_id=%s", (target.id,))
        con.commit()
    bot.reply_to(message, f"🗑 Uploader removed: {target.first_name} (ID: {target.id})")

# =========================
# Upload / UploadID
# =========================
@bot.message_handler(commands=["upload"])
def upload_auto(message):
    if not is_uploader(message.from_user.id):
        return bot.reply_to(message, "⛔ You are not an uploader.")
    card, err = extract_card_from_reply(message)
    if err:
        return bot.reply_to(message, err)

    with db() as con:
        with con.cursor() as cur:
            cur.execute("""
                INSERT INTO characters (name, anime, rarity_key, event_key, image_file_id, uploaded_by, uploaded_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                card["name"], card["anime"], card["rarity_key"], card["event_key"],
                card["file_id"], message.from_user.id, int(time.time())
            ))
            new_id = int(cur.fetchone()[0])
        con.commit()

    try:
        repost_to_channel(new_id)
        bot.reply_to(message, f"✅ Uploaded #{new_id} and posted to {DB_CHANNEL_USERNAME}")
    except Exception as ex:
        bot.reply_to(message, f"✅ Uploaded #{new_id} (DB saved)\n⚠️ Channel post failed:\n{ex}")

@bot.message_handler(regexp=r"^/uploadid(\s+\d+)?$")
def upload_manual_id(message):
    if not is_uploader(message.from_user.id):
        return bot.reply_to(message, "⛔ You are not an uploader.")
    m = re.match(r"^/uploadid\s+(\d+)$", (message.text or "").strip())
    if not m:
        return bot.reply_to(message, "Usage: /uploadid 25 (reply to photo)")
    desired_id = int(m.group(1))
    if desired_id <= 0:
        return bot.reply_to(message, "❌ ID باید مثبت باشه.")

    card, err = extract_card_from_reply(message)
    if err:
        return bot.reply_to(message, err)

    with db() as con:
        with con.cursor() as cur:
            cur.execute("SELECT 1 FROM characters WHERE id=%s", (desired_id,))
            if cur.fetchone():
                return bot.reply_to(message, f"❌ ID {desired_id} قبلاً وجود داره.")

            cur.execute("""
                INSERT INTO characters (id, name, anime, rarity_key, event_key, image_file_id, uploaded_by, uploaded_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                desired_id, card["name"], card["anime"], card["rarity_key"], card["event_key"],
                card["file_id"], message.from_user.id, int(time.time())
            ))
        con.commit()

    try:
        repost_to_channel(desired_id)
        bot.reply_to(message, f"✅ Uploaded with ID #{desired_id} and posted to {DB_CHANNEL_USERNAME}")
    except Exception as ex:
        bot.reply_to(message, f"✅ Uploaded with ID #{desired_id} (DB saved)\n⚠️ Channel post failed:\n{ex}")

# =========================
# Delete
# =========================
@bot.message_handler(regexp=r"^/delete(\s+\d+)?$")
def delete_character_cmd(message):
    if not is_owner(message.from_user.id):
        return
    m = re.match(r"^/delete\s+(\d+)$", (message.text or "").strip())
    if not m:
        return bot.reply_to(message, "Usage: /delete 25")
    char_id = int(m.group(1))
    c = get_character(char_id)
    if not c:
        return bot.reply_to(message, "❌ not found.")

    with db() as con:
        with con.cursor() as cur:
            cur.execute("DELETE FROM characters WHERE id=%s", (char_id,))
            cur.execute("DELETE FROM inventory WHERE char_id=%s", (char_id,))
            cur.execute("DELETE FROM active_spawns WHERE char_id=%s", (char_id,))
        con.commit()

    if c["channel_msg_id"]:
        try:
            bot.delete_message(DB_CHAT_ID, c["channel_msg_id"])
        except Exception:
            pass

    bot.reply_to(message, f"🗑 Deleted #{char_id} ✅")

# =========================
# Update fields + Update photo
# =========================
@bot.message_handler(regexp=r"^/update(\s+.+)?$")
def update_field_cmd(message):
    if not is_owner(message.from_user.id):
        return
    parts = (message.text or "").strip().split(maxsplit=3)
    if len(parts) < 4:
        return bot.reply_to(message,
                            "Usage:\n"
                            "/update 25 name New Name\n"
                            "/update 25 anime New Anime\n"
                            "/update 25 rarity 🌌 Cosmic\n"
                            "/update 25 event none")
    _, sid, field, new_value = parts
    try:
        char_id = int(sid)
    except:
        return bot.reply_to(message, "❌ ID باید عدد باشه.")
    c = get_character(char_id)
    if not c:
        return bot.reply_to(message, "❌ not found.")

    field = field.lower().strip()

    with db() as con:
        with con.cursor() as cur:
            if field == "name":
                cur.execute("UPDATE characters SET name=%s WHERE id=%s", (new_value.strip(), char_id))
            elif field == "anime":
                cur.execute("UPDATE characters SET anime=%s WHERE id=%s", (new_value.strip(), char_id))
            elif field == "rarity":
                rk = parse_rarity(new_value)
                if not rk:
                    return bot.reply_to(message, "❌ Rarity نامعتبره. مثال: 🌌 Cosmic")
                cur.execute("UPDATE characters SET rarity_key=%s WHERE id=%s", (rk, char_id))
            elif field == "event":
                ek = parse_event_optional(new_value)
                cur.execute("UPDATE characters SET event_key=%s WHERE id=%s", (ek, char_id))
            else:
                return bot.reply_to(message, "❌ field فقط: name | anime | rarity | event")
        con.commit()

    try:
        repost_to_channel(char_id)
    except Exception:
        pass

    bot.reply_to(message, f"✅ Updated #{char_id} ({field})")

@bot.message_handler(regexp=r"^/updatephoto(\s+\d+)?$")
def update_photo_cmd(message):
    if not is_owner(message.from_user.id):
        return
    m = re.match(r"^/updatephoto\s+(\d+)$", (message.text or "").strip())
    if not m:
        return bot.reply_to(message, "Usage: reply to NEW photo: /updatephoto 25")
    char_id = int(m.group(1))
    c = get_character(char_id)
    if not c:
        return bot.reply_to(message, "❌ not found.")
    if not message.reply_to_message or not message.reply_to_message.photo:
        return bot.reply_to(message, "❌ باید روی عکس جدید ریپلای کنی.")
    new_file_id = message.reply_to_message.photo[-1].file_id

    with db() as con:
        with con.cursor() as cur:
            cur.execute("UPDATE characters SET image_file_id=%s WHERE id=%s", (new_file_id, char_id))
        con.commit()

    try:
        repost_to_channel(char_id)
    except Exception:
        pass

    bot.reply_to(message, f"🖼 Updated photo for #{char_id} ✅")

# =========================
# /rarity
# =========================
@bot.message_handler(commands=["rarity"])
def rarity_cmd(message):
    user_id = message.from_user.id
    total_map, owned_map = rarity_deck_stats(user_id)

    total_owned_all = sum(owned_map.values())
    total_all = sum(total_map.values())

    lines = []
    lines.append(f"🗂 {message.from_user.first_name}'s Rarity Deck")
    lines.append(f"Total Collected: {total_owned_all} (unique)")
    lines.append(f"Collection: {total_owned_all}/{total_all} ({(total_owned_all/total_all*100 if total_all else 0):.1f}%)")
    lines.append("————————————")

    order = ["oblivion","infinity","transcendent","cosmic","flat","legendary","epic","rare","common"]

    for rk in order:
        meta = RARITIES.get(rk, {"emoji": "❔", "title": rk})
        owned = owned_map.get(rk, 0)
        total = total_map.get(rk, 0)
        pct = (owned / total * 100) if total else 0.0

        lines.append(f"{meta['emoji']} {meta['title']} ({owned}/{total})")
        lines.append(f"Progress: {pct:.0f}%")
        lines.append("")

    bot.reply_to(message, "\n".join(lines))

# =========================
# /check
# =========================
def get_card_global_stats(char_id: int):
    with db() as con:
        with con.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM inventory WHERE char_id=%s", (char_id,))
            total_copies = int(cur.fetchone()[0] or 0)

            cur.execute("SELECT COUNT(DISTINCT user_id) FROM inventory WHERE char_id=%s", (char_id,))
            total_unique_users = int(cur.fetchone()[0] or 0)

            cur.execute("""
                SELECT user_id, COUNT(*) as cnt
                FROM inventory
                WHERE char_id=%s
                GROUP BY user_id
                ORDER BY cnt DESC
                LIMIT 10
            """, (char_id,))
            top_users = cur.fetchall()

    return total_copies, total_unique_users, top_users

@bot.message_handler(regexp=r"^/check(\s+\d+)?$")
def check_cmd(message):
    m = re.match(r"^/check\s+(\d+)$", (message.text or "").strip())
    if not m:
        return bot.reply_to(message, "Usage: /check 25")

    char_id = int(m.group(1))
    c = get_character(char_id)
    if not c:
        return bot.reply_to(message, "❌ Character not found.")

    total_copies, total_unique_users, top_users = get_card_global_stats(char_id)

    r = RARITIES.get(c["rarity_key"], {"emoji": "❔", "title": c["rarity_key"]})
    e_title = event_title(c["event_key"])

    lines = []
    lines.append(f"🔎 Card Check — ID: {c['id']}")
    lines.append(f"👤 Name: {c['name']}")
    lines.append(f"🎬 Anime: {c['anime']}")
    lines.append(f"✨ Rarity: {r['emoji']} {r['title']}")
    lines.append(f"🎉 Event: {e_title}")
    lines.append("")
    lines.append(f"📦 Total Obtained (all chats): {total_copies}")
    lines.append(f"👥 Unique Owners: {total_unique_users}")
    lines.append("")
    lines.append("🏆 Top Owners (Top 10):")

    if not top_users:
        lines.append("— None")
    else:
        for i, (uid, cnt) in enumerate(top_users, start=1):
            try:
                u = bot.get_chat(uid)
                name = (u.first_name or "User").strip()
                if u.username:
                    name = f"@{u.username}"
            except Exception:
                name = str(uid)
            lines.append(f"{i}. {name} — x{cnt}")

    text = "\n".join(lines)

    try:
        bot.send_photo(message.chat.id, c["image_file_id"], caption=text)
    except Exception:
        bot.reply_to(message, text)

# =========================
# Message counter -> spawn every N messages
# =========================
@bot.message_handler(func=lambda m: True, content_types=["text", "photo", "sticker", "video", "animation", "document"])
def every_message_counter(message):
    if message.chat.type not in ("group", "supergroup"):
        return

    if message.content_type == "text" and message.text and message.text.startswith("/"):
        return

    counter, every, enabled = increment_counter(message.chat.id)
    if not enabled or every <= 0:
        return

    if counter % every == 0:
        try:
            spawn_character_in_chat(message.chat.id)
        except Exception as e:
            print("spawn error:", e)

print("Bot is running...")
bot.infinity_polling(timeout=30, long_polling_timeout=30)import re
import time
import random
import os

import psycopg
import telebot
from telebot import types

# =========================
# تنظیمات اصلی
# =========================
TOKEN = os.environ.get("TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")

OWNER_ID = 2043594987
DB_CHANNEL_USERNAME = "@hunter_database"  # کانال دیتابیس
VERSION = "HunterBot v13 (Neon/Postgres build)"

if not TOKEN:
    raise RuntimeError("TOKEN env is missing")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL env is missing")

bot = telebot.TeleBot(TOKEN, parse_mode=None)

# =========================
# RARITY / EVENTS
# =========================
RARITIES = {
    "common":       {"emoji": "🔵", "title": "Common"},
    "rare":         {"emoji": "🟠", "title": "Rare"},
    "epic":         {"emoji": "🟣", "title": "Epic"},
    "legendary":    {"emoji": "🟡", "title": "Legendary"},
    "flat":         {"emoji": "🔮", "title": "Flat"},
    "transcendent": {"emoji": "🪞", "title": "Transcendent"},
    "cosmic":       {"emoji": "🌌", "title": "Cosmic"},
    "infinity":     {"emoji": "♾️", "title": "Infinity"},
    "oblivion":     {"emoji": "🩸", "title": "Oblivion"},
}

EVENTS = {
    "post_apocalyptic_survivor": "Post-Apocalyptic Survivor ☢️",
    "space_explorer": "Space Explorer 🚀",
    "festival_fireworks": "Festival Fireworks 🎆",
    "monster_side": "Monster Side🐉",
    "rome": "Rome 🏰",
    "halloween": "Halloween 🎃",
    "valentine": "Valentine 💝",
    "wedding": "Wedding 💍",
    "school": "School 🏫",
    "cosplay": "Cosplay 🎭",
    "winter": "Winter ❄️",
    "christmas": "Christmas 🎄",
    "summer": "Summer 🏖",
    "gamer": "Gamer 🎮",
    "police": "𝗣𝗢𝗟𝗜𝗖𝗘 🚨",
    "doctor": "Doctor 🧬",
    "maid": "Maid 🧹",
    "idol": "Idol 🎤",
    "office_lady": "Office Lady 💼",
    "sports": "sports ⚽️",
    "warrior": "warrior 🛡",
}

NO_EVENT_KEY = "none"
NO_EVENT_TITLE = "None"

# =========================
# Spawn config (قابل تغییر)
# =========================
RARITY_SPAWN_WEIGHTS = {
    "common": 60,
    "rare": 25,
    "epic": 10,
    "legendary": 4,
    "flat": 1,
    "transcendent": 0.4,
    "cosmic": 0.1,
    "infinity": 0,
    "oblivion": 0,
}

DEFAULT_SPAWN_EVERY = 100
DEFAULT_SPAWN_ENABLED = True

# =========================
# DB (Postgres / Neon)
# =========================
def db():
    # Neon/Postgres
    return psycopg.connect(DATABASE_URL, autocommit=False)

def init_db():
    with db() as con:
        with con.cursor() as cur:
            cur.execute("""
            CREATE TABLE IF NOT EXISTS uploaders (
                tg_id BIGINT PRIMARY KEY,
                added_by BIGINT NOT NULL,
                added_at BIGINT NOT NULL
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS characters (
                id BIGSERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                anime TEXT NOT NULL,
                rarity_key TEXT NOT NULL,
                event_key TEXT NOT NULL,
                image_file_id TEXT NOT NULL,
                channel_msg_id BIGINT,
                uploaded_by BIGINT NOT NULL,
                uploaded_at BIGINT NOT NULL
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS chat_settings (
                chat_id BIGINT PRIMARY KEY,
                spawn_enabled BOOLEAN NOT NULL,
                spawn_every INTEGER NOT NULL,
                msg_counter BIGINT NOT NULL
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS active_spawns (
                chat_id BIGINT PRIMARY KEY,
                char_id BIGINT NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
                spawned_msg_id BIGINT NOT NULL,
                spawned_at BIGINT NOT NULL,
                claimed_by BIGINT,
                claimed_at BIGINT
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS inventory (
                id BIGSERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                chat_id BIGINT NOT NULL,
                char_id BIGINT NOT NULL REFERENCES characters(id) ON DELETE CASCADE,
                obtained_at BIGINT NOT NULL
            )
            """)

            cur.execute("""
            CREATE TABLE IF NOT EXISTS favorites (
                user_id BIGINT PRIMARY KEY,
                char_id BIGINT NOT NULL REFERENCES characters(id) ON DELETE CASCADE
            )
            """)

            # indexes
            cur.execute("CREATE INDEX IF NOT EXISTS idx_inventory_user ON inventory(user_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_inventory_chat_user ON inventory(chat_id, user_id)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_characters_rarity ON characters(rarity_key)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_characters_name ON characters(name)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_characters_anime ON characters(anime)")

        con.commit()

init_db()

# =========================
# Resolve DB channel chat_id
# =========================
DB_CHAT_ID = None

def resolve_db_chat_id():
    global DB_CHAT_ID
    try:
        chat = bot.get_chat(DB_CHANNEL_USERNAME)
        DB_CHAT_ID = chat.id
        print("DB channel resolved:", DB_CHANNEL_USERNAME, "=>", DB_CHAT_ID)
    except Exception as e:
        print("Failed to resolve DB channel id:", e)
        DB_CHAT_ID = DB_CHANNEL_USERNAME

resolve_db_chat_id()

# =========================
# Helpers
# =========================
def is_owner(uid: int) -> bool:
    return uid == OWNER_ID

def is_uploader(uid: int) -> bool:
    if is_owner(uid):
        return True
    with db() as con:
        with con.cursor() as cur:
            cur.execute("SELECT 1 FROM uploaders WHERE tg_id=%s", (uid,))
            row = cur.fetchone()
    return row is not None

def normalize(s: str) -> str:
    s = (s or "").strip().lower()
    s = s.replace("ي", "ی").replace("ك", "ک")
    s = re.sub(r"\s+", " ", s)
    return s

def parse_rarity(line: str):
    raw = (line or "").strip()
    t = normalize(raw).replace(":", " ")
    t = re.sub(r"\s+", " ", t).strip()

    if t in RARITIES:
        return t
    for key, meta in RARITIES.items():
        if key in t:
            return key
        if normalize(meta["title"]) in t:
            return key
        if meta["emoji"] and meta["emoji"] in raw:
            return key
    return None

def parse_event_optional(line: str):
    raw = (line or "").strip()
    if not raw:
        return NO_EVENT_KEY

    t = normalize(raw)
    t = t.replace("event", "").replace(":", " ")
    t = re.sub(r"\s+", " ", t).strip()

    if t in (NO_EVENT_KEY, "noevent", "no event", "none", "null", "-"):
        return NO_EVENT_KEY
    if t in EVENTS:
        return t
    for key, title in EVENTS.items():
        if normalize(title) in normalize(raw):
            return key
        if key in t:
            return key
    return NO_EVENT_KEY

def event_title(key: str) -> str:
    return NO_EVENT_TITLE if key == NO_EVENT_KEY else EVENTS.get(key, NO_EVENT_TITLE)

def extract_card_from_reply(message):
    if not message.reply_to_message:
        return None, "❌ باید روی پیام عکس ریپلای کنی."
    src = message.reply_to_message
    if not src.photo:
        return None, "❌ پیام ریپلای باید Photo باشه."

    caption = (src.caption or "").strip()
    lines = [ln.strip() for ln in caption.splitlines() if ln.strip()]

    if len(lines) not in (3, 4):
        return None, (
            "❌ کپشن باید ۳ یا ۴ خط باشه:\n"
            "3 lines:\nName\nAnime\nRarity\n\n"
            "4 lines:\nName\nAnime\nRarity\nEvent(optional)"
        )

    if len(lines) == 3:
        name, anime, rarity_line = lines
        event_line = ""
    else:
        name, anime, rarity_line, event_line = lines

    rarity_key = parse_rarity(rarity_line)
    if not rarity_key:
        return None, "❌ Rarity نامعتبره. مثال: 🌌 Cosmic"

    event_key = parse_event_optional(event_line)
    file_id = src.photo[-1].file_id

    return {
        "name": name,
        "anime": anime,
        "rarity_key": rarity_key,
        "event_key": event_key,
        "file_id": file_id
    }, None

def get_character(char_id: int):
    with db() as con:
        with con.cursor() as cur:
            cur.execute("""
                SELECT id, name, anime, rarity_key, event_key, image_file_id, channel_msg_id
                FROM characters WHERE id=%s
            """, (char_id,))
            row = cur.fetchone()
    if not row:
        return None
    return {
        "id": row[0],
        "name": row[1],
        "anime": row[2],
        "rarity_key": row[3],
        "event_key": row[4],
        "image_file_id": row[5],
        "channel_msg_id": row[6],
    }

def repost_to_channel(char_id: int):
    c = get_character(char_id)
    if not c:
        raise Exception("Character not found in DB")

    if c["channel_msg_id"]:
        try:
            bot.delete_message(DB_CHAT_ID, c["channel_msg_id"])
        except Exception:
            pass

    r = RARITIES[c["rarity_key"]]
    e_title = event_title(c["event_key"])
    channel_caption = (
        "OWO! CHECK OUT THIS CHARACTER!\n\n"
        f"[ ANIME : {c['anime']} ]\n"
        f"[ ID : {c['id']} {c['name']} ]\n"
        f"[ RARITY : {r['emoji']} {r['title']} ]\n"
        f"[ EVENT : {e_title} ]\n\n"
        "➤ UPDATED/ADDED"
    )
    sent = bot.send_photo(DB_CHAT_ID, c["image_file_id"], caption=channel_caption)

    with db() as con:
        with con.cursor() as cur:
            cur.execute("UPDATE characters SET channel_msg_id=%s WHERE id=%s", (sent.message_id, char_id))
        con.commit()

# =========================
# SEARCH HELPERS
# =========================
def search_characters_in_db(query: str):
    q = (query or "").strip()
    if not q:
        return []
    like = f"%{q}%"

    with db() as con:
        with con.cursor() as cur:
            cur.execute("""
                SELECT id, name, anime, rarity_key, event_key, image_file_id
                FROM characters
                WHERE LOWER(name) LIKE LOWER(%s)
                   OR LOWER(anime) LIKE LOWER(%s)
                ORDER BY id ASC
            """, (like, like))
            rows = cur.fetchall()
    return rows

def short_search_preview(rows, limit=12):
    ids = [str(r[0]) for r in rows[:limit]]
    if not ids:
        return "—"
    more = ""
    if len(rows) > limit:
        more = f" (+{len(rows)-limit} more)"
    return ", ".join(ids) + more

# =========================
# Spawn System
# =========================
def get_or_create_chat_settings(chat_id: int):
    with db() as con:
        with con.cursor() as cur:
            cur.execute("SELECT spawn_enabled, spawn_every, msg_counter FROM chat_settings WHERE chat_id=%s", (chat_id,))
            row = cur.fetchone()
            if not row:
                cur.execute("""
                    INSERT INTO chat_settings (chat_id, spawn_enabled, spawn_every, msg_counter)
                    VALUES (%s, %s, %s, %s)
                """, (chat_id, DEFAULT_SPAWN_ENABLED, DEFAULT_SPAWN_EVERY, 0))
                con.commit()
                row = (DEFAULT_SPAWN_ENABLED, DEFAULT_SPAWN_EVERY, 0)
    return {"enabled": bool(row[0]), "every": int(row[1]), "counter": int(row[2])}

def set_chat_settings(chat_id: int, enabled=None, every=None):
    s = get_or_create_chat_settings(chat_id)
    enabled_val = (s["enabled"] if enabled is None else bool(enabled))
    every_val = s["every"] if every is None else int(every)
    if every_val < 1:
        every_val = 1
    with db() as con:
        with con.cursor() as cur:
            cur.execute("""
                UPDATE chat_settings
                SET spawn_enabled=%s, spawn_every=%s
                WHERE chat_id=%s
            """, (enabled_val, every_val, chat_id))
        con.commit()

def increment_counter(chat_id: int):
    s = get_or_create_chat_settings(chat_id)
    new_counter = s["counter"] + 1
    with db() as con:
        with con.cursor() as cur:
            cur.execute("UPDATE chat_settings SET msg_counter=%s WHERE chat_id=%s", (new_counter, chat_id))
        con.commit()
    return new_counter, s["every"], s["enabled"]

def has_active_spawn(chat_id: int):
    with db() as con:
        with con.cursor() as cur:
            cur.execute("SELECT char_id, spawned_msg_id, claimed_by FROM active_spawns WHERE chat_id=%s", (chat_id,))
            row = cur.fetchone()
    return row

def weighted_choice_rarity():
    items = [(k, float(v)) for k, v in RARITY_SPAWN_WEIGHTS.items() if float(v) > 0]
    if not items:
        return "common"
    total = sum(w for _, w in items)
    r = random.random() * total
    upto = 0.0
    for key, w in items:
        upto += w
        if upto >= r:
            return key
    return items[-1][0]

def pick_random_character_by_rarity(rarity_key: str):
    with db() as con:
        with con.cursor() as cur:
            cur.execute("SELECT id FROM characters WHERE rarity_key=%s ORDER BY RANDOM() LIMIT 1", (rarity_key,))
            row = cur.fetchone()
    return row[0] if row else None

def pick_random_character_any():
    with db() as con:
        with con.cursor() as cur:
            cur.execute("SELECT id FROM characters ORDER BY RANDOM() LIMIT 1")
            row = cur.fetchone()
    return row[0] if row else None

def spawn_character_in_chat(chat_id: int):
    active = has_active_spawn(chat_id)
    if active and active[2] is None:
        return None

    rarity_key = weighted_choice_rarity()
    cid = pick_random_character_by_rarity(rarity_key)
    if cid is None:
        cid = pick_random_character_any()
        if cid is None:
            return None

    c = get_character(cid)
    if not c:
        return None

    caption = (
        "✨ A new character has just spawned in the chat!\n"
        "Use /hunt [Name] to hunt them for yourself."
    )
    msg = bot.send_photo(chat_id, c["image_file_id"], caption=caption)

    with db() as con:
        with con.cursor() as cur:
            cur.execute("""
                INSERT INTO active_spawns (chat_id, char_id, spawned_msg_id, spawned_at, claimed_by, claimed_at)
                VALUES (%s, %s, %s, %s, NULL, NULL)
                ON CONFLICT (chat_id) DO UPDATE SET
                    char_id=EXCLUDED.char_id,
                    spawned_msg_id=EXCLUDED.spawned_msg_id,
                    spawned_at=EXCLUDED.spawned_at,
                    claimed_by=NULL,
                    claimed_at=NULL
            """, (chat_id, c["id"], msg.message_id, int(time.time())))
        con.commit()

    return c["id"]

def claim_spawn(chat_id: int, user_id: int):
    with db() as con:
        with con.cursor() as cur:
            cur.execute("SELECT char_id, spawned_msg_id, claimed_by FROM active_spawns WHERE chat_id=%s", (chat_id,))
            row = cur.fetchone()
            if not row:
                return (False, "❌ No active spawn.")
            char_id, spawned_msg_id, claimed_by = row
            if claimed_by is not None:
                return (False, "❌ This spawn is already claimed.")

            now = int(time.time())
            cur.execute("UPDATE active_spawns SET claimed_by=%s, claimed_at=%s WHERE chat_id=%s",
                        (user_id, now, chat_id))
            cur.execute("INSERT INTO inventory (user_id, chat_id, char_id, obtained_at) VALUES (%s, %s, %s, %s)",
                        (user_id, chat_id, char_id, now))
        con.commit()
    return (True, (char_id, spawned_msg_id))

def name_matches(user_text: str, real_name: str) -> bool:
    u = normalize(user_text)
    r = normalize(real_name)
    if not u or len(u) < 2:
        return False
    return (u == r)

# =========================
# HAREM + FAV helpers
# =========================
def get_user_fav_char_id(user_id: int):
    with db() as con:
        with con.cursor() as cur:
            cur.execute("SELECT char_id FROM favorites WHERE user_id=%s", (user_id,))
            row = cur.fetchone()
    return int(row[0]) if row else None

def user_owns_char_in_chat(chat_id: int, user_id: int, char_id: int) -> bool:
    with db() as con:
        with con.cursor() as cur:
            cur.execute("""
                SELECT 1 FROM inventory
                WHERE chat_id=%s AND user_id=%s AND char_id=%s
                LIMIT 1
            """, (chat_id, user_id, char_id))
            ok = cur.fetchone() is not None
    return ok

def get_harem_cover_file_id(chat_id: int, user_id: int):
    fav_id = get_user_fav_char_id(user_id)
    if fav_id and user_owns_char_in_chat(chat_id, user_id, fav_id):
        c = get_character(fav_id)
        if c:
            return c["image_file_id"]

    with db() as con:
        with con.cursor() as cur:
            cur.execute("""
                SELECT c.image_file_id
                FROM inventory i
                JOIN characters c ON c.id=i.char_id
                WHERE i.chat_id=%s AND i.user_id=%s
                ORDER BY i.obtained_at DESC
                LIMIT 1
            """, (chat_id, user_id))
            row = cur.fetchone()
    return row[0] if row else None

def get_user_collection_counts(chat_id: int, user_id: int):
    with db() as con:
        with con.cursor() as cur:
            cur.execute("""
                SELECT c.anime, c.id, c.name, c.rarity_key, c.event_key, COUNT(*) as cnt
                FROM inventory i
                JOIN characters c ON c.id = i.char_id
                WHERE i.chat_id=%s AND i.user_id=%s
                GROUP BY c.anime, c.id, c.name, c.rarity_key, c.event_key
                ORDER BY LOWER(c.anime) ASC, c.id ASC
            """, (chat_id, user_id))
            rows = cur.fetchall()

    if not rows:
        return 0, []

    per = {}
    for anime, cid, name, rk, ek, cnt in rows:
        if anime not in per:
            per[anime] = {"anime": anime, "total_unique": 0, "samples": []}
        per[anime]["total_unique"] += 1
        if len(per[anime]["samples"]) < 6:
            per[anime]["samples"].append((cid, name, rk, ek, cnt))

    per_list = list(per.values())
    total_unique = sum(x["total_unique"] for x in per_list)
    return total_unique, per_list

def render_harem_page(title_name: str, total_unique: int, per_anime: list, page: int, page_size: int = 4):
    total_pages = max(1, (len(per_anime) + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))
    start = (page - 1) * page_size
    chunk = per_anime[start:start + page_size]

    lines = []
    lines.append(f"🗂 {title_name}'s Harem — Page: {page}/{total_pages}")
    lines.append("")
    for block in chunk:
        anime = block["anime"]
        lines.append(f"⚜️ {anime} ({block['total_unique']})")
        lines.append("————————————")
        for (cid, name, rk, ek, cnt) in block["samples"]:
            r = RARITIES.get(rk, {"emoji": "❔", "title": rk})
            extra = f" (x{cnt})" if cnt and cnt > 1 else ""
            lines.append(f"{r['emoji']} [{cid}] | {name}{extra}")
        lines.append("")

    return "\n".join(lines).strip(), total_pages, page

def harem_keyboard(total_unique: int, page: int, total_pages: int, target_user_id: int):
    kb = types.InlineKeyboardMarkup(row_width=3)
    row = []
    if page > 1:
        row.append(types.InlineKeyboardButton("⬅️", callback_data=f"harem:{page-1}:{target_user_id}"))
    row.append(types.InlineKeyboardButton(f"{page}/{total_pages}", callback_data="noop"))
    if page < total_pages:
        row.append(types.InlineKeyboardButton("➡️", callback_data=f"harem:{page+1}:{target_user_id}"))
    kb.row(*row)

    kb.row(types.InlineKeyboardButton(
        f"See Collection ({total_unique})",
        switch_inline_query_current_chat=f"mycards {target_user_id}"
    ))
    return kb

def rarity_deck_stats(user_id: int):
    with db() as con:
        with con.cursor() as cur:
            cur.execute("""
                SELECT rarity_key, COUNT(*)
                FROM characters
                GROUP BY rarity_key
            """)
            total_rows = cur.fetchall()
            total_map = {rk: int(cnt) for rk, cnt in total_rows}

            cur.execute("""
                SELECT c.rarity_key, COUNT(DISTINCT i.char_id)
                FROM inventory i
                JOIN characters c ON c.id = i.char_id
                WHERE i.user_id=%s
                GROUP BY c.rarity_key
            """, (user_id,))
            owned_rows = cur.fetchall()
            owned_map = {rk: int(cnt) for rk, cnt in owned_rows}

    for rk in RARITIES.keys():
        total_map.setdefault(rk, 0)
        owned_map.setdefault(rk, 0)

    return total_map, owned_map

# =========================
# Commands
# =========================
@bot.message_handler(commands=["start"])
def start(message):
    role = "OWNER" if is_owner(message.from_user.id) else ("UPLOADER" if is_uploader(message.from_user.id) else "USER")
    bot.reply_to(
        message,
        f"✅ Bot is online!\n{VERSION}\nRole: {role}\n\n"
        "Player:\n"
        "- /hunt Name   (example: /hunt Rangiku)\n"
        "- /harem (or reply to someone: /harem)\n"
        "- /fav ID   (set harem cover)\n"
        "- /search text (search cards in DB)\n\n"
        "Owner (spawn settings per chat):\n"
        "- /changetime 20\n"
        "- /spawn on | /spawn off\n"
        "- /spawnstatus\n"
        "- /forcespawn\n"
        "- /clearspawn\n"
        "- /reset (reply to user)\n\n"
        "Uploader:\n"
        "- reply /upload\n"
        "- reply /uploadid 25\n\n"
        "Owner edit:\n"
        "- /delete 25\n"
        "- /update 25 name New Name\n"
        "- /update 25 anime New Anime\n"
        "- /update 25 rarity 🌌 Cosmic\n"
        "- /update 25 event none\n"
        "- reply /updatephoto 25\n"
        "- /check 25\n"
        "- /rarity\n"
    )

@bot.message_handler(commands=["ping"])
def ping(message):
    bot.reply_to(message, "🏓 Pong!")

# =========================
# /search
# =========================
@bot.message_handler(regexp=r"^/search(\s+.+)?$")
def search_cmd(message):
    m = re.match(r"^/search\s+(.+)$", (message.text or "").strip(), flags=re.I)
    if not m:
        return bot.reply_to(message, "Usage: /search NameOrAnime\nExample: /search Rangiku")

    q = m.group(1).strip()
    rows = search_characters_in_db(q)

    kb = types.InlineKeyboardMarkup()
    kb.row(types.InlineKeyboardButton("🔍 View results (inline)", switch_inline_query_current_chat=f"search {q}"))

    if not rows:
        return bot.reply_to(message, f"❌ No cards found for: {q}", reply_markup=kb)

    preview = short_search_preview(rows, limit=12)
    bot.reply_to(
        message,
        f"✅ Search results for: {q}\n"
        f"Found: {len(rows)} card(s)\n"
        f"IDs: {preview}",
        reply_markup=kb
    )

# =========================
# Spawn settings (Owner)
# =========================
@bot.message_handler(regexp=r"^/changetime(\s+\d+)?$")
def changetime(message):
    if not is_owner(message.from_user.id):
        return
    if message.chat.type not in ("group", "supergroup"):
        return bot.reply_to(message, "Use in group.")
    m = re.match(r"^/changetime\s+(\d+)$", (message.text or "").strip())
    if not m:
        return bot.reply_to(message, "Usage: /changetime 20")
    n = int(m.group(1))
    if n < 1:
        return bot.reply_to(message, "❌ عدد باید حداقل 1 باشه.")
    set_chat_settings(message.chat.id, every=n)
    bot.reply_to(message, f"✅ Spawn interval set to every {n} messages (this chat).")

@bot.message_handler(regexp=r"^/spawn(\s+(on|off))?$")
def spawn_toggle(message):
    if not is_owner(message.from_user.id):
        return
    if message.chat.type not in ("group", "supergroup"):
        return bot.reply_to(message, "Use in group.")
    m = re.match(r"^/spawn\s+(on|off)$", (message.text or "").strip())
    if not m:
        return bot.reply_to(message, "Usage: /spawn on  OR  /spawn off")
    val = (m.group(1) == "on")
    set_chat_settings(message.chat.id, enabled=val)
    bot.reply_to(message, f"✅ Spawn {'enabled' if val else 'disabled'} for this chat.")

# =========================
# Spawn debug (Owner)
# =========================
@bot.message_handler(commands=["spawnstatus"])
def spawn_status(message):
    if message.chat.type not in ("group", "supergroup"):
        return bot.reply_to(message, "Use in group.")
    s = get_or_create_chat_settings(message.chat.id)
    active = has_active_spawn(message.chat.id)

    txt = (
        f"📊 Spawn Status\n"
        f"- enabled: {s['enabled']}\n"
        f"- every: {s['every']}\n"
        f"- counter: {s['counter']}\n"
    )
    if active:
        txt += f"- active_spawn: YES | char_id={active[0]} | claimed_by={active[2]}\n"
        if active[2] is None:
            txt += "⚠️ Active spawn is UNCLAIMED → new spawns are blocked until hunted.\n"
    else:
        txt += "- active_spawn: NO\n"
    bot.reply_to(message, txt)

@bot.message_handler(commands=["forcespawn"])
def force_spawn(message):
    if not is_owner(message.from_user.id):
        return
    if message.chat.type not in ("group", "supergroup"):
        return bot.reply_to(message, "Use in group.")
    try:
        cid = spawn_character_in_chat(message.chat.id)
        if cid is None:
            bot.reply_to(message, "❌ Force spawn failed (maybe no characters in DB OR active spawn locked).")
        else:
            bot.reply_to(message, f"✅ Forced spawn done. char_id={cid}")
    except Exception as e:
        bot.reply_to(message, f"❌ Force spawn error:\n{e}")

@bot.message_handler(commands=["clearspawn"])
def clear_spawn(message):
    if not is_owner(message.from_user.id):
        return
    if message.chat.type not in ("group", "supergroup"):
        return bot.reply_to(message, "Use in group.")
    with db() as con:
        with con.cursor() as cur:
            cur.execute("DELETE FROM active_spawns WHERE chat_id=%s", (message.chat.id,))
        con.commit()
    bot.reply_to(message, "✅ Active spawn cleared for this chat.")

# =========================
# Hunt (Players)
# =========================
@bot.message_handler(regexp=r"^/hunt(\s+.+)?$")
def hunt_cmd(message):
    if message.chat.type == "private":
        return bot.reply_to(message, "❌ /hunt works only inside groups.")

    m = re.match(r"^/hunt\s+(.+)$", (message.text or "").strip())
    if not m:
        return bot.reply_to(message, "Usage: /hunt Name\nExample: /hunt Rangiku")

    guess = m.group(1).strip()

    with db() as con:
        with con.cursor() as cur:
            cur.execute("SELECT char_id, claimed_by FROM active_spawns WHERE chat_id=%s", (message.chat.id,))
            row = cur.fetchone()

    if not row:
        return bot.reply_to(message, "❌ No active spawn right now.")

    char_id, claimed_by = row
    if claimed_by is not None:
        return bot.reply_to(message, "❌ This character is already claimed.")

    c = get_character(char_id)
    if not c:
        return bot.reply_to(message, "❌ Spawn data not found.")

    if not name_matches(guess, c["name"]):
        return bot.reply_to(message, "❌ Wrong name!")

    # GLOBAL CAPACITY 25
    with db() as con:
        with con.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM inventory WHERE user_id=%s", (message.from_user.id,))
            count = int(cur.fetchone()[0] or 0)

    MAX_CAPACITY = 25
    if count >= MAX_CAPACITY:
        return bot.reply_to(
            message,
            "🚫 Storage Limit Reached!\n\n"
            "Your total collection capacity is full (25/25).\n"
            "You can't hunt more characters until the Owner resets your storage."
        )

    ok, info = claim_spawn(message.chat.id, message.from_user.id)
    if not ok:
        return bot.reply_to(message, info)

    r = RARITIES[c["rarity_key"]]
    e_title = event_title(c["event_key"])

    bot.reply_to(
        message,
        f"🏹 {message.from_user.first_name} claimed!\n"
        f"ID: {c['id']} | {c['name']} ({c['anime']})\n"
        f"{r['emoji']} {r['title']} | Event: {e_title}"
    )

@bot.message_handler(commands=["reset"])
def reset_collection(message):
    if not is_owner(message.from_user.id):
        return bot.reply_to(message, "⛔ Only the Owner can use this command.")

    if message.reply_to_message:
        target_id = message.reply_to_message.from_user.id
        target_name = message.reply_to_message.from_user.first_name
    else:
        target_id = message.from_user.id
        target_name = message.from_user.first_name

    with db() as con:
        with con.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM inventory WHERE user_id=%s", (target_id,))
            total = int(cur.fetchone()[0] or 0)
            cur.execute("DELETE FROM inventory WHERE user_id=%s", (target_id,))
        con.commit()

    bot.reply_to(
        message,
        f"♻️ {target_name}'s storage has been fully reset.\n"
        f"{total} cards removed.\n"
        f"They can now collect up to 25 new characters again."
    )

# =========================
# /fav
# =========================
@bot.message_handler(regexp=r"^/fav(\s+\d+)?$")
def fav_cmd(message):
    if message.chat.type == "private":
        return bot.reply_to(message, "❌ /fav فقط داخل گروه کار می‌کنه.")
    m = re.match(r"^/fav\s+(\d+)$", (message.text or "").strip())
    if not m:
        return bot.reply_to(message, "Usage: /fav ID (مثال: /fav 25)")
    cid = int(m.group(1))
    if not get_character(cid):
        return bot.reply_to(message, "❌ این ID وجود نداره.")
    if not user_owns_char_in_chat(message.chat.id, message.from_user.id, cid):
        return bot.reply_to(message, "❌ این کارت رو توی همین گروه نداری.")

    with db() as con:
        with con.cursor() as cur:
            cur.execute("""
                INSERT INTO favorites (user_id, char_id)
                VALUES (%s, %s)
                ON CONFLICT (user_id) DO UPDATE SET char_id=EXCLUDED.char_id
            """, (message.from_user.id, cid))
        con.commit()

    bot.reply_to(message, f"✅ Favorite set to #{cid} (for your /harem cover).")

# =========================
# /harem
# =========================
@bot.message_handler(commands=["harem"])
def harem_cmd(message):
    if message.chat.type == "private":
        return bot.reply_to(message, "❌ /harem فقط داخل گروه کار می‌کنه.")

    target_user_id = message.from_user.id
    target_name = message.from_user.first_name

    if message.reply_to_message and message.reply_to_message.from_user:
        target_user_id = message.reply_to_message.from_user.id
        target_name = message.reply_to_message.from_user.first_name

    total_unique, per_anime = get_user_collection_counts(message.chat.id, target_user_id)
    if total_unique == 0:
        return bot.reply_to(message, "You Have Not Hunted any Characters Yet.")

    cover = get_harem_cover_file_id(message.chat.id, target_user_id)
    text, total_pages, page = render_harem_page(target_name, total_unique, per_anime, page=1)
    kb = harem_keyboard(total_unique, page, total_pages, target_user_id)

    if cover:
        bot.send_photo(message.chat.id, cover, caption=text, reply_markup=kb)
    else:
        bot.reply_to(message, text, reply_markup=kb)

@bot.callback_query_handler(func=lambda call: call.data and call.data.startswith("harem:"))
def harem_page_callback(call):
    try:
        _, page_str, target_str = call.data.split(":")
        page = int(page_str)
        target_user_id = int(target_str)
    except:
        return bot.answer_callback_query(call.id)

    chat_id = call.message.chat.id

    total_unique, per_anime = get_user_collection_counts(chat_id, target_user_id)
    if total_unique == 0:
        bot.answer_callback_query(call.id, "No cards.")
        try:
            bot.edit_message_caption("You Have Not Hunted any Characters Yet.", chat_id, call.message.message_id)
        except:
            try:
                bot.edit_message_text("You Have Not Hunted any Characters Yet.", chat_id, call.message.message_id)
            except:
                pass
        return

    title_name = "Harem"
    try:
        u = bot.get_chat(target_user_id)
        title_name = u.first_name or "Player"
    except:
        title_name = "Player"

    text, total_pages, page = render_harem_page(title_name, total_unique, per_anime, page=page)
    kb = harem_keyboard(total_unique, page, total_pages, target_user_id)

    try:
        bot.edit_message_caption(chat_id=chat_id, message_id=call.message.message_id, caption=text, reply_markup=kb)
    except:
        try:
            bot.edit_message_text(chat_id=chat_id, message_id=call.message.message_id, text=text, reply_markup=kb)
        except:
            pass

    bot.answer_callback_query(call.id)

@bot.callback_query_handler(func=lambda call: call.data == "noop")
def noop(call):
    bot.answer_callback_query(call.id)

# =========================
# Inline Mode: mycards + search
# =========================
@bot.inline_handler(func=lambda inline_query: True)
def inline_handler(inline_query):
    q_raw = (inline_query.query or "").strip()
    q = q_raw.lower()

    # SEARCH MODE
    if q.startswith("search "):
        search_text = q_raw[7:].strip()
        rows = search_characters_in_db(search_text)

        if not rows:
            results = [
                types.InlineQueryResultArticle(
                    id="search_empty",
                    title="No results",
                    input_message_content=types.InputTextMessageContent(f"No cards found for: {search_text}")
                )
            ]
            bot.answer_inline_query(inline_query.id, results, cache_time=1, is_personal=False)
            return

        try:
            offset = int(inline_query.offset or "0")
        except:
            offset = 0

        page_size = 15
        chunk = rows[offset:offset + page_size]
        next_offset = str(offset + page_size) if (offset + page_size) < len(rows) else ""

        results = []
        for idx, (cid, name, anime, rk, ek, file_id) in enumerate(chunk):
            r = RARITIES.get(rk, {"emoji": "❔", "title": rk})
            e_title = event_title(ek)
            caption = f"ID: {cid} | {name} ({anime})\n{r['emoji']} {r['title']} | Event: {e_title}"

            results.append(
                types.InlineQueryResultCachedPhoto(
                    id=f"search_{cid}_{offset}_{idx}",
                    photo_file_id=file_id,
                    caption=caption
                )
            )

        bot.answer_inline_query(
            inline_query.id,
            results,
            cache_time=1,
            is_personal=False,
            next_offset=next_offset
        )
        return

    # MYCARDS MODE
    if not q.startswith("mycards"):
        return

    m = re.match(r"^mycards\s+(\d+)$", q_raw.strip(), flags=re.I)
    if m:
        target_user_id = int(m.group(1))
    else:
        target_user_id = inline_query.from_user.id

    with db() as con:
        with con.cursor() as cur:
            cur.execute("""
                SELECT c.id, c.name, c.anime, c.rarity_key, c.event_key, c.image_file_id, COUNT(*) as cnt
                FROM inventory i
                JOIN characters c ON c.id = i.char_id
                WHERE i.user_id=%s
                GROUP BY c.id, c.name, c.anime, c.rarity_key, c.event_key, c.image_file_id
                ORDER BY c.id ASC
            """, (target_user_id,))
            rows = cur.fetchall()

    if not rows:
        results = [
            types.InlineQueryResultArticle(
                id="empty",
                title="No characters yet",
                input_message_content=types.InputTextMessageContent("No characters yet.")
            )
        ]
        bot.answer_inline_query(inline_query.id, results, cache_time=1, is_personal=True)
        return

    try:
        offset = int(inline_query.offset or "0")
    except:
        offset = 0

    page_size = 15
    chunk = rows[offset:offset + page_size]
    next_offset = str(offset + page_size) if (offset + page_size) < len(rows) else ""

    results = []
    for idx, (cid, name, anime, rk, ek, file_id, cnt) in enumerate(chunk):
        r = RARITIES.get(rk, {"emoji": "❔", "title": rk})
        e_title = event_title(ek)
        extra = f" (x{cnt})" if cnt and cnt > 1 else ""
        caption = f"ID: {cid} | {name}{extra} ({anime})\n{r['emoji']} {r['title']} | Event: {e_title}"

        results.append(
            types.InlineQueryResultCachedPhoto(
                id=f"{cid}_{offset}_{idx}",
                photo_file_id=file_id,
                caption=caption
            )
        )

    bot.answer_inline_query(
        inline_query.id,
        results,
        cache_time=1,
        is_personal=True,
        next_offset=next_offset
    )

# =========================
# Uploader/Admin management
# =========================
@bot.message_handler(commands=["adduploader"])
def add_uploader(message):
    if not is_owner(message.from_user.id):
        return bot.reply_to(message, "⛔ فقط Owner.")
    if not message.reply_to_message:
        return bot.reply_to(message, "❌ روی پیام شخص ریپلای کن بعد /adduploader بزن.")
    target = message.reply_to_message.from_user
    with db() as con:
        with con.cursor() as cur:
            cur.execute("""
                INSERT INTO uploaders (tg_id, added_by, added_at)
                VALUES (%s, %s, %s)
                ON CONFLICT (tg_id) DO NOTHING
            """, (target.id, OWNER_ID, int(time.time())))
        con.commit()
    bot.reply_to(message, f"✅ Uploader added: {target.first_name} (ID: {target.id})")

@bot.message_handler(commands=["deluploader"])
def del_uploader(message):
    if not is_owner(message.from_user.id):
        return bot.reply_to(message, "⛔ فقط Owner.")
    if not message.reply_to_message:
        return bot.reply_to(message, "❌ روی پیام شخص ریپلای کن بعد /deluploader بزن.")
    target = message.reply_to_message.from_user
    with db() as con:
        with con.cursor() as cur:
            cur.execute("DELETE FROM uploaders WHERE tg_id=%s", (target.id,))
        con.commit()
    bot.reply_to(message, f"🗑 Uploader removed: {target.first_name} (ID: {target.id})")

# =========================
# Upload / UploadID
# =========================
@bot.message_handler(commands=["upload"])
def upload_auto(message):
    if not is_uploader(message.from_user.id):
        return bot.reply_to(message, "⛔ You are not an uploader.")
    card, err = extract_card_from_reply(message)
    if err:
        return bot.reply_to(message, err)

    with db() as con:
        with con.cursor() as cur:
            cur.execute("""
                INSERT INTO characters (name, anime, rarity_key, event_key, image_file_id, uploaded_by, uploaded_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (
                card["name"], card["anime"], card["rarity_key"], card["event_key"],
                card["file_id"], message.from_user.id, int(time.time())
            ))
            new_id = int(cur.fetchone()[0])
        con.commit()

    try:
        repost_to_channel(new_id)
        bot.reply_to(message, f"✅ Uploaded #{new_id} and posted to {DB_CHANNEL_USERNAME}")
    except Exception as ex:
        bot.reply_to(message, f"✅ Uploaded #{new_id} (DB saved)\n⚠️ Channel post failed:\n{ex}")

@bot.message_handler(regexp=r"^/uploadid(\s+\d+)?$")
def upload_manual_id(message):
    if not is_uploader(message.from_user.id):
        return bot.reply_to(message, "⛔ You are not an uploader.")
    m = re.match(r"^/uploadid\s+(\d+)$", (message.text or "").strip())
    if not m:
        return bot.reply_to(message, "Usage: /uploadid 25 (reply to photo)")
    desired_id = int(m.group(1))
    if desired_id <= 0:
        return bot.reply_to(message, "❌ ID باید مثبت باشه.")

    card, err = extract_card_from_reply(message)
    if err:
        return bot.reply_to(message, err)

    with db() as con:
        with con.cursor() as cur:
            cur.execute("SELECT 1 FROM characters WHERE id=%s", (desired_id,))
            if cur.fetchone():
                return bot.reply_to(message, f"❌ ID {desired_id} قبلاً وجود داره.")

            cur.execute("""
                INSERT INTO characters (id, name, anime, rarity_key, event_key, image_file_id, uploaded_by, uploaded_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                desired_id, card["name"], card["anime"], card["rarity_key"], card["event_key"],
                card["file_id"], message.from_user.id, int(time.time())
            ))
        con.commit()

    try:
        repost_to_channel(desired_id)
        bot.reply_to(message, f"✅ Uploaded with ID #{desired_id} and posted to {DB_CHANNEL_USERNAME}")
    except Exception as ex:
        bot.reply_to(message, f"✅ Uploaded with ID #{desired_id} (DB saved)\n⚠️ Channel post failed:\n{ex}")

# =========================
# Delete
# =========================
@bot.message_handler(regexp=r"^/delete(\s+\d+)?$")
def delete_character_cmd(message):
    if not is_owner(message.from_user.id):
        return
    m = re.match(r"^/delete\s+(\d+)$", (message.text or "").strip())
    if not m:
        return bot.reply_to(message, "Usage: /delete 25")
    char_id = int(m.group(1))
    c = get_character(char_id)
    if not c:
        return bot.reply_to(message, "❌ not found.")

    with db() as con:
        with con.cursor() as cur:
            cur.execute("DELETE FROM characters WHERE id=%s", (char_id,))
            cur.execute("DELETE FROM inventory WHERE char_id=%s", (char_id,))
            cur.execute("DELETE FROM active_spawns WHERE char_id=%s", (char_id,))
        con.commit()

    if c["channel_msg_id"]:
        try:
            bot.delete_message(DB_CHAT_ID, c["channel_msg_id"])
        except Exception:
            pass

    bot.reply_to(message, f"🗑 Deleted #{char_id} ✅")

# =========================
# Update fields + Update photo
# =========================
@bot.message_handler(regexp=r"^/update(\s+.+)?$")
def update_field_cmd(message):
    if not is_owner(message.from_user.id):
        return
    parts = (message.text or "").strip().split(maxsplit=3)
    if len(parts) < 4:
        return bot.reply_to(message,
                            "Usage:\n"
                            "/update 25 name New Name\n"
                            "/update 25 anime New Anime\n"
                            "/update 25 rarity 🌌 Cosmic\n"
                            "/update 25 event none")
    _, sid, field, new_value = parts
    try:
        char_id = int(sid)
    except:
        return bot.reply_to(message, "❌ ID باید عدد باشه.")
    c = get_character(char_id)
    if not c:
        return bot.reply_to(message, "❌ not found.")

    field = field.lower().strip()

    with db() as con:
        with con.cursor() as cur:
            if field == "name":
                cur.execute("UPDATE characters SET name=%s WHERE id=%s", (new_value.strip(), char_id))
            elif field == "anime":
                cur.execute("UPDATE characters SET anime=%s WHERE id=%s", (new_value.strip(), char_id))
            elif field == "rarity":
                rk = parse_rarity(new_value)
                if not rk:
                    return bot.reply_to(message, "❌ Rarity نامعتبره. مثال: 🌌 Cosmic")
                cur.execute("UPDATE characters SET rarity_key=%s WHERE id=%s", (rk, char_id))
            elif field == "event":
                ek = parse_event_optional(new_value)
                cur.execute("UPDATE characters SET event_key=%s WHERE id=%s", (ek, char_id))
            else:
                return bot.reply_to(message, "❌ field فقط: name | anime | rarity | event")
        con.commit()

    try:
        repost_to_channel(char_id)
    except Exception:
        pass

    bot.reply_to(message, f"✅ Updated #{char_id} ({field})")

@bot.message_handler(regexp=r"^/updatephoto(\s+\d+)?$")
def update_photo_cmd(message):
    if not is_owner(message.from_user.id):
        return
    m = re.match(r"^/updatephoto\s+(\d+)$", (message.text or "").strip())
    if not m:
        return bot.reply_to(message, "Usage: reply to NEW photo: /updatephoto 25")
    char_id = int(m.group(1))
    c = get_character(char_id)
    if not c:
        return bot.reply_to(message, "❌ not found.")
    if not message.reply_to_message or not message.reply_to_message.photo:
        return bot.reply_to(message, "❌ باید روی عکس جدید ریپلای کنی.")
    new_file_id = message.reply_to_message.photo[-1].file_id

    with db() as con:
        with con.cursor() as cur:
            cur.execute("UPDATE characters SET image_file_id=%s WHERE id=%s", (new_file_id, char_id))
        con.commit()

    try:
        repost_to_channel(char_id)
    except Exception:
        pass

    bot.reply_to(message, f"🖼 Updated photo for #{char_id} ✅")

# =========================
# /rarity
# =========================
@bot.message_handler(commands=["rarity"])
def rarity_cmd(message):
    user_id = message.from_user.id
    total_map, owned_map = rarity_deck_stats(user_id)

    total_owned_all = sum(owned_map.values())
    total_all = sum(total_map.values())

    lines = []
    lines.append(f"🗂 {message.from_user.first_name}'s Rarity Deck")
    lines.append(f"Total Collected: {total_owned_all} (unique)")
    lines.append(f"Collection: {total_owned_all}/{total_all} ({(total_owned_all/total_all*100 if total_all else 0):.1f}%)")
    lines.append("————————————")

    order = ["oblivion","infinity","transcendent","cosmic","flat","legendary","epic","rare","common"]

    for rk in order:
        meta = RARITIES.get(rk, {"emoji": "❔", "title": rk})
        owned = owned_map.get(rk, 0)
        total = total_map.get(rk, 0)
        pct = (owned / total * 100) if total else 0.0

        lines.append(f"{meta['emoji']} {meta['title']} ({owned}/{total})")
        lines.append(f"Progress: {pct:.0f}%")
        lines.append("")

    bot.reply_to(message, "\n".join(lines))

# =========================
# /check
# =========================
def get_card_global_stats(char_id: int):
    with db() as con:
        with con.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM inventory WHERE char_id=%s", (char_id,))
            total_copies = int(cur.fetchone()[0] or 0)

            cur.execute("SELECT COUNT(DISTINCT user_id) FROM inventory WHERE char_id=%s", (char_id,))
            total_unique_users = int(cur.fetchone()[0] or 0)

            cur.execute("""
                SELECT user_id, COUNT(*) as cnt
                FROM inventory
                WHERE char_id=%s
                GROUP BY user_id
                ORDER BY cnt DESC
                LIMIT 10
            """, (char_id,))
            top_users = cur.fetchall()

    return total_copies, total_unique_users, top_users

@bot.message_handler(regexp=r"^/check(\s+\d+)?$")
def check_cmd(message):
    m = re.match(r"^/check\s+(\d+)$", (message.text or "").strip())
    if not m:
        return bot.reply_to(message, "Usage: /check 25")

    char_id = int(m.group(1))
    c = get_character(char_id)
    if not c:
        return bot.reply_to(message, "❌ Character not found.")

    total_copies, total_unique_users, top_users = get_card_global_stats(char_id)

    r = RARITIES.get(c["rarity_key"], {"emoji": "❔", "title": c["rarity_key"]})
    e_title = event_title(c["event_key"])

    lines = []
    lines.append(f"🔎 Card Check — ID: {c['id']}")
    lines.append(f"👤 Name: {c['name']}")
    lines.append(f"🎬 Anime: {c['anime']}")
    lines.append(f"✨ Rarity: {r['emoji']} {r['title']}")
    lines.append(f"🎉 Event: {e_title}")
    lines.append("")
    lines.append(f"📦 Total Obtained (all chats): {total_copies}")
    lines.append(f"👥 Unique Owners: {total_unique_users}")
    lines.append("")
    lines.append("🏆 Top Owners (Top 10):")

    if not top_users:
        lines.append("— None")
    else:
        for i, (uid, cnt) in enumerate(top_users, start=1):
            try:
                u = bot.get_chat(uid)
                name = (u.first_name or "User").strip()
                if u.username:
                    name = f"@{u.username}"
            except Exception:
                name = str(uid)
            lines.append(f"{i}. {name} — x{cnt}")

    text = "\n".join(lines)

    try:
        bot.send_photo(message.chat.id, c["image_file_id"], caption=text)
    except Exception:
        bot.reply_to(message, text)

# =========================
# Message counter -> spawn every N messages
# =========================
@bot.message_handler(func=lambda m: True, content_types=["text", "photo", "sticker", "video", "animation", "document"])
def every_message_counter(message):
    if message.chat.type not in ("group", "supergroup"):
        return

    if message.content_type == "text" and message.text and message.text.startswith("/"):
        return

    counter, every, enabled = increment_counter(message.chat.id)
    if not enabled or every <= 0:
        return

    if counter % every == 0:
        try:
            spawn_character_in_chat(message.chat.id)
        except Exception as e:
            print("spawn error:", e)

print("Bot is running...")
bot.infinity_polling(timeout=30, long_polling_timeout=30)
