import os, sqlite3, logging
from datetime import datetime, timezone
from telegram import Update
from telegram.constants import ChatMemberStatus
from telegram.ext import Application, CommandHandler, ChatMemberHandler, ContextTypes

TOKEN = os.getenv("BOT_TOKEN", "")
GROUP_ID = int(os.getenv("GROUP_ID", "0"))
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()}
DB = os.getenv("DB_PATH", "referral_bot.db")

logging.basicConfig(level=logging.INFO)
db = sqlite3.connect(DB, check_same_thread=False)
db.row_factory = sqlite3.Row

def init_db():
    db.executescript("""
    CREATE TABLE IF NOT EXISTS users(
      user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT,
      points INTEGER DEFAULT 0, joins INTEGER DEFAULT 0, created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS invites(
      invite_link TEXT PRIMARY KEY, owner_id INTEGER, chat_id INTEGER, created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS credited(
      joined_user_id INTEGER PRIMARY KEY, owner_id INTEGER, invite_link TEXT, joined_at TEXT
    );
    """)
    db.commit()

def save_user(u):
    db.execute("""INSERT INTO users(user_id,username,first_name,created_at)
      VALUES(?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET
      username=excluded.username, first_name=excluded.first_name""",
      (u.id,u.username or "",u.first_name or "",datetime.now(timezone.utc).isoformat()))
    db.commit()

def name(r):
    return ("@" + r["username"]) if r["username"] else (r["first_name"] or str(r["user_id"]))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    save_user(update.effective_user)
    await update.message.reply_text(
        "🏆 Referral Competition Bot\n\n"
        "/link — আপনার referral link\n"
        "/points — আপনার point\n"
        "/leaderboard — Top 10\n"
        "/help — সব command")

async def link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not GROUP_ID:
        await update.message.reply_text("GROUP_ID সেট করুন।"); return
    u=update.effective_user; save_user(u)
    try:
        inv=await context.bot.create_chat_invite_link(
            chat_id=GROUP_ID, name=f"ref_{u.id}", creates_join_request=False)
        db.execute("INSERT OR REPLACE INTO invites VALUES(?,?,?,?)",
                   (inv.invite_link,u.id,GROUP_ID,datetime.now(timezone.utc).isoformat()))
        db.commit()
        await update.message.reply_text(
            f"🔗 আপনার Referral Link:\n{inv.invite_link}\n\n"
            "এই link দিয়ে নতুন member join করলে +1 point পাবেন।")
    except Exception:
        await update.message.reply_text(
            "❌ Link তৈরি হয়নি। Bot-কে Group Admin করুন এবং Invite Users permission দিন।")

async def points(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u=update.effective_user; save_user(u)
    r=db.execute("SELECT * FROM users WHERE user_id=?",(u.id,)).fetchone()
    await update.message.reply_text(f"🏆 Points: {r['points']}\n👥 Successful joins: {r['joins']}")

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows=db.execute("SELECT * FROM users ORDER BY points DESC, joins DESC LIMIT 10").fetchall()
    if not rows:
        await update.message.reply_text("এখনও কোনো data নেই।"); return
    medals=["🥇","🥈","🥉"]
    text="🏆 Leaderboard\n\n"
    for i,r in enumerate(rows,1):
        text += f"{medals[i-1] if i<=3 else str(i)+'.'} {name(r)} — {r['points']} pts\n"
    await update.message.reply_text(text)

async def winners(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        await update.message.reply_text("⛔ Admin only."); return
    rows=db.execute("SELECT * FROM users ORDER BY points DESC, joins DESC LIMIT 3").fetchall()
    if not rows:
        await update.message.reply_text("কোনো winner data নেই।"); return
    labels=["🥇 ১ম","🥈 ২য়","🥉 ৩য়"]
    await update.message.reply_text("\n".join(
        [f"{labels[i]} — {name(r)} — {r['points']} points" for i,r in enumerate(rows)]
    ))

async def member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cm=update.chat_member
    if not cm or cm.chat.id != GROUP_ID: return
    old,new=cm.old_chat_member,cm.new_chat_member
    member_status={ChatMemberStatus.MEMBER,ChatMemberStatus.ADMINISTRATOR,
                   ChatMemberStatus.OWNER,ChatMemberStatus.RESTRICTED}
    if old.status in member_status or new.status not in member_status: return
    save_user(new.user)
    if not cm.invite_link: return
    inv=db.execute("SELECT owner_id FROM invites WHERE invite_link=? AND chat_id=?",
                   (cm.invite_link.invite_link,GROUP_ID)).fetchone()
    if not inv or inv["owner_id"]==new.user.id: return
    if db.execute("SELECT 1 FROM credited WHERE joined_user_id=?",(new.user.id,)).fetchone(): return
    db.execute("INSERT INTO credited VALUES(?,?,?,?)",
               (new.user.id,inv["owner_id"],cm.invite_link.invite_link,
                datetime.now(timezone.utc).isoformat()))
    db.execute("UPDATE users SET points=points+1, joins=joins+1 WHERE user_id=?",
               (inv["owner_id"],))
    db.commit()

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("/link\n/points\n/leaderboard\n/winners (admin)")

def main():
    if not TOKEN or not GROUP_ID:
        raise SystemExit("BOT_TOKEN এবং GROUP_ID সেট করতে হবে।")
    init_db()
    app=Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start",start))
    app.add_handler(CommandHandler("link",link))
    app.add_handler(CommandHandler("points",points))
    app.add_handler(CommandHandler("leaderboard",leaderboard))
    app.add_handler(CommandHandler("winners",winners))
    app.add_handler(CommandHandler("help",help_cmd))
    app.add_handler(ChatMemberHandler(member_update, ChatMemberHandler.CHAT_MEMBER))
    app.run_polling(allowed_updates=["message","chat_member"])

if __name__=="__main__":
    main()
