# 📋 Guía de Procedimientos y Estándares: GaBookAutoDownloader

Este documento define las directrices arquitectónicas, protocolos de seguridad, flujos de trabajo y estándares de desarrollo que deben seguirse obligatoriamente en este proyecto.

---

## 1. 🛡️ Principio de Cero Rupturas (Retrocompatibilidad Absoluta)

1. **UX Intocable:** La interfaz de Telegram orientada a usuarios no técnicos ("Zero Comandos") con botones táctiles inferiores, teclado persistente y lenguaje natural nunca debe ser sustituida por comandos complejos.
2. **Perfiles Familiares Garantizados:** El sistema de selección de 1 toque (👨‍🦳 Papá, 👦 Gonzalo, 👤 Mi Kindle) debe mantenerse siempre funcional a través de variables de entorno configuradas en `.env`, manteniendo fallbacks genéricos para terceros.
3. **Flujo de Previsualización y Envío:** El ciclo `Búsqueda -> Portada OpenLibrary -> Ficha Técnica -> Descarga temporal -> SMTP Gmail -> Verificación IMAP de Amazon` debe preservarse íntegramente.

---

## 2. 🔒 Política Estricta de Privacidad y Seguridad

1. **Cero Datos Personales en Git:**
   - **Prohibido** incluir en el repositorio correos reales (`@gmail.com`, `@kindle.com`), IDs de Telegram, nombres reales de familiares o contraseñas.
   - Todo dato sensible debe residir exclusivamente en `.env` (credenciales) y `users.json` (base de datos local).
2. **Plantillas Sanitizadas:**
   - Para compartir la configuración se deben mantener al día `.env.example` y `users.example.json` con datos simulados (`ejemplo@kindle.com`, `tu_correo@gmail.com`).
3. **Control de Ignorados (`.gitignore` y `.dockerignore`):**
   - Ambos archivos deben excluir estrictamente: `.env`, `users.json`, `venv/`, `downloads/`, `*.log`, `*.pyc`, `__pycache__/` y `.DS_Store`.
4. **Autoría en Git:**
   - Los commits deben usar siempre identidades anónimas protegidas por GitHub (ej. `gtrujillovdev-cyber <gtrujillovdev-cyber@users.noreply.github.com>`).

---

## 3. 🏗️ Estructura del Código y Patrón de la Industria (`src/` Layout)

El proyecto sigue rigurosamente el diseño estándar de paquetes Python:

```text
GaBookAutoDownloader/
├── src/
│   └── gabook/                     # Paquete principal de la aplicación
│       ├── __init__.py
│       ├── bot.py                  # Capa de presentación y handlers de Telegram
│       ├── config.py               # Configuración centralizada, rutas base y constantes
│       └── services/               # Servicios desacoplados de negocio
│           ├── __init__.py
│           ├── book_client.py      # Búsqueda multi-fuente y descarga de EPUBs
│           ├── gmail_monitor.py    # Monitor IMAP y auto-verificación de Amazon
│           ├── kindle_mailer.py    # Servicio SMTP con guardia de tamaño
│           └── user_manager.py     # Persistencia atómica de perfiles
├── tests/                          # Suite de pruebas automatizadas
│   ├── __init__.py
│   └── test_features.py            # Tests unitarios herméticos
├── scripts/                        # Scripts de despliegue y mantenimiento
│   └── setup_macos_service.sh      # Instalador de daemon launchd para macOS
├── docs/                           # Manuales y documentación de usuario
│   └── GUIA_USUARIO.md             # Guía visual para familiares
├── main.py                         # Punto de entrada primario
├── bot.py                          # Wrapper de compatibilidad hacia atrás
├── Dockerfile                      # Imagen para despliegue en la nube
├── .dockerignore                   # Reglas de exclusión para Docker
├── .env.example                    # Plantilla de variables de entorno
├── .gitignore                      # Exclusiones de Git
├── requirements.txt                # Dependencias fijadas
└── users.example.json              # Plantilla para la base de datos
```

* **Regla de Rutas:** Toda ruta a archivos (`downloads/`, `users.json`, `.env`) debe calcularse a partir de `config.PROJECT_ROOT` para evitar fallos según el directorio desde donde se invoque el proceso.

---

## 4. ⚡ Protocolos de Resiliencia y Estabilidad en el Pipeline

1. **Sanitización de Markdown en Telegram:**
   - Cualquier texto dinámico (título, autor, consulta de búsqueda, estado) **debe** pasar por `escape_md()` antes de enviarse con `ParseMode.MARKDOWN` para evitar caídas `Can't parse entities`.
2. **Conexión IMAP Persistente (No-Flooding):**
   - En `gmail_monitor.py` **nunca** abrir conexiones IMAP dentro de un bucle de polling. Se conecta una sola vez, se usa `mail.noop()`, se aplican timeouts (`IMAP_TIMEOUT = 25`) y se asegura el `logout()` en bloques `finally`.
3. **Protección de Tamaño en Envíos (< 22 MB):**
   - Antes de enviar un EPUB por SMTP, verificar `os.path.getsize()`. Si excede los 22 MB, notificar con mensaje amigable al usuario en Telegram en lugar de dejar que SMTP o Amazon fallen.
