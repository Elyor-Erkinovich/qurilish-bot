import logging
import os
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from database import Database
from reports import generate_daily_report
import pytz

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

db = Database()

# Conversation states
(TASK_TEXT, TASK_RESPONSIBLE, TASK_DEADLINE, TASK_PRIORITY,
 UPDATE_TASK_ID, UPDATE_STATUS, VOICE_TASK) = range(7)

TASHKENT_TZ = pytz.timezone("Asia/Tashkent")

# ─── Keyboards ────────────────────────────────────────────────────────────────

def main_keyboard():
    return ReplyKeyboardMarkup([
        ["➕ Топшириқ қўшиш", "📋 Жадвал кўриш"],
        ["📊 Статистика", "✅ Ҳолатни янгилаш"],
        ["🗑 Топшириқ ўчириш", "👥 Ходимлар рейтинги"],
    ], resize_keyboard=True)

def priority_keyboard():
    return ReplyKeyboardMarkup([
        ["🔴 Юқори", "🟡 Ўрта", "🟢 Паст"]
    ], resize_keyboard=True)

def status_keyboard():
    return ReplyKeyboardMarkup([
        ["⏳ Кутяпти", "🔄 Жараёнда", "✅ Бажарилди", "❌ Бекор қилинди"]
    ], resize_keyboard=True)

# ─── /start ───────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db.add_user(user.id, user.full_name, user.username or "")
    await update.message.reply_text(
        f"👋 Хуш келибсиз, {user.first_name}!\n\n"
        "📌 <b>Топшириқлар Менежери Боти</b>\n\n"
        "Бу бот орқали:\n"
        "• Топшириқлар қўшиш ва бошқариш\n"
        "• Ҳар куни соат 16:00 да автоматик ҳисобот\n"
        "• Ходимлар самарадорлигини кузатиш\n\n"
        "Бошлаш учун тугмалардан фойдаланинг 👇",
        parse_mode="HTML",
        reply_markup=main_keyboard()
    )

# ─── Add Task ─────────────────────────────────────────────────────────────────

async def add_task_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📝 <b>Янги топшириқ</b>\n\nТопшириқ матнини киритинг:",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardMarkup([["❌ Бекор қилиш"]], resize_keyboard=True)
    )
    return TASK_TEXT

async def add_task_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['task_text'] = update.message.text
    await update.message.reply_text(
        "👤 Масъул шахс исмини киритинг:"
    )
    return TASK_RESPONSIBLE

async def add_task_responsible(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['responsible'] = update.message.text
    await update.message.reply_text(
        "📅 Муддатни киритинг (масалан: 25.05.2025 ёки 25.05.2025 18:00):"
    )
    return TASK_DEADLINE

async def add_task_deadline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['deadline'] = update.message.text
    await update.message.reply_text(
        "🚦 Приоритетни танланг:",
        reply_markup=priority_keyboard()
    )
    return TASK_PRIORITY

async def add_task_priority(update: Update, context: ContextTypes.DEFAULT_TYPE):
    priority_map = {
        "🔴 Юқори": "Юқори", "🟡 Ўрта": "Ўрта", "🟢 Паст": "Паст"
    }
    priority = priority_map.get(update.message.text, "Ўрта")
    
    task_id = db.add_task(
        text=context.user_data['task_text'],
        responsible=context.user_data['responsible'],
        deadline=context.user_data['deadline'],
        priority=priority,
        created_by=update.effective_user.id,
        created_by_name=update.effective_user.full_name
    )
    
    await update.message.reply_text(
        f"✅ <b>Топшириқ #{task_id} қўшилди!</b>\n\n"
        f"📌 <b>Топшириқ:</b> {context.user_data['task_text']}\n"
        f"👤 <b>Масъул:</b> {context.user_data['responsible']}\n"
        f"📅 <b>Муддат:</b> {context.user_data['deadline']}\n"
        f"🚦 <b>Приоритет:</b> {priority}",
        parse_mode="HTML",
        reply_markup=main_keyboard()
    )
    return ConversationHandler.END

# ─── View Schedule ─────────────────────────────────────────────────────────────

async def view_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tasks = db.get_all_tasks()
    if not tasks:
        await update.message.reply_text(
            "📋 Ҳозирча топшириқлар мавжуд эмас.",
            reply_markup=main_keyboard()
        )
        return
    
    report = generate_daily_report(tasks, header="📋 <b>ТОПШИРИҚЛАР ЖАДВАЛИ</b>")
    for chunk in split_message(report):
        await update.message.reply_text(chunk, parse_mode="HTML")
    await update.message.reply_text("👆 Жадвал юқорида.", reply_markup=main_keyboard())

# ─── Statistics ────────────────────────────────────────────────────────────────

async def view_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tasks = db.get_all_tasks()
    stats = db.get_statistics()
    
    if not tasks:
        await update.message.reply_text("📊 Статистика учун топшириқлар йўқ.", reply_markup=main_keyboard())
        return
    
    total = stats['total']
    done = stats['done']
    in_progress = stats['in_progress']
    waiting = stats['waiting']
    cancelled = stats['cancelled']
    percent = round((done / total * 100), 1) if total > 0 else 0
    
    text = (
        "📊 <b>УМУМИЙ СТАТИСТИКА</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 Жами топшириқлар: <b>{total}</b>\n"
        f"✅ Бажарилди: <b>{done}</b>\n"
        f"🔄 Жараёнда: <b>{in_progress}</b>\n"
        f"⏳ Кутяпти: <b>{waiting}</b>\n"
        f"❌ Бекор қилинди: <b>{cancelled}</b>\n"
        f"📈 Умумий ижро фоизи: <b>{percent}%</b>\n\n"
    )
    
    # Progress bar
    filled = int(percent / 10)
    bar = "🟩" * filled + "⬜" * (10 - filled)
    text += f"{bar} {percent}%\n\n"
    
    # Per-employee stats
    emp_stats = db.get_employee_statistics()
    if emp_stats:
        text += "👥 <b>ХОДИМЛАР САМАРАДОРЛИГИ</b>\n"
        text += "━━━━━━━━━━━━━━━━━━━━━━\n"
        for i, emp in enumerate(emp_stats, 1):
            medal = ["🥇", "🥈", "🥉"][i-1] if i <= 3 else f"{i}."
            emp_pct = round(emp['percent'], 1)
            emp_bar = "🟩" * int(emp_pct / 10) + "⬜" * (10 - int(emp_pct / 10))
            text += (
                f"{medal} <b>{emp['responsible']}</b>\n"
                f"   Жами: {emp['total']} | ✅{emp['done']} 🔄{emp['in_progress']} ⏳{emp['waiting']}\n"
                f"   {emp_bar} <b>{emp_pct}%</b>\n\n"
            )
    
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=main_keyboard())

