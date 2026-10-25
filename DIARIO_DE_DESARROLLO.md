# Diario de Desarrollo — GaBookAutoDownloader

Bot de Telegram familiar para descarga de libros EPUB y envío a Kindle.
Producción: Render.com (Web Service free) — `https://gabookautodownloader.onrender.com`

---

## Sección 1 — Fundación del proyecto
**Fecha estimada:** 2026-09 / 2026-10

- Creación del bot Telegram con flujo "Zero Comandos": teclado táctil persistente, sin slash commands.
- Pipeline: Búsqueda multi-fuente (Libgen, Archive.org, OpenLibrary, Gutenberg, Standard Ebooks, ManyBooks, Anna's Archive, Z-Library) → portada OpenLibrary → ficha técnica → descarga EPUB → envío SMTP Gmail → verificación IMAP Amazon.
- Estructura `src/gabook/` con layout estándar de paquete Python.
- Perfiles familiares (Papá, Gonzalo, Mi Kindle) configurados via `.env`, nunca en el repo.
- Despliegue en Render.com: `render.yaml`, health server HTTP en `$PORT`, keep-alive UptimeRobot cada 5 min.
- Persistencia de usuarios: Upstash Redis cuando disponible; fallback a JSON local atómico.
- Suite de tests unitarios herméticos (43 tests).

---

## Sección 2 — Migración SMTP → Mailjet REST API + barra de progreso real
**Fecha:** 2026-10-23

### Contexto
Render free tier bloquea puertos SMTP salientes (465, 587). Los intentos de envío via `smtplib.SMTP_SSL` fallaban silenciosamente en producción.

### Cambios implementados

#### `src/gabook/services/kindle_mailer.py` — Reescritura completa
- Eliminado `smtplib` / `GMAIL_APP_PASSWORD`.
- Implementado cliente Mailjet REST API v3.1 (`https://api.mailjet.com/v3.1/send`) via `requests.post` con Basic Auth (API Key + Secret Key).
- Adjunto EPUB codificado en base64 en el payload JSON.
- Guardia de tamaño dual: 22 MB (límite general) + 10 MB adicional (límite Mailjet antes de overhead base64 ~33% → payload máx. 15 MB).
- Log del body de respuesta HTTP para diagnóstico de errores 4xx/5xx.

#### `src/gabook/services/book_client.py` — Mejoras de fiabilidad
- Añadido `_DOWNLOAD_HEADERS` con `Accept: application/epub+zip` — evita que Standard Ebooks devuelva HTML (8786 bytes) en lugar del EPUB.
- `_stream_to_file` acepta `progress_cb(done, total_bytes)` — callback de progreso real basado en bytes streamed.
- `download_epub` acepta y propaga `progress_cb`.
- `_libgen_download_candidates` prueba `library.lol/main/{md5}` como primer mirror (más fiable que los mirrors directos).

#### `src/gabook/bot.py` — Barra de progreso real
- Añadido `import functools`.
- Sustituido `_animate_download` (animación falsa con timer) por `_track_download_progress` (progreso real basado en bytes del queue).
- Bridge thread→async: `asyncio.Queue` + `loop.call_soon_threadsafe` para pasar datos de progreso desde el hilo de descarga (ejecutor blocking) al bucle asyncio de Telegram.
- `functools.partial(download_epub, progress_cb=_progress_cb)` para pasar el callback al ejecutor.
- La barra avanza de 0% a 99% durante la descarga y salta a 100% al completar — nunca vuelve a 0%.
- Guardia 10 MB pre-envío con mensaje amigable al usuario si el libro es demasiado grande.

#### `tests/test_features.py` — Actualización de mocks
- Tests de `kindle_mailer` migrados de `smtplib.SMTP_SSL` a `requests.post` mock.
- `fake_stream` en `test_download_falls_back_to_archive_metadata` actualizado con `progress_cb=None`.

#### `.env.example` — Actualización
- Añadidas entradas `MAILJET_API_KEY` y `MAILJET_SECRET_KEY`.

### Bug crítico resuelto: Mailjet 401 persistente
**Causa raíz:** API Key introducida incompleta en las variables de entorno (faltaba el primer carácter al copiarla del dashboard, 31 caracteres en lugar de 32).
**Solución:** Copiar la API Key completa (32 caracteres) y regenerar la Secret Key asociada.

Proceso de diagnóstico:
1. Logs Render mostraban `HTTP 401 Unauthorized` en cada intento de envío.
2. Test local con `python3` reproduciendo la llamada con las credenciales copiadas → 401.
3. Reset preventivo de Secret Key en el panel de Mailjet (`https://app.mailjet.com/account/apikeys`).
4. Generación de nueva Secret Key limpia.
5. Comparación visual de longitud de la API Key en el panel → detectado 1 carácter faltante al inicio.
6. Test local con la API Key completa de 32 caracteres + nueva Secret Key → `200 OK {"Messages":[{"Status":"success"}]}`.
7. Actualización de ambas env vars en Render Dashboard (`MAILJET_API_KEY`, `MAILJET_SECRET_KEY`) → redeploy → **Deploy succeeded (47s)**.

### Estado final
- 43/43 tests pasando.
- Bot live en producción con envío Mailjet funcional verificado end-to-end desde Telegram.
- Barra de progreso real refleja bytes descargados.
- Descarga fiable para Standard Ebooks (Accept headers) y Libgen (library.lol mirror).
