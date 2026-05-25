import sys
try:
    import logging
    import os
    import tempfile
    import io
    import csv
    import json
    import urllib.parse
    import re
    from datetime import datetime, timedelta
    from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup
    from telegram.ext import (
        Application, CommandHandler, MessageHandler, CallbackQueryHandler,
        filters, ContextTypes, ConversationHandler
    )
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from database import Database
    from reports import generate_daily_report, generate_employee_grouped_report
    from voice_processor import process_voice, format_voice_confirmation
    import pytz
except Exception as e:
    import traceback
    print(f"CRITICAL IMPORT ERROR: {e}", file=sys.stderr, flush=True)
    traceback.print_exc(file=sys.stderr)
    sys.exit(1)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN", "8918133105:AAHz3oy-uTrzauVJvtyFir1CINfJHWE0bYk")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

db = Database()

# Conversation states
(TASK_TEXT, TASK_RESPONSIBLE, TASK_DEADLINE, TASK_PRIORITY,
 SCHEDULE_MENU, SCHEDULE_EMPLOYEE_SELECT, SCHEDULE_EMPLOYEE_ACTION,
 SCHEDULE_EMPLOYEE_ADD_TEXT, SCHEDULE_EMPLOYEE_ADD_DEADLINE, SCHEDULE_EMPLOYEE_ADD_PRIORITY,
 SCHEDULE_EMPLOYEE_UPDATE_ID, SCHEDULE_EMPLOYEE_UPDATE_STATUS,
 SCHEDULE_GENERAL_UPDATE_ID, SCHEDULE_GENERAL_UPDATE_STATUS,
 SCHEDULE_DELETE_TASK_ID, SCHEDULE_ADD_ATTACH_TASK_ID, SCHEDULE_ADD_ATTACH_CONTENT) = range(17)

TASHKENT_TZ = pytz.timezone("Asia/Tashkent")

# ─── Keyboards ────────────────────────────────────────────────────────────────

EMPLOYEES = [
    "Анвар ака (Гл.Инжинер)",
    "Элёр (Котибият)",
    "Мирзоҳид ака (Қурилиш)",
    "Абдулатиф (Коммунал)",
    "Наргиза (Котибият)",
    "Дилноза опа (Уй-жой)",
    "Фаррух (БСК)",
    "Зоҳид (Қурилиш)",
    "Жўрабек ака (Қурилиш)",
    "Одилхон (Қурилиш)",
    "Азамат (Аукцион)",
    "Зияд (Қурилиш)"
]

EMPLOYEE_USERNAMES = {
    "Анвар ака (Гл.Инжинер)": "@vbjdbfksb",
    "Элёр (Котибият)": "@elyor_erkinovich",
    "Мирзоҳид ака (Қурилиш)": "@m_4883",
    "Абдулатиф (Коммунал)": "@vakhabov7007",
    "Наргиза (Котибият)": "@nargis_yh",
    "Дилноза опа (Уй-жой)": "@Dilnoz_Gafurjanovna",
    "Фаррух (БСК)": "@TFF_077",
    "Зоҳид (Қурилиш)": "@asrorovch",
    "Жўрабек ака (Қурилиш)": "@Jurabek_baxtiyarocih",
    "Одилхон (Қурилиш)": "@odilxon_khusniddinovich",
    "Азамат (Аукцион)": "",
    "Зияд (Қурилиш)": "@ZI7799"
}

def get_responsible_display(responsible_name: str) -> str:
    username = EMPLOYEE_USERNAMES.get(responsible_name, "")
    if username:
        return f"{responsible_name} ({username})"
    return responsible_name

AUTHORIZED_USERS = [
    1936991,            # Elyor Erkinovich (User ID)
    "elyor_erkinovich", # Elyor Erkinovich (Username)
    "iiiiiiiii9_9",     # Иккинчи раҳбар (Username)
]

def is_manager(user) -> bool:
    if not user:
        return False
    user_id = user.id
    username = user.username
    
    if user_id in AUTHORIZED_USERS:
        return True
    if username and username.lower() in [u.lower() for u in AUTHORIZED_USERS if isinstance(u, str)]:
        return True
        
    return False

async def track_group_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat and chat.type in ["group", "supergroup"]:
        db.add_group(chat.id, chat.title)

async def welcome_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    for member in update.message.new_chat_members:
        if member.id == context.bot.id:
            db.add_group(update.effective_chat.id, update.effective_chat.title)
            text = (
                "🤖 <b>Салом, янги гуруҳ!</b>\n\n"
                "Мен <b>Топшириқлар ва Вазифалар Менежери Боти</b>ман.\n\n"
                "Раҳбарият мен орқали топшириқларни овозли ва матнли ярата олади. Ходимлар эса ўз вазифаларини кузатиб, бажарилганлиги ҳақида ҳисобот юбора оладилар.\n\n"
                "⚙️ <b>Бошлаш учун:</b>\n"
                "• Раҳбарлар янги топшириқ қўшиш учун <code>➕ Топшириқ қўшиш</code> деб ёзиши ёки ушбу хабарга <b>Reply (Жавоб)</b> қилиб овозли хабар юбориши мумкин.\n"
                "• Ходимлар ўз шахсий вазифаларини кўриш учун шахсий чатларида /my_tasks ни босишлари лозим."
            )
            await update.message.reply_text(text, parse_mode="HTML", reply_markup=main_keyboard())

async def is_user_in_group(user_id: int, bot) -> bool:
    groups = db.get_all_groups()
    if not groups:
        return True
        
    for g in groups:
        try:
            member = await bot.get_chat_member(chat_id=g['chat_id'], user_id=user_id)
            if member.status in ['member', 'administrator', 'creator', 'restricted']:
                return True
        except Exception as e:
            logger.error(f"Error checking group membership in group {g['chat_id']}: {e}")
            continue
    return False

async def is_authorized_user(user, bot=None) -> bool:
    if not user:
        return False
    # 1. Check if manager
    if is_manager(user):
        return True
        
    # 2. Check if already mapped in database
    if db.get_mapped_employee(user.id) is not None:
        return True
        
    # 3. Check if their username matches any of the registered employee usernames
    username = user.username
    if username:
        target = f"@{username}".lower()
        if target in [u.lower() for u in EMPLOYEE_USERNAMES.values() if u]:
            return True
            
    # 4. Check group membership (optional fallback)
    if bot:
        in_group = await is_user_in_group(user.id, bot)
        if in_group:
            return True
            
    # 5. If they don't have a username, allow access to linking screen if there are unmapped names without usernames
    if not username:
        unmapped_no_username = []
        for emp in EMPLOYEES:
            if EMPLOYEE_USERNAMES.get(emp) == "":
                if db.get_user_by_mapped_employee(emp) is None:
                    unmapped_no_username.append(emp)
        if unmapped_no_username:
            return True
            
    return False

def parse_deadline(deadline_str: str) -> Optional[datetime]:
    deadline_str = deadline_str.strip()
    # Try standard DD.MM.YYYY HH:MM
    for fmt in ("%d.%m.%Y %H:%M", "%d.%m.%Y", "%d/%m/%Y %H:%M", "%d/%m/%Y"):
        try:
            dt = datetime.strptime(deadline_str, fmt)
            return dt
        except ValueError:
            continue
    # If not parsable, search for DD.MM.YYYY
    match = re.search(r"(\d{2})[\./-](\d{2})[\./-](\d{4})", deadline_str)
    if match:
        day, month, year = map(int, match.groups())
        try:
            return datetime(year, month, day)
        except ValueError:
            pass
    return None

async def check_approaching_deadlines(app):
    tasks = db.get_active_tasks()
    if not tasks:
        return
        
    now = datetime.now(pytz.timezone("Asia/Tashkent"))
    
    for t in tasks:
        # Skip if alert already sent
        if t.get('deadline_alert_sent', 0) == 1:
            continue
            
        dt = parse_deadline(t['deadline'])
        if not dt:
            continue
            
        dt_tz = pytz.timezone("Asia/Tashkent").localize(dt) if dt.tzinfo is None else dt.astimezone(pytz.timezone("Asia/Tashkent"))
        
        # Calculate time difference
        diff = dt_tz - now
        
        # If deadline is between 0 and 3 hours from now
        if timedelta(seconds=0) < diff <= timedelta(hours=3):
            responsible = t['responsible']
            emp_user = db.get_user_by_mapped_employee(responsible)
            
            warning_text = (
                f"⚠️ <b>ВАРНИНГ: Муддат яқинлашмоқда!</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📌 <b>Топшириқ #{t['id']}:</b> {t['text']}\n"
                f"⏰ <b>Бажарилиш муддати:</b> {t['deadline']}\n\n"
                f"💡 <i>Илтимос, вазифани тез орада бажариб, раҳбариятга ҳисобот юборинг!</i>"
            )
            
            if emp_user:
                try:
                    await app.bot.send_message(chat_id=emp_user['telegram_id'], text=warning_text, parse_mode="HTML")
                    logger.info(f"Deadline warning sent to {responsible} for task #{t['id']}")
                except Exception as e:
                    logger.error(f"Could not send warning to {responsible}: {e}")
            else:
                if "ҳамма" in responsible.lower() or "хамма" in responsible.lower():
                    users = db.get_all_users()
                    for u in users:
                        try:
                            await app.bot.send_message(chat_id=u['telegram_id'], text=warning_text, parse_mode="HTML")
                        except Exception:
                            pass
                            
            db.set_deadline_alert_sent(t['id'])