# ─── Update Status ─────────────────────────────────────────────────────────────

async def update_status_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tasks = db.get_active_tasks()
    if not tasks:
        await update.message.reply_text("Фаол топшириқлар мавжуд эмас.", reply_markup=main_keyboard())
        return ConversationHandler.END
    
    text = "🔄 <b>Ҳолатни янгилаш</b>\n\nТопшириқ рақамини киритинг:\n\n"
    for t in tasks[:20]:
        status_emoji = {"Кутяпти": "⏳", "Жараёнда": "🔄", "Бажарилди": "✅", "Бекор қилинди": "❌"}.get(t['status'], "❓")
        text += f"<code>#{t['id']}</code> {status_emoji} {t['text'][:40]} — <i>{t['responsible']}</i>\n"
    
    await update.message.reply_text(text, parse_mode="HTML",
        reply_markup=ReplyKeyboardMarkup([["❌ Бекор қилиш"]], resize_keyboard=True))
    return UPDATE_TASK_ID

async def update_task_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        task_id = int(update.message.text.replace("#", "").strip())
        task = db.get_task(task_id)
        if not task:
            await update.message.reply_text("❌ Топшириқ топилмади. Рақамни текширинг.")
            return UPDATE_TASK_ID
        context.user_data['update_task_id'] = task_id
        await update.message.reply_text(
            f"📌 <b>#{task_id}</b> — {task['text']}\n\nЯнги ҳолатни танланг:",
            parse_mode="HTML",
            reply_markup=status_keyboard()
        )
        return UPDATE_STATUS
    except ValueError:
        await update.message.reply_text("Илтимос, рақам киритинг.")
        return UPDATE_TASK_ID

async def update_task_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status_map = {
        "⏳ Кутяпти": "Кутяпти", "🔄 Жараёнда": "Жараёнда",
        "✅ Бажарилди": "Бажарилди", "❌ Бекор қилинди": "Бекор қилинди"
    }
    status = status_map.get(update.message.text)
    if not status:
        await update.message.reply_text("Ҳолатни тугмалардан танланг.")
        return UPDATE_STATUS
    
    task_id = context.user_data['update_task_id']
    db.update_task_status(task_id, status, update.effective_user.full_name)
    
    await update.message.reply_text(
        f"✅ <b>#{task_id}</b> топшириқ ҳолати «<b>{status}</b>» га янгиланди!",
        parse_mode="HTML",
        reply_markup=main_keyboard()
    )
    return ConversationHandler.END

# ─── Delete Task ───────────────────────────────────────────────────────────────

async def delete_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text(
            "🗑 Ўчириш учун: /del_task &lt;рақам&gt;\nМасалан: /del_task 5",
            parse_mode="HTML", reply_markup=main_keyboard()
        )
        return
    try:
        task_id = int(args[0])
        if db.delete_task(task_id):
            await update.message.reply_text(f"🗑 Топшириқ #{task_id} ўчирилди.", reply_markup=main_keyboard())
        else:
            await update.message.reply_text("❌ Топшириқ топилмади.", reply_markup=main_keyboard())
    except ValueError:
        await update.message.reply_text("Рақам киритинг.", reply_markup=main_keyboard())

