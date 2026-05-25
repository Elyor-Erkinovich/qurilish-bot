"""
voice_processor.py
──────────────────
Ovozli xabarni Gemini 2.5 Flash orqali qayta ishlash moduli.
Uzbek tilidagi ovozni matnga o'giradi va vazifa ma'lumotlarini ajratib oladi.
Yangi google-genai SDK ishlatiladi.
"""

import os
import json
import base64
import asyncio
import logging
from datetime import datetime, timedelta

from pydantic import BaseModel, Field

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "AIzaSyAWApWixnBNjJPPpCfAVRtUNHOPziNgAPk")

# Yangi SDK client
client = genai.Client(api_key=GEMINI_API_KEY)
MODEL_NAME = "gemini-2.5-flash"


class TaskData(BaseModel):
    task_text: str = Field(description="Topshiriq matni (aniq, qisqa va o'zbek tilida)")
    responsible: str = Field(description="Mas'ul shaxs ismi va familiyasi. Topilmasa 'Кўрсатилмаган'")
    deadline: str = Field(description="Topshiriqni bajarish muddati (bugungi sanadan kelib chiqib). Topilmasa 'Кўрсатилмаган'")
    priority: str = Field(description="Prioritet darajasi: 'Юқори', 'Ўрта' yoki 'Паст'. Default: 'Ўрта'")


# ─── Prompt ────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """Siz vazifa boshqaruv tizimi uchun yordamchisiz.
Berilgan audio xabarni tinglang va undan vazifa ma'lumotlarini ajratib oling.

Audio asosan O'zbek tilida bo'ladi, ba'zan Rus tilida ham bo'lishi mumkin.

Mas'ul shaxslar (responsible) ro'yxati (Faqat ushbu ro'yxatdan tanlang va ko'rsatilgan formatda yozing):
- Анвар ака (Гл.Инжинер)
- Элёр (Котибият)
- Мирзоҳид ака (Қурилиш)
- Абдулатиф (Коммунал)
- Наргиза (Котибият)
- Дилноза опа (Уй-жой)
- Фаррух (БСК)
- Зоҳид (Қурилиш)
- Жўрабек ака (Қурилиш)
- Одилхон (Қурилиш)
- Азамат (Аукцион)
- Зияд (Қурилиш)

Qoidalar:
- task_text: topshiriq mohiyatini aniq yozing, o'zbek tilida
- responsible: ism va aytilgan qismga qarab yuqoridagi ro'yxatdan aniq mos keladigan mas'ul shaxsning to'liq ismini (masalan, 'Mirzohid aka' yoki 'Mirzohid' aytilsa 'Мирзоҳид ака (Қурилиш)' deb) tanlang. Agar ro'yxatdagilardan hech kim aytilmagan bo'lsa, 'Кўрсатилмаган' deb yozing.
- deadline: agar aniq sana aytilmasa lekin "ertaga", "bu hafta", "3 kunda" kabi so'zlar bo'lsa, bugungi sanadan hisoblang. Bugun: {today}. Agar umuman aytilmasa "Кўрсатилмаган" yozing
- priority: "muhim"/"shoshilinch"/"yuqori" → "Юқори", "oddiy"/"o'rta"/"normal" → "Ўрта", "past"/"shoshilmaslik" → "Паст". Default: "Ўрта"
"""


def build_prompt() -> str:
    """Bugungi sana bilan prompt yaratadi."""
    today = datetime.now()
    tomorrow = today + timedelta(days=1)
    return SYSTEM_PROMPT.format(
        today=today.strftime("%d.%m.%Y"),
        tomorrow=tomorrow.strftime("%d.%m.%Y")
    )


# ─── Asosiy funksiya ───────────────────────────────────────────────────────────

async def process_voice(audio_bytes: bytes) -> dict:
    """
    OGG audio baytlarini Gemini 2.5 Flash ga yuboradi va vazifani qaytaradi.

    Returns:
        dict: {task_text, responsible, deadline, priority}
              yoki xato bo'lsa None
    """
    raw_text = ""
    try:
        logger.info(f"Audio baytlari qabul qilindi: {len(audio_bytes)} bayt")

        prompt_text = build_prompt()

        # Yangi SDK client yordamida native async Gemini chaqiruvi
        response = await client.aio.models.generate_content(
            model=MODEL_NAME,
            contents=[
                types.Part.from_bytes(
                    data=audio_bytes,
                    mime_type="audio/ogg"
                ),
                types.Part.from_text(text=prompt_text)
            ],
            config=types.GenerateContentConfig(
                temperature=0.1,
                response_mime_type="application/json",
                response_schema=TaskData,
            )
        )

        raw_text = response.text.strip()
        logger.info(f"Gemini javobi: {raw_text}")

        # JSON ni tozalash va o'qish (Structured output tufayli kafolatlangan)
        task_data = json.loads(raw_text)

        # Majburiy maydonlarni tekshirish
        for field in ["task_text", "responsible", "deadline", "priority"]:
            if field not in task_data or not str(task_data[field]).strip():
                task_data[field] = "Кўрсатилмаган"

        # Priority ni tekshirish
        if task_data["priority"] not in ["Юқори", "Ўрта", "Паст"]:
            task_data["priority"] = "Ўрта"

        logger.info(f"Vazifa muvaffaqiyatli ajratildi: {task_data}")
        return task_data

    except json.JSONDecodeError as e:
        logger.error(f"JSON parse xatosi: {e} | Matn: {raw_text!r}")
        return None
    except Exception as e:
        logger.error(f"Ovoz qayta ishlashda xato: {type(e).__name__}: {e}")
        return None


EMPLOYEE_USERNAMES = {
    "Анвар ака (Гл.Инжинер)": "@vbjdbfksb",
    "Элёр (Котибият)": "@elyor_erkinovich",
    "Мирзоҳид ака (Қурилиш)": "@m_4883",
    "Абдулатиф (Коммунал)": "@vakhabov7007",
    "Наргиза (Котибият)": "@nargis_yh",
    "Дилноза опа (Уй-жой)": "",
    "Фаррух (БСК)": "@TFF_077",
    "Зоҳид (Қурилиш)": "@asrorovch",
    "Жўрабек ака (Қурилиш)": "",
    "Одилхон (Қурилиш)": "@odilxon_khusniddinovich",
    "Азамат (Аукцион)": "",
    "Зияд (Қурилиш)": "@ZI7799"
}

def format_voice_confirmation(task_data: dict, task_id: int) -> str:
    """Foydalanuvchiga ko'rsatiladigan tasdiqlash xabarini shakllantiradi."""
    priority_emoji = {"Юқори": "🔴", "Ўрта": "🟡", "Паст": "🟢"}.get(
        task_data["priority"], "🟡"
    )
    responsible = task_data["responsible"]
    username = EMPLOYEE_USERNAMES.get(responsible, "")
    responsible_display = f"{responsible} ({username})" if username else responsible
    
    return (
        f"🎙️ <b>Овозли топшириқ #{task_id} сақланди!</b>\n\n"
        f"📌 <b>Топшириқ:</b> {task_data['task_text']}\n"
        f"👤 <b>Масъул:</b> {responsible_display}\n"
        f"📅 <b>Муддат:</b> {task_data['deadline']}\n"
        f"{priority_emoji} <b>Приоритет:</b> {task_data['priority']}\n\n"
        f"<i>🎙 Овозli buayruq orqali avtomatik qo'shildi</i>"
    )
