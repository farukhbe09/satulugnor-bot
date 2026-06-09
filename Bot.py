import logging
import sqlite3
import random
from telegram import Update, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler, CallbackQueryHandler
)
from telegram.error import TelegramError

# ============================================================
BOT_TOKEN = "8883539030:AAGjVz-nJ1yNf9h-z4K8mikpjW7SHTLA3Do"
MAIN_CHANNEL = "@satulugnor"
OLIMPIADA_GROUP = -1003525865374
ADMIN_ID = 2050241265
REQUIRED_REFS = 5
BOT_USERNAME = "satulugnorbot"

PRIZES = {
    1: "🥇 1-o'rin — 50,000 so'm 💵",
    2: "🥈 2-o'rin — 30,000 so'm 💵",
    3: "🥉 3-o'rin — Telegram Gift 🎁",
}
# ============================================================

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ASK_NAME, ASK_SURNAME = 1, 2

def init_db():
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id     INTEGER PRIMARY KEY,
            full_name   TEXT,
            username    TEXT DEFAULT '',
            invited_by  INTEGER,
            completed   INTEGER DEFAULT 0,
            joined_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS refs (
            referrer_id INTEGER,
            referee_id  INTEGER,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (referrer_id, referee_id)
        )
    """)
    conn.commit()
    conn.close()

def db(query, params=(), fetch=None):
    conn = sqlite3.connect("bot.db")
    c = conn.cursor()
    c.execute(query, params)
    result = None
    if fetch == "one":
        result = c.fetchone()
    elif fetch == "all":
        result = c.fetchall()
    else:
        conn.commit()
    conn.close()
    return result

def db_get_user(user_id):
    return db("SELECT * FROM users WHERE user_id=?", (user_id,), fetch="one")

def db_ensure_user(user_id, username=""):
    db("INSERT OR IGNORE INTO users (user_id, username) VALUES (?,?)", (user_id, username))

def db_set_name(user_id, full_name):
    db("UPDATE users SET full_name=? WHERE user_id=?", (full_name, user_id))

def db_count_refs(user_id):
    row = db("SELECT COUNT(*) FROM refs WHERE referrer_id=?", (user_id,), fetch="one")
    return row[0] if row else 0

def db_add_ref(referrer_id, referee_id):
    db("INSERT OR IGNORE INTO refs (referrer_id, referee_id) VALUES (?,?)", (referrer_id, referee_id))

def db_set_invited_by(user_id, referrer_id):
    db("UPDATE users SET invited_by=? WHERE user_id=? AND invited_by IS NULL", (referrer_id, user_id))

def db_set_completed(user_id):
    db("UPDATE users SET completed=1 WHERE user_id=?", (user_id,))

def db_is_completed(user_id):
    row = db("SELECT completed FROM users WHERE user_id=?", (user_id,), fetch="one")
    return bool(row and row[0])

def db_top5():
    return db("""
        SELECT u.full_name, COUNT(r.referee_id) as cnt
        FROM users u LEFT JOIN refs r ON u.user_id=r.referrer_id
        WHERE u.full_name IS NOT NULL
        GROUP BY u.user_id ORDER BY cnt DESC LIMIT 5
    """, fetch="all") or []

def db_winners():
    return db("""
        SELECT u.full_name, COUNT(r.referee_id) as cnt
        FROM users u LEFT JOIN refs r ON u.user_id=r.referrer_id
        WHERE u.completed=1
        GROUP BY u.user_id ORDER BY cnt DESC LIMIT 3
    """, fetch="all") or []

def db_all_users():
    rows = db("SELECT user_id FROM users WHERE full_name IS NOT NULL", fetch="all")
    return [r[0] for r in rows] if rows else []

def db_total():
    row = db("SELECT COUNT(*) FROM users WHERE full_name IS NOT NULL", fetch="one")
    return row[0] if row else 0

def db_completed_count():
    row = db("SELECT COUNT(*) FROM users WHERE completed=1", fetch="one")
    return row[0] if row else 0

def ref_link(user_id):
    return f"https://t.me/{BOT_USERNAME}?start={user_id}"

def progress_bar(count, total=REQUIRED_REFS):
    filled = min(count, total)
    empty = total - filled
    bar = "🟦" * filled + "⬜️" * empty
    return f"{bar}  {count}/{total}"

def main_text(full_name, user_id, count):
    return (
        f"👋 Salom, *{full_name}*!\n\n"
        f"🏆 *OLIMPIADA SOVG'ALARI*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🥇 1-o'rin — 50,000 so'm 💵\n"
        f"🥈 2-o'rin — 30,000 so'm 💵\n"
        f"🥉 3-o'rin — Telegram Gift 🎁\n"
        f"🎲 Random 2 ta — Telegram Gift 🎁\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 *Hisobingiz:*\n"
        f"{progress_bar(count)}\n\n"
        f"📌 Linkni *5 do'stingga* yubor!\n"
        f"Ular kanalga obuna bo'lib botga kirsin.\n\n"
        f"🔗 *Referal linking:*\n"
        f"`{ref_link(user_id)}`"
    )

def main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Hisobim", callback_data="myref"),
         InlineKeyboardButton("🏆 Reyting", callback_data="top")],
        [InlineKeyboardButton("📢 Kanal", url="https://t.me/satulugnor")]
    ])

def sub_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Kanalga obuna bo'lish", url="https://t.me/satulugnor")],
        [InlineKeyboardButton("✅ Obuna bo'ldim", callback_data="check_sub")]
    ])

async def is_subscribed(bot, user_id):
    try:
        m = await bot.get_chat_member(MAIN_CHANNEL, user_id)
        return m.status in ["member", "administrator", "creator"]
    except TelegramError:
        return False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id
    if context.args:
        try:
            context.user_data["ref_id"] = int(context.args[0])
        except ValueError:
            pass
    if not await is_subscribed(context.bot, uid):
        await update.message.reply_text(
            "╔══════════════════╗\n"
            "║  SAT ULUG'NOR    ║\n"
            "║    OLIMPIADA     ║\n"
            "╚══════════════════╝\n\n"
            "⚠️ Davom etish uchun avval\n"
            "*kanalimizga obuna bo'ling!*\n\n"
            "👇 Tugmani bosing:",
            parse_mode="Markdown",
            reply_markup=sub_keyboard()
        )
        return ConversationHandler.END
    db_ensure_user(uid, user.username or "")
    row = db_get_user(uid)
    if row and row[1]:
        count = db_count_refs(uid)
        await update.message.reply_text(
            main_text(row[1], uid, count),
            parse_mode="Markdown",
            reply_markup=main_keyboard()
        )
        return ConversationHandler.END
    await update.message.reply_text(
        "╔══════════════════╗\n"
        "║  SAT ULUG'NOR    ║\n"
        "║    OLIMPIADA     ║\n"
        "╚══════════════════╝\n\n"
        "🎓 *Xush kelibsiz!*\n\n"
        "📝 *Ismingizni* yuboring:",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove()
    )
    return ASK_NAME

async def check_sub_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    uid = query.from_user.id
    if not await is_subscribed(context.bot, uid):
        await query.answer("❌ Hali obuna bo'lmadingiz!", show_alert=True)
        return ConversationHandler.END
    await query.answer("✅ Tasdiqlandi!")
    db_ensure_user(uid, query.from_user.username or "")
    row = db_get_user(uid)
    if row and row[1]:
        count = db_count_refs(uid)
        await query.message.edit_text(
            main_text(row[1], uid, count),
            parse_mode="Markdown",
            reply_markup=main_keyboard()
        )
        return ConversationHandler.END
    await query.message.edit_text(
        "✅ *Obuna tasdiqlandi!*\n\n"
        "📝 *Ismingizni* yuboring:",
        parse_mode="Markdown"
    )
    return ASK_NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if len(name) < 2 or any(c.isdigit() for c in name):
        await update.message.reply_text(
            "❌ Noto'g'ri ism. Faqat harflar kiriting.\n"
            "📝 *Ismingizni* qayta yuboring:",
            parse_mode="Markdown"
        )
        return ASK_NAME
    context.user_data["first_name"] = name
    await update.message.reply_text(
        f"✅ Ism: *{name}*\n\n"
        "📝 *Familiyangizni* yuboring:",
        parse_mode="Markdown"
    )
    return ASK_SURNAME

async def get_surname(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    uid = user.id
    surname = update.message.text.strip()
    if len(surname) < 2 or any(c.isdigit() for c in surname):
        await update.message.reply_text(
            "❌ Noto'g'ri familiya. Faqat harflar kiriting.\n"
            "📝 *Familiyangizni* qayta yuboring:",
            parse_mode="Markdown"
        )
        return ASK_SURNAME
    first_name = context.user_data.get("first_name", "")
    full_name = f"{first_name} {surname}"
    db_ensure_user(uid, user.username or "")
    db_set_name(uid, full_name)
    ref_id = context.user_data.get("ref_id")
    row = db_get_user(uid)
    if ref_id and ref_id != uid and row and row[3] is None:
        db_set_invited_by(uid, ref_id)
        db_add_ref(ref_id, uid)
        count = db_count_refs(ref_id)
        try:
            await context.bot.send_message(
                ref_id,
                f"🎉 *{full_name}* do'stingiz qo'shildi!\n\n"
                f"📊 *Hisobingiz:*\n{progress_bar(count)}\n\n"
                + (f"🏆 *5 ta to'ldi! Olimpiadaga kirish yuborilmoqda...*"
                   if count >= REQUIRED_REFS
                   else f"💪 Yana *{REQUIRED_REFS - count} ta* do'st qoldi!"),
                parse_mode="Markdown"
            )
            if count >= REQUIRED_REFS and not db_is_completed(ref_id):
                db_set_completed(ref_id)
                await invite_to_olimpiada(context, ref_id)
        except TelegramError as e:
            logger.error(f"Ref notify error: {e}")
    count = db_count_refs(uid)
    await update.message.reply_text(
        f"🎊 *Ro'yxatdan o'tdingiz!*\n\n"
        + main_text(full_name, uid, count),
        parse_mode="Markdown",
        reply_markup=main_keyboard()
    )
    return ConversationHandler.END

async def invite_to_olimpiada(context, user_id):
    try:
        link = await context.bot.create_chat_invite_link(OLIMPIADA_GROUP, member_limit=1)
        row = db_get_user(user_id)
        full_name = row[1] if row else "Ishtirokchi"
        await context.bot.send_message(
            user_id,
            f"🏆 *Tabriklaymiz, {full_name}!*\n\n"
            f"5 ta do'st qo'shdingiz!\n"
            f"Siz olimpiadaga kirdingiz! 🎓\n\n"
            f"🔑 *Olimpiada guruhiga kirish:*\n"
            f"{link.invite_link}\n\n"
            f"⚠️ Link faqat *1 marta* ishlaydi!\n"
            f"Tezroq bosing! ⏰",
            parse_mode="Markdown"
        )
    except TelegramError as e:
        logger.error(f"Invite error: {e}")

async def myref_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    row = db_get_user(uid)
    full_name = row[1] if row and row[1] else "Foydalanuvchi"
    count = db_count_refs(uid)
    await query.message.reply_text(
        f"👤 *{full_name}*\n\n"
        f"📊 *Hisobingiz:*\n"
        f"{progress_bar(count)}\n\n"
        f"🔗 *Referal linkingiz:*\n"
        f"`{ref_link(uid)}`\n\n"
        f"💡 Linkni do'stlaringga yuboring!\n"
        f"Ular kanalga obuna bo'lib botga kirsin.",
        parse_mode="Markdown"
    )

async def top_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    top = db_top5()
    text = "🏆 *REYTING — TOP 5*\n━━━━━━━━━━━━━━━━━━━━\n\n"
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
    for i, (name, cnt) in enumerate(top):
        text += f"{medals[i]} *{name}* — {cnt} ta\n{progress_bar(min(cnt, REQUIRED_REFS))}\n\n"
    if not top:
        text += "Hali ishtirokchilar yo'q."
    await query.message.reply_text(text, parse_mode="Markdown")

async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    total = db_total()
    done = db_completed_count()
    top = db_top5()
    text = (
        f"📊 *ADMIN PANEL*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 Jami ishtirokchilar: *{total}*\n"
        f"✅ 5 ta to'lganlar: *{done}*\n\n"
        f"🏆 *Top 5:*\n"
    )
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
    for i, (name, cnt) in enumerate(top):
        text += f"{medals[i]} {name} — *{cnt} ta*\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def winners_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    top = db_winners()
    text = "🏆 *G'OLIBLAR*\n━━━━━━━━━━━━━━━━━━━━\n\n"
    for i, (name, cnt) in enumerate(top, 1):
        text += f"{PRIZES.get(i, '')}\n👤 *{name}* ({cnt} referal)\n\n"
    if not top:
        text += "Hali g'olib yo'q."
    await update.message.reply_text(text, parse_mode="Markdown")

async def random_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    participants = db_all_users()
    if len(participants) < 2:
        await update.message.reply_text("❌ Kamida 2 ta ishtirokchi kerak!")
        return
    chosen = random.sample(participants, 2)
    text = "🎲 *RANDOM TELEGRAM GIFT G'OLIBLARI*\n━━━━━━━━━━━━━━━━━━━━\n\n"
    for uid in chosen:
        row = db_get_user(uid)
        name = row[1] if row else str(uid)
        text += f"🎁 *{name}*\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    if not context.args:
        await update.message.reply_text("❌ /broadcast Xabar matni")
        return
    msg = " ".join(context.args)
    users = db_all_users()
    sent = 0
    for uid in users:
        try:
            await context.bot.send_message(uid, f"📢 *SAT ULUG'NOR:*\n\n{msg}", parse_mode="Markdown")
            sent += 1
        except TelegramError:
            pass
    await update.message.reply_text(f"✅ {sent} ta foydalanuvchiga yuborildi!")

async def myref_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    row = db_get_user(uid)
    full_name = row[1] if row and row[1] else "Foydalanuvchi"
    count = db_count_refs(uid)
    await update.message.reply_text(
        f"👤 *{full_name}*\n\n"
        f"📊 *Hisobingiz:*\n"
        f"{progress_bar(count)}\n\n"
        f"🔗 *Referal linkingiz:*\n"
        f"`{ref_link(uid)}`",
        parse_mode="Markdown"
    )

async def get_photo_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    photo = update.message.photo[-1]
    await update.message.reply_text(f"📸 *Rasm file_id:*\n`{photo.file_id}`", parse_mode="Markdown")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Bekor qilindi. /start bosing.")
    return ConversationHandler.END

def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    conv = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            CallbackQueryHandler(check_sub_callback, pattern="^check_sub$"),
        ],
        states={
            ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            ASK_SURNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_surname)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        per_message=False,
    )
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(myref_cb, pattern="^myref$"))
    app.add_handler(CallbackQueryHandler(top_cb, pattern="^top$"))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("winners", winners_cmd))
    app.add_handler(CommandHandler("random", random_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))
    app.add_handler(CommandHandler("myref", myref_cmd))
    app.add_handler(MessageHandler(filters.PHOTO, get_photo_id))
    logger.info("✅ SAT ULUG'NOR Bot ishga tushdi!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
