# 🚀 Guía de Despliegue en la Nube Gratuita (Render.com + UptimeRobot)

Esta guía explica paso a paso cómo dejar **GaBookAutoDownloader** funcionando **24/7 en la nube de forma 100% gratuita**, sin depender de tener el ordenador encendido, y cómo monitorizar cada componente del pipeline.

---

## 🎛️ Centro de Control: Enlaces de Monitorización del Pipeline

Guarda estos enlaces para supervisar y auditar la salud de cada servicio del sistema:

| Servicio | Propósito | Enlace Directo |
| :--- | :--- | :--- |
| **Render Dashboard** | Logs en vivo, despliegues automáticos y métricas del bot | [dashboard.render.com](https://dashboard.render.com) |
| **Endpoint de Salud (Público)** | Test instantáneo HTTP 200 OK del worker | [`https://gabookautodownloader.onrender.com/health`](https://gabookautodownloader.onrender.com/health) |
| **UptimeRobot** | Monitorización de disponibilidad 24/7 y pings keep-alive | [uptimerobot.com/dashboard](https://uptimerobot.com/dashboard) |
| **Upstash Redis Console** | Persistencia serverless, datos de usuarios y perfiles | [console.upstash.com](https://console.upstash.com) |
| **Mailjet Dashboard** | Estadísticas de envíos de emails y entrega a Kindle | [app.mailjet.com/dashboard](https://app.mailjet.com/dashboard) |
| **GitHub Actions (CI/CD)** | Ejecución de la suite de 44 tests unitarios en cada push | [GitHub Actions](https://github.com/gtrujillovdev-cyber/GaBookAutoDownloader/actions) |
| **Amazon Kindle (Ajustes)** | Gestión de remitentes aprobados y correo `@kindle.com` | [Preferencias de Amazon](https://www.amazon.es/hz/mycd/myx#/home/settings/payment) |
| **Bot en Telegram** | Acceso e interacción directa con el bot | [@GaBookAutoDownloaderBot](https://t.me/GaBookAutoDownloaderBot) |

---

## 📋 Resumen de la Arquitectura en la Nube

* **Alojamiento:** [Render.com](https://render.com) (Plan Web Service Free - 750 horas/mes gratis).
* **Endpoint de Salud:** `https://gabookautodownloader.onrender.com/health` (responde `200 OK`).
* **Keep-Alive (24/7):** [UptimeRobot.com](https://uptimerobot.com) (Monitoreo HTTP gratuito cada 5-10 minutos para evitar que el contenedor entre en reposo).
* **Base de Datos Distribuida:** [Upstash Redis](https://upstash.com) (Persistencia serverless de perfiles para superar el sistema de archivos efímero de Render).
* **Entrega a Kindle:** [Mailjet](https://mailjet.com) (API REST transaccional con control de cuotas y guardia < 22 MB).

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
| `MAILJET_API_KEY` | *API Key pública de Mailjet* |
| `MAILJET_SECRET_KEY` | *Secret Key privada de Mailjet* |
| `UPSTASH_REDIS_REST_URL` | *URL REST de tu base de datos Upstash Redis* |
| `UPSTASH_REDIS_REST_TOKEN` | *Token REST de autenticación de Upstash Redis* |
| `KINDLE_EMAIL` | *Correo Kindle principal* |
| `KINDLE_EMAIL_PAPA` | *(Opcional)* Correo Kindle secundario / familiar 1 |
| `KINDLE_EMAIL_GONZALO` | *(Opcional)* Correo Kindle secundario / familiar 2 |
| `KINDLE_EMAIL_GABRIEL` | *(Opcional)* Correo Kindle personal |
| `GROQ_API_KEY` | *(Opcional)* Clave gratuita de Groq para transcribir audios de voz |
| `ALLOWED_USER_IDS` | *(Opcional)* IDs de Telegram autorizados (vacío para acceso libre) |
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
   * **URL (or IP):** `https://gabookautodownloader.onrender.com/health`
   * **Monitoring Interval:** `Every 5 minutes`
4. Guarda el monitor pulsando **"Create Monitor"**.

UptimeRobot enviará una petición a tu bot cada 5 minutos, manteniendo el bot siempre despierto y activo en Telegram las 24 horas del día.

---

## Paso 5: Desactivación permanente de instancias locales

Telegram solo permite una única conexión escuchando `getUpdates` por token. Para evitar el error `Conflict 409`:
* El servicio local de macOS (`launchd`) ha sido retirado permanentemente.
* No ejecutes `python main.py` en local mientras el servicio en Render esté desplegado y activo.

---

## 💡 Notas de Alta Disponibilidad en Producción

* **Persistencia Serverless con Upstash Redis:** A diferencia de un filesystem efímero donde los datos se reinician, los perfiles de los usuarios y su historial se almacenan en la nube de Upstash Redis mediante llamadas REST seguras.
* **Control de Envíos con Mailjet:** Se utiliza la API REST oficial de Mailjet para entrega rápida a los servidores de Amazon Kindle, con límite estricto de 22 MB por archivo.
* **Auto-Aprobación en Amazon:** El monitor IMAP en segundo plano (`gmail_monitor.py`) intercepta correos de verificación de Amazon y aprueba automáticamente la recepción de los documentos.
