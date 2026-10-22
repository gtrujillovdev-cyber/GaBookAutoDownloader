import os
import re
import time
import uuid
import asyncio
import logging
from typing import Dict, Optional, Tuple

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    LinkPreviewOptions
)
from telegram.constants import ParseMode, ChatAction
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

from gabook.config import (
    TELEGRAM_BOT_TOKEN,
    GMAIL_SENDER,
    PAGE_SIZE,
    TOPICS,
    TOPICS_PAGE_SIZE,
    PRESET_KINDLES,
    KINDLE_MODELS,
    LANG_MAP,
    DOWNLOADS_DIR,
    SESSION_TTL_SECONDS,
    MAX_ACTIVE_SESSIONS,
    PORT
)
from gabook.services.health_server import start_health_server
from gabook.services.book_client import (
    search_epubs,
    download_epub,
    parse_query_and_language,
    get_book_cover,
    get_book_synopsis
)
from gabook.services.kindle_mailer import send_to_kindle
from gabook.services.gmail_monitor import monitor_kindle_delivery
from gabook.services.user_manager import (
    get_user_data,
    set_kindle_email,
    set_personal_email,
    set_kindle_model,
    set_kindle_free_space,
    record_book_sent,
    get_kindle_storage_info,
    get_user_history,
    set_user_lang
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Cache for active searches: { session_id: { "books": [...], "query": "...", "lang": "...", "page": 0, "note": "", "created_at": ... } }
SEARCH_SESSIONS: Dict[str, dict] = {}

def escape_md(text: Optional[str]) -> str:
    """Escapes Telegram Markdown v1 reserved syntax characters (_, *, `, [) to prevent entity crashes."""
    if not text:
        return ""
    return re.sub(r'([_*`\[])', r'\\\1', str(text))

def cleanup_expired_sessions():
    """Removes search sessions older than SESSION_TTL_SECONDS to avoid RAM bloat over time."""
    now = time.time()
    expired = [
        sid for sid, data in SEARCH_SESSIONS.items()
        if (now - data.get("created_at", now)) > SESSION_TTL_SECONDS
    ]
    for sid in expired:
        SEARCH_SESSIONS.pop(sid, None)

    if len(SEARCH_SESSIONS) > MAX_ACTIVE_SESSIONS:
        sorted_sids = sorted(
            SEARCH_SESSIONS.keys(),
            key=lambda k: SEARCH_SESSIONS[k].get("created_at", 0)
        )
        for sid in sorted_sids[:(len(SEARCH_SESSIONS) - MAX_ACTIVE_SESSIONS)]:
            SEARCH_SESSIONS.pop(sid, None)

def is_valid_email(email_str: str) -> bool:
    """Basic email format validator."""
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email_str.strip()))

def parse_size_to_mb(size_str: Optional[str]) -> float:
    """Parses book size string (e.g. '2.5 MB', '650 kB') to float megabytes."""
    if not size_str:
        return 1.5
    try:
        cleaned = re.sub(r'[^0-9.,]', '', size_str).replace(',', '.')
        if not cleaned:
            return 1.5
        val = float(cleaned)
        if 'kb' in size_str.lower():
            return val / 1024.0
        if 'gb' in size_str.lower():
            return val * 1024.0
        return val
    except Exception:
        return 1.5

def parse_storage_text_to_mb(text: str) -> Optional[float]:
    """Parses user input string into megabytes (e.g., '500 MB', '2.5 GB')."""
    t = text.strip().lower()
    m = re.search(r'([0-9]+(?:[\.,][0-9]+)?)', t)
    if not m:
        return None
    val = float(m.group(1).replace(',', '.'))
    if 'gb' in t:
        return val * 1024.0
    return val

def build_preset_keyboard(include_back: bool = False) -> InlineKeyboardMarkup:
    """Generates dynamic keyboard for preset Kindle devices."""
    rows = [
        [InlineKeyboardButton(PRESET_KINDLES["papa"]["label"], callback_data="preset:papa")],
        [InlineKeyboardButton(PRESET_KINDLES["gonzalo"]["label"], callback_data="preset:gonzalo")],
        [InlineKeyboardButton(PRESET_KINDLES["gabriel"]["label"], callback_data="preset:gabriel")]
    ]
    if include_back:
        rows.append([InlineKeyboardButton("⬅️ Volver al Perfil", callback_data="menu:profile")])
    return InlineKeyboardMarkup(rows)

