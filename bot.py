import os
import logging
import tempfile
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, ContextTypes, filters,
    ConversationHandler
)
from tiktok import TikTokUploader
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_USER_IDS = list(map(int, os.getenv("ALLOWED_USER_IDS", "").split(","))) if os.getenv("ALLOWED_USER_IDS") else []

tiktok = TikTokUploader()

# ConversationHandler states
WAITING_ALIAS = 1
WAITING_CODE  = 2

# ─── Auth ─────────────────────────────────────────────────────────────────────

def is_authorized(user_id: int) -> bool:
    if not ALLOWED_USER_IDS:
        return True
    return user_id in ALLOWED_USER_IDS

# ─── /start ───────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("⛔ No tienes permiso para usar este bot.")
        return

    text = (
        "👋 *Bot de TikTok* listo!\n\n"
        "📤 Envíame un video y te preguntaré a qué cuenta subirlo.\n\n"
        "Comandos:\n"
        "/cuentas – Ver cuentas conectadas\n"
        "/addcuenta – Conectar nueva cuenta de TikTok\n"
        "/eliminarcuenta – Eliminar una cuenta\n"
        "/seleccionar – Cambiar cuenta activa\n"
        "/status – Estado de la cuenta activa\n"
        "/help – Ayuda"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

# ─── /cuentas ─────────────────────────────────────────────────────────────────

async def cuentas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return

    accounts = tiktok.list_accounts()
    selected = tiktok.selected_account

    if not accounts:
        await update.message.reply_text(
            "No hay cuentas conectadas.\nUsa /addcuenta para agregar una."
        )
        return

    lines = ["📋 *Cuentas de TikTok conectadas:*\n"]
    for acc in accounts:
        status_icon = "✅" if acc.is_authenticated() else "⚠️"
        active_mark = " ← *activa*" if selected and selected.alias == acc.alias else ""
        lines.append(f"{status_icon} `{acc.alias}` — @{acc.username}{active_mark}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

# ─── /addcuenta ───────────────────────────────────────────────────────────────

async def addcuenta_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return
    await update.message.reply_text(
        "¿Qué alias le quieres dar a esta cuenta?\n"
        "Ej: `personal`, `empresa`, `marca2`\n\n"
        "_(Escribe /cancelar para salir)_",
        parse_mode="Markdown"
    )
    return WAITING_ALIAS

async def addcuenta_alias(update: Update, context: ContextTypes.DEFAULT_TYPE):
    alias = update.message.text.strip().lower().replace(" ", "_")

    if not alias or len(alias) > 30:
        await update.message.reply_text("⚠️ Alias inválido. Intenta con un nombre corto sin espacios.")
        return WAITING_ALIAS

    if tiktok.get_account(alias):
        await update.message.reply_text(
            f"⚠️ Ya existe una cuenta con alias `{alias}`.\nElige otro nombre.",
            parse_mode="Markdown"
        )
        return WAITING_ALIAS

    context.user_data["pending_alias"] = alias
    auth_url = tiktok.get_auth_url(alias)

    keyboard = [[InlineKeyboardButton("🔑 Autorizar en TikTok", url=auth_url)]]
    await update.message.reply_text(
        f"Conectando cuenta: `{alias}`\n\n"
        "1️⃣ Haz clic en el botón\n"
        "2️⃣ Inicia sesión con la cuenta de TikTok correcta\n"
        "3️⃣ Copia el *código* de la URL de redirección\n"
        "4️⃣ Pégalo aquí",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return WAITING_CODE

async def addcuenta_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code  = update.message.text.strip()
    alias = context.user_data.get("pending_alias")

    if not alias:
        await update.message.reply_text("❌ Sesión perdida. Usa /addcuenta nuevamente.")
        return ConversationHandler.END

    msg = await update.message.reply_text("⏳ Canjeando código...")
    success = tiktok.exchange_code(code, alias)

    if success:
        acc = tiktok.get_account(alias)
        tiktok.select_account(alias)
        await msg.edit_text(
            f"✅ Cuenta `{alias}` (@{acc.username}) conectada y seleccionada como activa!",
            parse_mode="Markdown"
        )
    else:
        await msg.edit_text("❌ Código inválido o expirado. Usa /addcuenta para intentar de nuevo.")

    context.user_data.pop("pending_alias", None)
    return ConversationHandler.END

async def cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text("❌ Operación cancelada.")
    return ConversationHandler.END

# ─── /seleccionar ─────────────────────────────────────────────────────────────

async def seleccionar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return

    accounts = tiktok.list_accounts()
    if not accounts:
        await update.message.reply_text("No hay cuentas. Usa /addcuenta primero.")
        return

    keyboard = []
    for acc in accounts:
        icon = "✅" if acc.is_authenticated() else "⚠️"
        keyboard.append([InlineKeyboardButton(
            f"{icon} {acc.alias} — @{acc.username}",
            callback_data=f"select_{acc.alias}"
        )])

    await update.message.reply_text(
        "¿A qué cuenta quieres cambiar?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def seleccionar_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    alias = query.data.replace("select_", "")
    if tiktok.select_account(alias):
        acc = tiktok.get_account(alias)
        await query.edit_message_text(
            f"✅ Cuenta activa: `{alias}` (@{acc.username})",
            parse_mode="Markdown"
        )
    else:
        await query.edit_message_text("❌ Cuenta no encontrada.")

# ─── /eliminarcuenta ──────────────────────────────────────────────────────────

async def eliminarcuenta(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return

    accounts = tiktok.list_accounts()
    if not accounts:
        await update.message.reply_text("No hay cuentas conectadas.")
        return

    keyboard = []
    for acc in accounts:
        keyboard.append([InlineKeyboardButton(
            f"🗑 {acc.alias} — @{acc.username}",
            callback_data=f"delete_{acc.alias}"
        )])

    await update.message.reply_text(
        "¿Qué cuenta quieres eliminar?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def eliminarcuenta_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    alias = query.data.replace("delete_", "")
    if tiktok.remove_account(alias):
        await query.edit_message_text(f"🗑 Cuenta `{alias}` eliminada.", parse_mode="Markdown")
    else:
        await query.edit_message_text("❌ Cuenta no encontrada.")

# ─── /status ──────────────────────────────────────────────────────────────────

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return

    acc = tiktok.selected_account
    if not acc:
        accounts = tiktok.list_accounts()
        if not accounts:
            await update.message.reply_text("No hay cuentas. Usa /addcuenta.")
        else:
            await update.message.reply_text(
                "No hay cuenta activa. Usa /seleccionar para elegir una."
            )
        return

    icon = "✅" if acc.is_authenticated() else "⚠️ Token expirado"
    await update.message.reply_text(
        f"{icon} Cuenta activa: `{acc.alias}` (@{acc.username})",
        parse_mode="Markdown"
    )

# ─── Video Handler ────────────────────────────────────────────────────────────

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("⛔ No tienes permiso para usar este bot.")
        return

    video = update.message.video or update.message.document
    if not video:
        await update.message.reply_text("⚠️ Por favor envía un archivo de video.")
        return

    if hasattr(video, 'file_size') and video.file_size and video.file_size > 50 * 1024 * 1024:
        await update.message.reply_text("⚠️ El video es demasiado grande. Máximo 50MB via Telegram.")
        return

    accounts = tiktok.list_accounts()
    if not accounts:
        await update.message.reply_text("No hay cuentas conectadas. Usa /addcuenta.")
        return

    caption = update.message.caption or ""
    context.user_data["pending_video_caption"] = caption

    # If only one account or one already selected → upload directly
    if len(accounts) == 1:
        await _do_upload(update, context, accounts[0].alias, caption, video)
        return

    # Ask which account to use
    keyboard = []
    selected = tiktok.selected_account
    for acc in accounts:
        icon = "⭐" if selected and selected.alias == acc.alias else "📱"
        keyboard.append([InlineKeyboardButton(
            f"{icon} {acc.alias} — @{acc.username}",
            callback_data=f"upload_{acc.alias}"
        )])

    # Store file_id to retrieve later
    context.user_data["pending_video_file_id"] = video.file_id
    context.user_data["pending_video_is_doc"] = update.message.document is not None

    await update.message.reply_text(
        "¿A qué cuenta de TikTok quieres subir este video?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def upload_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    alias   = query.data.replace("upload_", "")
    caption = context.user_data.pop("pending_video_caption", "")
    file_id = context.user_data.pop("pending_video_file_id", None)

    if not file_id:
        await query.edit_message_text("❌ No se encontró el video. Envíalo de nuevo.")
        return

    await query.edit_message_text(f"⬇️ Descargando video para `{alias}`...", parse_mode="Markdown")

    tmp_path = None
    try:
        from telegram import Bot
        bot = query.get_bot()
        file = await bot.get_file(file_id)

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp_path = tmp.name
        await file.download_to_drive(tmp_path)

        await query.edit_message_text(f"⬆️ Subiendo a TikTok cuenta `{alias}`...", parse_mode="Markdown")

        result = await tiktok.upload_video(tmp_path, alias=alias, caption=caption)

        acc = tiktok.get_account(alias)
        name = f"@{acc.username}" if acc else alias

        if result["success"]:
            await query.edit_message_text(
                f"✅ ¡Video subido a {name} exitosamente!\n"
                f"🎵 Puede tardar unos minutos en aparecer."
            )
        else:
            await query.edit_message_text(f"❌ Error: {result.get('error', 'Error desconocido')}")

    except Exception as e:
        logger.error(f"Upload error: {e}")
        await query.edit_message_text(f"❌ Error inesperado: {str(e)}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)

async def _do_upload(update, context, alias, caption, video):
    """Direct upload when only one account exists."""
    msg = await update.message.reply_text("⬇️ Descargando video...")
    tmp_path = None
    try:
        file = await video.get_file()
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            tmp_path = tmp.name
        await file.download_to_drive(tmp_path)
        await msg.edit_text("⬆️ Subiendo a TikTok...")

        result = await tiktok.upload_video(tmp_path, alias=alias, caption=caption)
        if result["success"]:
            await msg.edit_text("✅ ¡Video subido exitosamente!\n🎵 Puede tardar unos minutos en aparecer.")
        else:
            await msg.edit_text(f"❌ Error: {result.get('error')}")
    except Exception as e:
        await msg.edit_text(f"❌ Error inesperado: {str(e)}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)

# ─── /help ────────────────────────────────────────────────────────────────────

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🤖 *Ayuda del Bot de TikTok*\n\n"
        "*Gestión de cuentas:*\n"
        "/cuentas – Ver todas las cuentas conectadas\n"
        "/addcuenta – Conectar una nueva cuenta de TikTok\n"
        "/seleccionar – Cambiar cuenta activa\n"
        "/eliminarcuenta – Eliminar una cuenta\n"
        "/status – Ver cuenta activa\n\n"
        "*Subir videos:*\n"
        "Simplemente envía un video. Si tienes varias cuentas, "
        "el bot te preguntará a cuál subirlo.\n\n"
        "*Formatos:* MP4, MOV, AVI\n"
        "*Tamaño máximo:* 50MB"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # ConversationHandler para agregar cuenta
    conv = ConversationHandler(
        entry_points=[CommandHandler("addcuenta", addcuenta_start)],
        states={
            WAITING_ALIAS: [MessageHandler(filters.TEXT & ~filters.COMMAND, addcuenta_alias)],
            WAITING_CODE:  [MessageHandler(filters.TEXT & ~filters.COMMAND, addcuenta_code)],
        },
        fallbacks=[CommandHandler("cancelar", cancelar)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cuentas", cuentas))
    app.add_handler(CommandHandler("seleccionar", seleccionar))
    app.add_handler(CommandHandler("eliminarcuenta", eliminarcuenta))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(seleccionar_callback, pattern="^select_"))
    app.add_handler(CallbackQueryHandler(eliminarcuenta_callback, pattern="^delete_"))
    app.add_handler(CallbackQueryHandler(upload_callback, pattern="^upload_"))
    app.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, handle_video))

    logger.info("🤖 Bot iniciado con soporte multi-cuenta...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
