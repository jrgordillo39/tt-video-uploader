import os
import logging
import tempfile
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from tiktok import TikTokUploader
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_USER_IDS = list(map(int, os.getenv("ALLOWED_USER_IDS", "").split(","))) if os.getenv("ALLOWED_USER_IDS") else []

tiktok = TikTokUploader()

# ─── Helpers ──────────────────────────────────────────────────────────────────

def is_authorized(user_id: int) -> bool:
    """Only allow specific users if ALLOWED_USER_IDS is set."""
    if not ALLOWED_USER_IDS:
        return True
    return user_id in ALLOWED_USER_IDS

# ─── Handlers ─────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("⛔ No tienes permiso para usar este bot.")
        return

    text = (
        "👋 *Bot de TikTok* listo!\n\n"
        "📤 Envíame un video y lo subiré a TikTok.\n\n"
        "Puedes agregar un *caption* como descripción del video "
        "escribiéndolo como *caption* del video al enviarlo.\n\n"
        "Comandos:\n"
        "/start – Este mensaje\n"
        "/auth – Autorizar tu cuenta de TikTok\n"
        "/status – Ver estado de autenticación\n"
        "/help – Ayuda"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def auth(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("⛔ No tienes permiso para usar este bot.")
        return

    auth_url = tiktok.get_auth_url()
    keyboard = [[InlineKeyboardButton("🔑 Autorizar en TikTok", url=auth_url)]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        "Para subir videos necesitas autorizar el bot con tu cuenta de TikTok.\n\n"
        "1️⃣ Haz clic en el botón\n"
        "2️⃣ Inicia sesión en TikTok\n"
        "3️⃣ Copia el *código* de la URL de redirección\n"
        "4️⃣ Envíame: `/code TU_CODIGO`",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )


async def code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive OAuth code from user."""
    if not is_authorized(update.effective_user.id):
        return

    if not context.args:
        await update.message.reply_text("⚠️ Uso: `/code CODIGO_DE_TIKTOK`", parse_mode="Markdown")
        return

    auth_code = context.args[0]
    msg = await update.message.reply_text("⏳ Canjeando código...")

    success = tiktok.exchange_code(auth_code)
    if success:
        await msg.edit_text("✅ ¡Autenticado exitosamente! Ya puedes enviarme videos.")
    else:
        await msg.edit_text("❌ Error al canjear el código. Intenta `/auth` nuevamente.", parse_mode="Markdown")


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return

    if tiktok.is_authenticated():
        await update.message.reply_text("✅ TikTok autenticado y listo.")
    else:
        await update.message.reply_text(
            "❌ No autenticado. Usa /auth para conectar tu cuenta de TikTok."
        )


async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("⛔ No tienes permiso para usar este bot.")
        return

    if not tiktok.is_authenticated():
        await update.message.reply_text(
            "❌ Primero debes autenticar tu cuenta de TikTok. Usa /auth"
        )
        return

    video = update.message.video or update.message.document
    if not video:
        await update.message.reply_text("⚠️ Por favor envía un archivo de video.")
        return

    # Validate file size (TikTok max: 4GB, Telegram bot API max: ~50MB for bots)
    if hasattr(video, 'file_size') and video.file_size and video.file_size > 50 * 1024 * 1024:
        await update.message.reply_text("⚠️ El video es demasiado grande. Máximo 50MB via Telegram.")
        return

    caption = update.message.caption or ""
    msg = await update.message.reply_text("⬇️ Descargando video...")

    try:
        # Download video to temp file
        file = await video.get_file()
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp_path = tmp.name

        await file.download_to_drive(tmp_path)
        await msg.edit_text("⬆️ Subiendo a TikTok...")

        # Upload to TikTok
        result = await tiktok.upload_video(tmp_path, caption=caption)

        if result["success"]:
            await msg.edit_text(
                f"✅ ¡Video subido exitosamente a TikTok!\n\n"
                f"🎵 Puede tardar unos minutos en aparecer en tu perfil."
            )
        else:
            await msg.edit_text(f"❌ Error al subir: {result.get('error', 'Error desconocido')}")

    except Exception as e:
        logger.error(f"Error handling video: {e}")
        await msg.edit_text(f"❌ Error inesperado: {str(e)}")
    finally:
        # Cleanup temp file
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🤖 *Ayuda del Bot de TikTok*\n\n"
        "*Cómo usar:*\n"
        "1. Usa /auth para conectar tu cuenta de TikTok\n"
        "2. Envía cualquier video al bot\n"
        "3. Agrega un caption al video como descripción\n\n"
        "*Formatos soportados:* MP4, MOV, AVI\n"
        "*Tamaño máximo:* 50MB\n\n"
        "*Comandos:*\n"
        "/start – Inicio\n"
        "/auth – Autenticar con TikTok\n"
        "/code CODIGO – Ingresar código OAuth\n"
        "/status – Estado de autenticación\n"
        "/help – Esta ayuda"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("auth", auth))
    app.add_handler(CommandHandler("code", code))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, handle_video))

    logger.info("🤖 Bot iniciado...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
