import os
import re
import time
import uuid
import asyncio
import logging
from typing import Dict, Optional, Tuple
from dotenv import load_dotenv

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    LinkPreviewOptions
)
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)

from book_client import (
    search_epubs,
    download_epub,
    parse_query_and_language,
    get_book_cover,
    LANG_MAP
)
from kindle_mailer import send_to_kindle
from gmail_monitor import monitor_kindle_delivery
from user_manager import (
    get_user_data,
    set_kindle_email,
    set_user_lang
)

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GMAIL_SENDER = os.getenv("GMAIL_USER", "tu_correo@gmail.com")

PAGE_SIZE = 5

# Preset profiles for 1-tap setup (configurable via .env, with safe generic fallbacks)
KINDLE_PAPA = os.getenv("KINDLE_EMAIL_PAPA", "familiar1@kindle.com")
KINDLE_GONZALO = os.getenv("KINDLE_EMAIL_GONZALO", "familiar2@kindle.com")
KINDLE_GABRIEL = os.getenv("KINDLE_EMAIL_GABRIEL", os.getenv("KINDLE_EMAIL", "tu_kindle@kindle.com"))

PRESET_KINDLES = {
    "papa": {"label": os.getenv("KINDLE_LABEL_PAPA", "👨‍🦳 Kindle de Papá"), "email": KINDLE_PAPA},
    "gonzalo": {"label": os.getenv("KINDLE_LABEL_GONZALO", "👦 Kindle de Gonzalo"), "email": KINDLE_GONZALO},
    "gabriel": {"label": os.getenv("KINDLE_LABEL_GABRIEL", "👤 Mi Kindle"), "email": KINDLE_GABRIEL}
}

