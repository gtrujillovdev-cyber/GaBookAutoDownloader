import os
from pathlib import Path
from dotenv import load_dotenv

# Resolve project root directory
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(dotenv_path=PROJECT_ROOT / ".env")

# Base paths
DOWNLOADS_DIR = os.getenv("DOWNLOADS_DIR", str(PROJECT_ROOT / "downloads"))
USERS_FILE = os.getenv("USERS_FILE", str(PROJECT_ROOT / "users.json"))

# Credentials & Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GMAIL_USER = os.getenv("GMAIL_USER")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
GMAIL_SENDER = GMAIL_USER or "tu_correo@gmail.com"
DEFAULT_KINDLE_EMAIL = os.getenv("KINDLE_EMAIL", "tu_kindle@kindle.com")

# Network & Protocol Timeouts
SMTP_TIMEOUT = 30
IMAP_TIMEOUT = 25
MAX_ATTACHMENT_BYTES = 22 * 1024 * 1024  # 22 MB safety ceiling for Gmail base64 encoding

# Pagination & Cache
PAGE_SIZE = 5
TOPICS_PAGE_SIZE = 8
SESSION_TTL_SECONDS = 7200  # 2 hours lifetime per search session
MAX_ACTIVE_SESSIONS = 150   # Max pool size in RAM

# HTTP Client Headers
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
}

# Family preset profiles for 1-tap setup (configurable via .env, with safe generic fallbacks)
KINDLE_PAPA = os.getenv("KINDLE_EMAIL_PAPA", "familiar1@kindle.com")
KINDLE_GONZALO = os.getenv("KINDLE_EMAIL_GONZALO", "familiar2@kindle.com")
KINDLE_GABRIEL = os.getenv("KINDLE_EMAIL_GABRIEL", DEFAULT_KINDLE_EMAIL)

PRESET_KINDLES = {
    "papa": {"label": os.getenv("KINDLE_LABEL_PAPA", "👨‍🦳 Kindle de Papá"), "email": KINDLE_PAPA},
    "gonzalo": {"label": os.getenv("KINDLE_LABEL_GONZALO", "👦 Kindle de Gonzalo"), "email": KINDLE_GONZALO},
    "gabriel": {"label": os.getenv("KINDLE_LABEL_GABRIEL", "👤 Mi Kindle"), "email": KINDLE_GABRIEL}
}

# Thematic categories for browsing (24 curated genres across 3 pages)
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

# Natural language map for target language parsing
LANG_MAP = {
    "es": "Spanish",
    "esp": "Spanish",
    "español": "Spanish",
    "espanol": "Spanish",
    "spanish": "Spanish",
    "castellano": "Spanish",
    "en": "English",
    "eng": "English",
    "ingles": "English",
    "inglés": "English",
    "english": "English",
    "fr": "French",
    "fra": "French",
    "francés": "French",
    "frances": "French",
    "french": "French",
    "de": "German",
    "ger": "German",
    "alemán": "German",
    "aleman": "German",
    "german": "German",
    "it": "Italian",
    "italiano": "Italian",
    "italian": "Italian",
    "pt": "Portuguese",
    "portugués": "Portuguese",
    "portugues": "Portuguese",
    "portuguese": "Portuguese",
    "todos": None,
    "all": None,
    "any": None
}
