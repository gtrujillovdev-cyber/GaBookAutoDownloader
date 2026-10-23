@AGENTS.md

# Instrucciones específicas para Claude Code

## Contexto de infraestructura
- **Plataforma de producción:** Render.com (Web Service, plan free) — `https://gabookautodownloader.onrender.com`
- **Keep-alive:** UptimeRobot pingea `/health` cada 5 min para evitar que Render suspenda el servicio
- **REGLA CRÍTICA:** El daemon local de macOS (`launchd`) debe estar **APAGADO** mientras Render esté activo. Dos instancias simultáneas causan `telegram.error.Conflict 409`.

## Herramientas y flujo de trabajo

### Exploración del código
- El proyecto tiene `.codegraph/` indexado. Usar `codegraph_explore` ANTES de grep/Read.

### Flujo obligatorio ante cualquier cambio
```bash
# 1. Tests — deben pasar al 100%
python -m unittest discover -s tests

# 2. Limpieza pre-commit
find . -name "*.pyc" -delete && find . -name "__pycache__" -type d -prune -exec rm -rf {} + \
  && find . -name ".DS_Store" -delete && find . -name "*.log" -delete

# 3. Auditoría de seguridad (verificar que .env y users.json NO aparecen)
git status && git diff --cached

# 4. Commit con autoría anónima
git commit -m "tipo: descripción"

# 5. Push (Render auto-deploya)
git push origin main

# 6. Verificar salud en producción
curl https://gabookautodownloader.onrender.com/health
```

## Diagnóstico rápido del error Conflict 409
Si aparece `telegram.error.Conflict: terminated by other getUpdates`:
```bash
# En el Mac local — verificar si el daemon está corriendo
launchctl list | grep gabook
# Si aparece: pararlo
launchctl unload ~/Library/LaunchAgents/com.gabook.bot.plist 2>/dev/null
pkill -f "main.py"
```

## Convenciones de commits (Conventional Commits + autoría anónima)
```bash
git commit -m "fix: descripción del fix" \
  --author="gtrujillovdev-cyber <gtrujillovdev-cyber@users.noreply.github.com>"
```

## Reglas de seguridad estrictas
- **NUNCA** incluir en el repo: `.env`, `users.json`, correos reales, IDs de Telegram reales
- Mantener al día `.env.example` y `users.example.json` con datos ficticios
- `downloads/` y `*.log` en `.gitignore` siempre

## Estructura de paquete (`src/gabook/`)
- `bot.py` — handlers Telegram (UX táctil, Zero Comandos); títulos en botones hasta 55 chars
- `config.py` — rutas desde `PROJECT_ROOT`
- `services/book_client.py` — búsqueda y descarga en 8 fuentes paralelas: Libgen, Archive.org, OpenLibrary, Gutenberg, Standard Ebooks, ManyBooks, Anna's Archive, Z-Library
- `services/kindle_mailer.py` — SMTP con guardia 22 MB
- `services/gmail_monitor.py` — IMAP persistente (una conexión, no flooding)
- `services/user_manager.py` — Upstash Redis cuando env vars presentes; fallback a JSON local

## Variables de entorno clave en Render
Configuradas en el dashboard de Render (no en `.env` del repo):
`TELEGRAM_BOT_TOKEN`, `GMAIL_USER`, `GMAIL_APP_PASSWORD`, `KINDLE_EMAIL_*`, `GROQ_API_KEY`, `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN`

## Recordatorios clave
- Textos dinámicos en Telegram → pasar siempre por `escape_md()` para evitar crashes
- Conexión IMAP: una sola conexión con `noop()`, nunca dentro de un bucle de polling
- Archivos temporales con UUID: `{titulo}_{uuid[:6]}.epub`
- Sesiones de búsqueda (`SEARCH_SESSIONS`) con TTL 2h, máximo 150 sesiones
- Archive.org: filtrar lending items con `-access-restricted-item:true` en query Solr
- Títulos Archive.org: cortar en primer `:` si prefijo ≥ 10 chars para evitar títulos largos
- `user_manager.py`: si `UPSTASH_REDIS_REST_URL` está en env → usa Redis; si no → JSON local
- Daemon local macOS (`launchd`) eliminado permanentemente — no recrear