def build_preset_keyboard() -> InlineKeyboardMarkup:
    """Generates dynamic keyboard for preset Kindle devices."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(PRESET_KINDLES["papa"]["label"], callback_data="preset:papa")],
        [InlineKeyboardButton(PRESET_KINDLES["gonzalo"]["label"], callback_data="preset:gonzalo")],
        [InlineKeyboardButton(PRESET_KINDLES["gabriel"]["label"], callback_data="preset:gabriel")]
    ])

# Thematic categories for browsing (24 curated genres)
TOPICS = [
    # Página 1: Historia, Arqueología, Humanidades y Clásicos
    {"label": "🏺 Arqueología y Civiliz.", "query": "civilizaciones antiguas", "title": "Arqueología y Civilizaciones Antiguas"},
    {"label": "🦴 Antropología y Evolución", "query": "antropologia", "title": "Antropología y Evolución Humana"},
    {"label": "🏛️ Arquitectura y Urbanismo", "query": "arquitectura", "title": "Arquitectura, Urbanismo y Diseño"},
    {"label": "⚔️ Novela Histórica Épica", "query": "novela historica", "title": "Novela Histórica Épica"},
    {"label": "📜 Historia de España", "query": "historia espana", "title": "Historia y Crónicas de España"},
    {"label": "🪖 Ficción Bélica y Militar", "query": "historia militar", "title": "Ficción Bélica y Militar"},
    {"label": "🕵️ Espionaje y Guerra Fría", "query": "novela espionaje", "title": "Espionaje y Guerra Fría"},
    {"label": "🌐 Geopolítica y Estrategia", "query": "geopolitica", "title": "Geopolítica y Relaciones Internacionales"},

    # Página 2: Investigación, Pensamiento, Crónica Real y Viajes
    {"label": "🔍 Novela Negra y Policiaca", "query": "novela negra", "title": "Novela Negra y Policiaca"},
    {"label": "🕵️‍♂️ Mafia y Crónica Real", "query": "mafia", "title": "Mafia, Crimen Organizado y Crónica Real"},
    {"label": "🧭 Grandes Viajes y Explor.", "query": "viajes expedicion", "title": "Grandes Viajes y Exploración"},
    {"label": "🤔 Filosofía y Pensamiento", "query": "filosofia", "title": "Filosofía y Grandes Pensadores"},
    {"label": "👤 Biografías y Memorias", "query": "biografia", "title": "Biografías y Memorias"},
    {"label": "🔬 Divulgación Científica", "query": "divulgacion cientifica", "title": "Divulgación Científica y Tecnología"},
    {"label": "📖 Clásicos Universales", "query": "clasicos literatura", "title": "Grandes Clásicos de la Literatura"},
    {"label": "⏳ Ucronías (Hist. Alternativa)", "query": "ucronia", "title": "Historia Alternativa (Ucronías)"},

    # Página 3: Ficción, Suspense y Géneros Narrativos
    {"label": "💻 Thriller Tecnológico", "query": "tecno thriller", "title": "Thriller Tecnológico / Tecno-thriller"},
    {"label": "🧠 Suspense Psicológico", "query": "suspense psicologico", "title": "Suspense Psicológico"},
    {"label": "🚀 Ciencia Ficción", "query": "ciencia ficcion", "title": "Ciencia Ficción"},
    {"label": "🧙‍♂️ Fantasía Épica", "query": "fantasia epica", "title": "Fantasía Épica"},
    {"label": "🧩 Misterio / Whodunit", "query": "novela misterio", "title": "Misterio / Whodunit (Enigmas)"},
    {"label": "👻 Terror y Novela Gótica", "query": "novela terror", "title": "Terror y Horror"},
    {"label": "✒️ Poesía y Antologías", "query": "poesia", "title": "Poesía y Antologías"},
    {"label": "🌱 Desarrollo Personal", "query": "desarrollo personal", "title": "Desarrollo Personal y Autoayuda"}
]

TOPICS_PAGE_SIZE = 8

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

# Cache for active searches: { session_id: { "books": [...], "query": "...", "lang": "...", "page": 0, "note": "", "created_at": ... } }
SEARCH_SESSIONS: Dict[str, dict] = {}
SESSION_TTL_SECONDS = 7200  # 2 hours lifetime per search session
MAX_ACTIVE_SESSIONS = 150   # Max pool size in RAM

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
        "   Toca *'🚀 Enviar a mi Kindle'* y el bot lo descargará, enviará y verificará automáticamente.\n\n"
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

    reply_markup = build_preset_keyboard()
    user_data = get_user_data(user_id)
    current = user_data.get("kindle_email") or "Ninguno"

    await update.message.reply_text(
        f"🎯 *Configuración de Kindle*\n\n"
        f"Destino actual: `{current}`\n\n"
        "Toca para elegir tu Kindle directamente:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )

async def perfil_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Shows user profile and settings."""
    user = update.effective_user
    user_id = user.id
    data = get_user_data(user_id)

    profile_text = (
        f"👤 *Perfil: {user.first_name}*\n\n"
        f"📖 *Kindle vinculado:* `{data.get('kindle_email') or 'No configurado'}`\n"
        f"🌐 *Idioma favorito:* `{data.get('lang') or 'Español'}`\n"
        f"📤 *Remitente de envío:* `{GMAIL_SENDER}`\n\n"
        "Toca abajo para cambiar tu Kindle o explorar temas."
    )
    await update.message.reply_text(profile_text, parse_mode=ParseMode.MARKDOWN, reply_markup=MAIN_KEYBOARD)

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

    clean_query, target_lang = parse_query_and_language(raw_query, default_lang=default_lang)
    lang_display = target_lang if target_lang else "Todos"
    label = display_name or clean_query

    status_msg = await update.message.reply_text(
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
    query = update.message.text.strip()
    logger.info(f"📩 Mensaje recibido de {user.first_name} (ID: {user.id}): '{query}'")

    if query.startswith("/"):
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

    # Handle preset Kindle selector
    if data.startswith("preset:"):
        key = data.split(":")[1]
        preset = PRESET_KINDLES.get(key)
        if preset:
            set_kindle_email(user_id, preset["email"], user.first_name)
            await query.edit_message_text(
                f"🎉 *¡Configurado con éxito!*\n\n"
                f"🎯 Destino: `{preset['email']}`\n\n"
                "Ahora ya puedes escribir cualquier libro o tocar *'📚 Explorar por Temas'*.",
                parse_mode=ParseMode.MARKDOWN
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

    # STEP A: SHOW BOOK PREVIEW WITH COVER
    if data.startswith("dl:"):
        _, session_id, idx_str = data.split(":")
        idx = int(idx_str)

        session = SEARCH_SESSIONS.get(session_id)
        if not session or idx >= len(session["books"]):
            await query.edit_message_text("⚠️ La sesión de búsqueda ha caducado. Vuelve a escribir el título.")
            return

        b = session["books"][idx]
        year_str = f"{b['year']}" if b.get('year') else "No especificado"

        preview_text = (
            "📖 *PREVISUALIZACIÓN DEL LIBRO*\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📌 *Título:* *{escape_md(b['title'])}*\n"
            f"✍️ *Autor:* _{escape_md(b['author'])}_\n"
            f"🌐 *Idioma:* {escape_md(b['lang'])}\n"
            f"📅 *Año:* {escape_md(year_str)}\n"
            f"📦 *Formato:* EPUB ({escape_md(b['size'])})\n"
            f"🎯 *Destino:* `{kindle_email}`\n\n"
            "¿Deseas enviar este libro a tu Kindle?"
        )

        preview_keyboard = [
            [InlineKeyboardButton("🚀 Enviar a mi Kindle", callback_data=f"send:{session_id}:{idx}")],
            [InlineKeyboardButton("⬅️ Ver otras versiones", callback_data=f"back:{session_id}")],
            [InlineKeyboardButton("❌ Cancelar", callback_data=f"cancel:{session_id}")]
        ]

        # Fetch book cover in background
        loop = asyncio.get_running_loop()
        cover_url = await loop.run_in_executor(None, get_book_cover, b['title'], b['author'])

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

    # STEP B: CONFIRM AND SEND
    if not data.startswith("send:"):
        return

    _, session_id, idx_str = data.split(":")
    idx = int(idx_str)

    session = SEARCH_SESSIONS.get(session_id)
    if not session or idx >= len(session["books"]):
        await query.edit_message_text("⚠️ La sesión de búsqueda ha caducado. Vuelve a escribir el título.")
        return

    selected_book = session["books"][idx]
    book_title = selected_book["title"]
    book_author = selected_book["author"]
    title_md = escape_md(book_title)
    author_md = escape_md(book_author)

    # Step 1: Download
    await query.edit_message_text(
        f"⏳ *[1/3] Descargando EPUB...*\n\n"
        f"📖 *{title_md}*\n"
        f"✍️ _{author_md}_\n"
        f"📦 Tamaño: {escape_md(selected_book['size'])} | Idioma: *{escape_md(selected_book['lang'])}*",
        parse_mode=ParseMode.MARKDOWN
    )

    loop = asyncio.get_running_loop()
    filepath = await loop.run_in_executor(None, download_epub, selected_book, "downloads")

    if not filepath or not os.path.exists(filepath):
        await query.edit_message_text(
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
            await query.edit_message_text(
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

        # Step 2: Send to personalized Kindle
        await query.edit_message_text(
            f"⏳ *[2/3] Enviando a tu Kindle...*\n\n"
            f"📖 *{title_md}*\n"
            f"📧 Destino: `{kindle_email}`",
            parse_mode=ParseMode.MARKDOWN
        )

        sent = await loop.run_in_executor(None, send_to_kindle, filepath, book_title, kindle_email)

        if not sent:
            await query.edit_message_text(
                "❌ *Error en el envío*: No se pudo enviar el correo a Amazon.\n"
                "Verifica la configuración del servidor de correo.",
                parse_mode=ParseMode.MARKDOWN
            )
            return

        # Step 3: Monitor Gmail for Amazon confirmation
        await query.edit_message_text(
            f"⏳ *[3/3] Correo enviado. Verificando confirmación de Amazon en Gmail...*\n\n"
            f"📖 *{title_md}*\n"
            "_Comprobando si Amazon solicita verificación o aprueba la entrega..._",
            parse_mode=ParseMode.MARKDOWN
        )

        verify_result = await loop.run_in_executor(None, monitor_kindle_delivery, 60, 5)

        # Step 4: Final notification
        status_icon = "🎉" if verify_result["status"] in ["verified_auto", "delivered_silent"] else "⚠️"
        final_message = (
            f"{status_icon} *¡Operación completada!*\n\n"
            f"📖 *{title_md}*\n"
            f"✍️ _{author_md}_\n"
            f"🎯 Destino: `{kindle_email}`\n"
            f"🌐 Idioma: {escape_md(selected_book['lang'])}\n\n"
            f"📬 *Estado:* {escape_md(verify_result['message'])}\n\n"
            "💡 *Próximo paso:* Enciende el Wi-Fi de tu Kindle para que se sincronice automáticamente.\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "👇 *¿Quieres pedir otro libro?*\n"
            "Escribe su nombre o toca un botón de abajo:"
        )

        final_keyboard = [
            [InlineKeyboardButton("🔍 Buscar otro libro", callback_data="action:new_search")],
            [InlineKeyboardButton("📚 Explorar Temas", callback_data="tpage:0")],
            [InlineKeyboardButton("🔄 Cambiar de Kindle", callback_data="action:change_kindle")]
        ]
        reply_markup = InlineKeyboardMarkup(final_keyboard)

        await query.edit_message_text(final_message, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

    finally:
        # Guarantee 100% deletion of the downloaded EPUB to avoid accumulating digital waste
        if filepath and os.path.exists(filepath):
            try:
                os.remove(filepath)
                logger.info(f"🗑️ Archivo temporal eliminado tras envío: {filepath}")
            except Exception as e:
                logger.warning(f"No se pudo eliminar archivo temporal {filepath}: {e}")

def cleanup_downloads_dir():
    """Removes any stale downloaded files on startup to prevent accumulating digital waste."""
    downloads_path = os.path.join(os.path.dirname(__file__), "downloads")
    if os.path.exists(downloads_path):
        for f in os.listdir(downloads_path):
            file_path = os.path.join(downloads_path, f)
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
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_error_handler(error_handler)

    print("✅ Bot con exploración por temas, portadas y paginación activo.")
    application.run_polling()

if __name__ == "__main__":
    main()