4. **Nombres Únicos de Archivos Temporales:**
   - Las descargas deben usar sufijo UUID (`{titulo}_{uuid[:6]}.epub`) para evitar condiciones de carrera si dos usuarios descargan simultáneamente. Al enviarse por correo, el asunto y adjunto deben mostrar el nombre limpio.
5. **Escritura Atómica en Base de Datos:**
   - Cualquier modificación en `users.json` debe escribirse en un archivo temporal (`NamedTemporaryFile`) y reemplazarse con `os.replace` para evitar archivos corruptos o truncados a 0 bytes.
6. **Gestión de Memoria en RAM (TTL):**
   - El diccionario `SEARCH_SESSIONS` debe purgarse periódicamente con `cleanup_expired_sessions()` (TTL de 2 horas, máximo 150 sesiones) para permitir ejecuciones ininterrumpidas 24/7 sin fugas de memoria.

---

## 5. 🧪 Calidad y Pruebas Automatizadas

1. **Tests Obligatorios:** Antes de realizar cualquier commit o push, debe ejecutarse la suite de pruebas:
   ```bash
   python -m unittest discover -s tests
   ```
2. **Pruebas Herméticas (Offline):** Las pruebas unitarias nunca deben depender de servicios externos o internet activo; las llamadas de red deben mockearse (`unittest.mock.patch`).

---

## 6. 🧹 Protocolo de Higiene y Limpieza Pre-Commit

1. **Cero Basura:** Antes de hacer commit, asegurar que no existan:
   * Archivos `.DS_Store`
   * Directorios `__pycache__/` y archivos `*.pyc`
   * Archivos de registro `*.log`
   * Archivos temporales en `downloads/`
   * Scripts de depuración o de un solo uso
2. **Comando de limpieza rápida:**
   ```bash
   find . -name "*.pyc" -delete && find . -name "__pycache__" -type d -prune -exec rm -rf {} + && find . -name ".DS_Store" -delete && find . -name "*.log" -delete
   ```

---

## 7. ☁️ Protocolo de Despliegue Cloud y Modo de Proceder en Cada Cambio

Para garantizar que el bot opere 24/7 de forma ininterrumpida sin conflictos y de manera completamente gratuita, **todo agente o desarrollador debe seguir obligatoriamente este procedimiento en cada cambio**:

### 1. Arquitectura de Despliegue en Producción
* **Plataforma:** Render como **Web Service** (`plan: free`) orquestado por `render.yaml`.
* **Servidor de Salud HTTP:** El bot arranca en un hilo demonio un servidor HTTP (`src/gabook/services/health_server.py`) que escucha en `0.0.0.0:$PORT` y responde `200 OK` en `/health`.
* **Keep-Alive con UptimeRobot:** Render Free se suspende tras 15 minutos de inactividad HTTP. UptimeRobot monitoriza `https://gabookautodownloader.onrender.com/health` con ping cada 5 minutos, garantizando funcionamiento continuo 24/7/365.
* **Prohibición de Instancias Duplicadas:** Telegram solo admite un proceso escuchando `getUpdates` por token. El demonio local en macOS (`launchd`) ha sido **eliminado permanentemente** (`~/Library/LaunchAgents/com.gabookautodownloader.plist` borrado) para evitar conflictos `Conflict 409`.
* **Persistencia de Usuarios (Upstash Redis):** `user_manager.py` almacena los perfiles en Upstash Redis cuando `UPSTASH_REDIS_REST_URL` y `UPSTASH_REDIS_REST_TOKEN` están configuradas. Render free tiene filesystem efímero — sin Redis los datos se pierden en cada restart. Las credenciales se configuran en el dashboard de Render, nunca en el repo.

### 2. Flujo de Trabajo Obligatorio ante Cada Cambio
Ante cualquier modificación, corrección o mejora en el código, se debe ejecutar estrictamente este ciclo:

```text
[Modificación de Código]
        ↓
1. Ejecutar Suite de Tests (python -m unittest discover -s tests)
        ↓
2. Limpieza de Basura (pyc, __pycache__, logs, .DS_Store)
        ↓
3. Auditoría de Seguridad (Cero correos reales/tokens en git diff)
        ↓
4. Commit con Autoría Anónima (gtrujillovdev-cyber)
        ↓
5. Push a GitHub (git push origin main)
        ↓ (Render Auto-Deploy)
6. Verificación de Salud en Producción (curl https://gabookautodownloader.onrender.com/health)
```

1. **Pruebas Locales:** Nunca hacer commit sin pasar los tests unitarios al 100%.
2. **Sanitización Estricta:** Verificar con `git status` y `git diff` que ningún archivo sensible (`.env`, `users.json`) sea incluido ni existan datos personales en la documentación.
3. **Despliegue Automático:** Al hacer push a `origin main`, Render compila y levanta la nueva versión automáticamente vía webhook.
4. **Comprobación de Salud:** Validar con una petición HTTP que el endpoint `/health` de Render responda con `{"status": "healthy"}` tras el despliegue.

