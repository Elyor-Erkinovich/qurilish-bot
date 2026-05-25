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


def generate_employee_grouped_report(tasks: List[Dict], header: str = "📋 ТОПШИРИҚЛАР", employees: List[str] = None) -> str:
    if not tasks:
        return f"{header}\n\nТопшириқлар мавжуд эмас."

    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    text = f"{header}\n"
    text += f"📅 {now}\n"
    text += "━━━━━━━━━━━━━━━━━━━━━━\n\n"

    # Group tasks by employee
    emp_groups = {}
    for t in tasks:
        resp = t['responsible']
        if resp not in emp_groups:
            emp_groups[resp] = []
        emp_groups[resp].append(t)

    # Sort employees: if list of employees is provided, use that order, then any others
    sorted_emps = []
    if employees:
        for emp in employees:
            if emp in emp_groups:
                sorted_emps.append(emp)
        # Any other employees not in the standard list (e.g. manual text entry or voice)
        for emp in sorted(emp_groups.keys()):
            if emp not in sorted_emps:
                sorted_emps.append(emp)
    else:
        sorted_emps = sorted(emp_groups.keys())

    for emp in sorted_emps:
        text += f"👤 <b>{emp}</b>\n"
        text += "──────────────────────\n"
        for t in emp_groups[emp]:
            status_e = STATUS_EMOJI.get(t['status'], "❓")
            prio_e = PRIORITY_EMOJI.get(t['priority'], "🟡")
            text += (
                f"  <code>#{t['id']}</code> {status_e} <b>{t['text']}</b>\n"
                f"       Муддат: 📅 {t['deadline']}  |  Приоритет: {prio_e} {t['priority']}\n"
                f"       Ҳолат: <i>{t['status']}</i>\n"
            )
            if t.get('updated_at') and t['status'] in ('Бажарилди', 'Жараёнда'):
                text += f"       🕐 Янгиланди: {t['updated_at'][:16]}\n"
        text += "\n"

    return text

