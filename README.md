# 📋 Топшириқлар Менежери Telegram Боти

## Функционал
- ➕ Топшириқ қўшиш (матн, масъул, муддат, приоритет)
- 📋 Жадвал кўриш (приоритет бўйича гуруҳланган)
- ✅ Ҳолатни янгилаш
- 📊 Умумий статистика + ижро фоизи
- 👥 Ходимлар рейтинги ва самарадорлик
- 🕓 Ҳар куни соат **16:00** (Тошкент вақти) да автоматик ҳисобот
- 🗑 Топшириқ ўчириш

## Ўрнатиш

### 1. Python ва кутубхоналарни ўрнатиш
```bash
pip install -r requirements.txt
```

### 2. Telegram Bot Token олиш
1. Telegramda [@BotFather](https://t.me/BotFather) га ёзинг
2. `/newbot` командасини юборинг
3. Ботга исм ва username беринг
4. Token нусхасини олинг

### 3. Token ни созлаш

**Вариант А — environment variable:**
```bash
export BOT_TOKEN="1234567890:ABCdefGHIjklMNOpqrsTUVwxyz"
python bot.py
```

**Вариант Б — `bot.py` ичида:**
```python
TOKEN = "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz"
```

### 4. Ботни ишга тушириш
```bash
python bot.py
```

## Фойдаланиш

| Тугма | Функция |
|-------|---------|
| ➕ Топшириқ қўшиш | Янги топшириқ яратиш |
| 📋 Жадвал кўриш | Барча топшириқлар жадвали |
| 📊 Статистика | Умумий ва ходимлар статистикаси |
| ✅ Ҳолатни янгилаш | Топшириқ ҳолатини ўзгартириш |
| 👥 Ходимлар рейтинги | Самарадорлик рейтинги |
| 🗑 Топшириқ ўчириш | `/del_task <рақам>` |

## Ҳолатлар
- ⏳ **Кутяпти** — янги топшириқ
- 🔄 **Жараёнда** — бажарилмоқда
- ✅ **Бажарилди** — тугатилди
- ❌ **Бекор қилинди** — бекор бўлди

## Приоритетлар
- 🔴 Юқори
- 🟡 Ўрта
- 🟢 Паст

## Маълумотлар базаси
SQLite (`tasks.db` файли автоматик яратилади)

## Сервер / VPS да ишлатиш (systemd)
```ini
[Unit]
Description=Task Manager Telegram Bot
After=network.target

[Service]
Type=simple
WorkingDirectory=/path/to/task_bot
ExecStart=/usr/bin/python3 bot.py
Environment=BOT_TOKEN=YOUR_TOKEN_HERE
Restart=always

[Install]
WantedBy=multi-user.target
```
