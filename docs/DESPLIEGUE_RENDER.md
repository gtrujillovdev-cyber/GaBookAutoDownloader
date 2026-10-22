# 🚀 Guía de Despliegue en la Nube Gratuita (Render.com + UptimeRobot)

Esta guía explica paso a paso cómo dejar **GaBookAutoDownloader** funcionando **24/7 en la nube de forma 100% gratuita**, sin depender de tener el MacBook encendido.

---

## 📋 Resumen de la Arquitectura en la Nube

* **Alojamiento:** [Render.com](https://render.com) (Plan Web Service Free - 750 horas/mes gratis).
* **Endpoint de Salud:** `https://tu-servicio.onrender.com/health` (responde `200 OK`).
* **Keep-Alive (24/7):** [UptimeRobot.com](https://uptimerobot.com) (Monitoreo HTTP gratuito cada 10 minutos para evitar que el contenedor entre en reposo).

---

## Paso 1: Subir tus cambios a GitHub

Asegúrate de que tu rama `main` en GitHub tiene los últimos cambios:
```bash
git push origin main
```

---

## Paso 2: Crear el servicio en Render.com

1. Inicia sesión o regístrate gratis en **[dashboard.render.com](https://dashboard.render.com)** (puedes entrar directamente con tu cuenta de GitHub).
2. Haz clic en el botón azul **"New +"** (arriba a la derecha) y selecciona **"Web Service"**.
3. Selecciona la opción **"Build and deploy from a Git repository"** y pulsa **Next**.
4. Conecta tu repositorio `GaBookAutoDownloader`.
5. Configura los siguientes campos:
   * **Name:** `gabook-auto-downloader` (o el nombre que prefieras).
   * **Region:** Frankfurt (EU Central) o la más cercana a ti.
   * **Branch:** `main`
   * **Runtime:** `Python 3`
   * **Build Command:** `pip install -r requirements.txt`
   * **Start Command:** `python main.py`
   * **Instance Type:** `Free` (0 $/mes)
6. Despliega la sección **"Advanced"**:
   * **Health Check Path:** `/health`
   * **Auto-Deploy:** `Yes`

---

## Paso 3: Configurar las Variables de Entorno en Render

En la misma pantalla (o en la pestaña **Environment** de tu servicio en Render), añade las siguientes variables copiando los valores de tu archivo local `.env`:

| Key (Nombre) | Value (Valor) |
| :--- | :--- |
| `TELEGRAM_BOT_TOKEN` | *Tu token de BotFather* |
| `GMAIL_USER` | *Tu correo de Gmail* |
| `GMAIL_APP_PASSWORD` | *Tu contraseña de aplicación de 16 letras* |
| `KINDLE_EMAIL` | *Correo Kindle principal* |
| `KINDLE_EMAIL_PAPA` | *Correo Kindle de Papá* |
| `KINDLE_EMAIL_GONZALO` | *Correo Kindle de Gonzalo* |
| `KINDLE_EMAIL_GABRIEL` | *Tu correo Kindle personal* |
| `GROQ_API_KEY` | *(Opcional)* Clave gratuita de Groq para transcribir audios de voz |
| `PYTHONUNBUFFERED` | `1` |

> ⚠️ **Importante:** Render asigna automáticamente la variable `PORT`. El bot detectará este puerto y levantará el servidor de salud HTTP en segundo plano.

Haz clic en **"Deploy Web Service"**. Render compilará e iniciará el bot en unos 60 segundos.

---

## Paso 4: Configurar UptimeRobot para mantenerlo activo 24/7

En el plan gratuito de Render, los servicios web se suspenden tras 15 minutos sin peticiones web. Para evitarlo:

1. Regístrate gratis en **[uptimerobot.com](https://uptimerobot.com)**.
2. Haz clic en **"+ Add New Monitor"**.
3. Configura:
   * **Monitor Type:** `HTTP(s)`
   * **Friendly Name:** `GaBook Keep-Alive`
   * **URL (or IP):** La URL pública que te dio Render (ej. `https://gabook-auto-downloader.onrender.com/health`)
   * **Monitoring Interval:** `Every 10 minutes` (o cada 5 minutos)
4. Guarda el monitor pulsando **"Create Monitor"**.

UptimeRobot enviará una petición a tu bot cada 10 minutos, manteniendo el bot siempre despierto y activo en Telegram las 24 horas del día.

---

## Paso 5: Detener el servicio local en el MacBook Pro

Para evitar conflictos de doble conexión (`Conflict: terminated by other getUpdates request`), desactiva el servicio local de tu Mac una vez que Render esté funcionando:

```bash
launchctl unload ~/Library/LaunchAgents/com.gabookautodownloader.plist
```

*(Si algún día quieres volver a correrlo en tu Mac, solo ejecutas `launchctl load ~/Library/LaunchAgents/com.gabookautodownloader.plist`).*
