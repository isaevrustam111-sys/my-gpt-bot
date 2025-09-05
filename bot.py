import os
import json
from pathlib import Path
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes
)
from openai import OpenAI

# === Конфиг / ключи ===
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_KEY)

DATA_FILE = Path("data.json")

# === База (JSON) ===
def load_data() -> dict:
    if not DATA_FILE.exists():
        return {}
    try:
        with DATA_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return {}

def save_data(data: dict) -> None:
    with DATA_FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def ensure_user(data: dict, user_id: int) -> None:
    uid = str(user_id)
    if uid not in data:
        data[uid] = {"dice": 0, "messages": 0, "chat_mode": False, "quiz": None}
    data[uid].setdefault("chat_mode", False)
    data[uid].setdefault("quiz", None)

# === GPT ===
async def ask_gpt(prompt: str) -> str:
    if not OPENAI_KEY:
        return "⚠️ Не задан OPENAI_API_KEY в .env"
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=350,
        )
        return (resp.choices[0].message.content or "").strip()
    except Exception as e:
        return f"⚠️ Ошибка GPT: {e}"

# === Викторина ===
QUIZ_QUESTIONS = [
    "Сколько будет 2 + 2?",
    "Столица Франции?",
    "Что тяжелее: 1 кг ваты или 1 кг железа?"
]

async def start_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE, from_button=False):
    uid = str(update.effective_user.id)
    data = load_data()
    ensure_user(data, update.effective_user.id)

    data[uid]["quiz"] = {"q": 0, "score": 0}
    save_data(data)

    msg = f"📝 Викторина началась!\nВопрос 1: {QUIZ_QUESTIONS[0]}"
    if from_button:
        await update.callback_query.message.reply_text(msg)
    else:
        await update.message.reply_text(msg)

async def on_button_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start_quiz(update, context, from_button=True)

# === Вспомогательные клавиатуры ===
def main_menu_kb() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("🎲 Кубик", callback_data="ROLL_DICE")],
        [InlineKeyboardButton("📚 Помощь", callback_data="HELP")],
        [InlineKeyboardButton("🧠 Ассистент GPT", callback_data="GPT_CHAT")],
        [InlineKeyboardButton("🎯 Викторина", callback_data="QUIZ_START")],
    ]
    return InlineKeyboardMarkup(rows)

def back_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад в меню", callback_data="BACK_TO_MENU")]])

# === Хэндлеры ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    name = user.first_name or "друг"

    data = load_data()
    ensure_user(data, user.id)
    state = "включён" if data[str(user.id)]["chat_mode"] else "выключен"

    await update.message.reply_text(
        f"Привет, {name}! 👋\n"
        f"Режим «Ассистент GPT» сейчас {state}.\n"
        f"Нажми кнопку ниже, чтобы начать диалог с GPT.",
        reply_markup=main_menu_kb()
    )

async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    uid = str(q.from_user.id)

    data = load_data()
    ensure_user(data, q.from_user.id)

    if q.data == "ROLL_DICE":
        import random
        v = random.randint(1, 6)
        data[uid]["dice"] += 1
        save_data(data)
        await q.message.reply_text(f"🎲 Выпало: {v}")

    elif q.data == "HELP":
        await q.message.reply_text(
            "Я умею:\n"
            "• /start — меню\n"
            "• /stats — твоя статистика\n"
            "• /reset — сброс статистики\n"
            "• 🎲 Кубик, 🧠 Ассистент GPT (кнопки)\n\n"
            "В режиме «Ассистент GPT» просто пиши сообщения — я отвечу с помощью GPT.",
            reply_markup=main_menu_kb()
        )

    elif q.data == "GPT_CHAT":
        data[uid]["chat_mode"] = True
        save_data(data)
        await q.message.reply_text(
            "🧠 Режим «Ассистент GPT» включён.\n"
            "Пиши свой вопрос — отвечу через GPT.\n"
            "Чтобы выйти, нажми «🔙 Назад в меню».",
            reply_markup=back_menu_kb()
        )

    elif q.data == "BACK_TO_MENU":
        data[uid]["chat_mode"] = False
        save_data(data)
        await q.message.reply_text(
            "Возврат в главное меню.",
            reply_markup=main_menu_kb()
        )

    elif q.data == "QUIZ_START":
        await on_button_quiz(update, context)

async def echo_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    uid = str(update.effective_user.id)

    data = load_data()
    ensure_user(data, update.effective_user.id)
    data[uid]["messages"] += 1
    save_data(data)

    if text.startswith("/"):
        return

    if data[uid]["quiz"] is not None:
        q_index = data[uid]["quiz"]["q"]
        score = data[uid]["quiz"]["score"]

        question = QUIZ_QUESTIONS[q_index]
        check_prompt = (
            f"Вопрос: {question}\n"
            f"Ответ ученика: {text}\n"
            f"Правильный ли ответ? Ответь только 'да' или 'нет'."
        )
        verdict = await ask_gpt(check_prompt)

        if verdict.lower().startswith("да"):
            score += 1
            await update.message.reply_text("✅ Верно!")
        else:
            await update.message.reply_text("❌ Неверно.")

        q_index += 1
        if q_index < len(QUIZ_QUESTIONS):
            data[uid]["quiz"] = {"q": q_index, "score": score}
            save_data(data)
            await update.message.reply_text(f"Вопрос {q_index+1}: {QUIZ_QUESTIONS[q_index]}")
        else:
            await update.message.reply_text(f"🏁 Викторина окончена! Твои баллы: {score}/{len(QUIZ_QUESTIONS)}")
            data[uid]["quiz"] = None
            save_data(data)
        return

    if data[uid]["chat_mode"]:
        answer = await ask_gpt(text)
        await update.message.reply_text(answer, reply_markup=back_menu_kb())
        return

    await update.message.reply_text(f'Ты написал: "{text}"', reply_markup=main_menu_kb())

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    data = load_data()
    ensure_user(data, update.effective_user.id)
    u = data[uid]
    await update.message.reply_text(
        f"📊 Твоя статистика:\n— кубик: {u['dice']}\n— сообщений: {u['messages']}"
    )

async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = str(update.effective_user.id)
    data = load_data()
    data[uid] = {"dice": 0, "messages": 0, "chat_mode": False, "quiz": None}
    save_data(data)
    await update.message.reply_text("♻️ Твоя статистика сброшена.", reply_markup=main_menu_kb())

def main():
    if not BOT_TOKEN:
        raise RuntimeError("Нет BOT_TOKEN в .env")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo_text))
    print("✅ Бот запущен: режим «Ассистент GPT» доступен кнопкой")
    app.run_polling()

if __name__ == "__main__":
    main()
   
