import os
import logging
import asyncio
import json
from typing import List, Tuple

from aiogram import Bot, Dispatcher, types
from aiogram.utils.executor import start_webhook
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

logging.basicConfig(level=logging.INFO)

# ====== Налаштування ======
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("❌ BOT_TOKEN не встановлений!")

ADMIN_IDS = []
if os.getenv("ADMIN_IDS"):
    ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS").split(",") if x.strip()]

WEBHOOK_HOST = os.getenv("WEBHOOK_HOST")  # https://mybot.onrender.com
PORT = int(os.getenv("PORT", "10000"))
POST_INTERVAL = int(os.getenv("POST_INTERVAL", "600"))  # 10 хв за замовчуванням

DATA_FILE = "data.json"
WEBHOOK_PATH = f"/webhook/{TOKEN}"
WEBHOOK_URL = (WEBHOOK_HOST or "") + WEBHOOK_PATH

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# ====== FSM для створення постів ======
class PostStates(StatesGroup):
    text = State()
    photo = State()
    buttons = State()

# ====== Збереження даних ======
def load_data():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {"chat_id": None, "posts": []}

def save_data(d):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)

data = load_data()

def is_admin(user_id: int):
    return user_id in ADMIN_IDS

def build_keyboard(buttons_list: List[Tuple[str, str]]):
    kb = InlineKeyboardMarkup()
    for t, u in buttons_list:
        kb.add(InlineKeyboardButton(text=t, url=u))
    return kb

# ====== Команди ======
@dp.message_handler(commands=["start"])
async def cmd_start(msg: types.Message):
    await msg.reply("Привіт! Я автопостинг-бот.\n\nКоманди:\n/setchat <chat_id>\n/addpost\n/showqueue")

@dp.message_handler(commands=["setchat"])
async def cmd_setchat(msg: types.Message):
    if not is_admin(msg.from_user.id):
        return await msg.reply("⛔ Немає прав.")
    args = msg.get_args().strip()
    if not args:
        return await msg.reply("Використання: /setchat <chat_id>")
    try:
        data["chat_id"] = int(args)
        save_data(data)
        await msg.reply(f"✅ Чат встановлено: {data['chat_id']}")
    except:
        await msg.reply("❌ Помилка: chat_id має бути числом.")

@dp.message_handler(commands=["addpost"])
async def cmd_addpost(msg: types.Message):
    if not is_admin(msg.from_user.id):
        return await msg.reply("⛔ Немає прав.")
    await msg.reply("Введи текст поста:")
    await PostStates.text.set()

@dp.message_handler(state=PostStates.text, content_types=types.ContentTypes.TEXT)
async def process_text(m: types.Message, state: FSMContext):
    await state.update_data(text=m.text)
    await m.reply("Пришли фото або напиши 'skip':")
    await PostStates.photo.set()

@dp.message_handler(state=PostStates.photo, content_types=[types.ContentType.PHOTO, types.ContentType.TEXT])
async def process_photo(m: types.Message, state: FSMContext):
    if m.content_type == "photo":
        await state.update_data(photo=m.photo[-1].file_id)
    elif m.text.lower().strip() == "skip":
        await state.update_data(photo=None)
    else:
        return await m.reply("❌ Надішли фото або 'skip'.")
    await m.reply("Введи кнопки у форматі:\nТекст - https://link\nАбо 'skip'")
    await PostStates.buttons.set()

@dp.message_handler(state=PostStates.buttons, content_types=types.ContentType.TEXT)
async def process_buttons(m: types.Message, state: FSMContext):
    buttons_list = []
    if m.text.lower().strip() != "skip":
        try:
            for line in m.text.splitlines():
                txt, url = line.split(" - ", 1)
                buttons_list.append((txt.strip(), url.strip()))
        except:
            return await m.reply("❌ Формат: Назва - https://силка")
    d = await state.get_data()
    post = {"text": d["text"], "photo": d.get("photo"), "buttons": buttons_list}
    data["posts"].append(post)
    save_data(data)
    await state.finish()
    await m.reply("✅ Пост додано в чергу!")

@dp.message_handler(commands=["showqueue"])
async def cmd_showqueue(msg: types.Message):
    if not is_admin(msg.from_user.id):
        return await msg.reply("⛔ Немає прав.")
    posts = data.get("posts", [])
    if not posts:
        return await msg.reply("Черга порожня.")
    text = "Черга постів:\n"
    for i, p in enumerate(posts, 1):
        text += f"{i}. {p['text'][:40]}...\n"
    await msg.reply(text)

# ====== Автопостинг ======
async def auto_poster():
    while True:
        if data.get("chat_id") and data["posts"]:
            post = data["posts"].pop(0)
            save_data(data)
            kb = build_keyboard(post["buttons"]) if post.get("buttons") else None
            try:
                if post["photo"]:
                    await bot.send_photo(data["chat_id"], post["photo"], caption=post["text"], reply_markup=kb)
                else:
                    await bot.send_message(data["chat_id"], post["text"], reply_markup=kb)
                logging.info("✅ Пост відправлено.")
            except Exception as e:
                logging.error(f"Помилка відправки: {e}")
        await asyncio.sleep(POST_INTERVAL)

# ====== Webhook запуск ======
async def on_startup(dp):
    await bot.set_webhook(WEBHOOK_URL)
    asyncio.create_task(auto_poster())
    logging.info(f"Webhook встановлено: {WEBHOOK_URL}")

async def on_shutdown(dp):
    await bot.delete_webhook()

if __name__ == "__main__":
    if not WEBHOOK_HOST:
        raise RuntimeError("❌ Вкажи WEBHOOK_HOST у Render Environment!")
    start_webhook(
        dispatcher=dp,
        webhook_path=WEBHOOK_PATH,
        on_startup=on_startup,
        on_shutdown=on_shutdown,
        skip_updates=True,
        host="0.0.0.0",
        port=PORT,
    )