async def send_weekly_report(app):
    tasks = db.get_all_tasks()
    if not tasks:
        return
        
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow([
        "ID", "Топшириқ матни", "Масъул", "Муддат", "Приоритет", "Ҳолати", 
        "Яратилган вақти", "Яратган ходим", "Янгилаган ходим"
    ])
    for t in tasks:
        writer.writerow([
            t['id'],
            t['text'],
            t['responsible'],
            t['deadline'],
            t['priority'],
            t['status'],
            t['created_at'],
            t['created_by_name'] or "",
            t['updated_by'] or ""
        ])
        
    csv_data = output.getvalue().encode('utf-8-sig')
    
    groups = db.get_all_groups()
    for g in groups:
        try:
            file_stream = io.BytesIO(csv_data)
            file_stream.name = "haftalik_hisobot.csv"
            await app.bot.send_document(
                chat_id=g['chat_id'],
                document=file_stream,
                filename="haftalik_hisobot.csv",
                caption="📅 <b>АВТОМАТИК ҲАФТАЛИК ЯКУНИЙ ҲИСОБОТ (Excel форматида)</b>",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Could not send weekly report to group {g['chat_id']}: {e}")
            
    users = db.get_all_users()
    for u in users:
        is_u_manager = (
            u['telegram_id'] in AUTHORIZED_USERS or 
            (u['username'] and u['username'].lower() in [a.lower() for a in AUTHORIZED_USERS if isinstance(a, str)])
        )
        if is_u_manager:
            try:
                file_stream = io.BytesIO(csv_data)
                file_stream.name = "haftalik_hisobot.csv"
                await app.bot.send_document(
                    chat_id=u['telegram_id'],
                    document=file_stream,
                    filename="haftalik_hisobot.csv",
                    caption="📅 <b>АВТОМАТИК ҲАФТАЛИК ЯКУНИЙ ҲИСОБОТ (Excel форматида)</b>",
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"Could not send weekly report to manager {u['telegram_id']}: {e}")

async def send_morning_reminders(app):
    tasks = db.get_active_tasks()
    if not tasks:
        return
        
    now = datetime.now(pytz.timezone("Asia/Tashkent"))
    today_date = now.date()
    
    overdue_tasks = []
    due_today_tasks = []
    
    for t in tasks:
        dt = parse_deadline(t['deadline'])
        if not dt:
            continue
            
        # Standardize timezone to Asia/Tashkent
        dt_tz = pytz.timezone("Asia/Tashkent").localize(dt) if dt.tzinfo is None else dt.astimezone(pytz.timezone("Asia/Tashkent"))
        
        if dt_tz.date() < today_date:
            overdue_tasks.append(t)
        elif dt_tz.date() == today_date:
            due_today_tasks.append(t)
            
    if not overdue_tasks and not due_today_tasks:
        return
        
    report = "🔔 <b>ЭРТАЛАБКИ ЭСЛАТМА (соат 09:00)</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    if overdue_tasks:
        report += "⏰ <b>МУДДАТИ ЎТИБ КЕТГАН ТОПШИРИҚЛАР:</b>\n"
        for i, t in enumerate(overdue_tasks, 1):
            report += f"❌ <code>#{t['id']}</code> {t['text']} — <b>{t['responsible']}</b> (Муддати: 📅 {t['deadline']})\n"
        report += "\n"
        
    if due_today_tasks:
        report += "📅 <b>БУГУН ТУГАЙДИГАН ТОПШИРИҚЛАР:</b>\n"
        for i, t in enumerate(due_today_tasks, 1):
            report += f"⚠️ <code>#{t['id']}</code> {t['text']} — <b>{t['responsible']}</b> (Муддати: 📅 {t['deadline']})\n"
        report += "\n"
        
    report += "💡 <i>Илтимос, вазифаларни муддатида бажариб, раҳбарларга тасдиқлаш учун юборинг.</i>"
    
    users = db.get_all_users()
    groups = db.get_all_groups()
    
    for user in users:
        try:
            for chunk in split_message(report):
                await app.bot.send_message(chat_id=user['telegram_id'], text=chunk, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Could not send reminder to user {user['telegram_id']}: {e}")
            
    for g in groups:
        try:
            for chunk in split_message(report):
                await app.bot.send_message(chat_id=g['chat_id'], text=chunk, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Could not send reminder to group {g['chat_id']}: {e}")

async def notify_task_created(task_id: int, text: str, responsible: str, deadline: str, priority: str, created_by_name: str, bot) -> None:
    priority_emoji = {"Юқори": "🔴", "Ўрта": "🟡", "Паст": "🟢"}.get(priority, "🟡")
    
    notification_text = (
        f"📅 <b>ЯНГИ ТОПШИРИҚ!</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📌 <b>Топшириқ #{task_id}:</b> {text}\n"
        f"👤 <b>Масъул:</b> {responsible}\n"
        f"📅 <b>Муддат:</b> {deadline}\n"
        f"{priority_emoji} <b>Приоритет:</b> {priority}\n"
        f"✍️ <b>Яратди:</b> {created_by_name}\n\n"
        f"💡 <i>Илтимос, вазифани муддатида бажариб, шахсий чатда /my_tasks орқали тасдиқлаш учун юборинг.</i>"
    )
    
    is_specific = (
        responsible in EMPLOYEES and 
        responsible != "Кўрсатилмаган" and 
        "хамма" not in responsible.lower() and 
        "ҳамма" not in responsible.lower()
    )
    
    if is_specific:
        emp_user = db.get_user_by_mapped_employee(responsible)
        if emp_user:
            try:
                await bot.send_message(chat_id=emp_user['telegram_id'], text=notification_text, parse_mode="HTML")
                logger.info(f"Notification sent to responsible employee {responsible} (ID: {emp_user['telegram_id']})")
            except Exception as e:
                logger.error(f"Could not send notification to {responsible}: {e}")
        else:
            logger.info(f"Responsible employee {responsible} is not mapped in database yet, cannot send private message.")
    else:
        users = db.get_all_users()
        logger.info(f"No specific responsible person assigned (value: {responsible}). Sending to all {len(users)} users.")
        for u in users:
            try:
                await bot.send_message(chat_id=u['telegram_id'], text=notification_text, parse_mode="HTML")
            except Exception as e:
                logger.error(f"Could not send notification to user {u['telegram_id']}: {e}")

def main_keyboard():
    """Main menu using Inline Keyboard."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Топшириқ қўшиш", callback_data="main_add_task"),
         InlineKeyboardButton("📋 Топшириқлар жадвали", callback_data="main_schedule")]
    ])

def main_reply_keyboard():
    """Main persistent bottom keyboard."""
    return ReplyKeyboardMarkup([
        ["➕ Топшириқ қўшиш", "📋 Топшириқлар жадвали"],
        ["📋 Менинг вазифаларим"]
    ], resize_keyboard=True)

def employee_keyboard(prefix: str):
    """Employee selection inline keyboard."""
    keyboard = []
    row = []
    for emp in EMPLOYEES:
        row.append(InlineKeyboardButton(emp, callback_data=f"{prefix}:{emp}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton("❌ Бекор қилиш", callback_data="cancel_action")])
    return InlineKeyboardMarkup(keyboard)

def employee_report_keyboard(employee_name: str):
    """Actions with employee inline keyboard."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"➕ {employee_name}га топшириқ қўшиш", callback_data=f"emp_add_task:{employee_name}")],
        [InlineKeyboardButton(f"⚙️ {employee_name} вазифасини янгилаш", callback_data=f"emp_update_task:{employee_name}")],
        [InlineKeyboardButton("🔄 Бошқа ходимлар", callback_data="sched_by_emp"),
         InlineKeyboardButton("❌ Бекор қилиш", callback_data="cancel_action")]
    ])

def priority_keyboard():
    """Priority inline keyboard."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔴 Юқори", callback_data="priority:Юқори"),
         InlineKeyboardButton("🟡 Ўрта", callback_data="priority:Ўрта"),
         InlineKeyboardButton("🟢 Паст", callback_data="priority:Паст")],
        [InlineKeyboardButton("❌ Бекор қилиш", callback_data="cancel_action")]
    ])

def status_keyboard(task_id: int, prefix="gen_status_update"):
    """Status update inline keyboard."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⏳ Кутяпти", callback_data=f"{prefix}:{task_id}:Кутяпти"),
         InlineKeyboardButton("🔄 Жараёнда", callback_data=f"{prefix}:{task_id}:Жараёнда")],
        [InlineKeyboardButton("✅ Бажарилди", callback_data=f"{prefix}:{task_id}:Бажарилди"),
         InlineKeyboardButton("❌ Бекор қилинди", callback_data=f"{prefix}:{task_id}:Бекор қилинди")],
        [InlineKeyboardButton("❌ Бекор қилиш", callback_data="cancel_action")]
    ])

