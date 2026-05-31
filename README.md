# 🤖 TikTok Telegram Bot

Bot de Telegram que recibe videos y los sube automáticamente a TikTok.

---

## 📋 Requisitos

- Python 3.10+
- Cuenta de Telegram
- Cuenta de TikTok Developer

---

## 🚀 Instalación

### 1. Clona o descarga el proyecto
```bash
git clone <tu-repo>
cd tiktok-telegram-bot
```

### 2. Instala dependencias
```bash
pip install -r requirements.txt
```

### 3. Configura las variables de entorno
```bash
cp .env.example .env
# Edita .env con tus credenciales
```

---

## 🔑 Obtener credenciales

### Telegram Bot Token
1. Abre Telegram y busca **@BotFather**
2. Envía `/newbot` y sigue las instrucciones
3. Copia el token y ponlo en `TELEGRAM_BOT_TOKEN`

### TikTok App
1. Ve a [developers.tiktok.com](https://developers.tiktok.com)
2. Crea una cuenta de desarrollador
3. Crea una nueva app
4. En **Products**, activa **Content Posting API**
5. En **Scopes**, agrega:
   - `user.info.basic`
   - `video.publish`
   - `video.upload`
6. En **Redirect URI**, pon: `https://localhost/callback`
7. Copia **Client Key** y **Client Secret** a tu `.env`

---

## ▶️ Uso

### Iniciar el bot
```bash
python bot.py
```

### Autenticar con TikTok
1. En Telegram, envía `/auth` al bot
2. Haz clic en el botón para ir a TikTok
3. Autoriza la app
4. En la URL de redirección, copia el valor del parámetro `code`
   - La URL se ve así: `https://localhost/callback?code=XXXXXXXX&state=...`
5. Envía al bot: `/code XXXXXXXX`

### Subir un video
- Simplemente envía cualquier video al bot
- Opcionalmente agrega un caption (descripción) al enviarlo

---

## ⚙️ Configuración adicional

### Privacidad del video
En `tiktok.py`, busca `privacy_level` y cámbialo según necesites:
- `"SELF_ONLY"` – Solo tú (recomendado para pruebas)
- `"FOLLOWER_OF_CREATOR"` – Solo seguidores
- `"MUTUAL_FOLLOW_FRIENDS"` – Amigos mutuos
- `"PUBLIC_TO_EVERYONE"` – Público

### Restringir usuarios
En `.env`, agrega tu ID de Telegram en `ALLOWED_USER_IDS`.
(Consigue tu ID hablando con @userinfobot en Telegram)

---

## 🌐 Deploy en Railway / Render

1. Sube el proyecto a GitHub
2. Conecta tu repo en [railway.app](https://railway.app) o [render.com](https://render.com)
3. Agrega las variables de entorno en el panel
4. El comando de inicio es: `python bot.py`

---

## 📁 Estructura del proyecto

```
tiktok-telegram-bot/
├── bot.py          # Lógica principal del bot de Telegram
├── tiktok.py       # Módulo de autenticación y upload a TikTok
├── requirements.txt
├── .env.example    # Plantilla de variables de entorno
└── README.md
```

---

## ⚠️ Notas importantes

- La API de TikTok requiere que tu app sea **aprobada** para publicación pública
- Durante el desarrollo, solo el dueño de la app puede usarla
- Los videos pueden tardar unos minutos en aparecer en TikTok
- Tamaño máximo por limitación de Telegram Bot API: **50MB**
