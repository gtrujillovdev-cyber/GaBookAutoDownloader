import os
from pathlib import Path
from dotenv import load_dotenv

# Resolve project root directory
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(dotenv_path=PROJECT_ROOT / ".env")

# Base paths & Port
DOWNLOADS_DIR = os.getenv("DOWNLOADS_DIR", str(PROJECT_ROOT / "downloads"))
USERS_FILE = os.getenv("USERS_FILE", str(PROJECT_ROOT / "users.json"))
PORT = int(os.getenv("PORT")) if os.getenv("PORT") and os.getenv("PORT").isdigit() else None

# Credentials & Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GMAIL_USER = os.getenv("GMAIL_USER", "gabook.sender@gmail.com")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
GMAIL_SENDER = os.getenv("GMAIL_SENDER") or GMAIL_USER or "gabook.sender@gmail.com"
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

# Preset profiles for 1-tap setup (configurable via .env, with safe generic fallbacks)
KINDLE_PAPA = os.getenv("KINDLE_EMAIL_PAPA", "familiar1@kindle.com")
KINDLE_GONZALO = os.getenv("KINDLE_EMAIL_GONZALO", "familiar2@kindle.com")
KINDLE_GABRIEL = os.getenv("KINDLE_EMAIL_GABRIEL", DEFAULT_KINDLE_EMAIL)

PRESET_KINDLES = {
    "papa": {"label": os.getenv("KINDLE_LABEL_PAPA", "📖 Lector 1"), "email": KINDLE_PAPA},
    "gonzalo": {"label": os.getenv("KINDLE_LABEL_GONZALO", "📖 Lector 2"), "email": KINDLE_GONZALO},
    "gabriel": {"label": os.getenv("KINDLE_LABEL_GABRIEL", "📱 Mi Kindle"), "email": KINDLE_GABRIEL}
}

# Kindle Hardware Profiles & Usable Storage Capacities (in MB)
KINDLE_MODELS = {
    "basic_8gb": {"label": "Kindle Básico (8 GB)", "total_mb": 6000.0},
    "pw_8gb": {"label": "Paperwhite / Oasis (8 GB)", "total_mb": 6000.0},
    "pw_16gb": {"label": "Paperwhite (16 GB)", "total_mb": 13500.0},
    "sig_32gb": {"label": "Signature / Oasis (32 GB)", "total_mb": 27500.0},
    "scribe_16gb": {"label": "Kindle Scribe (16 GB)", "total_mb": 13500.0},
    "scribe_32gb": {"label": "Kindle Scribe (32 GB)", "total_mb": 27500.0},
    "scribe_64gb": {"label": "Kindle Scribe (64 GB)", "total_mb": 55000.0},
    "legacy_4gb": {"label": "Kindle Antiguo (4 GB)", "total_mb": 3000.0},
}
DEFAULT_KINDLE_MODEL_KEY = "basic_8gb"
DEFAULT_STORAGE_TOTAL_MB = 6000.0
LOW_STORAGE_THRESHOLD_MB = 300.0  # Alert when less than 300 MB remaining

# Thematic categories for browsing (24 curated genres across 3 pages)
TOPICS = [
    # Página 1: Superventas, Ficción Popular y Novedades Recomendadas
    {"label": "🔥 Top Más Leídos", "query": "bestseller", "title": "Los Libros Más Leídos y Populares"},
    {"label": "🏆 Premios y Éxitos", "query": "premio planeta", "title": "Obras Premiadas y Grandes Éxitos"},
    {"label": "⚔️ Novela Histórica", "query": "novela historica", "title": "Novela Histórica Épica"},
    {"label": "🔍 Novela Negra / Thriller", "query": "novela negra", "title": "Novela Negra, Policiaca y Thriller"},
    {"label": "🧠 Suspense Psicológico", "query": "suspense psicologico", "title": "Suspense y Misterio Psicológico"},
    {"label": "🚀 Ciencia Ficción", "query": "ciencia ficcion", "title": "Ciencia Ficción y Futuro"},
    {"label": "🧙‍♂️ Fantasía Épica", "query": "fantasia epica", "title": "Fantasía Épica y Magia"},
    {"label": "🌱 Crecimiento Personal", "query": "desarrollo personal", "title": "Desarrollo Personal y Bienestar"},

    # Página 2: Investigación, Crónica Real, Viajes y Pensamiento
    {"label": "📜 Historia de España", "query": "historia espana", "title": "Historia y Crónicas de España"},
    {"label": "🏺 Arqueología y Civiliz.", "query": "civilizaciones antiguas", "title": "Arqueología y Civilizaciones Antiguas"},
    {"label": "🕵️‍♂️ Mafia y Crónica Negra", "query": "mafia", "title": "Mafia, Crimen y Crónica Real"},
    {"label": "🕵️ Espionaje / Guerra Fría", "query": "novela espionaje", "title": "Espionaje y Guerra Fría"},
    {"label": "🧭 Grandes Viajes y Explor.", "query": "viajes expedicion", "title": "Grandes Viajes y Exploración"},
    {"label": "👤 Biografías y Memorias", "query": "biografia", "title": "Biografías y Memorias"},
    {"label": "🔬 Ciencia y Tecnología", "query": "divulgacion cientifica", "title": "Divulgación Científica y Tecnología"},
    {"label": "🤔 Filosofía y Reflexión", "query": "filosofia", "title": "Filosofía y Grandes Pensadores"},

    # Página 3: Clásicos, Humanidades y Otros Géneros
    {"label": "📖 Clásicos Universales", "query": "clasicos literatura", "title": "Grandes Clásicos de la Literatura"},
    {"label": "🏛️ Arquitectura y Diseño", "query": "arquitectura", "title": "Arquitectura, Urbanismo y Diseño"},
    {"label": "🦴 Antropología y Evolución", "query": "antropologia", "title": "Antropología y Evolución Humana"},
    {"label": "🪖 Historia Bélica y Militar", "query": "historia militar", "title": "Ficción e Historia Militar"},
    {"label": "🌐 Geopolítica y Estrategia", "query": "geopolitica", "title": "Geopolítica y Relaciones Internacionales"},
    {"label": "⏳ Historia Alternativa", "query": "ucronia", "title": "Historia Alternativa (Ucronías)"},
    {"label": "👻 Terror y Novela Gótica", "query": "novela terror", "title": "Terror, Misterio y Gótico"},
    {"label": "✒️ Poesía y Relatos", "query": "poesia", "title": "Poesía y Antologías"}
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