def schedule_keyboard():
    """Schedule menu inline keyboard."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🌐 Умумий жадвал", callback_data="sched_general")],
        [InlineKeyboardButton("👤 Ходимлар бўйича", callback_data="sched_by_emp"),
         InlineKeyboardButton("📅 Ҳафталик тақвим", callback_data="sched_weekly")],
        [InlineKeyboardButton("✅ Ҳолатни янгилаш", callback_data="sched_update"),
         InlineKeyboardButton("🗑 Топшириқ ўчириш", callback_data="sched_delete")],
        [InlineKeyboardButton("💬 Изоҳ/Файл қўшиш", callback_data="sched_add_attachment"),
         InlineKeyboardButton("📥 Excel'га экспорт", callback_data="sched_export")],
        [InlineKeyboardButton("📊 Статистика", callback_data="main_stats"),
         InlineKeyboardButton("👥 Ходимлар рейтинги", callback_data="main_rating")],
        [InlineKeyboardButton("❌ Бекор қилиш", callback_data="cancel_action")]
    ])

# ─── /start ───────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not await is_authorized_user(user, context.bot):
        text = (
            "❌ <b>Кириш рад этилди!</b>\n\n"
            "Ушбу ботдаги вазифалар ва иш жадваллари махфий бўлиб, ундан фойдаланиш фақат белгиланган жамоа аъзолари (раҳбарлар ва ходимлар) учун рухсат этилган."
        )
        if update.callback_query:
            await update.callback_query.answer("Кириш тақиқланган!", show_alert=True)
            await update.callback_query.message.reply_text(text, parse_mode="HTML")
        else:
            await update.message.reply_text(text, parse_mode="HTML")
        return ConversationHandler.END

    db.add_user(user.id, user.full_name, user.username or "")
    text = (
        f"👋 Хуш келибсиз, {user.first_name}!\n\n"
        "📌 <b>Топшириқлар Менежери Боти</b>\n\n"
        "Бу бот орқали:\n"
        "• Топшириқлар қўшиш ва бошқариш\n"
        "• 🎙️ <b>Овозли буйруқ</b> орқали топшириқ қўшиш (ўзбекча)\n"
        "• Ҳар куни соат 16:00 да автоматик ҳисобот\n"
        "• Ходимлар самарадорлигини кузатиш\n\n"
        "💡 <i>Овозли топшириқ: микрофон тугмасини босиб гапиринг!</i>\n\n"
        "Бошлаш учун тугмалардан фойдаланинг 👇"
    )
    
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(
            text, parse_mode="HTML", reply_markup=main_reply_keyboard()
        )
    else:
        await update.message.reply_text(
            text, parse_mode="HTML", reply_markup=main_reply_keyboard()
        )
    return ConversationHandler.END

# ─── Global Cancel ────────────────────────────────────────────────────────────

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop('responsible', None)
    context.user_data.pop('task_text', None)
    context.user_data.pop('deadline', None)
    context.user_data.pop('prompt_message_id', None)
    context.user_data.pop('report_emp_name', None)
    context.user_data.pop('report_task_text', None)
    context.user_data.pop('report_task_deadline', None)
    context.user_data.pop('report_update_task_id', None)
    context.user_data.pop('general_update_task_id', None)

    text = "❌ <b>Амал бекор қилинди.</b>\n\nБошлаш учун қуйидаги тугмалардан фойдаланинг 👇"
    
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.edit_text(text, parse_mode="HTML", reply_markup=main_keyboard())
    else:
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=main_reply_keyboard())
    return ConversationHandler.END

async def cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await cancel(update, context)

# ─── Add Task ─────────────────────────────────────────────────────────────────

async def add_task_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_manager(user):
        text = "❌ <b>Рад этилди!</b>\n\nЯнги топшириқ қўшиш ҳуқуқи фақат раҳбарларга берилган."
        if update.callback_query:
            await update.callback_query.answer("Амал тақиқланган!", show_alert=True)
            await update.callback_query.message.reply_text(text, parse_mode="HTML")
        else:
            await update.message.reply_text(text, parse_mode="HTML")
        return ConversationHandler.END

    context.user_data.pop('responsible', None)
    context.user_data.pop('task_text', None)
    context.user_data.pop('prompt_message_id', None)
    
    text_msg = "📝 <b>Янги топшириқ</b>\n\nТопшириқ матнини ёзиб юборинг ёки пастдаги тугмалардан масъул ходимни танланг 👇"
    
    if update.callback_query:
        await update.callback_query.answer()
        sent_msg = await update.callback_query.message.edit_text(
            text_msg,
            parse_mode="HTML",
            reply_markup=employee_keyboard("add_emp")
        )
    else:
        sent_msg = await update.message.reply_text(
            text_msg,
            parse_mode="HTML",
            reply_markup=employee_keyboard("add_emp")
        )
    
    context.user_data['prompt_message_id'] = sent_msg.message_id
    return TASK_TEXT

async def add_task_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        if not update.message.reply_to_message or update.message.reply_to_message.message_id != context.user_data.get('prompt_message_id'):
            return # Ignore
            
    text = update.message.text
    context.user_data['task_text'] = text
    
    sent_msg = await update.message.reply_text(
        "👤 Масъул шахсни танланг:",
        reply_markup=employee_keyboard("add_emp")
    )
    context.user_data['prompt_message_id'] = sent_msg.message_id
    return TASK_RESPONSIBLE

async def add_task_emp_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    emp = query.data.split(":", 1)[1]
    
    context.user_data['responsible'] = emp
    
    if 'task_text' in context.user_data:
        sent_msg = await query.message.edit_text(
            f"👤 <b>Масъул:</b> {emp}\n📌 <b>Топшириқ:</b> {context.user_data['task_text']}\n\n"
            f"📅 Муддатни киритинг (масалан: 25.05.2025 ёки 25.05.2025 18:00):\n"
            f"<i>Илтимос, ушбу хабарга Reply қилиб ёзинг.</i>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Бекор қилиш", callback_data="cancel_action")]])
        )
        context.user_data['prompt_message_id'] = sent_msg.message_id
        return TASK_DEADLINE
    else:
        sent_msg = await query.message.edit_text(
            f"👤 <b>Масъул:</b> {emp}\n\n"
            f"📝 Энди ушбу ходимга бериладиган топшириқ матнини киритинг:\n"
            f"<i>Илтимос, ушбу хабарга Reply қилиб ёзинг.</i>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Бекор қилиш", callback_data="cancel_action")]])
        )
        context.user_data['prompt_message_id'] = sent_msg.message_id
        return TASK_RESPONSIBLE

async def add_task_responsible(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        if not update.message.reply_to_message or update.message.reply_to_message.message_id != context.user_data.get('prompt_message_id'):
            return # Ignore
            
    text = update.message.text
    
    if 'responsible' in context.user_data:
        context.user_data['task_text'] = text
    else:
        context.user_data['responsible'] = text
        
    sent_msg = await update.message.reply_text(
        "📅 Муддатни киритинг (масалан: 25.05.2025 ёки 25.05.2025 18:00):\n"
        "<i>Илтимос, ушбу хабарга Reply қилиб ёзинг.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Бекор қилиш", callback_data="cancel_action")]])
    )
    context.user_data['prompt_message_id'] = sent_msg.message_id
    return TASK_DEADLINE

async def add_task_deadline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        if not update.message.reply_to_message or update.message.reply_to_message.message_id != context.user_data.get('prompt_message_id'):
            return # Ignore
            
    context.user_data['deadline'] = update.message.text
    sent_msg = await update.message.reply_text(
        "🚦 Приоритетни танланг:",
        reply_markup=priority_keyboard()
    )
    context.user_data['prompt_message_id'] = sent_msg.message_id
    return TASK_PRIORITY

async def add_task_priority(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_manager(user):
        await update.message.reply_text("❌ <b>Рад этилди!</b>\n\nЯнги топшириқ қўшиш ҳуқуқи фақат раҳбарларга берилган.", parse_mode="HTML")
        return ConversationHandler.END

    priority = "Ўрта"
    
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        priority = query.data.split(":", 1)[1]
    else:
        if update.effective_chat.type != "private":
            if not update.message.reply_to_message or update.message.reply_to_message.message_id != context.user_data.get('prompt_message_id'):
                return # Ignore
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
    
    await notify_task_created(
        task_id=task_id,
        text=context.user_data['task_text'],
        responsible=context.user_data['responsible'],
        deadline=context.user_data['deadline'],
        priority=priority,
        created_by_name=update.effective_user.full_name,
        bot=context.bot
    )
    
    confirm_text = (
        f"✅ <b>Топшириқ #{task_id} қўшилди!</b>\n\n"
        f"📌 <b>Топшириқ:</b> {context.user_data['task_text']}\n"
        f"👤 <b>Масъул:</b> {get_responsible_display(context.user_data['responsible'])}\n"
        f"📅 <b>Муддат:</b> {context.user_data['deadline']}\n"
        f"🚦 <b>Приоритет:</b> {priority}"
    )
    
    if update.callback_query:
        await update.callback_query.message.edit_text(confirm_text, parse_mode="HTML", reply_markup=main_keyboard())
    else:
        await update.message.reply_text(confirm_text, parse_mode="HTML", reply_markup=main_keyboard())
        
    return ConversationHandler.END

# ─── Schedule & Reports ───────────────────────────────────────────────────────

async def schedule_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not await is_authorized_user(user, context.bot):
        text = (
            "❌ <b>Кириш рад этилди!</b>\n\n"
            "Ушбу ботдаги вазифалар ва иш жадваллари махфий бўлиб, ундан фойдаланиш фақат белгиланган жамоа аъзолари (раҳбарлар ва ходимлар) учун рухсат этилган."
        )
        if update.callback_query:
            await update.callback_query.answer("Кириш тақиқланган!", show_alert=True)
            await update.callback_query.message.reply_text(text, parse_mode="HTML")
        else:
            await update.message.reply_text(text, parse_mode="HTML")
        return ConversationHandler.END

    text_msg = (
        "📋 <b>Топшириқлар жадвали ва бошқарув бўлими</b>\n\n"
        "Қайси амални бажармоқчисиз? Пастдаги тугмалардан танланг:\n"
        "• 🌐 <b>Умумий жадвал</b> — барча ходимларнинг топшириқларини умумий жадвал сифатида кўриш\n"
        "• 👤 <b>Ходимлар бўйича</b> — ходимлар рўйхати, уларнинг статистикаси ва топшириқлари\n"
        "• ✅ <b>Ҳолатни янгилаш</b> — топшириқ рақамини киритиб, унинг ҳолатини ўзгартириш\n"
        "• 🗑 <b>Топшириқ ўчириш</b> — топшириқ рақамини киритиб ўчириш"
    )
    
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        sent_msg = await query.message.edit_text(
            text_msg,
            parse_mode="HTML",
            reply_markup=schedule_keyboard()
        )
    else:
        sent_msg = await update.message.reply_text(
            text_msg,
            parse_mode="HTML",
            reply_markup=schedule_keyboard()
        )
    context.user_data['prompt_message_id'] = sent_msg.message_id
    return SCHEDULE_MENU

async def schedule_show(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = ""
    query = None
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        text = query.data
    else:
        text = update.message.text
        if text == "❌ Бекор қилиш":
            await update.message.reply_text("⬅️ Асосий меню", reply_markup=main_reply_keyboard())
            return ConversationHandler.END
            
    if text == "sched_general" or text == "🌐 Умумий жадвал":
        tasks = db.get_all_tasks()
        if not tasks:
            msg_text = "📋 Ҳозирча топшириқлар мавжуд эмас."
            if query:
                await query.message.edit_text(msg_text, reply_markup=schedule_keyboard())
            else:
                await update.message.reply_text(msg_text, reply_markup=schedule_keyboard())
            return SCHEDULE_MENU

        report = generate_employee_grouped_report(tasks, header="🌐 <b>УМУМИЙ ТОПШИРИҚЛАР ЖАДВАЛИ (ХОДИМЛАР КЕСИМИДА)</b>", employees=EMPLOYEES)
        chunks = split_message(report)
        for chunk in chunks[:-1]:
            if query:
                await query.message.reply_text(chunk, parse_mode="HTML")
            else:
                await update.message.reply_text(chunk, parse_mode="HTML")
                
        if query:
            await query.message.reply_text(chunks[-1], parse_mode="HTML", reply_markup=schedule_keyboard())
        else:
            await update.message.reply_text(chunks[-1], parse_mode="HTML", reply_markup=schedule_keyboard())
        return SCHEDULE_MENU

    if text == "sched_by_emp" or text == "👤 Ходимлар бўйича":
        msg_text = (
            "👤 <b>Ходимлар бўйича ҳисобот ва бошқарув</b>\n\n"
            "Қайси ходим бўйича ҳисоботни кўрмоқчисиз? Пастдаги рўйхатдан танланг 👇"
        )
        if query:
            sent_msg = await query.message.edit_text(msg_text, parse_mode="HTML", reply_markup=employee_keyboard("select_emp"))
        else:
            sent_msg = await update.message.reply_text(msg_text, parse_mode="HTML", reply_markup=employee_keyboard("select_emp"))
        context.user_data['prompt_message_id'] = sent_msg.message_id
        return SCHEDULE_EMPLOYEE_SELECT

    if text == "sched_weekly" or text == "📅 Ҳафталик тақвим":
        tasks = db.get_active_tasks()
        if not tasks:
            msg_text = "📅 Ҳозирча фаол топшириқлар мавжуд эмас."
            if query:
                await query.message.edit_text(msg_text, reply_markup=schedule_keyboard())
            else:
                await update.message.reply_text(msg_text, reply_markup=schedule_keyboard())
            return SCHEDULE_MENU

        days_names = ["Душанба", "Сешанба", "Чоршанба", "Пайшанба", "Жума", "Шанба", "Якшанба"]
        grouped_tasks = {name: [] for name in days_names}
        others = []

        now = datetime.now(pytz.timezone("Asia/Tashkent"))
        start_of_week = now - timedelta(days=now.weekday())
        start_of_week = start_of_week.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_week = start_of_week + timedelta(days=7)

        for t in tasks:
            dt = parse_deadline(t['deadline'])
            if dt:
                dt_tz = pytz.timezone("Asia/Tashkent").localize(dt) if dt.tzinfo is None else dt.astimezone(pytz.timezone("Asia/Tashkent"))
                if start_of_week <= dt_tz < end_of_week:
                    day_name = days_names[dt_tz.weekday()]
                    grouped_tasks[day_name].append(t)
                else:
                    others.append(t)
            else:
                others.append(t)

        report = "📅 <b>ҲАФТАЛИК ТОПШИРИҚЛАР ТАҚВИМИ</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
        has_tasks = False
        for day in days_names:
            day_tasks = grouped_tasks[day]
            if day_tasks:
                has_tasks = True
                report += f"📌 <b>{day}:</b>\n"
                for i, t in enumerate(day_tasks, 1):
                    status_emoji = {"Кутяпти": "⏳", "Жараёнда": "🔄"}.get(t['status'], "⏳")
                    priority_emoji = {"Юқори": "🔴", "Ўрта": "🟡", "Паст": "🟢"}.get(t['priority'], "🟡")
                    report += f"   {i}. <code>#{t['id']}</code> {t['text']} — <b>{t['responsible']}</b> (Муддат: {t['deadline']})\n"
                report += "\n"

        if not has_tasks:
            report += "📭 Ушбу ҳафта учун фаол топшириқлар режалаштирилмаган.\n\n"
            
        if others:
            report += "⏳ <b>БОШҚА МУДДАТДАГИ ВАЗИФАЛАР (ҲАФТАДАН ТАШҚАРИ):</b>\n"
            for i, t in enumerate(others[:10], 1):
                report += f"   • <code>#{t['id']}</code> {t['text']} — <b>{t['responsible']}</b> (📅 {t['deadline']})\n"
            if len(others) > 10:
                report += f"   <i>... ва яна {len(others) - 10} та бошқа вазифалар.</i>\n"

        chunks = split_message(report)
        for chunk in chunks[:-1]:
            if query:
                await query.message.reply_text(chunk, parse_mode="HTML")
            else:
                await update.message.reply_text(chunk, parse_mode="HTML")
                
        if query:
            await query.message.reply_text(chunks[-1], parse_mode="HTML", reply_markup=schedule_keyboard())
        else:
            await update.message.reply_text(chunks[-1], parse_mode="HTML", reply_markup=schedule_keyboard())
        return SCHEDULE_MENU

    if text == "sched_add_attachment" or text == "💬 Изоҳ/Файл қўшиш":
        if not is_manager(update.effective_user):
            msg = "❌ <b>Рад этилди!</b>\n\nИзоҳ ёки файл қўшиш ҳуқуқи фақат раҳбарларга берилган."
            if query:
                await query.answer("Сизда бу амалга ҳуқуқ йўқ!", show_alert=True)
                await query.message.reply_text(msg, parse_mode="HTML", reply_markup=schedule_keyboard())
            else:
                await update.message.reply_text(msg, parse_mode="HTML", reply_markup=schedule_keyboard())
            return SCHEDULE_MENU

        tasks = db.get_active_tasks()
        if not tasks:
            msg_text = "❌ Фаол топшириқлар мавжуд эмас."
            if query:
                await query.message.edit_text(msg_text, reply_markup=schedule_keyboard())
            else:
                await update.message.reply_text(msg_text, reply_markup=schedule_keyboard())
            return SCHEDULE_MENU

        text_msg = "💬 <b>Изоҳ ёки файл қўшиш</b>\n\nТопшириқ рақамини киритинг:\n\n"
        for t in tasks[:20]:
            status_emoji = {"Кутяпти": "⏳", "Жараёнда": "🔄", "Бажарилди": "✅", "Бекор қилинди": "❌"}.get(t['status'], "❓")
            text_msg += f"<code>#{t['id']}</code> {status_emoji} {t['text'][:40]} — <i>{t['responsible']}</i>\n"

        if query:
            sent_msg = await query.message.edit_text(
                text_msg,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Бекор қилиш", callback_data="cancel_action")]])
            )
        else:
            sent_msg = await update.message.reply_text(
                text_msg,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Бекор қилиш", callback_data="cancel_action")]])
            )
        context.user_data['prompt_message_id'] = sent_msg.message_id
        return SCHEDULE_ADD_ATTACH_TASK_ID

    if text == "sched_update" or text == "✅ Ҳолатни янгилаш":
        if not is_manager(update.effective_user):
            msg = "❌ <b>Рад этилди!</b>\n\nТопшириқлар ҳолатини ўзгартириш ҳуқуқи фақат раҳбарларга берилган."
            if query:
                await query.answer("Сизда бу амалга ҳуқуқ йўқ!", show_alert=True)
                await query.message.reply_text(msg, parse_mode="HTML", reply_markup=schedule_keyboard())
            else:
                await update.message.reply_text(msg, parse_mode="HTML", reply_markup=schedule_keyboard())
            return SCHEDULE_MENU

        tasks = db.get_active_tasks()
        if not tasks:
            msg_text = "❌ Фаол топшириқлар мавжуд эмас."
            if query:
                await query.message.edit_text(msg_text, reply_markup=schedule_keyboard())
            else:
                await update.message.reply_text(msg_text, reply_markup=schedule_keyboard())
            return SCHEDULE_MENU

        text_msg = "🔄 <b>Ҳолатни янгилаш</b>\n\nТопшириқ рақамини киритинг:\n\n"
        for t in tasks[:20]:
            status_emoji = {"Кутяпти": "⏳", "Жараёнда": "🔄", "Бажарилди": "✅", "Бекор қилинди": "❌"}.get(t['status'], "❓")
            text_msg += f"<code>#{t['id']}</code> {status_emoji} {t['text'][:40]} — <i>{t['responsible']}</i>\n"

        if query:
            sent_msg = await query.message.edit_text(
                text_msg,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Бекор қилиш", callback_data="cancel_action")]])
            )
        else:
            sent_msg = await update.message.reply_text(
                text_msg,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Бекор қилиш", callback_data="cancel_action")]])
            )
        context.user_data['prompt_message_id'] = sent_msg.message_id
        return SCHEDULE_GENERAL_UPDATE_ID

    if text == "sched_export" or text == "📥 Excel'га экспорт":
        tasks = db.get_all_tasks()
        if not tasks:
            msg_text = "❌ Экспорт қилиш учун топшириқлар мавжуд эмас."
            if query:
                await query.message.edit_text(msg_text, reply_markup=schedule_keyboard())
            else:
                await update.message.reply_text(msg_text, reply_markup=schedule_keyboard())
            return SCHEDULE_MENU

        output = io.StringIO()
        writer = csv.writer(output, delimiter=';')
        writer.writerow([
            "ID", "Топшириқ матни", "Масъул", "Муддат", "Приоритет", "Ҳолати", 
            "Яратилган вақти", "Яратган ходим", "Янгилаган ходим"
        ])
        for t in tasks:
            writer.writerow([
                t['id'],
                t['text'],
                t['responsible'],
                t['deadline'],
                t['priority'],
                t['status'],
                t['created_at'],
                t['created_by_name'] or "",
                t['updated_by'] or ""
            ])
            
        csv_data = output.getvalue().encode('utf-8-sig')
        file_stream = io.BytesIO(csv_data)
        file_stream.name = "topshiriqlar.csv"

        if query:
            await query.message.reply_document(
                document=file_stream,
                filename="topshiriqlar.csv",
                caption="📊 <b>Барча топшириқлар жадвали (Excel/CSV форматида)</b>",
                parse_mode="HTML"
            )
            await query.message.reply_text("📋 Топшириқлар жадвали бўлими:", reply_markup=schedule_keyboard())
        else:
            await update.message.reply_document(
                document=file_stream,
                filename="topshiriqlar.csv",
                caption="📊 <b>Барча топшириқлар жадвали (Excel/CSV форматида)</b>",
                parse_mode="HTML"
            )
            await update.message.reply_text("📋 Топшириқлар жадвали бўлими:", reply_markup=schedule_keyboard())
        return SCHEDULE_MENU

    if text == "sched_delete" or text == "🗑 Топшириқ ўчириш":
        if not is_manager(update.effective_user):
            msg = "❌ <b>Рад этилди!</b>\n\nТопшириқларни ўчириш ҳуқуқи фақат раҳбарларга берилган."
            if query:
                await query.answer("Сизда бу амалга ҳуқуқ йўқ!", show_alert=True)
                await query.message.reply_text(msg, parse_mode="HTML", reply_markup=schedule_keyboard())
            else:
                await update.message.reply_text(msg, parse_mode="HTML", reply_markup=schedule_keyboard())
            return SCHEDULE_MENU

        tasks = db.get_active_tasks()
        if not tasks:
            msg_text = "❌ Фаол топшириқлар мавжуд эмас."
            if query:
                await query.message.edit_text(msg_text, reply_markup=schedule_keyboard())
            else:
                await update.message.reply_text(msg_text, reply_markup=schedule_keyboard())
            return SCHEDULE_MENU

        text_msg = "🗑 <b>Топшириқни ўчириш</b>\n\nЎчирмоқчи бўлган топшириқ рақамини киритинг:\n\n"
        for t in tasks[:20]:
            status_emoji = {"Кутяпти": "⏳", "Жараёнда": "🔄", "Бажарилди": "✅", "Бекор қилинди": "❌"}.get(t['status'], "❓")
            text_msg += f"<code>#{t['id']}</code> {status_emoji} {t['text'][:40]} — <i>{t['responsible']}</i>\n"

        if query:
            sent_msg = await query.message.edit_text(
                text_msg,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Бекор қилиш", callback_data="cancel_action")]])
            )
        else:
            sent_msg = await update.message.reply_text(
                text_msg,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Бекор қилиш", callback_data="cancel_action")]])
            )
        context.user_data['prompt_message_id'] = sent_msg.message_id
        return SCHEDULE_DELETE_TASK_ID

    if text == "cancel_action":
        return await cancel(update, context)

    return SCHEDULE_MENU

async def schedule_employee_select(update: Update, context: ContextTypes.DEFAULT_TYPE):
    emp = ""
    query = None
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        emp = query.data.split(":", 1)[1]
    else:
        if update.effective_chat.type != "private":
            if not update.message.reply_to_message or update.message.reply_to_message.message_id != context.user_data.get('prompt_message_id'):
                return # Ignore
        emp = update.message.text
        if emp == "❌ Бекор қилиш":
            return await cancel(update, context)
            
    if emp not in EMPLOYEES:
        return SCHEDULE_EMPLOYEE_SELECT

    context.user_data['report_emp_name'] = emp
    return await show_employee_report_and_actions(update, context, emp)

async def show_employee_report_and_actions(update: Update, context: ContextTypes.DEFAULT_TYPE, emp_name: str):
    stats = db.get_single_employee_statistics(emp_name)
    tasks = db.get_employee_tasks(emp_name)

    total = stats['total']
    done = stats['done']
    in_progress = stats['in_progress']
    waiting = stats['waiting']
    cancelled = stats['cancelled']

    percent = round((done / total * 100), 1) if total > 0 else 0
    filled = int(percent / 10)
    bar = "🟩" * filled + "⬜" * (10 - filled)

    report = (
        f"👤 <b>Ходим: {emp_name}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 Жами топшириқлар: <b>{total}</b>\n"
        f"✅ Бажарилди: <b>{done}</b>\n"
        f"🔄 Жараёнда: <b>{in_progress}</b>\n"
        f"⏳ Кутяпти: <b>{waiting}</b>\n"
        f"❌ Бекор қилинди: <b>{cancelled}</b>\n"
        f"📈 Ижро фоизи: <b>{percent}%</b>\n"
        f"{bar}\n\n"
    )

    if not tasks:
        report += "📭 Ушбу ходимда ҳозирча топшириқлар мавжуд эмас.\n"
    else:
        report += "📋 <b>ТОПШИРИҚЛАР РЎЙХАТИ:</b>\n\n"
        for i, t in enumerate(tasks, 1):
            status_emoji = {"Кутяпти": "⏳", "Жараёнда": "🔄", "Бажарилди": "✅", "Бекор қилинди": "❌"}.get(t['status'], "❓")
            priority_emoji = {"Юқори": "🔴", "Ўрта": "🟡", "Паст": "🟢"}.get(t['priority'], "🟡")

            report += (
                f"<b>{i}. #{t['id']} {t['text']}</b>\n"
                f"   Ҳолати: {status_emoji} {t['status']} | Приоритет: {priority_emoji} {t['priority']}\n"
                f"   Муддати: 📅 {t['deadline']}\n"
            )
            attachments = db.get_task_attachments(t['id'])
            if attachments:
                report += "   💬 <b>Изоҳлар/Файллар:</b>\n"
                for att in attachments:
                    att_time = att['created_at']
                    if att['type'] == 'text':
                        report += f"     • {att['content']} (📅 {att_time})\n"
                    else:
                        caption = att['content'].split("|", 1)[1] if "|" in att['content'] else ""
                        file_type = "Расм" if att['type'] == 'photo' else "Ҳужжат"
                        if caption:
                            report += f"     • [{file_type}] {caption} (📅 {att_time})\n"
                        else:
                            report += f"     • [{file_type}] (📅 {att_time})\n"
            report += "\n"

    chunks = split_message(report)
    for chunk in chunks[:-1]:
        if update.callback_query:
            await update.callback_query.message.reply_text(chunk, parse_mode="HTML")
        else:
            await update.message.reply_text(chunk, parse_mode="HTML")
            
    if update.callback_query:
        sent_msg = await update.callback_query.message.reply_text(
            chunks[-1], 
            parse_mode="HTML", 
            reply_markup=employee_report_keyboard(emp_name)
        )
    else:
        sent_msg = await update.message.reply_text(
            chunks[-1], 
            parse_mode="HTML", 
            reply_markup=employee_report_keyboard(emp_name)
        )
    context.user_data['prompt_message_id'] = sent_msg.message_id
    return SCHEDULE_EMPLOYEE_ACTION

async def schedule_employee_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    action = ""
    query = None
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        action = query.data
    else:
        if update.effective_chat.type != "private":
            if not update.message.reply_to_message or update.message.reply_to_message.message_id != context.user_data.get('prompt_message_id'):
                return # Ignore
        action = update.message.text
        
    emp = context.user_data.get('report_emp_name')
    if not emp:
        return await cancel(update, context)

    if action == "cancel_action" or action == "❌ Бекор қилиш":
        return await cancel(update, context)

    if action == "sched_by_emp" or action == "🔄 Бошқа ходимлар":
        msg_text = "👤 Ходимни танланг:"
        if query:
            sent_msg = await query.message.edit_text(msg_text, reply_markup=employee_keyboard("select_emp"))
        else:
            sent_msg = await update.message.reply_text(msg_text, reply_markup=employee_keyboard("select_emp"))
        context.user_data['prompt_message_id'] = sent_msg.message_id
        return SCHEDULE_EMPLOYEE_SELECT

    if action.startswith("emp_add_task:") or action == f"➕ {emp}га топшириқ қўшиш":
        if not is_manager(update.effective_user):
            msg = "❌ <b>Рад этилди!</b>\n\nХодимга янги топшириқ қўшиш ҳуқуқи фақат раҳбарларга берилган."
            if query:
                await query.answer("Сизда бу амалга ҳуқуқ йўқ!", show_alert=True)
                await query.message.reply_text(msg, parse_mode="HTML")
            else:
                await update.message.reply_text(msg, parse_mode="HTML")
            return SCHEDULE_EMPLOYEE_ACTION

        msg_text = f"📝 <b>{emp}</b> учун янги топшириқ матнини киритинг:\n<i>Илтимос, ушбу хабарга Reply қилиб ёзинг.</i>"
        if query:
            sent_msg = await query.message.reply_text(msg_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Бекор қилиш", callback_data="cancel_action")]]))
        else:
            sent_msg = await update.message.reply_text(msg_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Бекор қилиш", callback_data="cancel_action")]]))
        context.user_data['prompt_message_id'] = sent_msg.message_id
        return SCHEDULE_EMPLOYEE_ADD_TEXT

    if action.startswith("emp_update_task:") or action == f"⚙️ {emp} вазифасини янгилаш":
        if not is_manager(update.effective_user):
            msg = "❌ <b>Рад этилди!</b>\n\nТопшириқ ҳолатини ўзгартириш ҳуқуқи фақат раҳбарларга берилган."
            if query:
                await query.answer("Сизда бу амалга ҳуқуқ йўқ!", show_alert=True)
                await query.message.reply_text(msg, parse_mode="HTML")
            else:
                await update.message.reply_text(msg, parse_mode="HTML")
            return SCHEDULE_EMPLOYEE_ACTION

        msg_text = f"🔄 <b>{emp}</b> нинг қайси топшириқ рақамини янгиламоқчисиз? (масалан, 5):\n<i>Илтимос, ушбу хабарга Reply қилиб ёзинг.</i>"
        if query:
            sent_msg = await query.message.reply_text(msg_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Бекор қилиш", callback_data="cancel_action")]]))
        else:
            sent_msg = await update.message.reply_text(msg_text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Бекор қилиш", callback_data="cancel_action")]]))
        context.user_data['prompt_message_id'] = sent_msg.message_id
        return SCHEDULE_EMPLOYEE_UPDATE_ID

    return SCHEDULE_EMPLOYEE_ACTION

async def schedule_employee_add_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        if not update.message.reply_to_message or update.message.reply_to_message.message_id != context.user_data.get('prompt_message_id'):
            return # Ignore
            
    text = update.message.text
    context.user_data['report_task_text'] = text
    
    sent_msg = await update.message.reply_text(
        "📅 Муддатни киритинг (масалан: 25.05.2025 ёки 25.05.2025 18:00):\n"
        "<i>Илтимос, ушбу хабарга Reply қилиб ёзинг.</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Бекор қилиш", callback_data="cancel_action")]])
    )
    context.user_data['prompt_message_id'] = sent_msg.message_id
    return SCHEDULE_EMPLOYEE_ADD_DEADLINE

async def schedule_employee_add_deadline(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        if not update.message.reply_to_message or update.message.reply_to_message.message_id != context.user_data.get('prompt_message_id'):
            return # Ignore
            
    text = update.message.text
    context.user_data['report_task_deadline'] = text
    
    sent_msg = await update.message.reply_text(
        "🚦 Приоритетни танланг:",
        reply_markup=priority_keyboard()
    )
    context.user_data['prompt_message_id'] = sent_msg.message_id
    return SCHEDULE_EMPLOYEE_ADD_PRIORITY

async def schedule_employee_add_priority(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_manager(user):
        await update.message.reply_text("❌ <b>Рад этилди!</b>\n\nТопшириқ қўшиш ҳуқуқи фақат раҳбарларга берилган.", parse_mode="HTML")
        return ConversationHandler.END

    priority = "Ўрта"
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        priority = query.data.split(":", 1)[1]
    else:
        if update.effective_chat.type != "private":
            if not update.message.reply_to_message or update.message.reply_to_message.message_id != context.user_data.get('prompt_message_id'):
                return # Ignore
        priority_map = {
            "🔴 Юқори": "Юқори", "🟡 Ўрта": "Ўрта", "🟢 Паст": "Паст"
        }
        priority = priority_map.get(update.message.text, "Ўрта")

    emp = context.user_data.get('report_emp_name')
    task_id = db.add_task(
        text=context.user_data['report_task_text'],
        responsible=emp,
        deadline=context.user_data['report_task_deadline'],
        priority=priority,
        created_by=update.effective_user.id,
        created_by_name=update.effective_user.full_name
    )

    await notify_task_created(
        task_id=task_id,
        text=context.user_data['report_task_text'],
        responsible=emp,
        deadline=context.user_data['report_task_deadline'],
        priority=priority,
        created_by_name=update.effective_user.full_name,
        bot=context.bot
    )

    confirm_text = (
        f"✅ <b>Топшириқ #{task_id} қўшилди!</b>\n\n"
        f"📌 <b>Топшириқ:</b> {context.user_data['report_task_text']}\n"
        f"👤 <b>Масъул:</b> {get_responsible_display(emp)}\n"
        f"📅 <b>Муддат:</b> {context.user_data['report_task_deadline']}\n"
        f"🚦 <b>Приоритет:</b> {priority}"
    )

    if update.callback_query:
        await update.callback_query.message.reply_text(confirm_text, parse_mode="HTML")
    else:
        await update.message.reply_text(confirm_text, parse_mode="HTML")

    return await show_employee_report_and_actions(update, context, emp)

async def schedule_employee_update_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_manager(user):
        await update.message.reply_text("❌ <b>Рад этилди!</b>\n\nАмал тақиқланган.", parse_mode="HTML")
        return ConversationHandler.END

    if update.effective_chat.type != "private":
        if not update.message.reply_to_message or update.message.reply_to_message.message_id != context.user_data.get('prompt_message_id'):
            return # Ignore
            
    text = update.message.text
    emp = context.user_data.get('report_emp_name')

    try:
        task_id = int(text.replace("#", "").strip())
        task = db.get_task(task_id)

        if not task:
            await update.message.reply_text("❌ Топшириқ топилмади. Рақамни тўғри киритинг:")
            return SCHEDULE_EMPLOYEE_UPDATE_ID

        if task['responsible'] != emp:
            await update.message.reply_text(
                f"⚠️ Бу топшириқ {emp} га тегишли эмас! "
                f"Илтимос, ушбу ходимнинг топшириқларидан бирининг рақамини киритинг:"
            )
            return SCHEDULE_EMPLOYEE_UPDATE_ID

        context.user_data['report_update_task_id'] = task_id
        sent_msg = await update.message.reply_text(
            f"📌 <b>#{task_id}</b> — {task['text']}\n\nЯнги ҳолатни танланг:",
            parse_mode="HTML",
            reply_markup=status_keyboard(task_id, prefix="emp_status_update")
        )
        context.user_data['prompt_message_id'] = sent_msg.message_id
        return SCHEDULE_EMPLOYEE_UPDATE_STATUS
    except ValueError:
        await update.message.reply_text("Илтимос, топшириқ рақамини киритинг:")
        return SCHEDULE_EMPLOYEE_UPDATE_ID

async def schedule_employee_update_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_manager(user):
        if update.callback_query:
            await update.callback_query.answer("Сизда бу амалга ҳуқуқ йўқ!", show_alert=True)
            await update.callback_query.message.reply_text("❌ <b>Рад этилди!</b>\n\nАмал тақиқланган.", parse_mode="HTML")
        else:
            await update.message.reply_text("❌ <b>Рад этилди!</b>\n\nАмал тақиқланган.", parse_mode="HTML")
        return ConversationHandler.END

    status = ""
    query = None
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        parts = query.data.split(":")
        task_id = int(parts[1])
        status = parts[2]
    else:
        if update.effective_chat.type != "private":
            if not update.message.reply_to_message or update.message.reply_to_message.message_id != context.user_data.get('prompt_message_id'):
                return # Ignore
        status_map = {
            "⏳ Кутяпти": "Кутяпти", "🔄 Жараёнда": "Жараёнда",
            "✅ Бажарилди": "Бажарилди", "❌ Бекор қилинди": "Бекор қилинди"
        }
        status = status_map.get(update.message.text)
        task_id = context.user_data.get('report_update_task_id')

    if not status or not task_id:
        return SCHEDULE_EMPLOYEE_UPDATE_STATUS

    db.update_task_status(task_id, status, update.effective_user.full_name)

    confirm_text = f"✅ <b>#{task_id}</b> топшириқ ҳолати «<b>{status}</b>» га янгиланди!"
    if query:
        await query.message.reply_text(confirm_text, parse_mode="HTML")
    else:
        await update.message.reply_text(confirm_text, parse_mode="HTML")

    emp = context.user_data.get('report_emp_name')
    return await show_employee_report_and_actions(update, context, emp)

async def schedule_general_update_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_manager(user):
        await update.message.reply_text("❌ <b>Рад этилди!</b>\n\nАмал тақиқланган.", parse_mode="HTML")
        return ConversationHandler.END

    if update.effective_chat.type != "private":
        if not update.message.reply_to_message or update.message.reply_to_message.message_id != context.user_data.get('prompt_message_id'):
            return # Ignore
            
    text = update.message.text
    try:
        task_id = int(text.replace("#", "").strip())
        task = db.get_task(task_id)
        if not task:
            await update.message.reply_text("❌ Топшириқ топилмади. Рақамни текшириб қайтадан киритинг:")
            return SCHEDULE_GENERAL_UPDATE_ID

        context.user_data['general_update_task_id'] = task_id
        sent_msg = await update.message.reply_text(
            f"📌 <b>#{task_id}</b> — {task['text']} ({task['responsible']})\n\nЯнги ҳолатни танланг:",
            parse_mode="HTML",
            reply_markup=status_keyboard(task_id, prefix="gen_status_update")
        )
        context.user_data['prompt_message_id'] = sent_msg.message_id
        return SCHEDULE_GENERAL_UPDATE_STATUS
    except ValueError:
        await update.message.reply_text("Илтимос, рақам киритинг:")
        return SCHEDULE_GENERAL_UPDATE_ID

async def schedule_general_update_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_manager(user):
        if update.callback_query:
            await update.callback_query.answer("Сизда бу амалга ҳуқуқ йўқ!", show_alert=True)
            await update.callback_query.message.reply_text("❌ <b>Рад этилди!</b>\n\nАмал тақиқланган.", parse_mode="HTML")
        else:
            await update.message.reply_text("❌ <b>Рад этилди!</b>\n\nАмал тақиқланган.", parse_mode="HTML")
        return ConversationHandler.END

    status = ""
    query = None
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        parts = query.data.split(":")
        task_id = int(parts[1])
        status = parts[2]
    else:
        if update.effective_chat.type != "private":
            if not update.message.reply_to_message or update.message.reply_to_message.message_id != context.user_data.get('prompt_message_id'):
                return # Ignore
        status_map = {
            "⏳ Кутяпти": "Кутяпти", "🔄 Жараёнда": "Жараёнда",
            "✅ Бажарилди": "Бажарилди", "❌ Бекор қилинди": "Бекор қилинди"
        }
        status = status_map.get(update.message.text)
        task_id = context.user_data.get('general_update_task_id')

    if not status or not task_id:
        return SCHEDULE_GENERAL_UPDATE_STATUS

    db.update_task_status(task_id, status, update.effective_user.full_name)

    confirm_text = f"✅ <b>#{task_id}</b> топшириқ ҳолати «<b>{status}</b>» га янгиланди!"
    if query:
        await query.message.edit_text(confirm_text, parse_mode="HTML")
    else:
        await update.message.reply_text(confirm_text, parse_mode="HTML")

    return await schedule_start(update, context)

async def schedule_delete_task_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_manager(user):
        await update.message.reply_text("❌ <b>Рад этилди!</b>\n\nАмал тақиқланган.", parse_mode="HTML")
        return ConversationHandler.END

    if update.effective_chat.type != "private":
        if not update.message.reply_to_message or update.message.reply_to_message.message_id != context.user_data.get('prompt_message_id'):
            return # Ignore
            
    text = update.message.text
    try:
        task_id = int(text.replace("#", "").strip())
        task = db.get_task(task_id)
        if not task:
            await update.message.reply_text("❌ Топшириқ топилмади. Рақамни тўғри киритинг:")
            return SCHEDULE_DELETE_TASK_ID

        if db.delete_task(task_id):
            await update.message.reply_text(
                f"🗑 <b>#{task_id}</b> топшириқ муваффақиятли ўчирилди!",
                parse_mode="HTML"
            )
        else:
            await update.message.reply_text("❌ Топшириқни ўчириб бўлмади.")

        return await schedule_start(update, context)
    except ValueError:
        await update.message.reply_text("Илтимос, топшириқ рақамини киритинг:")
        return SCHEDULE_DELETE_TASK_ID

async def schedule_add_attachment_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_manager(user):
        await update.message.reply_text("❌ <b>Рад этилди!</b>\n\nАмал тақиқланган.", parse_mode="HTML")
        return ConversationHandler.END

    if update.effective_chat.type != "private":
        if not update.message.reply_to_message or update.message.reply_to_message.message_id != context.user_data.get('prompt_message_id'):
            return # Ignore
            
    text = update.message.text
    try:
        task_id = int(text.replace("#", "").strip())
        task = db.get_task(task_id)
        if not task:
            await update.message.reply_text("❌ Топшириқ топилмади. Рақамни текшириб қайтадан киритинг:")
            return SCHEDULE_ADD_ATTACH_TASK_ID

        context.user_data['attach_task_id'] = task_id
        sent_msg = await update.message.reply_text(
            f"📌 <b>#{task_id}</b> — {task['text']} ({task['responsible']})\n\n"
            f"Ушбу топшириққа қўшмоқчи бўлган изоҳингизни ёзиб юборинг ёки расм/ҳужжат файлини юборинг:\n"
            f"<i>Илтимос, ушбу хабарга Reply қилиб юборинг.</i>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Бекор қилиш", callback_data="cancel_action")]])
        )
        context.user_data['prompt_message_id'] = sent_msg.message_id
        return SCHEDULE_ADD_ATTACH_CONTENT
    except ValueError:
        await update.message.reply_text("Илтимос, рақам киритинг:")
        return SCHEDULE_ADD_ATTACH_TASK_ID

async def schedule_add_attachment_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_manager(user):
        await update.message.reply_text("❌ <b>Рад этилди!</b>\n\nАмал тақиқланган.", parse_mode="HTML")
        return ConversationHandler.END

    if update.effective_chat.type != "private":
        if not update.message.reply_to_message or update.message.reply_to_message.message_id != context.user_data.get('prompt_message_id'):
            return # Ignore

    task_id = context.user_data.get('attach_task_id')
    if not task_id:
        await update.message.reply_text("❌ Хатолик: Топшириқ топилмади. Амал бекор қилинди.")
        return await schedule_start(update, context)

    task = db.get_task(task_id)
    if not task:
        await update.message.reply_text("❌ Хатолик: Топшириқ топилмади. Амал бекор қилинди.")
        return await schedule_start(update, context)

    att_type = "text"
    att_content = ""
    file_id = None

    if update.message.photo:
        att_type = "photo"
        file_id = update.message.photo[-1].file_id
        att_content = file_id
        caption = update.message.caption or ""
        if caption:
            att_content = f"{file_id}|{caption}"
    elif update.message.document:
        att_type = "document"
        file_id = update.message.document.file_id
        att_content = file_id
        caption = update.message.caption or ""
        if caption:
            att_content = f"{file_id}|{caption}"
    elif update.message.text:
        att_type = "text"
        att_content = update.message.text

    db.add_task_attachment(task_id, att_type, att_content)

    responsible = task['responsible']
    emp_user = db.get_user_by_mapped_employee(responsible)
    
    notify_text = (
        f"💬 <b>ТОПШИРИҚҚА ЯНГИ ИЗОҲ/ФАЙЛ ҚЎШИЛДИ!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📌 <b>Топшириқ #{task_id}:</b> {task['text']}\n"
        f"✍️ <b>Қўшди:</b> {user.full_name}\n"
    )
    if att_type == "text":
        notify_text += f"💬 <b>Изоҳ:</b> {att_content}\n"
    else:
        caption = att_content.split("|", 1)[1] if "|" in att_content else ""
        if caption:
            notify_text += f"💬 <b>Изоҳ:</b> {caption}\n"
        else:
            notify_text += f"📸 <b>Илова:</b> Файл юборилди\n"

    async def send_notify_msg(chat_id):
        if att_type == "photo":
            await context.bot.send_photo(chat_id=chat_id, photo=file_id, caption=notify_text, parse_mode="HTML")
        elif att_type == "document":
            await context.bot.send_document(chat_id=chat_id, document=file_id, caption=notify_text, parse_mode="HTML")
        else:
            await context.bot.send_message(chat_id=chat_id, text=notify_text, parse_mode="HTML")

    if emp_user:
        try:
            await send_notify_msg(emp_user['telegram_id'])
        except Exception as e:
            logger.error(f"Could not send attachment notification to employee {responsible}: {e}")
    else:
        if "ҳамма" in responsible.lower() or "хамма" in responsible.lower():
            users = db.get_all_users()
            for u in users:
                if u['telegram_id'] != user.id:
                    try:
                        await send_notify_msg(u['telegram_id'])
                    except Exception:
                        pass

    await update.message.reply_text(
        f"✅ <b>#{task_id}</b> топшириққа янги изоҳ/файл муваффақиятли қўшилди ва масъул ходимга хабар юборилди!",
        parse_mode="HTML"
    )

    context.user_data.pop('attach_task_id', None)
    return await schedule_start(update, context)

# ─── Statistics & Ratings ─────────────────────────────────────────────────────

async def view_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not await is_authorized_user(user, context.bot):
        text = (
            "❌ <b>Кириш рад этилди!</b>\n\n"
            "Ушбу ботдаги вазифалар ва иш жадваллари махфий бўлиб, ундан фойдаланиш фақат белгиланган жамоа аъзолари (раҳбарлар ва ходимлар) учун рухсат этилган."
        )
        if update.callback_query:
            await update.callback_query.answer("Кириш тақиқланган!", show_alert=True)
            await update.callback_query.message.reply_text(text, parse_mode="HTML")
        else:
            await update.message.reply_text(text, parse_mode="HTML")
        return

    query = update.callback_query
    if query:
        await query.answer()
        
    tasks = db.get_all_tasks()
    stats = db.get_statistics()
    
    if not tasks:
        msg_text = "📊 Статистика учун топшириқлар йўқ."
        if query:
            await query.message.reply_text(msg_text, reply_markup=schedule_keyboard())
        else:
            await update.message.reply_text(msg_text, reply_markup=schedule_keyboard())
        return
    
    total = stats['total']
    done = stats['done'] or 0
    in_progress = stats['in_progress'] or 0
    waiting = stats['waiting'] or 0
    cancelled = stats['cancelled'] or 0
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
    
    filled = int(percent / 10)
    bar = "🟩" * filled + "⬜" * (10 - filled)
    text += f"{bar} {percent}%\n\n"
    
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
            
    # Generate QuickChart doughnut chart
    chart_config = {
        "type": "doughnut",
        "data": {
            "labels": [
                f"Бажарилди ({done})",
                f"Жараёнда ({in_progress})",
                f"Кутяпти ({waiting})",
                f"Бекор қилинди ({cancelled})"
            ],
            "datasets": [{
                "data": [done, in_progress, waiting, cancelled],
                "backgroundColor": ["#4caf50", "#2196f3", "#ffeb3b", "#f44336"],
                "borderWidth": 2
            }]
        },
        "options": {
            "plugins": {
                "legend": { "position": "bottom" },
                "doughnutlabel": {
                    "labels": [
                        { "text": str(total), "font": { "size": 30, "weight": "bold" } },
                        { "text": "Вазифалар", "font": { "size": 14 } }
                    ]
                }
            }
        }
    }
    chart_url = f"https://quickchart.io/chart?w=500&h=400&c={urllib.parse.quote(json.dumps(chart_config))}"
    
    if query:
        try:
            await query.message.delete()
        except Exception:
            pass
            
    try:
        await context.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=chart_url,
            caption=text,
            parse_mode="HTML",
            reply_markup=schedule_keyboard()
        )
    except Exception as e:
        logger.error(f"Could not send chart: {e}")
        # Fallback to plain text if photo sending fails
        if query:
            await query.message.reply_text(text, parse_mode="HTML", reply_markup=schedule_keyboard())
        else:
            await update.message.reply_text(text, parse_mode="HTML", reply_markup=schedule_keyboard())

async def employee_rating(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not await is_authorized_user(user, context.bot):
        text = (
            "❌ <b>Кириш рад этилди!</b>\n\n"
            "Ушбу ботдаги вазифалар ва иш жадваллари махфий бўлиб, ундан фойдаланиш фақат белгиланган жамоа аъзолари (раҳбарлар ва ходимлар) учун рухсат этилган."
        )
        if update.callback_query:
            await update.callback_query.answer("Кириш тақиқланган!", show_alert=True)
            await update.callback_query.message.reply_text(text, parse_mode="HTML")
        else:
            await update.message.reply_text(text, parse_mode="HTML")
        return

    query = update.callback_query
    if query:
        await query.answer()
        
    emp_stats = db.get_employee_statistics()
    if not emp_stats:
        msg_text = "Ҳозирча маълумот йўқ."
        if query:
            await query.message.reply_text(msg_text, reply_markup=schedule_keyboard())
        else:
            await update.message.reply_text(msg_text, reply_markup=schedule_keyboard())
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
        
    if query:
        await query.message.reply_text(text, parse_mode="HTML", reply_markup=schedule_keyboard())
    else:
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=schedule_keyboard())

# ─── Command Handlers ─────────────────────────────────────────────────────────

async def delete_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_manager(user):
        await update.message.reply_text(
            "❌ <b>Рад этилди!</b>\n\nТопшириқларни ўчириш ҳуқуқи фақат раҳбарларга берилган.",
            parse_mode="HTML", reply_markup=main_keyboard()
        )
        return

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

# ─── Employee Personal Cabinet & Approvals ────────────────────────────────────

async def my_tasks_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not await is_authorized_user(user, context.bot):
        text = (
            "❌ <b>Кириш рад этилди!</b>\n\n"
            "Ушбу ботдаги вазифалар ва иш жадваллари махфий бўлиб, ундан фойдаланиш фақат белгиланган жамоа аъзолари (раҳбарлар ва ходимлар) учун рухсат этилган."
        )
        if update.callback_query:
            await update.callback_query.answer("Кириш тақиқланган!", show_alert=True)
            await update.callback_query.message.reply_text(text, parse_mode="HTML")
        else:
            await update.message.reply_text(text, parse_mode="HTML")
        return

    telegram_id = user.id
    mapped_emp = db.get_mapped_employee(telegram_id)
    
    # Auto-map by username if possible
    if not mapped_emp and user.username:
        target_username = f"@{user.username}".lower()
        for emp, username in EMPLOYEE_USERNAMES.items():
            if username.lower() == target_username:
                db.map_user_to_employee(telegram_id, emp)
                mapped_emp = emp
                break
                
    if not mapped_emp:
        # Send a keyboard to select who they are
        keyboard = []
        for emp in EMPLOYEES:
            keyboard.append([InlineKeyboardButton(emp, callback_data=f"link_account:{emp}")])
        keyboard.append([InlineKeyboardButton("❌ Бекор қилиш", callback_data="cancel_action")])
        
        text = (
            "👤 <b>Ходимни боғлаш</b>\n\n"
            "Сизнинг Telegram аккаунтингиз ходимлар рўйхатига боғланмаган.\n"
            "Илтимос, тизимдан ўз исмингизни танлаб, аккаунтингизни боғланг 👇"
        )
        if update.callback_query:
            await update.callback_query.answer()
            await update.callback_query.message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await update.message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
        return
        
    await show_my_tasks(update, context, mapped_emp)

async def show_my_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE, emp_name: str):
    tasks = db.get_employee_tasks(emp_name)
    active_tasks = [t for t in tasks if t['status'] not in ['Бажарилди', 'Бекор қилинди']]
    
    text = f"👤 <b>Менинг вазифаларим: {emp_name}</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
    if not active_tasks:
        text += "📭 Сизда ҳозирда фаол вазифалар мавжуд эмас! Баракалла! 🎉"
        reply_markup = main_keyboard()
        
        if update.callback_query:
            await update.callback_query.message.reply_text(text, parse_mode="HTML", reply_markup=reply_markup)
        else:
            await update.message.reply_text(text, parse_mode="HTML", reply_markup=reply_markup)
        return
        
    for i, t in enumerate(active_tasks, 1):
        status_emoji = {"Кутяпти": "⏳", "Жараёнда": "🔄"}.get(t['status'], "⏳")
        priority_emoji = {"Юқори": "🔴", "Ўрта": "🟡", "Паст": "🟢"}.get(t['priority'], "🟡")
        text += (
            f"<b>{i}. #{t['id']} {t['text']}</b>\n"
            f"   Ҳолат: {status_emoji} {t['status']} | Приоритет: {priority_emoji} {t['priority']}\n"
            f"   Муддат: 📅 {t['deadline']}\n"
        )
        attachments = db.get_task_attachments(t['id'])
        if attachments:
            text += "   💬 <b>Изоҳлар/Файллар:</b>\n"
            for att in attachments:
                att_time = att['created_at']
                if att['type'] == 'text':
                    text += f"     • {att['content']} (📅 {att_time})\n"
                else:
                    caption = att['content'].split("|", 1)[1] if "|" in att['content'] else ""
                    file_type = "Расм" if att['type'] == 'photo' else "Ҳужжат"
                    if caption:
                        text += f"     • [{file_type}] {caption} (📅 {att_time})\n"
                    else:
                        text += f"     • [{file_type}] (📅 {att_time})\n"
        text += "\n"
        
    # Send the tasks list with buttons for each task
    keyboard = []
    for t in active_tasks[:5]:
        keyboard.append([InlineKeyboardButton(f"✅ #{t['id']} бажарилди деб белгилашни сўраш", callback_data=f"request_complete:{t['id']}")])
    keyboard.append([InlineKeyboardButton("📊 Менинг самарадорлигим (График)", callback_data=f"emp_chart:{emp_name}")])
    keyboard.append([InlineKeyboardButton("❌ Бекор қилиш", callback_data="cancel_action")])
    
    if update.callback_query:
        await update.callback_query.message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_link_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    emp = query.data.split(":", 1)[1]
    user = update.effective_user
    
    if not await is_authorized_user(user, context.bot):
        await query.message.reply_text(
            "❌ <b>Кириш рад этилди!</b>\n\nУшбу амал фақат белгиланган ходимлар ва раҳбарлар учун.",
            parse_mode="HTML"
        )
        return
        
    # Check if this employee name is already claimed by someone else
    existing_link = db.get_user_by_mapped_employee(emp)
    if existing_link and existing_link['telegram_id'] != user.id:
        await query.message.edit_text(
            f"⚠️ <b>Хатолик!</b>\n\n«{emp}» ходими аллақачон бошқа Telegram аккаунтига боғланган. "
            f"Агар бу хатолик бўлса, илтимос, раҳбариятга мурожаат қилинг.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ Ёпиш", callback_data="cancel_action")]])
        )
        return
        
    db.map_user_to_employee(user.id, emp)
    
    await query.message.edit_text(
        f"✅ Аккаунтингиз муваффақиятли боғланди!\n👤 <b>Ходим:</b> {emp}\n\nВазифаларингизни кўриш учун пастдаги тугмани босинг:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 Менинг вазифаларим", callback_data="my_tasks_view"),
             InlineKeyboardButton("📊 Самарадорлик графиги", callback_data=f"emp_chart:{emp}")],
            [InlineKeyboardButton("❌ Бекор қилиш", callback_data="cancel_action")]
        ])
    )

async def handle_employee_chart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    emp_name = query.data.split(":", 1)[1]
    
    stats = db.get_single_employee_statistics(emp_name)
    total = stats['total']
    done = stats['done'] or 0
    in_progress = stats['in_progress'] or 0
    waiting = stats['waiting'] or 0
    cancelled = stats['cancelled'] or 0
    percent = round((done / total * 100), 1) if total > 0 else 0
    
    text = (
        f"📊 <b>МЕНИНГ САМАРАДОРЛИГИМ</b>\n"
        f"👤 <b>Ходим:</b> {emp_name}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📌 Жами топшириқлар: <b>{total}</b>\n"
        f"✅ Бажарилди: <b>{done}</b>\n"
        f"🔄 Жараёнда: <b>{in_progress}</b>\n"
        f"⏳ Кутяпти: <b>{waiting}</b>\n"
        f"❌ Бекор қилинди: <b>{cancelled}</b>\n"
        f"📈 Ижро фоизи: <b>{percent}%</b>\n\n"
    )
    
    filled = int(percent / 10)
    bar = "🟩" * filled + "⬜" * (10 - filled)
    text += f"{bar} {percent}%\n\n"
    
    chart_config = {
        "type": "doughnut",
        "data": {
            "labels": [
                f"Бажарилди ({done})",
                f"Жараёнда ({in_progress})",
                f"Кутяпти ({waiting})",
                f"Бекор қилинди ({cancelled})"
            ],
            "datasets": [{
                "data": [done, in_progress, waiting, cancelled],
                "backgroundColor": ["#4caf50", "#2196f3", "#ffeb3b", "#f44336"],
                "borderWidth": 2
            }]
        },
        "options": {
            "plugins": {
                "legend": { "position": "bottom" },
                "doughnutlabel": {
                    "labels": [
                        { "text": str(total), "font": { "size": 30, "weight": "bold" } },
                        { "text": "Вазифалар", "font": { "size": 14 } }
                    ]
                }
            }
        }
    }
    chart_url = f"https://quickchart.io/chart?w=500&h=400&c={urllib.parse.quote(json.dumps(chart_config))}"
    
    try:
        await query.message.delete()
    except Exception:
        pass
        
    try:
        await context.bot.send_photo(
            chat_id=update.effective_chat.id,
            photo=chart_url,
            caption=text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 Менинг вазифаларим", callback_data="my_tasks_view")],
                [InlineKeyboardButton("❌ Ёпиш", callback_data="cancel_action")]
            ])
        )
    except Exception as e:
        logger.error(f"Could not send personal chart: {e}")
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=text,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 Менинг вазифаларим", callback_data="my_tasks_view")],
                [InlineKeyboardButton("❌ Ёпиш", callback_data="cancel_action")]
            ])
        )

async def handle_request_complete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    
    if not await is_authorized_user(user, context.bot):
        await query.message.reply_text(
            "❌ <b>Кириш рад этилди!</b>\n\nУшбу амал фақат белгиланган ходимлар ва раҳбарлар учун.",
            parse_mode="HTML"
        )
        return
        
    task_id = int(query.data.split(":", 1)[1])
    
    task = db.get_task(task_id)
    if not task:
        await query.message.reply_text("❌ Топшириқ топилмади.")
        return

    # Set state to wait for photo proof
    context.user_data['waiting_photo_task_id'] = task_id
    
    text = (
        f"📸 <b>Бажарилган иш фото-ҳисоботи</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📌 <b>#{task_id}</b> — {task['text']}\n\n"
        f"Илтимос, бажарилган ишнинг фотосуратини (ёки лойиҳа ҳужжатини) юборинг.\n"
        f"Бу расм раҳбарларга тасдиқлаш учун юборилади.\n\n"
        f"<i>Агар расмингиз бўлмаса, «❌ Расмисиз юбориш» тугмасини босинг 👇</i>"
    )
    
    reply_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("❌ Расмисиз юбориш", callback_data=f"send_no_photo:{task_id}")],
        [InlineKeyboardButton("❌ Бекор қилиш", callback_data="cancel_photo_proof")]
    ])
    
    await query.message.reply_text(text, parse_mode="HTML", reply_markup=reply_markup)

async def handle_send_no_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    parts = query.data.split(":")
    task_id = int(parts[1])
    
    if context.user_data.get('waiting_photo_task_id') == task_id:
        context.user_data.pop('waiting_photo_task_id', None)
        
    try:
        await query.message.delete()
    except Exception:
        pass
        
    await send_complete_approval_request(task_id, update, context)

async def handle_cancel_photo_proof(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.pop('waiting_photo_task_id', None)
    await query.message.edit_text("❌ Фото-ҳисобот юбориш бекор қилинди.")

async def send_complete_approval_request(task_id: int, update: Update, context: ContextTypes.DEFAULT_TYPE, photo_file_id: str = None, document_file_id: str = None):
    task = db.get_task(task_id)
    if not task:
        return
        
    user = update.effective_user
    emp = task['responsible']
    
    text = (
        f"🔔 <b>БАЗАГА БАЖАРИЛДИ ДЕБ БЕЛГИЛАШ СЎРОВИ!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>Ходим:</b> {emp}\n"
        f"📌 <b>Топшириқ #{task_id}:</b> {task['text']}\n"
        f"📅 <b>Муддати:</b> {task['deadline']}\n"
        f"🚦 <b>Приоритет:</b> {task['priority']}\n"
    )
    if photo_file_id or document_file_id:
        text += f"📸 <b>Илова:</b> Фото-ҳисобот юборилган\n"
    text += f"\nИлтимос, ушбу топшириқ бажарилганлигини тасдиқланг 👇"
    
    reply_markup = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Тасдиқлаш (Бажарилди)", callback_data=f"approve_complete:{task_id}"),
            InlineKeyboardButton("❌ Рад этиш", callback_data=f"reject_complete:{task_id}")
        ]
    ])
    
    async def send_msg_to_chat(chat_id):
        if photo_file_id:
            await context.bot.send_photo(chat_id=chat_id, photo=photo_file_id, caption=text, parse_mode="HTML", reply_markup=reply_markup)
        elif document_file_id:
            await context.bot.send_document(chat_id=chat_id, document=document_file_id, caption=text, parse_mode="HTML", reply_markup=reply_markup)
        else:
            await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML", reply_markup=reply_markup)

    groups = db.get_all_groups()
    for g in groups:
        try:
            await send_msg_to_chat(g['chat_id'])
        except Exception as e:
            logger.error(f"Could not send approval request to group {g['chat_id']}: {e}")
            
    users = db.get_all_users()
    for u in users:
        is_u_manager = (
            u['telegram_id'] in AUTHORIZED_USERS or 
            (u['username'] and u['username'].lower() in [a.lower() for a in AUTHORIZED_USERS if isinstance(a, str)])
        )
        if is_u_manager and u['telegram_id'] != user.id:
            try:
                await send_msg_to_chat(u['telegram_id'])
            except Exception as e:
                logger.error(f"Could not send approval request to manager {u['telegram_id']}: {e}")
                
    confirm_msg = (
        f"📤 <b>#{task_id}</b> топшириқни «Бажарилди» деб белгилаш бўйича раҳбарларга сўров юборилди!\n\n"
        f"Раҳбарлар тасдиқлаши билан вазифа ҳолати янгиланади."
    )
    if update.callback_query:
        await update.callback_query.message.reply_text(confirm_msg, parse_mode="HTML")
    else:
        await update.message.reply_text(confirm_msg, parse_mode="HTML")

async def handle_employee_proof_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    task_id = context.user_data.get('waiting_photo_task_id')
    if not task_id:
        return
        
    context.user_data.pop('waiting_photo_task_id', None)
    
    photo_file_id = None
    document_file_id = None
    
    if update.message.photo:
        photo_file_id = update.message.photo[-1].file_id
    elif update.message.document:
        document_file_id = update.message.document.file_id
        
    await send_complete_approval_request(task_id, update, context, photo_file_id=photo_file_id, document_file_id=document_file_id)

async def handle_approve_complete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    
    if not is_manager(user):
        await query.answer("Сизда бу амални бажариш ҳуқуқи йўқ!", show_alert=True)
        return
        
    await query.answer("Сўров тасдиқланди!")
    task_id = int(query.data.split(":", 1)[1])
    
    task = db.get_task(task_id)
    if not task:
        await query.message.edit_text("❌ Топшириқ топилмади.")
        return
        
    db.update_task_status(task_id, "Бажарилди", user.full_name)
    
    await query.message.edit_text(
        f"✅ <b>Топшириқ #{task_id} бажарилганлиги тасдиқланди!</b>\n\n"
        f"📌 <b>Топшириқ:</b> {task['text']}\n"
        f"👤 <b>Масъул:</b> {task['responsible']}\n"
        f"💼 <b>Тасдиқлади:</b> {user.full_name}",
        parse_mode="HTML"
    )
    
    emp_user = db.get_user_by_mapped_employee(task['responsible'])
    if emp_user:
        try:
            await context.bot.send_message(
                chat_id=emp_user['telegram_id'],
                text=f"🎉 <b>Ура! Раҳбарият #{task_id} топшириқ бажарилганлигини тасдиқлади!</b>\n\n📌 <i>{task['text']}</i>",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Could not notify employee of approval: {e}")

async def handle_reject_complete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    
    if not is_manager(user):
        await query.answer("Сизда бу амални бажариш ҳуқуқи йўқ!", show_alert=True)
        return
        
    await query.answer("Сўров рад этилди!")
    task_id = int(query.data.split(":", 1)[1])
    
    task = db.get_task(task_id)
    if not task:
        await query.message.edit_text("❌ Топшириқ топилмади.")
        return
        
    await query.message.edit_text(
        f"❌ <b>Топшириқ #{task_id} бажарилганлиги рад этилди!</b>\n\n"
        f"📌 <b>Топшириқ:</b> {task['text']}\n"
        f"👤 <b>Масъул:</b> {task['responsible']}\n"
        f"💼 <b>Рад этди:</b> {user.full_name}",
        parse_mode="HTML"
    )
    
    emp_user = db.get_user_by_mapped_employee(task['responsible'])
    if emp_user:
        try:
            await context.bot.send_message(
                chat_id=emp_user['telegram_id'],
                text=f"⚠️ <b>#{task_id} топшириқни бажарилди деб белгилаш сўрови рад этилди!</b>\n\n📌 <i>{task['text']}</i>\nИлтимос, топшириқни қайтадан кўриб чиқинг.",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Could not notify employee of rejection: {e}")

# ─── Silent Voice Command Handler ──────────────────────────────────────────────

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_type = update.effective_chat.type
    user = update.effective_user

    # Check authorization (is_manager)
    if not is_manager(user):
        if chat_type == "private":
            await update.message.reply_text(
                "❌ <b>Рад этилди!</b>\n\nЯнги топшириқ қўшиш ҳуқуқи фақат раҳбарларга берилган.",
                parse_mode="HTML",
                reply_markup=main_keyboard()
            )
        else:
            is_reply_to_bot = (
                update.message.reply_to_message and 
                update.message.reply_to_message.from_user.is_bot
            )
            if is_reply_to_bot:
                await update.message.reply_text(
                    "❌ <b>Рад этилди!</b>\n\nЯнги топшириқ қўшиш ҳуқуқи фақат раҳбарларга берилган.",
                    parse_mode="HTML"
                )
        return ConversationHandler.END

    # In groups/supergroups, ignore voice messages unless they are a reply to the bot
    if chat_type != "private":
        is_reply_to_bot = (
            update.message.reply_to_message and 
            update.message.reply_to_message.from_user.is_bot
        )
        if not is_reply_to_bot:
            logger.info("Guruhdagi oddiy ovozli xabar e'tiborsiz qoldirildi.")
            return

    db.add_user(user.id, user.full_name, user.username or "")

    try:
        voice = update.message.voice
        voice_file = await context.bot.get_file(voice.file_id)
        audio_bytes = await voice_file.download_as_bytearray()
        logger.info(f"Ovoz xotiraga yuklandi: {len(audio_bytes)} bayt ({voice.duration}s)")

        task_data = await process_voice(bytes(audio_bytes))

        if not task_data:
            await update.message.reply_text(
                "❌ <b>Овозни таниб олишда хатолик юз берди.</b>\n\n"
                "Илтимос:\n"
                "• Аниқроқ ва баландроқ гапиринг\n"
                "• Топшириқни, масъул шахсни ва муддатни айтинг\n"
                "• Қайтадан уриниб кўринг 🎙️",
                parse_mode="HTML",
                reply_markup=main_keyboard()
            )
            return ConversationHandler.END

        if task_data['responsible'] == "Кўрсатилмаган":
            task_data['responsible'] = "Ҳамма ходимлар"

        task_id = db.add_task(
            text=task_data['task_text'],
            responsible=task_data['responsible'],
            deadline=task_data['deadline'],
            priority=task_data['priority'],
            created_by=user.id,
            created_by_name=user.full_name
        )

        await notify_task_created(
            task_id=task_id,
            text=task_data['task_text'],
            responsible=task_data['responsible'],
            deadline=task_data['deadline'],
            priority=task_data['priority'],
            created_by_name=user.full_name,
            bot=context.bot
        )

        confirmation = format_voice_confirmation(task_data, task_id)
        await update.message.reply_text(
            confirmation, 
            parse_mode="HTML",
            reply_markup=main_keyboard()
        )
        logger.info(f"Ovozli vazifa #{task_id} saqlandi: {user.full_name}")
        return ConversationHandler.END

    except Exception as e:
        logger.error(f"handle_voice xatosi: {e}")
        await update.message.reply_text(
            "❌ <b>Хатолик юз берди.</b>\n"
            f"<code>{str(e)[:200]}</code>\n\n"
            "Илтимос қайтадан уриниб кўринг.",
            parse_mode="HTML",
            reply_markup=main_keyboard()
        )
        return ConversationHandler.END

# ─── In Progress Tasks Scheduler (11:00) ───────────────────────────────────────

async def send_inprogress_tasks_report(app):
    from collections import defaultdict
    tasks = db.get_all_tasks()
    inprogress = [t for t in tasks if t['status'] == 'Жараёнда']
    
    if not inprogress:
        report = "🔄 <b>ЖАРАЁНДАГИ ТОПШИРИҚЛАР (соат 11:00)</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n🟢 Ҳозирда жараёнда бўлган фаол топшириқлар мавжуд эмас."
    else:
        report = "🔄 <b>ЖАРАЁНДАГИ ТОПШИРИҚЛАР ЖАДВАЛИ (соат 11:00)</b>\n━━━━━━━━━━━━━━━━━━━━━━\n\n"
        grouped = defaultdict(list)
        for t in inprogress:
            grouped[t['responsible']].append(t)
            
        for emp, emp_tasks in grouped.items():
            report += f"👤 <b>{emp}:</b>\n"
            for i, t in enumerate(emp_tasks, 1):
                priority_emoji = {"Юқори": "🔴", "Ўрта": "🟡", "Паст": "🟢"}.get(t['priority'], "🟡")
                report += f"   {i}. <code>#{t['id']}</code> {t['text']} (📅 {t['deadline']}) {priority_emoji}\n"
            report += "\n"
            
        report += "💡 <i>Масъул ходимлар вазифаларни ўз вақтида бажариб, ҳисобот юборишингизни сўраймиз!</i>"

    groups = db.get_all_groups()
    for g in groups:
        try:
            for chunk in split_message(report):
                await app.bot.send_message(chat_id=g['chat_id'], text=chunk, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Could not send 11:00 report to group {g['chat_id']}: {e}")
            
    users = db.get_all_users()
    for u in users:
        is_u_manager = (
            u['telegram_id'] in AUTHORIZED_USERS or 
            (u['username'] and u['username'].lower() in [a.lower() for a in AUTHORIZED_USERS if isinstance(a, str)])
        )
        if is_u_manager:
            try:
                for chunk in split_message(report):
                    await app.bot.send_message(chat_id=u['telegram_id'], text=chunk, parse_mode="HTML")
            except Exception as e:
                logger.error(f"Could not send 11:00 report to manager {u['telegram_id']}: {e}")

# ─── Daily Report Scheduler ────────────────────────────────────────────────────

async def send_daily_report(app):
    tasks = db.get_all_tasks()
    stats = db.get_employee_statistics()
    
    report = generate_daily_report(tasks, header="🕓 <b>КУНДАЛИК ҲИСОБОТ — 16:00</b>")
    
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

    groups = db.get_all_groups()
    for g in groups:
        try:
            for chunk in split_message(report):
                await app.bot.send_message(chat_id=g['chat_id'], text=chunk, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Could not send to group {g['chat_id']}: {e}")

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
    
    # Add task conversation handler
    add_task_conv = ConversationHandler(
        entry_points=[
            CommandHandler("add_task", add_task_start),
            CallbackQueryHandler(add_task_start, pattern="^main_add_task$"),
            MessageHandler(filters.Regex("^➕ Топшириқ қўшиш$"), add_task_start),
            MessageHandler(filters.VOICE, handle_voice)
        ],
        states={
            TASK_TEXT: [
                CallbackQueryHandler(cancel_callback, pattern="^cancel_action$"),
                CallbackQueryHandler(add_task_emp_click, pattern="^add_emp:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_task_text_input),
                MessageHandler(filters.VOICE, handle_voice)
            ],
            TASK_RESPONSIBLE: [
                CallbackQueryHandler(cancel_callback, pattern="^cancel_action$"),
                CallbackQueryHandler(add_task_emp_click, pattern="^add_emp:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_task_responsible),
                MessageHandler(filters.VOICE, handle_voice)
            ],
            TASK_DEADLINE: [
                CallbackQueryHandler(cancel_callback, pattern="^cancel_action$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_task_deadline),
                MessageHandler(filters.VOICE, handle_voice)
            ],
            TASK_PRIORITY: [
                CallbackQueryHandler(cancel_callback, pattern="^cancel_action$"),
                CallbackQueryHandler(add_task_priority, pattern="^priority:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_task_priority),
                MessageHandler(filters.VOICE, handle_voice)
            ],
        },
        fallbacks=[
            CallbackQueryHandler(cancel_callback, pattern="^cancel_action$"),
            MessageHandler(filters.Regex("^❌ Бекор қилиш$"), cancel),
            CommandHandler("start", start)
        ],
    )
    
    # Schedule & reports conversation handler
    schedule_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(schedule_start, pattern="^main_schedule$"),
            MessageHandler(filters.Regex("^(📋 Топшириқлар жадвали|📋 Жадвал кўриш)$"), schedule_start),
            MessageHandler(filters.VOICE, handle_voice)
        ],
        states={
            SCHEDULE_MENU: [
                CallbackQueryHandler(cancel_callback, pattern="^cancel_action$"),
                CallbackQueryHandler(schedule_show, pattern="^(sched_general|sched_by_emp|sched_weekly|sched_update|sched_delete|sched_export|sched_add_attachment|cancel_action)$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, schedule_show),
                MessageHandler(filters.VOICE, handle_voice)
            ],
            SCHEDULE_EMPLOYEE_SELECT: [
                CallbackQueryHandler(cancel_callback, pattern="^cancel_action$"),
                CallbackQueryHandler(schedule_employee_select, pattern="^select_emp:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, schedule_employee_select),
                MessageHandler(filters.VOICE, handle_voice)
            ],
            SCHEDULE_EMPLOYEE_ACTION: [
                CallbackQueryHandler(cancel_callback, pattern="^cancel_action$"),
                CallbackQueryHandler(schedule_employee_action, pattern="^(sched_by_emp|cancel_action|emp_add_task:|emp_update_task:).+$"),
                CallbackQueryHandler(schedule_employee_action, pattern="^(sched_by_emp|cancel_action)$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, schedule_employee_action),
                MessageHandler(filters.VOICE, handle_voice)
            ],
            SCHEDULE_EMPLOYEE_ADD_TEXT: [
                CallbackQueryHandler(cancel_callback, pattern="^cancel_action$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, schedule_employee_add_text),
                MessageHandler(filters.VOICE, handle_voice)
            ],
            SCHEDULE_EMPLOYEE_ADD_DEADLINE: [
                CallbackQueryHandler(cancel_callback, pattern="^cancel_action$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, schedule_employee_add_deadline),
                MessageHandler(filters.VOICE, handle_voice)
            ],
            SCHEDULE_EMPLOYEE_ADD_PRIORITY: [
                CallbackQueryHandler(cancel_callback, pattern="^cancel_action$"),
                CallbackQueryHandler(schedule_employee_add_priority, pattern="^priority:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, schedule_employee_add_priority),
                MessageHandler(filters.VOICE, handle_voice)
            ],
            SCHEDULE_EMPLOYEE_UPDATE_ID: [
                CallbackQueryHandler(cancel_callback, pattern="^cancel_action$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, schedule_employee_update_id),
                MessageHandler(filters.VOICE, handle_voice)
            ],
            SCHEDULE_EMPLOYEE_UPDATE_STATUS: [
                CallbackQueryHandler(cancel_callback, pattern="^cancel_action$"),
                CallbackQueryHandler(schedule_employee_update_status, pattern="^emp_status_update:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, schedule_employee_update_status),
                MessageHandler(filters.VOICE, handle_voice)
            ],
            SCHEDULE_GENERAL_UPDATE_ID: [
                CallbackQueryHandler(cancel_callback, pattern="^cancel_action$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, schedule_general_update_id),
                MessageHandler(filters.VOICE, handle_voice)
            ],
            SCHEDULE_GENERAL_UPDATE_STATUS: [
                CallbackQueryHandler(cancel_callback, pattern="^cancel_action$"),
                CallbackQueryHandler(schedule_general_update_status, pattern="^gen_status_update:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, schedule_general_update_status),
                MessageHandler(filters.VOICE, handle_voice)
            ],
            SCHEDULE_DELETE_TASK_ID: [
                CallbackQueryHandler(cancel_callback, pattern="^cancel_action$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, schedule_delete_task_id),
                MessageHandler(filters.VOICE, handle_voice)
            ],
            SCHEDULE_ADD_ATTACH_TASK_ID: [
                CallbackQueryHandler(cancel_callback, pattern="^cancel_action$"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, schedule_add_attachment_id),
                MessageHandler(filters.VOICE, handle_voice)
            ],
            SCHEDULE_ADD_ATTACH_CONTENT: [
                CallbackQueryHandler(cancel_callback, pattern="^cancel_action$"),
                MessageHandler(filters.TEXT | filters.PHOTO | filters.Document.ALL & ~filters.COMMAND, schedule_add_attachment_content),
                MessageHandler(filters.VOICE, handle_voice)
            ]
        },
        fallbacks=[
            CallbackQueryHandler(cancel_callback, pattern="^cancel_action$"),
            MessageHandler(filters.Regex("^❌ Бекор қилиш$"), cancel),
            CommandHandler("start", start)
        ]
    )
    
    app.add_handler(MessageHandler(filters.ALL, track_group_chat), group=-1)
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_group))

    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, handle_employee_proof_upload))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("del_task", delete_task))
    app.add_handler(CommandHandler("my_tasks", my_tasks_start))
    app.add_handler(add_task_conv)
    app.add_handler(schedule_conv)
    
    # Callback query button handlers outside active conversations
    app.add_handler(CallbackQueryHandler(start, pattern="^main_menu$"))
    app.add_handler(CallbackQueryHandler(view_statistics, pattern="^main_stats$"))
    app.add_handler(CallbackQueryHandler(employee_rating, pattern="^main_rating$"))
    app.add_handler(CallbackQueryHandler(cancel_callback, pattern="^cancel_action$"))
    app.add_handler(CallbackQueryHandler(my_tasks_start, pattern="^my_tasks_view$"))
    
    # Employee Personal Cabinet callback queries
    app.add_handler(CallbackQueryHandler(handle_link_account, pattern="^link_account:"))
    app.add_handler(CallbackQueryHandler(handle_request_complete, pattern="^request_complete:"))
    app.add_handler(CallbackQueryHandler(handle_approve_complete, pattern="^approve_complete:"))
    app.add_handler(CallbackQueryHandler(handle_reject_complete, pattern="^reject_complete:"))
    app.add_handler(CallbackQueryHandler(handle_send_no_photo, pattern="^send_no_photo:"))
    app.add_handler(CallbackQueryHandler(handle_cancel_photo_proof, pattern="^cancel_photo_proof$"))
    app.add_handler(CallbackQueryHandler(handle_employee_chart, pattern="^emp_chart:"))
    
    # Reply filters fallback outside conversations
    app.add_handler(MessageHandler(filters.Regex("^❌ Бекор қилиш$"), cancel))
    app.add_handler(MessageHandler(filters.Regex("^(📋 Топшириқлар жадвали|📋 Жадвал кўриш)$"), schedule_start))
    app.add_handler(MessageHandler(filters.Regex("^📊 Статистика$"), view_statistics))
    app.add_handler(MessageHandler(filters.Regex("^👥 Ходимлар рейтинги$"), employee_rating))
    app.add_handler(MessageHandler(filters.Regex("^🗑 Топшириқ ўчириш$"), schedule_start))
    app.add_handler(MessageHandler(filters.Regex("^📋 Менинг вазифаларим$"), my_tasks_start))
    
    # Silent Voice Note parser
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    
    # Scheduler
    scheduler = AsyncIOScheduler(timezone=TASHKENT_TZ)
    scheduler.add_job(
        send_inprogress_tasks_report,
        trigger='cron',
        hour=11, minute=0,
        args=[app]
    )
    scheduler.add_job(
        send_daily_report,
        trigger='cron',
        hour=16, minute=0,
        args=[app]
    )
    scheduler.add_job(
        send_morning_reminders,
        trigger='cron',
        hour=9, minute=0,
        args=[app]
    )
    scheduler.add_job(
        send_weekly_report,
        trigger='cron',
        day_of_week='sat',
        hour=17, minute=0,
        args=[app]
    )
    scheduler.add_job(
        check_approaching_deadlines,
        trigger='interval',
        minutes=30,
        args=[app]
    )

    async def on_startup(application):
        from telegram import BotCommand
        commands = [
            BotCommand("add_task", "➕ Янги топшириқ қўшиш (Раҳбарлар учун)"),
            BotCommand("start", "🤖 Асосий бошқарув менюси"),
            BotCommand("my_tasks", "📋 Менинг фаол вазифаларим кабинети"),
            BotCommand("del_task", "🗑 Топшириқни ўчириш (Раҳбарлар учун)")
        ]
        try:
            await application.bot.set_my_commands(commands)
            logger.info("Бот меню буйруқлари муваффақиятли ўрнатилди (Menu Button).")
        except Exception as e:
            logger.error(f"Menu Button созлашда хатолик: {e}")
            
        scheduler.start()
        logger.info("Scheduler ishga tushdi. Hisobot 16:00 da, eslatmalar 09:00 da, жараёндагилар 11:00 да юборилади.")

    async def on_shutdown(application):
        if scheduler.running:
            scheduler.shutdown(wait=False)

    app.post_init = on_startup
    app.post_shutdown = on_shutdown

    # Start Web Health Check Server for Render free tier compliance
    import http.server
    import threading
    
    class HealthCheckHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path in ('/healthz', '/'):
                self.send_response(200)
                self.send_header('Content-type', 'text/plain')
                self.end_headers()
                self.wfile.write(b"OK")
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Not Found")
                
        def log_message(self, format, *args):
            return

    def run_health_server():
        port = int(os.environ.get("PORT", 8080))
        logger.info(f"Health check server listening on port {port}...")
        server = http.server.HTTPServer(('0.0.0.0', port), HealthCheckHandler)
        server.serve_forever()

    logger.info("Starting web health check server...")
    threading.Thread(target=run_health_server, daemon=True).start()

    logger.info("Bot started. Daily report scheduled at 16:00, morning reminders at 09:00, in-progress tasks at 11:00.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        import sys
        print(f"CRITICAL RUNTIME ERROR: {e}", file=sys.stderr, flush=True)
        traceback.print_exc(file=sys.stderr)
        sys.exit(1)
