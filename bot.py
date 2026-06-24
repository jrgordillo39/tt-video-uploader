import os
import asyncio
import logging
import tempfile
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import Conflict
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

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_BOT_TOKEN")
ALLOWED_USER_IDS = list(map(int, os.getenv("ALLOWED_USER_IDS", "").split(","))) if os.getenv("ALLOWED_USER_IDS") else []

tiktok = TikTokUploader()

# ConversationHandler states
WAITING_ALIAS   = 1
WAITING_CODE    = 2
WAITING_CAPTION = 3

# Delay en segundos para agrupar videos del mismo álbum
ALBUM_COLLECT_DELAY = 2.5

# ─── Auth ──────────────────────────────────────────────────────────────────────

def is_authorized(user_id: int) -> bool:
    if not ALLOWED_USER_IDS:
        return True
    return user_id in ALLOWED_USER_IDS

# ─── /start ────────────────────────────────────────────────────────────────────

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("⛔ No tienes permiso para usar este bot.")
        return

    text = (
        "👋 *Bot de TikTok* listo!\n\n"
        "📤 Envíame uno o varios videos (como álbum) y los subiré a TikTok.\n"
        "Todos los videos del mismo envío usarán el mismo caption.\n\n"
        "Comandos:\n"
        "/cuentas – Ver cuentas conectadas\n"
        "/addcuenta – Conectar nueva cuenta de TikTok\n"
        "/eliminarcuenta – Eliminar una cuenta\n"
        "/seleccionar – Cambiar cuenta activa\n"
        "/status – Estado de la cuenta activa\n"
        "/help – Ayuda"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

# ─── /cuentas ──────────────────────────────────────────────────────────────────

async def cuentas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return

    accounts = tiktok.list_accounts()
    selected = tiktok.selected_account

    if not accounts:
        await update.message.reply_text("No hay cuentas conectadas.\nUsa /addcuenta para agregar una.")
        return

    lines = ["📋 *Cuentas de TikTok conectadas:*\n"]
    for acc in accounts:
        status_icon = "✅" if acc.is_authenticated() else "⚠️"
        active_mark = " ← *activa*" if selected and selected.alias == acc.alias else ""
        lines.append(f"{status_icon} `{acc.alias}` — @{acc.username}{active_mark}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

# ─── /addcuenta ────────────────────────────────────────────────────────────────

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

# ─── /seleccionar ──────────────────────────────────────────────────────────────

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

    await update.message.reply_text("¿A qué cuenta quieres cambiar?", reply_markup=InlineKeyboardMarkup(keyboard))

async def seleccionar_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    alias = query.data.replace("select_", "")
    if tiktok.select_account(alias):
        acc = tiktok.get_account(alias)
        await query.edit_message_text(f"✅ Cuenta activa: `{alias}` (@{acc.username})", parse_mode="Markdown")
    else:
        await query.edit_message_text("❌ Cuenta no encontrada.")

# ─── /eliminarcuenta ───────────────────────────────────────────────────────────

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

    await update.message.reply_text("¿Qué cuenta quieres eliminar?", reply_markup=InlineKeyboardMarkup(keyboard))

async def eliminarcuenta_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    alias = query.data.replace("delete_", "")
    if tiktok.remove_account(alias):
        await query.edit_message_text(f"🗑 Cuenta `{alias}` eliminada.", parse_mode="Markdown")
    else:
        await query.edit_message_text("❌ Cuenta no encontrada.")

# ─── /status ───────────────────────────────────────────────────────────────────

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        return

    acc = tiktok.selected_account
    if not acc:
        accounts = tiktok.list_accounts()
        if not accounts:
            await update.message.reply_text("No hay cuentas. Usa /addcuenta.")
        else:
            await update.message.reply_text("No hay cuenta activa. Usa /seleccionar para elegir una.")
        return

    icon = "✅" if acc.is_authenticated() else "⚠️ Token expirado"
    await update.message.reply_text(
        f"{icon} Cuenta activa: `{acc.alias}` (@{acc.username})",
        parse_mode="Markdown"
    )

# ─── /caption ──────────────────────────────────────────────────────────────────

async def set_caption_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start conversation to set a saved caption for upcoming videos."""
    if not is_authorized(update.effective_user.id):
        return

    # If caption passed inline: /caption Mi texto aquí
    if context.args:
        caption = " ".join(context.args)
        context.user_data["saved_caption"] = caption
        await update.message.reply_text(
            f"✅ Caption guardado:\n_{caption}_\n\n"
            "Ahora reenvía los videos y se aplicará automáticamente.\n"
            "Usa /clearcaption para borrarlo.",
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    # Otherwise ask for it
    current = context.user_data.get("saved_caption")
    current_text = f"\n\nCaption actual: _{current}_" if current else ""
    await update.message.reply_text(
        f"Escribe el caption que quieres aplicar a los próximos videos:{current_text}\n\n"
        "_(Escribe /cancelar para salir)_",
        parse_mode="Markdown"
    )
    return WAITING_CAPTION

async def set_caption_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caption = update.message.text.strip()
    if not caption:
        await update.message.reply_text("⚠️ El caption no puede estar vacío.")
        return WAITING_CAPTION

    context.user_data["saved_caption"] = caption
    await update.message.reply_text(
        f"✅ Caption guardado:\n_{caption}_\n\n"
        "Ahora reenvía los videos y se aplicará automáticamente.\n"
        "Usa /clearcaption para borrarlo.",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def clear_caption(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Clear the saved caption."""
    if not is_authorized(update.effective_user.id):
        return
    context.user_data.pop("saved_caption", None)
    await update.message.reply_text("🗑 Caption borrado. Los próximos videos se subirán sin descripción.")

async def show_caption(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show the currently saved caption."""
    if not is_authorized(update.effective_user.id):
        return
    caption = context.user_data.get("saved_caption")
    if caption:
        await update.message.reply_text(
            f"📝 Caption activo:\n_{caption}_\n\nUsa /clearcaption para borrarlo.",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            "No hay caption guardado.\nUsa /caption para establecer uno."
        )

# ─── Video Handler (con soporte para álbumes) ──────────────────────────────────

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_authorized(update.effective_user.id):
        await update.message.reply_text("⛔ No tienes permiso para usar este bot.")
        return

    video = update.message.video or update.message.document
    if not video:
        return

    if hasattr(video, 'file_size') and video.file_size and video.file_size > 50 * 1024 * 1024:
        await update.message.reply_text("⚠️ Video demasiado grande. Máximo 50MB via Telegram.")
        return

    accounts = tiktok.list_accounts()
    if not accounts:
        await update.message.reply_text("No hay cuentas conectadas. Usa /addcuenta.")
        return

    # ── Resolver caption: mensaje > álbum en curso > /caption guardado ──
    media_group_id = update.message.media_group_id
    caption = (
        update.message.caption                          # caption del mensaje
        or context.user_data.get("album_caption", "")  # álbum en curso
        or context.user_data.get("saved_caption", "")  # guardado con /caption
    )

    if media_group_id:
        # Inicializar buffer del álbum
        if "album_videos" not in context.user_data:
            context.user_data["album_videos"]  = []
            context.user_data["album_caption"] = caption

        context.user_data["album_videos"].append(video.file_id)

        # Cancelar timer anterior si existe
        if "album_task" in context.user_data:
            context.user_data["album_task"].cancel()

        # Programar procesamiento tras el delay (espera a que lleguen todos los videos)
        loop = asyncio.get_event_loop()
        task = loop.create_task(
            _delayed_album_process(update, context, ALBUM_COLLECT_DELAY)
        )
        context.user_data["album_task"] = task

    else:
        # Video único — procesar inmediatamente
        await _ask_account_and_upload(update, context, [video.file_id], caption)


async def _delayed_album_process(update: Update, context: ContextTypes.DEFAULT_TYPE, delay: float):
    """Wait for all album messages to arrive, then ask which account to use."""
    await asyncio.sleep(delay)

    file_ids = context.user_data.pop("album_videos", [])
    caption  = context.user_data.pop("album_caption", "")
    context.user_data.pop("album_task", None)

    if file_ids:
        await _ask_account_and_upload(update, context, file_ids, caption)


async def _ask_account_and_upload_single(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show options menu for single-account flow using a plain message."""
    opts     = context.user_data.get("upload_opts", {})
    alias    = context.user_data.get("pending_alias", "")
    file_ids = context.user_data.get("pending_file_ids", [])
    count    = len(file_ids)

    def toggle(key):
        return "✅" if opts.get(key) else "☐"

    keyboard = [
        [InlineKeyboardButton(f"{toggle('disable_comment')} Desactivar comentarios",  callback_data="opt_disable_comment")],
        [InlineKeyboardButton(f"{toggle('disable_duet')}    Desactivar duetos",        callback_data="opt_disable_duet")],
        [InlineKeyboardButton(f"{toggle('disable_stitch')}  Desactivar stitch",        callback_data="opt_disable_stitch")],
        [InlineKeyboardButton(f"{toggle('brand_content')}   Contenido de marca (ads)", callback_data="opt_brand_content")],
        [InlineKeyboardButton(f"{toggle('brand_organic')}   Promoción propia (ads)",   callback_data="opt_brand_organic")],
        [InlineKeyboardButton(f"⬆️ Subir {count} video{'s' if count > 1 else ''} a {alias}", callback_data="opt_confirm")],
    ]
    await update.message.reply_text(
        f"⚙️ *Opciones para `{alias}`* ({count} video{'s' if count > 1 else ''}):\n\n"
        "Activa lo que necesites y luego pulsa *Subir*.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def _ask_account_and_upload(update: Update, context: ContextTypes.DEFAULT_TYPE, file_ids: list, caption: str):
    """Show account selector or upload directly if only one account."""
    accounts = tiktok.list_accounts()

    count_text = f"{len(file_ids)} video{'s' if len(file_ids) > 1 else ''}"

    if len(accounts) == 1:
        # Solo una cuenta → mostrar opciones directamente
        context.user_data["pending_file_ids"] = file_ids
        context.user_data["pending_caption"]  = caption
        context.user_data["pending_alias"]    = accounts[0].alias
        context.user_data["upload_opts"]      = {}
        msg = await update.message.reply_text(
            f"📦 {count_text} recibido{'s' if len(file_ids) > 1 else ''}.",
        )
        # Simulate a query-like object to reuse _show_options_menu
        await _ask_account_and_upload_single(update, context)
        return

    # Guardar datos pendientes
    context.user_data["pending_file_ids"] = file_ids
    context.user_data["pending_caption"]  = caption

    selected = tiktok.selected_account
    keyboard = []
    for acc in accounts:
        icon = "⭐" if selected and selected.alias == acc.alias else "📱"
        keyboard.append([InlineKeyboardButton(
            f"{icon} {acc.alias} — @{acc.username}",
            callback_data=f"upload_{acc.alias}"
        )])

    await update.message.reply_text(
        f"📦 {count_text} recibido{'s' if len(file_ids) > 1 else ''}. ¿A qué cuenta de TikTok quieres subirlo{'s' if len(file_ids) > 1 else ''}?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def upload_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """User selected an account — now show video options menu."""
    query = update.callback_query
    await query.answer()

    alias    = query.data.replace("upload_", "")
    file_ids = context.user_data.get("pending_file_ids", [])

    if not file_ids:
        await query.edit_message_text("❌ No se encontraron los videos. Envíalos de nuevo.")
        return

    # Store selected alias and show options menu
    context.user_data["pending_alias"] = alias
    await _show_options_menu(query, context)


async def _show_options_menu(query, context):
    """Show toggle options before uploading."""
    opts     = context.user_data.get("upload_opts", {})
    alias    = context.user_data.get("pending_alias", "")
    file_ids = context.user_data.get("pending_file_ids", [])
    count    = len(file_ids)

    def toggle(key):
        return "✅" if opts.get(key) else "☐"

    keyboard = [
        [InlineKeyboardButton(f"{toggle('disable_comment')} Desactivar comentarios",  callback_data="opt_disable_comment")],
        [InlineKeyboardButton(f"{toggle('disable_duet')}    Desactivar duetos",        callback_data="opt_disable_duet")],
        [InlineKeyboardButton(f"{toggle('disable_stitch')}  Desactivar stitch",        callback_data="opt_disable_stitch")],
        [InlineKeyboardButton(f"{toggle('brand_content')}   Contenido de marca (ads)",  callback_data="opt_brand_content")],
        [InlineKeyboardButton(f"{toggle('brand_organic')}   Promoción propia (ads)",    callback_data="opt_brand_organic")],
        [InlineKeyboardButton(f"⬆️ Subir {count} video{'s' if count > 1 else ''} a {alias}", callback_data="opt_confirm")],
    ]
    plural = 's' if count > 1 else ''
    await query.edit_message_text(
        f"⚙️ *Opciones para `{alias}`* ({count} video{plural}):\n\nActiva lo que necesites y luego pulsa *Subir*.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def options_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle option toggles and confirm button."""
    query = update.callback_query
    await query.answer()

    action = query.data.replace("opt_", "")

    if action == "confirm":
        alias    = context.user_data.pop("pending_alias", "")
        file_ids = context.user_data.pop("pending_file_ids", [])
        caption  = context.user_data.pop("pending_caption", "")
        opts     = context.user_data.pop("upload_opts", {})

        if not file_ids:
            await query.edit_message_text("❌ No se encontraron los videos.")
            return

        await query.edit_message_text(
            f"⏳ Preparando {len(file_ids)} video{'s' if len(file_ids) > 1 else ''} para `{alias}`...",
            parse_mode="Markdown"
        )
        await _do_upload_batch(update, context, alias, file_ids, caption, opts=opts, status_msg=query.message)

    else:
        # Toggle the option
        opts = context.user_data.get("upload_opts", {})
        opts[action] = not opts.get(action, False)
        context.user_data["upload_opts"] = opts
        await _show_options_menu(query, context)


async def _do_upload_batch(update, context, alias: str, file_ids: list, caption: str, opts: dict = None, status_msg=None):
    """Download and upload all videos in the batch sequentially."""
    bot      = update.get_bot()
    total    = len(file_ids)
    acc      = tiktok.get_account(alias)
    acc_name = f"@{acc.username}" if acc else alias
    results  = []
    opts     = opts or {}

    async def send(text):
        if status_msg:
            await status_msg.edit_text(text, parse_mode="Markdown")
        else:
            await update.message.reply_text(text, parse_mode="Markdown")

    await send(f"⬇️ Descargando {total} video{'s' if total > 1 else ''} para `{alias}`...")

    for i, file_id in enumerate(file_ids, 1):
        tmp_path = None
        try:
            await send(f"⬆️ Subiendo video {i}/{total} a `{alias}`...")

            file = await bot.get_file(file_id)
            with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
                tmp_path = tmp.name
            await file.download_to_drive(tmp_path)

            result = await tiktok.upload_video(tmp_path, alias=alias, caption=caption, options=opts)
            results.append(result)

        except Exception as e:
            logger.error(f"Error uploading video {i}: {e}")
            results.append({"success": False, "error": str(e)})
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    # ── Resumen final ──
    ok     = sum(1 for r in results if r.get("success"))
    failed = total - ok

    # Collect video_ids for ads
    video_ids = [r.get("video_id") for r in results if r.get("success") and r.get("video_id")]

    if failed == 0:
        msg = (
            f"✅ {ok}/{total} video{'s' if ok > 1 else ''} subido{'s' if ok > 1 else ''} "
            f"a {acc_name} exitosamente!\n"
            f"🎵 Puede tardar unos minutos en aparecer."
        )
        if opts.get("brand_content") or opts.get("brand_organic"):
            if video_ids:
                ids_text = "\n".join(f"  • `{vid}`" for vid in video_ids)
                msg += f"\n\n📢 *IDs para publicidad en TikTok Ads Manager:*\n{ids_text}"
            else:
                msg += "\n\n📢 El video fue marcado para publicidad. El ID estará disponible en tu perfil de TikTok en unos minutos."
    elif ok == 0:
        errors = "\n".join(f"• Video {i+1}: {r.get('error')}" for i, r in enumerate(results))
        msg = f"❌ Todos los videos fallaron:\n{errors}"
    else:
        errors = "\n".join(
            f"• Video {i+1}: {r.get('error')}"
            for i, r in enumerate(results) if not r.get("success")
        )
        msg = (
            f"⚠️ {ok}/{total} videos subidos a {acc_name}.\n"
            f"Fallaron:\n{errors}"
        )

    await send(msg)

# ─── /help ─────────────────────────────────────────────────────────────────────

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
        "• Envía un video solo → se sube directamente\n"
        "• Envía varios videos a la vez (álbum) → se suben todos con el mismo caption\n"
        "• Reenvía videos de otro chat → usa /caption antes para aplicar descripción\n"
        "• Si tienes varias cuentas, el bot te pregunta a cuál subirlos\n\n"
        "*Caption para videos reenviados:*\n"
        "/caption TEXTO – Guardar caption para próximos videos\n"
        "/mycaption – Ver caption activo\n"
        "/clearcaption – Borrar caption guardado\n\n"
        "*Formatos:* MP4, MOV, AVI\n"
        "*Tamaño máximo:* 50MB por video"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    """Handle unexpected exceptions from handlers and polling loop."""
    err = context.error
    if isinstance(err, Conflict):
        logger.error(
            "Conflicto de getUpdates: hay otra instancia usando el mismo bot token. "
            "Esta instancia se detendra para evitar bucles de error."
        )
        context.application.stop_running()
        return

    logger.exception("Error no controlado en el bot", exc_info=err)

# ─── Main ──────────────────────────────────────────────────────────────────────

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    conv_cuenta = ConversationHandler(
        entry_points=[CommandHandler("addcuenta", addcuenta_start)],
        states={
            WAITING_ALIAS: [MessageHandler(filters.TEXT & ~filters.COMMAND, addcuenta_alias)],
            WAITING_CODE:  [MessageHandler(filters.TEXT & ~filters.COMMAND, addcuenta_code)],
        },
        fallbacks=[CommandHandler("cancelar", cancelar)],
    )

    conv_caption = ConversationHandler(
        entry_points=[CommandHandler("caption", set_caption_start)],
        states={
            WAITING_CAPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_caption_receive)],
        },
        fallbacks=[CommandHandler("cancelar", cancelar)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("cuentas", cuentas))
    app.add_handler(CommandHandler("seleccionar", seleccionar))
    app.add_handler(CommandHandler("eliminarcuenta", eliminarcuenta))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("mycaption", show_caption))
    app.add_handler(CommandHandler("clearcaption", clear_caption))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(conv_cuenta)
    app.add_handler(conv_caption)
    app.add_handler(CallbackQueryHandler(seleccionar_callback, pattern="^select_"))
    app.add_handler(CallbackQueryHandler(eliminarcuenta_callback, pattern="^delete_"))
    app.add_handler(CallbackQueryHandler(upload_callback, pattern="^upload_"))
    app.add_handler(CallbackQueryHandler(options_callback, pattern="^opt_"))
    app.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, handle_video))
    app.add_error_handler(global_error_handler)

    logger.info("🤖 Bot iniciado con soporte multi-cuenta y multi-video...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
