from typing import List, Dict
from datetime import datetime

PRIORITY_EMOJI = {"Юқори": "🔴", "Ўрта": "🟡", "Паст": "🟢"}
STATUS_EMOJI = {
    "Кутяпти": "⏳", "Жараёнда": "🔄",
    "Бажарилди": "✅", "Бекор қилинди": "❌"
}

def generate_daily_report(tasks: List[Dict], header: str = "📋 ТОПШИРИҚЛАР") -> str:
    if not tasks:
        return f"{header}\n\nТопшириқлар мавжуд эмас."

    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    text = f"{header}\n"
    text += f"📅 {now}\n"
    text += "━━━━━━━━━━━━━━━━━━━━━━\n\n"

    # Group by status
    groups = {
        "🔴 ЮҚОРИ ПРИОРИТЕТ": [t for t in tasks if t['priority'] == 'Юқори'],
        "🟡 ЎРТА ПРИОРИТЕТ":  [t for t in tasks if t['priority'] == 'Ўрта'],
        "🟢 ПАСТ ПРИОРИТЕТ":  [t for t in tasks if t['priority'] == 'Паст'],
    }

    for group_name, group_tasks in groups.items():
        if not group_tasks:
            continue
        text += f"<b>{group_name}</b>\n"
        for t in group_tasks:
            status_e = STATUS_EMOJI.get(t['status'], "❓")
            text += (
                f"  <code>#{t['id']}</code> {status_e} <b>{t['text']}</b>\n"
                f"       👤 {t['responsible']}  |  📅 {t['deadline']}\n"
                f"       Ҳолат: <i>{t['status']}</i>\n"
            )
            if t.get('updated_at') and t['status'] in ('Бажарилди', 'Жараёнда'):
                text += f"       🕐 Янгиланди: {t['updated_at'][:16]}\n"
        text += "\n"

    return text