# ─── Employee Rating ────────────────────────────────────────────────────────────

async def employee_rating(update: Update, context: ContextTypes.DEFAULT_TYPE):
    emp_stats = db.get_employee_statistics()
    if not emp_stats:
        await update.message.reply_text("Ҳозирча маълумот йўқ.", reply_markup=main_keyboard())
        return
    
    text = "🏆 <b>ХОДИМЛАР РЕЙТИНГИ</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    medals = ["🥇", "🥈", "🥉"]
    for i, emp in enumerate(emp_stats, 1):
        medal = medals[i-1] if i <= 3 else f"{i}."
        pct = round(emp['percent'], 1)
        text += (
            f"{medal} <b>{emp['responsible']}</b>\n"
            f"   ✅ Бажарди: {emp['done']}/{emp['total']} — <b>{pct}%</b>\n\n"
        )
    
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=main_keyboard())

# ─── Cancel ────────────────────────────────────────────────────────────────────

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Бекор қилинди.", reply_markup=main_keyboard())
    return ConversationHandler.END

# ─── Daily Report Scheduler ────────────────────────────────────────────────────

async def send_daily_report(app):
    tasks = db.get_all_tasks()
    stats = db.get_employee_statistics()
    
    report = generate_daily_report(tasks, header="🕓 <b>КУНДАЛИК ҲИСОБОТ — 16:00</b>")
    
    # Stats summary
    all_stats = db.get_statistics()
    total = all_stats['total']
    done = all_stats['done']
    pct = round((done / total * 100), 1) if total > 0 else 0
    
    report += f"\n\n📈 <b>УМУМИЙ ИЖРО ФОИЗИ: {pct}%</b>\n"
    bar = "🟩" * int(pct / 10) + "⬜" * (10 - int(pct / 10))
    report += f"{bar}\n\n"
    
    if stats:
        report += "👥 <b>ХОДИМЛАР САМАРАДОРЛИГИ:</b>\n"
        for i, emp in enumerate(stats, 1):
            medal = ["🥇", "🥈", "🥉"][i-1] if i <= 3 else f"{i}."
            ep = round(emp['percent'], 1)
            report += f"{medal} {emp['responsible']}: {emp['done']}/{emp['total']} — <b>{ep}%</b>\n"
    
    users = db.get_all_users()
    for user in users:
        try:
            for chunk in split_message(report):
                await app.bot.send_message(chat_id=user['telegram_id'], text=chunk, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Could not send to {user['telegram_id']}: {e}")

# ─── Helpers ───────────────────────────────────────────────────────────────────

def split_message(text, max_len=4000):
    chunks = []
    while len(text) > max_len:
        split_at = text.rfind('\n', 0, max_len)
        if split_at == -1:
            split_at = max_len
        chunks.append(text[:split_at])
        text = text[split_at:]
    chunks.append(text)
    return chunks

# ─── Main ──────────────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(TOKEN).build()
    
    # Add task conversation
    add_task_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^➕ Топшириқ қўшиш$"), add_task_start)],
        states={
            TASK_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_task_text)],
            TASK_RESPONSIBLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_task_responsible)],
            TASK_DEADLINE: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_task_deadline)],
            TASK_PRIORITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_task_priority)],
        },
        fallbacks=[MessageHandler(filters.Regex("^❌ Бекор қилиш$"), cancel)],
    )
    
    # Update status conversation
    update_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^✅ Ҳолатни янгилаш$"), update_status_start)],
        states={
            UPDATE_TASK_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, update_task_id)],
            UPDATE_STATUS: [MessageHandler(filters.TEXT & ~filters.COMMAND, update_task_status)],
        },
        fallbacks=[MessageHandler(filters.Regex("^❌ Бекор қилиш$"), cancel)],
    )
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("del_task", delete_task))
    app.add_handler(add_task_conv)
    app.add_handler(update_conv)
    app.add_handler(MessageHandler(filters.Regex("^📋 Жадвал кўриш$"), view_schedule))
    app.add_handler(MessageHandler(filters.Regex("^📊 Статистика$"), view_statistics))
    app.add_handler(MessageHandler(filters.Regex("^👥 Ходимлар рейтинги$"), employee_rating))
    app.add_handler(MessageHandler(filters.Regex("^🗑 Топшириқ ўчириш$"),
        lambda u, c: u.message.reply_text("Ўчириш учун: /del_task <рақам>", reply_markup=main_keyboard())))
    
    # Scheduler — 16:00 Tashkent time
    scheduler = AsyncIOScheduler(timezone=TASHKENT_TZ)
    scheduler.add_job(
        send_daily_report,
        trigger='cron',
        hour=16, minute=0,
        args=[app]
    )
    scheduler.start()
    
    logger.info("Bot started. Daily report scheduled at 16:00 Tashkent time.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
