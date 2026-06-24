# 🚀 Guía de migración: Sandbox → Producción

## 1. TikTok Developers — Aprobar la app

1. Ve a https://developers.tiktok.com → tu app
2. Asegúrate de que estos campos estén completos:
   - Nombre de la app
   - Icono de la app
   - Descripción
   - URL de Política de Privacidad → https://TU-USUARIO.github.io/TU-REPO/privacy.html
   - URL de Términos de Servicio  → https://TU-USUARIO.github.io/TU-REPO/terms.html
3. En "Products → Content Posting API → Scopes", confirma que tienes activos:
   - user.info.basic
   - video.publish
   - video.upload
4. Haz clic en "Submit for review" o "Request production access"
5. Espera aprobación (3–10 días laborables)


## 2. Código — tiktok.py

### 2a. Cambiar privacidad por defecto de los videos
Busca esta línea en el método upload_video():

    "privacy_level": "SELF_ONLY",

Cámbiala por:

    "privacy_level": "PUBLIC_TO_EVERYONE",

O si prefieres que el usuario elija desde el bot (recomendado), déjalo
como está y sigue el paso 3 más abajo.

### 2b. Leer redirect_uri dinámicamente (evita caché)
Busca en __init__():

    self.redirect_uri = os.getenv("TIKTOK_REDIRECT_URI", "https://localhost/callback")

Reemplaza esa línea por una property. Añade esto justo después de __init__():

    @property
    def redirect_uri(self):
        return os.getenv("TIKTOK_REDIRECT_URI", "https://localhost/callback")

Y elimina la línea self.redirect_uri del __init__().


## 3. Código — bot.py (opcional pero recomendado)

### 3a. Agregar privacidad como opción en el menú
En la función _show_options_menu() y _ask_account_and_upload_single(),
añade estos botones al keyboard justo antes del botón de confirmar:

    [InlineKeyboardButton(f"{toggle('privacy_public')} Publicar como público",   callback_data="opt_privacy_public")],
    [InlineKeyboardButton(f"{toggle('privacy_private')} Publicar como privado",  callback_data="opt_privacy_private")],

En la función options_callback(), dentro del bloque else (donde se
hacen los toggles), añade esta lógica para que sean mutuamente
exclusivos:

    elif action == "privacy_public":
        opts["privacy_public"]  = not opts.get("privacy_public", False)
        opts["privacy_private"] = False
    elif action == "privacy_private":
        opts["privacy_private"] = not opts.get("privacy_private", False)
        opts["privacy_public"]  = False
    else:
        opts[action] = not opts.get(action, False)

En la función _do_upload_batch(), cuando se llama a tiktok.upload_video(),
la resolución de privacy_level queda así:

    if opts.get("privacy_public"):
        privacy = "PUBLIC_TO_EVERYONE"
    elif opts.get("privacy_private"):
        privacy = "SELF_ONLY"
    else:
        privacy = "PUBLIC_TO_EVERYONE"   # por defecto en producción

    result = await tiktok.upload_video(
        tmp_path,
        alias=alias,
        caption=caption,
        options={**opts, "privacy_level": privacy}
    )


## 4. Variables de entorno en Railway

Actualiza o confirma estos valores en Railway → Variables:

    TIKTOK_REDIRECT_URI = https://TU-APP.railway.app/callback

    # Opcional: restringe el bot a tu usuario de Telegram
    ALLOWED_USER_IDS = TU_ID_DE_TELEGRAM


## 5. TikTok Developers — Tras la aprobación

1. Ve a tu app → comprueba que el estado sea "Live" o "Approved"
2. Actualiza la Redirect URI si cambió:
   App → Edit → Redirect URI → https://TU-APP.railway.app/callback
3. Revoca los tokens actuales del bot usando /eliminarcuenta
   y vuelve a autenticarte con /addcuenta para obtener tokens
   de producción (los tokens de Sandbox no son válidos en producción)


## 6. Prueba final

Tras completar todo, verifica este flujo completo:

  [ ] /addcuenta → autenticación OAuth funciona
  [ ] Enviar un video → aparece el menú de opciones
  [ ] El video se sube y aparece como PÚBLICO en TikTok
  [ ] El resumen final muestra ✅ sin errores
  [ ] Si activaste branded content → el bot devuelve el video ID


## Resumen de archivos modificados

  tiktok.py  →  redirect_uri como property + privacy_level por defecto
  bot.py     →  opciones de privacidad en el menú (opcional)
