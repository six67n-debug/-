import asyncio
import logging
import os
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.filters import CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
import yt_dlp

# Токен вшит напрямую
BOT_TOKEN = "8804442351:AAGvudl6-E03mVm_38wiJmvAH4ZKh-ntUCg"

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
router = Router()
dp.include_router(router)

class BotStates(StatesGroup):
    waiting_for_link = State()

@router.message(CommandStart())
async def cmd_start(message: Message):
    welcome_text = (
        "👋 <b>Добро пожаловать!</b>\n\n"
        "Я — твой личный помощник по загрузке видео с YouTube.\n"
        "Отправь мне ссылку, и я скачаю видео в нужном тебе качестве.\n\n"
        "<i>Нажми кнопку ниже, чтобы начать работу.</i>"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟢 Принять и начать", callback_data="accept_terms")]
    ])
    await message.answer(welcome_text, reply_markup=keyboard)

@router.callback_query(F.data == "accept_terms")
async def on_accept_terms(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "🔗 <b>Отлично!</b>\n\n"
        "Загрузи ссылку на видео с ютуба (например: <code>https://youtu.be/...</code>)."
    )
    await state.set_state(BotStates.waiting_for_link)
    await callback.answer()

@router.message(StateFilter(BotStates.waiting_for_link), F.text.regexp(r'(https?://)?(www\.)?(youtube\.com|youtu\.?be)/.+'))
async def process_youtube_link(message: Message, state: FSMContext):
    processing_msg = await message.answer("⏳ <i>Глубокий анализ видео... Ищу все разрешения...</i>")
    url = message.text
    
    try:
        ydl_opts = {'quiet': True}
        def fetch_info():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(url, download=False)
        
        info = await asyncio.to_thread(fetch_info)
        
        available_resolutions = set()
        for f in info.get('formats', []):
            height = f.get('height')
            vcodec = f.get('vcodec')
            if height and vcodec != 'none':
                available_resolutions.add(height)
                    
        if not available_resolutions:
            await processing_msg.edit_text("❌ Не удалось найти разрешения для скачивания.")
            return

        await state.update_data(url=url, title=info.get('title', 'Видео'))
        
        sorted_res = sorted(list(available_resolutions), reverse=True)
        
        buttons = []
        for res in sorted_res:
            buttons.append([InlineKeyboardButton(text=f"🎥 Скачать {res}p", callback_data=f"dl_{res}")])
            
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        
        await processing_msg.edit_text(
            f"🎬 <b>{info.get('title', 'Видео')}</b>\n\n"
            f"Выберите качество для загрузки:\n"
            f"<i>(Учтите, видео тяжелее 50 МБ Telegram не пропустит)</i>",
            reply_markup=keyboard
        )

    except Exception as e:
        logging.error(f"Analysis error: {e}")
        await processing_msg.edit_text("❌ Ошибка при анализе ссылки. Убедитесь, что видео доступно.")

@router.callback_query(F.data.startswith("dl_"))
async def download_video(callback: CallbackQuery, state: FSMContext):
    resolution = callback.data.split("_")[1]
    user_data = await state.get_data()
    url = user_data.get("url")
    title = user_data.get("title", "Видео")
    
    if not url:
        await callback.answer("Ссылка устарела. Отправьте видео заново.", show_alert=True)
        return
        
    status_msg = await callback.message.edit_text(f"📥 <i>Загружаю видео в {resolution}p...\nПожалуйста, подождите.</i>")
    filename = f"video_{callback.from_user.id}.mp4"
    
    def perform_download(res, use_merge=True):
        if use_merge:
            fmt = f'bestvideo[height<={res}][ext=mp4]+bestaudio[ext=m4a]/best[height<={res}]'
        else:
            fmt = f'best[height<={res}]'
            
        ydl_opts = {
            'format': fmt,
            'outtmpl': filename,
            'quiet': True,
            'merge_output_format': 'mp4'
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

    try:
        await asyncio.to_thread(perform_download, resolution, True)
    except Exception:
        logging.warning("Нет утилиты ffmpeg. Запуск запасного варианта.")
        await status_msg.edit_text(f"⚠️ <i>Оптимизирую загрузку под ваше устройство, скачиваю...</i>")
        try:
            if os.path.exists(filename):
                os.remove(filename)
            await asyncio.to_thread(perform_download, resolution, False)
        except Exception:
            await status_msg.edit_text("❌ Ошибка при скачивании видео.")
            return

    if not os.path.exists(filename):
        await status_msg.edit_text("❌ Не удалось сохранить файл видео.")
        return

    file_size_mb = os.path.getsize(filename) / (1024 * 1024)
    if file_size_mb > 49.5:
        await status_msg.edit_text(
            f"❌ <b>Файл слишком большой!</b>\n\n"
            f"Ваше видео весит <b>{file_size_mb:.1f} МБ</b>.\n"
            f"Telegram блокирует загрузку файлов больше 50 МБ через ботов.\n\n"
            f"<i>Пожалуйста, загрузите ссылку заново и выберите разрешение поменьше.</i>"
        )
        os.remove(filename)
        return

    await status_msg.edit_text("🚀 <i>Отправляю видео в чат...</i>")
    try:
        video_file = FSInputFile(filename)
        await callback.message.answer_video(
            video=video_file,
            caption=f"✅ <b>{title}</b>\nРазрешение: {resolution}p"
        )
        await status_msg.delete()
    except Exception:
        await status_msg.edit_text("❌ Ошибка при отправке видео в Telegram.")
    finally:
        if os.path.exists(filename):
            os.remove(filename)

async def main():
    logging.basicConfig(level=logging.INFO)
    await bot.delete_webhook(drop_pending_updates=True)
    print("Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