def build_profile_markup(user_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    """Generates user profile overview with storage telemetry and action buttons."""
    user_data = get_user_data(user_id)
    storage_info = get_kindle_storage_info(user_id)

    kindle_email = user_data.get("kindle_email") or "No configurado"
    personal_email = user_data.get("personal_email") or "No configurado"
    lang = user_data.get("lang") or "Español"
    books_sent = user_data.get("books_sent_count", 0)

    if storage_info["is_low"]:
        storage_status = "⚠️ *Poco espacio disponible*"
    else:
        storage_status = "✅ *Espacio óptimo*"

    text = (
        "👤 *MI PERFIL Y DISPOSITIVOS*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📖 *Kindle Vinculado:* `{kindle_email}`\n"
        f"✉️ *Correo Personal:* `{personal_email}`\n"
        f"🌐 *Idioma Preferido:* `{lang}`\n"
        f"📚 *Libros enviados:* {books_sent}\n\n"
        "📦 *Almacenamiento de tu Kindle:*\n"
        f"📱 *Modelo:* {storage_info['model']}\n"
        f"📊 *Ocupación:* `{storage_info['progress_bar']}` *{storage_info['percent_used']:.0f}%* ({storage_status})\n"
        f"💾 *Espacio Libre:* *{storage_info['free_display']}* de {storage_info['total_display']}\n"
        f"📤 *Remitente autorizado Amazon:* `{GMAIL_SENDER}`\n\n"
        "Toca un botón para cambiar tu configuración:"
    )

    keyboard = [
        [
            InlineKeyboardButton("🎯 Cambiar Kindle", callback_data="menu:kindle"),
            InlineKeyboardButton("✉️ Correo Personal", callback_data="menu:set_personal_email")
        ],
        [
            InlineKeyboardButton("📱 Modelo de Kindle", callback_data="menu:models"),
            InlineKeyboardButton("🎛️ Calibrar Espacio", callback_data="menu:calibrate_storage")
        ],
        [
            InlineKeyboardButton("📚 Mis Libros Recientes", callback_data="menu:history"),
            InlineKeyboardButton("🌐 Cambiar Idioma", callback_data="menu:lang")
        ],
        [
            InlineKeyboardButton("❌ Cerrar", callback_data="cancel_menu")
        ]
    ]

    return text, InlineKeyboardMarkup(keyboard)

def build_history_markup(user_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    """Generates the recent readings list with 1-tap re-search buttons."""
    history = get_user_history(user_id)
    if not history:
        text = (
            "📚 *HISTORIAL DE LECTURAS*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "Aún no has solicitado libros. Tus libros enviados aparecerán aquí para que puedas "
            "volver a consultarlos o reenviarlos con 1 toque."
        )
        keyboard = [[InlineKeyboardButton("⬅️ Volver al Perfil", callback_data="menu:profile")]]
        return text, InlineKeyboardMarkup(keyboard)

    text = (
        "📚 *MIS LIBROS RECIENTES*\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Aquí tienes tus últimas solicitudes. Toca cualquiera para buscarlo o reenviarlo:\n"
    )

    keyboard = []
    for h in history:
        dest_icon = "📱" if h.get("destination") == "Kindle" else ("📥" if h.get("destination") == "Telegram" else "✉️")
        btn_text = f"📖 {h['title'][:25]} ({dest_icon} {h.get('sent_at', '')})"
        keyboard.append([InlineKeyboardButton(btn_text, callback_data=f"hist_search:{h['title'][:30]}")])

    keyboard.append([InlineKeyboardButton("⬅️ Volver al Perfil", callback_data="menu:profile")])
    return text, InlineKeyboardMarkup(keyboard)

def build_models_markup() -> InlineKeyboardMarkup:
    """Generates buttons for selecting Kindle hardware models."""
    keyboard = []
    for key, model in KINDLE_MODELS.items():
        keyboard.append([InlineKeyboardButton(f"📱 {model['label']}", callback_data=f"set_model:{key}")])
    keyboard.append([InlineKeyboardButton("⬅️ Volver al Perfil", callback_data="menu:profile")])
    return InlineKeyboardMarkup(keyboard)

def build_calibration_markup() -> InlineKeyboardMarkup:
    """Generates 1-tap options to calibrate remaining Kindle space."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🟢 Mucho espacio (> 4 GB libres)", callback_data="cal_storage:4000")],
        [InlineKeyboardButton("🟡 Espacio medio (~ 2 GB libres)", callback_data="cal_storage:2000")],
        [InlineKeyboardButton("🟠 Poco espacio (~ 500 MB libres)", callback_data="cal_storage:500")],
        [InlineKeyboardButton("🔴 Casi lleno (~ 150 MB libres - alerta)", callback_data="cal_storage:150")],
        [InlineKeyboardButton("✍️ Escribir espacio exacto...", callback_data="cal_storage:custom")],
        [InlineKeyboardButton("⬅️ Volver al Perfil", callback_data="menu:profile")]
    ])

def build_topics_markup(page: int = 0) -> Tuple[str, InlineKeyboardMarkup]:
    """Generates a paginated grid of thematic categories."""
    total_topics = len(TOPICS)
    total_pages = (total_topics + TOPICS_PAGE_SIZE - 1) // TOPICS_PAGE_SIZE
    page = max(0, min(page, total_pages - 1))

    start_idx = page * TOPICS_PAGE_SIZE
    end_idx = min(start_idx + TOPICS_PAGE_SIZE, total_topics)
    current_topics = TOPICS[start_idx:end_idx]

    keyboard = []
    row = []
    for idx_offset, topic in enumerate(current_topics):
        global_idx = start_idx + idx_offset
        row.append(InlineKeyboardButton(topic["label"], callback_data=f"topic:{global_idx}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    # Navigation buttons
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("⬅️ Anterior", callback_data=f"tpage:{page - 1}"))
    nav_row.append(InlineKeyboardButton(f"📄 {page + 1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton("Siguiente ➡️", callback_data=f"tpage:{page + 1}"))

    if len(nav_row) > 1:
        keyboard.append(nav_row)

    keyboard.append([InlineKeyboardButton("❌ Cerrar", callback_data="cancel_menu")])

    text = (
        "📚 *Explorador por Temáticas y Géneros*\n\n"
        "¿Qué tipo de lectura te apetece hoy?\n"
        f"_(Página {page + 1} de {total_pages} - {total_topics} géneros disponibles)_\n\n"
        "Toca una temática para descubrir los mejores libros disponibles:"
    )
    return text, InlineKeyboardMarkup(keyboard)

# Persistent bottom navigation keyboard
MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("🔍 Buscar Libro"), KeyboardButton("📚 Explorar por Temas")],
        [KeyboardButton("🎯 Mi Kindle"), KeyboardButton("🔄 Reiniciar")]
    ],
    resize_keyboard=True,
    is_persistent=True
)

def build_search_page_markup(session_id: str, page: int) -> Tuple[str, InlineKeyboardMarkup]:
    """Generates the text and keyboard for a specific page of search results."""
    session = SEARCH_SESSIONS.get(session_id)
    if not session:
        return "⚠️ Sesión caducada.", InlineKeyboardMarkup([])

    books = session["books"]
    query = session["query"]
    note = session.get("note", "")
    total_books = len(books)
    total_pages = max(1, (total_books + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    session["page"] = page

    start_idx = page * PAGE_SIZE
    end_idx = min(start_idx + PAGE_SIZE, total_books)
    current_books = books[start_idx:end_idx]

    keyboard = []
    for idx_offset, b in enumerate(current_books):
        global_idx = start_idx + idx_offset
        title_btn = b['title'][:28] + ("…" if len(b['title']) > 28 else "")
        meta = f"{b['lang']} | {b['size']}"
        button_text = f"📖 {title_btn} ({meta})"
        keyboard.append([InlineKeyboardButton(button_text, callback_data=f"dl:{session_id}:{global_idx}")])

    # Pagination navigation buttons
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("⬅️ Anterior", callback_data=f"page:{session_id}:{page - 1}"))
    
    nav_row.append(InlineKeyboardButton(f"📄 {page + 1}/{total_pages}", callback_data="noop"))

    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton("Siguiente ➡️", callback_data=f"page:{session_id}:{page + 1}"))

    if len(nav_row) > 1:
        keyboard.append(nav_row)

    keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data=f"cancel:{session_id}")])

    text = (
        f"{note}📚 *Resultados para:* _{escape_md(query)}_\n"
        f"_(Mostrando {start_idx + 1}-{end_idx} de {total_books} libros en EPUB)_\n\n"
        "Toca el libro que quieras para ver su ficha y portada:"
    )

    return text, InlineKeyboardMarkup(keyboard)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Welcomes the user and presents instructions and persistent keyboard."""
    user = update.effective_user
    user_id = user.id
    logger.info(f"🚀 /start recibido de {user.first_name} (ID: {user_id})")
    user_data = get_user_data(user_id)
    kindle_email = user_data.get("kindle_email")

    instructions = (
        "📖 *¿CÓMO FUNCIONA? (Guía rápida)*\n\n"
        "1️⃣ *Busca tu libro:*\n"
        "   Escribe el título o autor aquí abajo, o toca *'📚 Explorar por Temas'* para ver recomendaciones.\n\n"
        "2️⃣ *Previsualiza:*\n"
        "   Elige un libro para ver su ficha completa, portada y detalles.\n\n"
        "3️⃣ *Envía con 1 toque:*\n"
        "   Elige si enviarlo a tu *Kindle* o directamente a tu *correo personal* con 1 toque.\n\n"
        "4️⃣ *¡A leer!:*\n"
        "   Enciende el Wi-Fi de tu Kindle y aparecerá en tu biblioteca.\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"🌐 *Idioma actual:* `{user_data.get('lang') or 'Español'}`\n"
        f"📤 *Remitente aprobado en Amazon:* `{GMAIL_SENDER}`\n\n"
        "💡 *Sin comandos:* No hace falta escribir barras `/`. Puedes tocar los botones de abajo o escribir palabras como `reiniciar`, `temas` o el título del libro."
    )

    if not kindle_email:
        welcome_text = (
            f"👋 *¡Hola {user.first_name}! Bienvenido a tu Asistente Kindle.*\n\n"
            f"{instructions}\n"
            "⚠️ *Paso inicial:* Toca abajo tu Kindle para vincular tu dispositivo:"
        )
        await update.message.reply_text(
            welcome_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=build_preset_keyboard()
        )
    else:
        welcome_text = (
            f"📚 *¡Hola {user.first_name}! Tu Asistente Kindle está listo.*\n\n"
            f"🎯 *Libros destinados a:* `{kindle_email}`\n\n"
            f"{instructions}\n"
            "✍️ *¿Qué libro quieres leer hoy?* Escribe su nombre directamente o usa los botones de abajo:"
        )
        await update.message.reply_text(
            welcome_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=MAIN_KEYBOARD
        )

async def temas_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays paginated thematic categories for exploration."""
    text, reply_markup = build_topics_markup(0)
    if update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
    else:
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

async def kindle_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Allows selecting a preset Kindle or typing a custom one."""
    user = update.effective_user
    user_id = user.id

    if context.args:
        email_input = context.args[0].strip().lower()
        if not is_valid_email(email_input):
            await update.message.reply_text(
                "⚠️ Formato no válido. Debe ser algo como:\n`/kindle correo@kindle.com`",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        set_kindle_email(user_id, email_input, user.first_name)
        await update.message.reply_text(
            f"✅ *Kindle configurado con éxito:* `{email_input}`\n\n"
            f"Recuerda que `{GMAIL_SENDER}` debe estar en la lista de remitentes aprobados de Amazon.\n"
            "¡Ya puedes pedir cualquier libro!",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=MAIN_KEYBOARD
        )
        return

    text, reply_markup = build_profile_markup(user_id)
    await update.message.reply_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )

async def perfil_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows user profile, storage status and settings."""
    user = update.effective_user
    user_id = user.id
    text, reply_markup = build_profile_markup(user_id)
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

async def idioma_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Configures preferred search language."""
    user_id = update.effective_user.id

    if context.args:
        arg = context.args[0].lower()
        if arg in LANG_MAP:
            target = LANG_MAP[arg]
            set_user_lang(user_id, target)
            name = target or "Todos los idiomas"
            await update.message.reply_text(
                f"✅ Idioma predeterminado cambiado a: *{name}*",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=MAIN_KEYBOARD
            )
            return

    keyboard = [
        [
            InlineKeyboardButton("🇪🇸 Español", callback_data="setlang:Spanish"),
            InlineKeyboardButton("🇬🇧 English", callback_data="setlang:English")
        ],
        [
            InlineKeyboardButton("🇫🇷 Français", callback_data="setlang:French"),
            InlineKeyboardButton("🇩🇪 Deutsch", callback_data="setlang:German")
        ],
        [
            InlineKeyboardButton("🌍 Cualquier idioma (Todos)", callback_data="setlang:all")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    user_data = get_user_data(user_id)
    current = user_data.get("lang") or "Español"
    await update.message.reply_text(
        f"🌐 *Configuración de Idioma*\n\n"
        f"Idioma actual: *{current}*\n"
        "Selecciona el idioma por defecto para tus búsquedas:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )

async def handle_search(update: Update, context: ContextTypes.DEFAULT_TYPE, raw_query: str, display_name: Optional[str] = None):
    """Searches for EPUBs, caches multiple results, and presents paginated options."""
    if not raw_query.strip():
        await update.message.reply_text("⚠️ Por favor indica el título, autor o tema a buscar.", reply_markup=MAIN_KEYBOARD)
        return

    user_id = update.effective_user.id
    user_data = get_user_data(user_id)
    default_lang = user_data.get("lang", "Spanish")

    chat_id = update.effective_chat.id if update.effective_chat else None
    if chat_id:
        try:
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        except Exception:
            pass

    clean_query, target_lang = parse_query_and_language(raw_query, default_lang=default_lang)
    lang_display = target_lang if target_lang else "Todos"
    label = display_name or clean_query

    target_sender = update.message if update.message else (update.callback_query.message if update.callback_query else None)
    if not target_sender:
        return

    status_msg = await target_sender.reply_text(
        f"🔍 *Buscando:* _{escape_md(label)}_\n"
        f"🌐 *Idioma:* `{lang_display}`\n"
        f"_Buscando opciones en formato EPUB..._",
        parse_mode=ParseMode.MARKDOWN
    )

    loop = asyncio.get_running_loop()
    # Search with expanded range (up to 30 results)
    matching_books, other_books = await loop.run_in_executor(
        None, search_epubs, clean_query, 30, target_lang
    )

    books_to_show = matching_books
    note = ""

    if not books_to_show:
        if other_books:
            books_to_show = other_books
            note = f"⚠️ _No se encontraron en *{escape_md(lang_display)}*, pero aquí tienes opciones en otros idiomas:_\n\n"
        else:
            await status_msg.edit_text(
                f"❌ No se encontraron libros en formato EPUB para: *{escape_md(clean_query)}*.\n\n"
                "💡 Prueba con otra palabra clave, autor o explora con *'📚 Explorar por Temas'*.",
                parse_mode=ParseMode.MARKDOWN
            )
            return

    cleanup_expired_sessions()
    session_id = str(uuid.uuid4())[:8]
    SEARCH_SESSIONS[session_id] = {
        "books": books_to_show,
        "query": label,
        "lang": lang_display,
        "note": note,
        "page": 0,
        "created_at": time.time()
    }

    text, reply_markup = build_search_page_markup(session_id, 0)
    await status_msg.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

async def buscar_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the /buscar command."""
    query = " ".join(context.args)
    if not query:
        await update.message.reply_text(
            "Uso: `/buscar <título o tema>`\n"
            "Ejemplo: `/buscar El principito en español`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=MAIN_KEYBOARD
        )
        return
    await handle_search(update, context, query)

async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles natural keywords and free text book searches without slash commands."""
    user = update.effective_user
    user_id = user.id
    query = update.message.text.strip()
    logger.info(f"📩 Mensaje recibido de {user.first_name} (ID: {user_id}): '{query}'")

    if query.startswith("/"):
        return

    # Check interactive pending input states
    if "awaiting_email_for_send" in context.user_data:
        pending = context.user_data.pop("awaiting_email_for_send")
        if not is_valid_email(query):
            context.user_data["awaiting_email_for_send"] = pending
            await update.message.reply_text(
                "⚠️ *Correo no válido.* Por favor escribe una dirección correcta (ej: `usuario@gmail.com`):",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        set_personal_email(user_id, query)
        status_msg = await update.message.reply_text(f"✅ Correo `{query}` guardado. Preparando envío...")
        await execute_book_send(status_msg, user_id, pending["session_id"], pending["idx"], query, is_kindle=False)
        return

    if "awaiting_custom_email_send" in context.user_data:
        pending = context.user_data.pop("awaiting_custom_email_send")
        if not is_valid_email(query):
            context.user_data["awaiting_custom_email_send"] = pending
            await update.message.reply_text(
                "⚠️ *Correo no válido.* Por favor escribe una dirección correcta (ej: `usuario@gmail.com`):",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        is_kindle = query.lower().endswith("@kindle.com")
        status_msg = await update.message.reply_text(f"⏳ Preparando envío a `{query}`...")
        await execute_book_send(status_msg, user_id, pending["session_id"], pending["idx"], query, is_kindle=is_kindle)
        return

    if context.user_data.pop("awaiting_personal_email_only", False):
        if not is_valid_email(query):
            context.user_data["awaiting_personal_email_only"] = True
            await update.message.reply_text(
                "⚠️ *Correo no válido.* Por favor escribe una dirección correcta (ej: `usuario@gmail.com`):",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        set_personal_email(user_id, query)
        text, reply_markup = build_profile_markup(user_id)
        await update.message.reply_text(
            f"🎉 *¡Correo personal guardado con éxito:* `{query}`\n\n" + text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
        return

    if context.user_data.pop("awaiting_custom_storage_mb", False):
        mb = parse_storage_text_to_mb(query)
        if not mb or mb <= 0:
            context.user_data["awaiting_custom_storage_mb"] = True
            await update.message.reply_text(
                "⚠️ No pude reconocer la cantidad. Escribe algo como `500 MB` o `2.5 GB`:",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        set_kindle_free_space(user_id, mb)
        text, reply_markup = build_profile_markup(user_id)
        await update.message.reply_text(
            f"✅ *Espacio libre calibrado:* `{mb:.0f} MB`\n\n" + text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
        return

    q_lower = query.lower()

    # 1. Keywords to restart / start over
    if query in ["🔄 Reiniciar", "❓ Ayuda"] or q_lower in ["reiniciar", "inicio", "empezar", "reset", "hola", "buenas", "comenzar", "start", "menu", "menú"]:
        await start_command(update, context)
        return

    # 2. Keywords for topics and categories
    if query == "📚 Explorar por Temas" or q_lower in ["temas", "generos", "géneros", "categorias", "categorías", "que leer", "qué leer", "recomiendame", "recomiéndame"]:
        await temas_command(update, context)
        return

    # 3. Keywords for Kindle selection
    if query == "🎯 Mi Kindle" or q_lower in ["kindle", "mi kindle", "cambiar kindle", "dispositivo"]:
        await kindle_command(update, context)
        return

    # 4. Keywords for help
    if q_lower in ["ayuda", "como funciona", "cómo funciona", "instrucciones", "que hago", "qué hago", "guia", "guía"]:
        await start_command(update, context)
        return

    # 5. Keywords for language
    if q_lower in ["idioma", "idiomas", "lenguaje"]:
        await idioma_command(update, context)
        return

    # 6. Keyword prompt for search
    if query == "🔍 Buscar Libro" or q_lower in ["buscar", "buscar libro"]:
        await update.message.reply_text(
            "✍️ *Escribe el nombre del libro, autor o tema* que quieras buscar:\n"
            "• _Ejemplos:_ `Dune`, `Stephen King`, `novela policiaca`",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=MAIN_KEYBOARD
        )
        return

    # Treat any other text as an automatic book search query
    await handle_search(update, context, query)

async def voice_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles audio voice notes from users and transcribes or guides them seamlessly."""
    user = update.effective_user
    logger.info(f"🎙️ Mensaje de voz recibido de {user.first_name} (ID: {user.id})")

    groq_key = os.getenv("GROQ_API_KEY")
    openai_key = os.getenv("OPENAI_API_KEY")

    if not groq_key and not openai_key:
        await update.message.reply_text(
            f"🎙️ *¡Hola {user.first_name}! He recibido tu nota de voz.*\n\n"
            "💡 Para activar la transcripción automática por voz puedes añadir tu clave gratuita de Groq o Whisper en la configuración de la nube (`GROQ_API_KEY`).\n\n"
            "✍️ *Por ahora, por favor escribe el nombre del libro o autor que buscas aquí abajo:*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=MAIN_KEYBOARD
        )
        return

    status_msg = await update.message.reply_text("🎙️ _Escuchando tu audio y transcribiendo el título..._", parse_mode=ParseMode.MARKDOWN)
    voice_file = await context.bot.get_file(update.message.voice.file_id)
    temp_ogg = os.path.join(DOWNLOADS_DIR, f"voice_{uuid.uuid4().hex[:6]}.ogg")
    try:
        await voice_file.download_to_drive(temp_ogg)
        transcribed_text = None

        if groq_key:
            import requests
            with open(temp_ogg, "rb") as f:
                r = requests.post(
                    "https://api.groq.com/openai/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {groq_key}"},
                    files={"file": (os.path.basename(temp_ogg), f, "audio/ogg")},
                    data={"model": "whisper-large-v3-turbo", "language": "es"},
                    timeout=12
                )
                if r.status_code == 200:
                    transcribed_text = r.json().get("text", "").strip()
        elif openai_key:
            import requests
            with open(temp_ogg, "rb") as f:
                r = requests.post(
                    "https://api.openai.com/v1/audio/transcriptions",
                    headers={"Authorization": f"Bearer {openai_key}"},
                    files={"file": (os.path.basename(temp_ogg), f, "audio/ogg")},
                    data={"model": "whisper-1", "language": "es"},
                    timeout=15
                )
                if r.status_code == 200:
                    transcribed_text = r.json().get("text", "").strip()

        if transcribed_text:
            clean_search = re.sub(r'^(busca|búscame|quiero leer|descarga|ponme|libro)\s+', '', transcribed_text, flags=re.IGNORECASE).strip()
            clean_search = clean_search.strip('."\'')
            await status_msg.edit_text(f"🎙️ *Transcripción:* _{escape_md(clean_search)}_\n_Iniciando búsqueda..._", parse_mode=ParseMode.MARKDOWN)
            await handle_search(update, context, clean_search)
        else:
            await status_msg.edit_text("⚠️ No pude entender claramente el audio. Por favor escribe el título o autor con el teclado.")
    except Exception as e:
        logger.error(f"Error procesando voz: {e}")
        await status_msg.edit_text("⚠️ Ocurrió un error al procesar el audio. Por favor escribe el título con el teclado.")
    finally:
        if os.path.exists(temp_ogg):
            try:
                os.remove(temp_ogg)
            except OSError:
                pass

async def execute_book_send(
    target_msg,
    user_id: int,
    session_id: str,
    idx: int,
    target_email: str,
    is_kindle: bool
):
    """Executes the complete book download, size check, dispatch and notification pipeline."""
    session = SEARCH_SESSIONS.get(session_id)
    if not session or idx >= len(session["books"]):
        await target_msg.edit_text("⚠️ La sesión de búsqueda ha caducado. Vuelve a escribir el título.")
        return

    selected_book = session["books"][idx]
    book_title = selected_book["title"]
    book_author = selected_book["author"]
    title_md = escape_md(book_title)
    author_md = escape_md(book_author)

    dest_label = "tu Kindle" if is_kindle else "tu correo electrónico"
    total_steps = 3 if is_kindle else 2

    # Step 1: Download
    await target_msg.edit_text(
        f"⏳ *[1/{total_steps}] Descargando EPUB...*\n\n"
        f"📖 *{title_md}*\n"
        f"✍️ _{author_md}_\n"
        f"📦 Tamaño: {escape_md(selected_book['size'])} | Idioma: *{escape_md(selected_book['lang'])}*",
        parse_mode=ParseMode.MARKDOWN
    )

    loop = asyncio.get_running_loop()
    filepath = await loop.run_in_executor(None, download_epub, selected_book, DOWNLOADS_DIR)

    if not filepath or not os.path.exists(filepath):
        await target_msg.edit_text(
            f"❌ *Error en la descarga*: No se pudo descargar el archivo EPUB para _{title_md}_.\n"
            "Por favor intenta seleccionar otra versión de la lista.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    try:
        # Pre-flight check: File size limit (< 22 MB)
        file_size = os.path.getsize(filepath)
        if file_size > 22 * 1024 * 1024:
            size_mb = file_size / (1024 * 1024)
            await target_msg.edit_text(
                f"⚠️ *El archivo es demasiado grande ({size_mb:.1f} MB)*\n\n"
                f"Amazon y Gmail no permiten enviar archivos de más de 20 MB por correo.\n\n"
                "💡 Por favor toca *'Ver otras versiones'* y elige una opción más ligera de la lista.",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("⬅️ Ver otras versiones", callback_data=f"back:{session_id}")],
                    [InlineKeyboardButton("❌ Cancelar", callback_data=f"cancel:{session_id}")]
                ])
            )
            return

        if target_email == "telegram":
            # Direct Telegram document upload
            await target_msg.edit_text(
                f"⏳ *[2/2] Subiendo EPUB directamente a Telegram...*\n\n"
                f"📖 *{title_md}*\n"
                f"✍️ _{author_md}_",
                parse_mode=ParseMode.MARKDOWN
            )
            chat_id = target_msg.chat_id
            try:
                await target_msg.get_bot().send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_DOCUMENT)
            except Exception:
                pass

            clean_display_name = clean_filename(book_title) or "libro"
            with open(filepath, "rb") as doc_f:
                await target_msg.get_bot().send_document(
                    chat_id=chat_id,
                    document=doc_f,
                    filename=f"{clean_display_name}.epub",
                    caption=f"📖 *{title_md}*\n✍️ _{author_md}_\n📦 EPUB ({escape_md(selected_book['size'])})",
                    parse_mode=ParseMode.MARKDOWN
                )

            record_book_sent(
                user_id,
                file_size,
                is_kindle=False,
                title=book_title,
                author=book_author,
                destination="Telegram"
            )

            status_icon = "🎉"
            status_desc = "Libro subido con éxito y listo para leer en Telegram."
            next_tip = "💡 *¡Listo para leer!* Toca el archivo adjunto para abrirlo en Apple Books, Kindle App o tu lector habitual."

        else:
            # Step 2: Send via SMTP
            await target_msg.edit_text(
                f"⏳ *[2/{total_steps}] Enviando a {dest_label}...*\n\n"
                f"📖 *{title_md}*\n"
                f"📧 Destino: `{target_email}`",
                parse_mode=ParseMode.MARKDOWN
            )

            sent = await loop.run_in_executor(None, send_to_kindle, filepath, book_title, target_email)

            if not sent:
                await target_msg.edit_text(
                    "❌ *Error en el envío*: No se pudo enviar el correo.\n"
                    "Verifica la configuración del servidor de correo.",
                    parse_mode=ParseMode.MARKDOWN
                )
                return

            dest_type = "Kindle" if is_kindle else "Correo"
            record_book_sent(
                user_id,
                file_size,
                is_kindle=is_kindle,
                title=book_title,
                author=book_author,
                destination=dest_type
            )

            if is_kindle:
                # Step 3: Monitor Gmail for Amazon confirmation
                await target_msg.edit_text(
                    f"⏳ *[3/3] Correo enviado. Verificando confirmación de Amazon en Gmail...*\n\n"
                    f"📖 *{title_md}*\n"
                    "_Comprobando si Amazon solicita verificación o aprueba la entrega..._",
                    parse_mode=ParseMode.MARKDOWN
                )

                verify_result = await loop.run_in_executor(None, monitor_kindle_delivery, 60, 5)
                status_icon = "🎉" if verify_result["status"] in ["verified_auto", "delivered_silent"] else "⚠️"
                status_desc = escape_md(verify_result['message'])
                next_tip = (
                    "💡 *Pasos en tu Kindle:*\n"
                    "• Activa Wi-Fi y pulsa *Sincronizar*.\n"
                    "• En la Biblioteca, asegúrate de ver la pestaña *'Documentos'* o *'Todos'* (en los modelos modernos los envíos no aparecen en 'Libros').\n"
                    "• Si no aparece, comprueba si Amazon te envió un correo para autorizar/verificar la entrega."
                )
            else:
                status_icon = "🎉"
                status_desc = "Libro enviado con éxito a tu bandeja de entrada."
                next_tip = "💡 *Próximo paso:* Abre tu correo electrónico para descargar o leer tu archivo EPUB."

        storage_info = get_kindle_storage_info(user_id)
        storage_footer = f"\n📦 *Espacio restante en Kindle:* `{storage_info['progress_bar']}` {storage_info['free_display']} libres" if is_kindle else ""

        final_message = (
            f"{status_icon} *¡Operación completada!*\n\n"
            f"📖 *{title_md}*\n"
            f"✍️ _{author_md}_\n"
            f"🎯 Destino: `{target_email}`\n"
            f"🌐 Idioma: {escape_md(selected_book['lang'])}\n"
            f"📦 Tamaño: {escape_md(selected_book['size'])}{storage_footer}\n\n"
            f"📬 *Estado:* {status_desc}\n\n"
            f"{next_tip}\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "👇 *¿Quieres pedir otro libro?*\n"
            "Escribe su nombre o toca un botón de abajo:"
        )

        clean_author = selected_book.get("author", "").strip()
        final_keyboard = [
            [InlineKeyboardButton("🔍 Buscar otro libro", callback_data="action:new_search")],
        ]
        if clean_author and clean_author.lower() not in ["autor desconocido", "desconocido", "anonymous", "varios"]:
            short_author = clean_author[:20]
            final_keyboard.append([InlineKeyboardButton(f"✍️ Más de {short_author}", callback_data=f"more_author:{session_id}:{idx}")])

        final_keyboard.append([InlineKeyboardButton("📚 Explorar Temas", callback_data="tpage:0")])
        final_keyboard.append([InlineKeyboardButton("👤 Ver mi Perfil / Historial", callback_data="menu:profile")])

        await target_msg.edit_text(final_message, parse_mode=ParseMode.MARKDOWN, reply_markup=InlineKeyboardMarkup(final_keyboard))

    finally:
        if filepath and os.path.exists(filepath):
            try:
                os.remove(filepath)
                logger.info(f"🗑️ Archivo temporal eliminado tras envío: {filepath}")
            except Exception as e:
                logger.warning(f"Error al eliminar temporal {filepath}: {e}")

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles all inline keyboard interactions."""
    query = update.callback_query
    await query.answer()

    data = query.data
    user = update.effective_user
    user_id = user.id
    logger.info(f"🔘 Botón pulsado por {user.first_name} (ID: {user_id}): '{data}'")

    if data == "noop":
        return

    # Handle topics menu pagination
    if data.startswith("tpage:"):
        page = int(data.split(":")[1])
        text, reply_markup = build_topics_markup(page)
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
        return

    if data == "cancel_menu":
        await query.edit_message_text(
            "📚 Menú de temáticas cerrado.\n\n"
            "✍️ Puedes escribir directamente el nombre de cualquier libro o autor para buscarlo.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # Handle topic selection from topics menu
    if data.startswith("topic:"):
        topic_idx = int(data.split(":")[1])
        if topic_idx >= len(TOPICS):
            return
        topic = TOPICS[topic_idx]
        topic_query = topic["query"]
        topic_label = topic["title"]

        status_msg = await query.edit_message_text(
            f"🔍 *Cargando categoría:* _{escape_md(topic_label)}_\n_Buscando los mejores libros en EPUB..._",
            parse_mode=ParseMode.MARKDOWN
        )
        user_data = get_user_data(user_id)
        default_lang = user_data.get("lang", "Spanish")

        loop = asyncio.get_running_loop()
        matching_books, other_books = await loop.run_in_executor(
            None, search_epubs, topic_query, 35, default_lang
        )

        books_to_show = matching_books or other_books
        if not books_to_show:
            await status_msg.edit_text(f"❌ No se encontraron libros para la temática *{escape_md(topic_label)}*.")
            return

        cleanup_expired_sessions()
        session_id = str(uuid.uuid4())[:8]
        SEARCH_SESSIONS[session_id] = {
            "books": books_to_show,
            "query": topic_label,
            "lang": default_lang,
            "note": "",
            "page": 0,
            "created_at": time.time()
        }

        text, reply_markup = build_search_page_markup(session_id, 0)
        await status_msg.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
        return

    # Handle profile and settings menus
    if data == "menu:profile":
        text, reply_markup = build_profile_markup(user_id)
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
        return

    if data == "menu:kindle":
        reply_markup = build_preset_keyboard(include_back=True)
        await query.edit_message_text(
            "🎯 *Selecciona el Kindle que deseas usar:*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
        return

    if data == "menu:set_personal_email":
        context.user_data["awaiting_personal_email_only"] = True
        cancel_kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Volver al Perfil", callback_data="menu:profile")]])
        await query.edit_message_text(
            "✉️ *Configuración de Correo Personal*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            "✍️ *Escribe tu dirección de correo habitual* (ej: `tu_correo@gmail.com`):\n\n"
            "_La utilizaremos para enviarte libros cuando prefieras recibirlos en tu bandeja o tu Kindle esté casi lleno._",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=cancel_kb
        )
        return

    if data == "menu:models":
        await query.edit_message_text(
            "📱 *Selecciona el modelo de tu Kindle*\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Esto nos permite conocer su capacidad y avisarte si te queda poco espacio:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=build_models_markup()
        )
        return

    if data.startswith("set_model:"):
        model_key = data.split(":")[1]
        set_kindle_model(user_id, model_key)
        text, reply_markup = build_profile_markup(user_id)
        await query.edit_message_text(
            "🎉 *¡Modelo de Kindle actualizado!*\n\n" + text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
        return

    if data == "menu:calibrate_storage":
        await query.edit_message_text(
            "🎛️ *Calibración de Espacio Libre*\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "¿Cuánto espacio libre aproximado tiene tu Kindle actualmente?\n\n"
            "_(Puedes verlo en tu Kindle en Configuración ➔ Opciones de dispositivo ➔ Información del dispositivo)_",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=build_calibration_markup()
        )
        return

    if data.startswith("cal_storage:"):
        val = data.split(":")[1]
        if val == "custom":
            context.user_data["awaiting_custom_storage_mb"] = True
            cancel_kb = InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Volver", callback_data="menu:calibrate_storage")]])
            await query.edit_message_text(
                "✍️ *Escribe la cantidad de espacio libre en tu Kindle* (ejemplo: `500 MB` o `2.5 GB`):",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=cancel_kb
            )
            return

        free_mb = float(val)
        set_kindle_free_space(user_id, free_mb)
        text, reply_markup = build_profile_markup(user_id)
        await query.edit_message_text(
            "🎉 *¡Espacio libre calibrado con éxito!*\n\n" + text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
        return

    if data == "menu:lang":
        keyboard = [
            [
                InlineKeyboardButton("🇪🇸 Español", callback_data="setlang:Spanish"),
                InlineKeyboardButton("🇬🇧 English", callback_data="setlang:English")
            ],
            [
                InlineKeyboardButton("🇫🇷 Français", callback_data="setlang:French"),
                InlineKeyboardButton("🇩🇪 Deutsch", callback_data="setlang:German")
            ],
            [
                InlineKeyboardButton("🌍 Cualquier idioma", callback_data="setlang:all")
            ],
            [
                InlineKeyboardButton("⬅️ Volver al Perfil", callback_data="menu:profile")
            ]
        ]
        await query.edit_message_text(
            "🌐 *Selecciona tu idioma preferido para las búsquedas:*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return

    if data == "menu:history":
        text, reply_markup = build_history_markup(user_id)
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
        return

    if data.startswith("hist_search:"):
        q_text = data.split(":", 1)[1]
        await handle_search(update, context, q_text)
        return

    if data.startswith("more_author:"):
        _, session_id, idx_str = data.split(":")
        idx = int(idx_str)
        session = SEARCH_SESSIONS.get(session_id)
        if session and idx < len(session["books"]):
            author_to_search = session["books"][idx].get("author", "")
            if author_to_search:
                await handle_search(update, context, author_to_search)
                return

    # Handle preset Kindle selector
    if data.startswith("preset:"):
        key = data.split(":")[1]
        preset = PRESET_KINDLES.get(key)
        if preset:
            set_kindle_email(user_id, preset["email"], user.first_name)
            text, reply_markup = build_profile_markup(user_id)
            await query.edit_message_text(
                f"🎉 *¡Kindle configurado con éxito!* `{preset['email']}`\n\n" + text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup
            )
        return

    # Handle language settings
    if data.startswith("setlang:"):
        choice = data.split(":")[1]
        target = None if choice == "all" else choice
        set_user_lang(user_id, target)
        name = target or "Todos los idiomas"
        await query.edit_message_text(
            f"✅ *Idioma preferido actualizado:* `{name}`\n\n"
            "Ahora tus búsquedas se enfocarán en este idioma por defecto.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # Handle quick actions after download
    if data == "action:new_search":
        await query.message.reply_text(
            "✨ *¡Listo para una nueva búsqueda!*\n\n"
            "✍️ **Escribe directamente el nombre del libro** que quieras buscar:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=MAIN_KEYBOARD
        )
        return

    if data == "action:change_kindle":
        reply_markup = build_preset_keyboard()
        await query.message.reply_text(
            "🎯 *Selecciona el Kindle que quieras usar:*",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
        return

    # Handle cancellation
    if data.startswith("cancel:"):
        session_id = data.split(":")[1]
        SEARCH_SESSIONS.pop(session_id, None)
        await query.edit_message_text(
            "❌ Búsqueda cancelada.\n\n"
            "✍️ Escribe otro título o toca *'📚 Explorar por Temas'* en cualquier momento.",
            parse_mode=ParseMode.MARKDOWN
        )
        return

    # Handle search results pagination: page:{session_id}:{target_page}
    if data.startswith("page:"):
        _, session_id, page_str = data.split(":")
        page = int(page_str)
        text, reply_markup = build_search_page_markup(session_id, page)
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
        return

    # Handle 'back to search results' from preview
    if data.startswith("back:"):
        session_id = data.split(":")[1]
        session = SEARCH_SESSIONS.get(session_id)
        page = session.get("page", 0) if session else 0
        text, reply_markup = build_search_page_markup(session_id, page)
        await query.edit_message_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)
        return

    # Check Kindle configuration before proceeding with preview or send
    user_data = get_user_data(user_id)
    kindle_email = user_data.get("kindle_email")

    if not kindle_email:
        reply_markup = build_preset_keyboard()
        await query.edit_message_text(
            "⚠️ *Primero necesitamos saber en qué Kindle lo quieres leer:*\n"
            "Toca una de las opciones:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=reply_markup
        )
        return

    # STEP A: SHOW BOOK PREVIEW WITH COVER AND SEND OPTIONS
    if data.startswith("dl:"):
        _, session_id, idx_str = data.split(":")
        idx = int(idx_str)

        session = SEARCH_SESSIONS.get(session_id)
        if not session or idx >= len(session["books"]):
            await query.edit_message_text("⚠️ La sesión de búsqueda ha caducado. Vuelve a escribir el título.")
            return

        b = session["books"][idx]
        year_str = f"{b['year']}" if b.get('year') else "No especificado"

        user_data = get_user_data(user_id)
        storage_info = get_kindle_storage_info(user_id)
        kindle_email = user_data.get("kindle_email") or "No configurado"
        personal_email = user_data.get("personal_email")
        book_size_mb = parse_size_to_mb(b.get('size'))

        low_space_alert = ""
        if storage_info["is_low"] or storage_info["free_mb"] < book_size_mb:
            low_space_alert = f"\n⚠️ *Aviso de almacenamiento:* Te quedan solo {storage_info['free_display']} en tu Kindle.\n"

        # Fetch book cover and synopsis concurrently
        loop = asyncio.get_running_loop()
        cover_future = loop.run_in_executor(None, get_book_cover, b['title'], b['author'])
        synopsis_future = loop.run_in_executor(None, get_book_synopsis, b['title'], b['author'])
        cover_url, synopsis = await asyncio.gather(cover_future, synopsis_future)

        synopsis_block = f"📝 *Sinopsis:* _{escape_md(synopsis)}_\n\n" if synopsis else ""

        preview_text = (
            "📖 *PREVISUALIZACIÓN DEL LIBRO*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📌 *Título:* *{escape_md(b['title'])}*\n"
            f"✍️ *Autor:* _{escape_md(b['author'])}_\n"
            f"🌐 *Idioma:* {escape_md(b['lang'])}\n"
            f"📅 *Año:* {escape_md(year_str)}\n"
            f"📦 *Formato:* EPUB ({escape_md(b['size'])})\n\n"
            f"{synopsis_block}"
            f"🎯 *Kindle:* `{kindle_email}`\n"
            f"✉️ *Correo personal:* `{personal_email or 'No configurado'}`\n"
            f"📊 *Espacio Kindle:* `{storage_info['progress_bar']}` *{storage_info['free_display']} libres*{low_space_alert}\n"
            "¿A dónde deseas enviar este libro?"
        )

        preview_keyboard = [
            [InlineKeyboardButton("🚀 Enviar a mi Kindle", callback_data=f"send_choice:{session_id}:{idx}:kindle")],
            [InlineKeyboardButton("📥 Descargar aquí en Telegram", callback_data=f"send_choice:{session_id}:{idx}:telegram")]
        ]

        if personal_email:
            preview_keyboard.append([
                InlineKeyboardButton(f"✉️ Enviar a mi Correo ({personal_email[:20]}…)", callback_data=f"send_choice:{session_id}:{idx}:personal")
            ])
        else:
            preview_keyboard.append([
                InlineKeyboardButton("✉️ Enviar a mi Correo Personal", callback_data=f"send_choice:{session_id}:{idx}:personal")
            ])

        preview_keyboard.append([InlineKeyboardButton("✏️ Enviar a otro correo...", callback_data=f"send_choice:{session_id}:{idx}:custom")])
        preview_keyboard.append([InlineKeyboardButton("⬅️ Ver otras versiones", callback_data=f"back:{session_id}")])
        preview_keyboard.append([InlineKeyboardButton("❌ Cancelar", callback_data=f"cancel:{session_id}")])

        link_preview = None
        if cover_url:
            link_preview = LinkPreviewOptions(
                url=cover_url,
                is_disabled=False,
                prefer_large_media=True,
                show_above_text=True
            )

        await query.edit_message_text(
            preview_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(preview_keyboard),
            link_preview_options=link_preview
        )
        return

    # STEP B: PROCESS SEND SELECTIONS
    if data.startswith("send_choice:"):
        _, session_id, idx_str, dest = data.split(":")
        idx = int(idx_str)

        session = SEARCH_SESSIONS.get(session_id)
        if not session or idx >= len(session["books"]):
            await query.edit_message_text("⚠️ La sesión de búsqueda ha caducado. Vuelve a escribir el título.")
            return

        b = session["books"][idx]
        user_data = get_user_data(user_id)
        storage_info = get_kindle_storage_info(user_id)
        book_size_mb = parse_size_to_mb(b.get('size'))

        if dest == "telegram":
            await execute_book_send(query.message, user_id, session_id, idx, target_email="telegram", is_kindle=False)
            return

        if dest == "kindle":
            kindle_email = user_data.get("kindle_email")
            if not kindle_email:
                reply_markup = build_preset_keyboard(include_back=True)
                await query.edit_message_text(
                    "⚠️ *Primero necesitamos saber en qué Kindle lo quieres leer:*\n"
                    "Toca una de las opciones:",
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=reply_markup
                )
                return

            # Check if Kindle is low on storage
            if storage_info["is_low"] or storage_info["free_mb"] < book_size_mb:
                warning_text = (
                    "⚠️ *¡ATENCIÓN: Poco espacio en tu Kindle!*\n"
                    "━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"Tu dispositivo (*{storage_info['model']}*) tiene aproximadamente *{storage_info['free_display']} libres* "
                    f"({storage_info['percent_used']:.0f}% ocupado).\n\n"
                    f"El libro *{escape_md(b['title'])}* ocupa *~{book_size_mb:.1f} MB*.\n\n"
                    "Para evitar saturar la memoria o que Amazon falle al sincronizar:\n"
                    "¿Prefieres enviarlo a tu **correo electrónico normal** o continuar al Kindle de todas formas?"
                )
                warning_keyboard = [
                    [InlineKeyboardButton("✉️ Enviar a mi Correo Normal", callback_data=f"send_choice:{session_id}:{idx}:personal")],
                    [InlineKeyboardButton("🚀 Enviar a Kindle de todas formas", callback_data=f"send_confirmed:{session_id}:{idx}:kindle")],
                    [InlineKeyboardButton("✏️ Enviar a otro correo...", callback_data=f"send_choice:{session_id}:{idx}:custom")],
                    [InlineKeyboardButton("⬅️ Volver a la ficha", callback_data=f"dl:{session_id}:{idx}")]
                ]
                await query.edit_message_text(
                    warning_text,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_markup=InlineKeyboardMarkup(warning_keyboard)
                )
                return

            await execute_book_send(query.message, user_id, session_id, idx, target_email=kindle_email, is_kindle=True)
            return

        if dest == "personal":
            personal_email = user_data.get("personal_email")
            if personal_email:
                await execute_book_send(query.message, user_id, session_id, idx, target_email=personal_email, is_kindle=False)
                return

            # Not configured yet: ask user to input it
            context.user_data["awaiting_email_for_send"] = {"session_id": session_id, "idx": idx}
            cancel_kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Volver a la ficha", callback_data=f"dl:{session_id}:{idx}")],
                [InlineKeyboardButton("❌ Cancelar", callback_data=f"cancel:{session_id}")]
            ])
            await query.edit_message_text(
                "✉️ *Configuración de Correo Personal*\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                "Aún no tienes guardada una dirección de correo habitual en tu perfil.\n\n"
                "✍️ *Por favor escribe tu correo electrónico abajo* (ejemplo: `mi_correo@gmail.com`):\n\n"
                "_Lo guardaremos en tu perfil y te enviaremos este libro de inmediato._",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=cancel_kb
            )
            return

        if dest == "custom":
            context.user_data["awaiting_custom_email_send"] = {"session_id": session_id, "idx": idx}
            cancel_kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ Volver a la ficha", callback_data=f"dl:{session_id}:{idx}")],
                [InlineKeyboardButton("❌ Cancelar", callback_data=f"cancel:{session_id}")]
            ])
            await query.edit_message_text(
                "✏️ *Enviar a otra dirección de correo*\n"
                "━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📖 Libro: *{escape_md(b['title'])}*\n\n"
                "✍️ *Escribe la dirección de correo electrónico* de destino:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=cancel_kb
            )
            return

    # STEP C: CONFIRMED FORCED SEND OR LEGACY CALLBACKS
    if data.startswith("send_confirmed:"):
        _, session_id, idx_str, _ = data.split(":")
        idx = int(idx_str)
        user_data = get_user_data(user_id)
        kindle_email = user_data.get("kindle_email") or DEFAULT_KINDLE_EMAIL
        await execute_book_send(query.message, user_id, session_id, idx, target_email=kindle_email, is_kindle=True)
        return

    # Legacy callback compatibility
    if data.startswith("send:"):
        _, session_id, idx_str = data.split(":")
        idx = int(idx_str)
        user_data = get_user_data(user_id)
        kindle_email = user_data.get("kindle_email")
        if not kindle_email:
            reply_markup = build_preset_keyboard(include_back=True)
            await query.edit_message_text(
                "⚠️ *Primero necesitamos saber en qué Kindle lo quieres leer:*\n"
                "Toca una de las opciones:",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=reply_markup
            )
            return
        await execute_book_send(query.message, user_id, session_id, idx, target_email=kindle_email, is_kindle=True)
        return

def cleanup_downloads_dir():
    """Removes any stale downloaded files on startup to prevent accumulating digital waste."""
    if os.path.exists(DOWNLOADS_DIR):
        for f in os.listdir(DOWNLOADS_DIR):
            file_path = os.path.join(DOWNLOADS_DIR, f)
            if os.path.isfile(file_path):
                try:
                    os.remove(file_path)
                    logger.info(f"🧹 Basura digital eliminada: {file_path}")
                except Exception as e:
                    logger.warning(f"Error al limpiar {file_path}: {e}")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log the error and ignore harmless Telegram BadRequest exceptions like 'Message is not modified'."""
    if isinstance(context.error, BadRequest):
        err_msg = str(context.error)
        if "Message is not modified" in err_msg or "Query is too old" in err_msg:
            logger.debug(f"Silenced benign Telegram error: {err_msg}")
            return
    logger.error("Exception while handling an update:", exc_info=context.error)

def main():
    cleanup_downloads_dir()
    if PORT:
        start_health_server(PORT)

    if not TELEGRAM_BOT_TOKEN:
        print("❌ Error: TELEGRAM_BOT_TOKEN no configurado en .env")
        return

    print("🚀 Iniciando GaBookAutoDownloaderBot (Family UX 2.0)...")
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", start_command))
    application.add_handler(CommandHandler("temas", temas_command))
    application.add_handler(CommandHandler("kindle", kindle_command))
    application.add_handler(CommandHandler("perfil", perfil_command))
    application.add_handler(CommandHandler("idioma", idioma_command))
    application.add_handler(CommandHandler("buscar", buscar_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler))
    application.add_handler(MessageHandler(filters.VOICE, voice_message_handler))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_error_handler(error_handler)

    print("✅ Bot con exploración por temas, portadas y paginación activo.")
    application.run_polling()

if __name__ == "__main__":
    main()
