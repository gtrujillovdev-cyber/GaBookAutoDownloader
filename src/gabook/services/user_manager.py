import os
import json
import time
import shutil
import tempfile
import logging
import threading
import functools
from typing import Dict, Optional
from datetime import datetime
from gabook.config import (
    USERS_FILE,
    KINDLE_MODELS,
    DEFAULT_KINDLE_MODEL_KEY,
    DEFAULT_STORAGE_TOTAL_MB,
    LOW_STORAGE_THRESHOLD_MB
)

# --- Redis persistence (Upstash) ---
# If UPSTASH_REDIS_REST_URL is set, user data is stored in Redis (Render-safe).
# Otherwise falls back to the local users.json file (local dev / Docker with volume).
_REDIS_URL = os.getenv("UPSTASH_REDIS_REST_URL")
_REDIS_TOKEN = os.getenv("UPSTASH_REDIS_REST_TOKEN")
_REDIS_KEY = "gabook:users"
_redis_client = None

if _REDIS_URL and _REDIS_TOKEN:
    try:
        from upstash_redis import Redis as _UpstashRedis
        _redis_client = _UpstashRedis(url=_REDIS_URL, token=_REDIS_TOKEN)
    except Exception as _e:
        logging.getLogger(__name__).warning(f"Upstash Redis init failed, falling back to file: {_e}")

logger = logging.getLogger(__name__)

# Serializes read-modify-write cycles on USERS_FILE (handlers run in several threads).
_USERS_LOCK = threading.RLock()

def _locked(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with _USERS_LOCK:
            return fn(*args, **kwargs)
    return wrapper

def load_users() -> Dict[str, dict]:
    """Loads all registered users. Uses Upstash Redis when configured, else local file."""
    if _redis_client:
        try:
            raw = _redis_client.get(_REDIS_KEY)
            if raw is None:
                return {}
            data = json.loads(raw) if isinstance(raw, str) else raw
            if not isinstance(data, dict):
                raise ValueError("Redis payload is not a JSON object")
            return data
        except Exception as e:
            logger.error(f"Error loading users from Redis: {e}")
            return {}
    # --- file fallback (local dev / Docker with volume) ---
    if not os.path.exists(USERS_FILE):
        return {}
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("users file root must be a JSON object")
        return data
    except Exception as e:
        logger.error(f"Error loading {USERS_FILE}: {e}")
        try:
            backup = f"{USERS_FILE}.corrupt-{int(time.time())}"
            shutil.copy2(USERS_FILE, backup)
            logger.error(f"Corrupt users file preserved at {backup}")
        except Exception as be:
            logger.error(f"Could not back up corrupt users file: {be}")
        return {}

def save_users(users: Dict[str, dict]) -> bool:
    """Saves users dictionary. Uses Upstash Redis when configured, else local file."""
    if _redis_client:
        try:
            _redis_client.set(_REDIS_KEY, json.dumps(users, ensure_ascii=False))
            return True
        except Exception as e:
            logger.error(f"Error saving users to Redis: {e}")
            return False
    # --- file fallback (local dev / Docker with volume) ---
    dir_name = os.path.dirname(USERS_FILE) or "."
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile("w", dir=dir_name, delete=False, encoding="utf-8") as tf:
            json.dump(users, tf, indent=2, ensure_ascii=False)
            temp_name = tf.name
        os.replace(temp_name, USERS_FILE)
        return True
    except Exception as e:
        logger.error(f"Error saving {USERS_FILE}: {e}")
        if temp_name and os.path.exists(temp_name):
            try:
                os.remove(temp_name)
            except OSError:
                pass
        return False

def get_user_data(user_id: int) -> dict:
    """Retrieves configuration for a specific Telegram user with safe defaults."""
    users = load_users()
    key = str(user_id)
    raw = users.get(key, {})
    default_model = KINDLE_MODELS.get(DEFAULT_KINDLE_MODEL_KEY, {})

    return {
        "kindle_email": raw.get("kindle_email"),
        "personal_email": raw.get("personal_email"),
        "lang": raw.get("lang", "Spanish"),
        "name": raw.get("name"),
        "kindle_model_key": raw.get("kindle_model_key", DEFAULT_KINDLE_MODEL_KEY),
        "kindle_model": raw.get("kindle_model", default_model.get("label", "Kindle Básico (8 GB)")),
        "storage_total_mb": float(raw.get("storage_total_mb", DEFAULT_STORAGE_TOTAL_MB)),
        "storage_used_mb": float(raw.get("storage_used_mb", 0.0)),
        "books_sent_count": int(raw.get("books_sent_count", 0)),
        "amazon_authorized": bool(raw.get("amazon_authorized", False)),
        "created_at": raw.get("created_at")
    }

@_locked
def set_kindle_email(user_id: int, email: str, name: Optional[str] = None) -> bool:
    """Sets or updates the user's Kindle email address."""
    users = load_users()
    key = str(user_id)
    if key not in users:
        default_model = KINDLE_MODELS.get(DEFAULT_KINDLE_MODEL_KEY, {})
        users[key] = {
            "kindle_email": email.strip().lower(),
            "personal_email": None,
            "lang": "Spanish",
            "name": name,
            "kindle_model_key": DEFAULT_KINDLE_MODEL_KEY,
            "kindle_model": default_model.get("label", "Kindle Básico (8 GB)"),
            "storage_total_mb": DEFAULT_STORAGE_TOTAL_MB,
            "storage_used_mb": 0.0,
            "books_sent_count": 0,
            "created_at": datetime.now().isoformat()
        }
    else:
        users[key]["kindle_email"] = email.strip().lower()
        if name:
            users[key]["name"] = name
    return save_users(users)

@_locked
def set_personal_email(user_id: int, email: Optional[str]) -> bool:
    """Sets or updates the user's personal regular email address."""
    users = load_users()
    key = str(user_id)
    cleaned = email.strip().lower() if email else None
    if key not in users:
        default_model = KINDLE_MODELS.get(DEFAULT_KINDLE_MODEL_KEY, {})
        users[key] = {
            "kindle_email": None,
            "personal_email": cleaned,
            "lang": "Spanish",
            "name": None,
            "kindle_model_key": DEFAULT_KINDLE_MODEL_KEY,
            "kindle_model": default_model.get("label", "Kindle Básico (8 GB)"),
            "storage_total_mb": DEFAULT_STORAGE_TOTAL_MB,
            "storage_used_mb": 0.0,
            "books_sent_count": 0,
            "created_at": datetime.now().isoformat()
        }
    else:
        users[key]["personal_email"] = cleaned
    return save_users(users)

@_locked
def set_kindle_model(user_id: int, model_key: str) -> bool:
    """Updates user's Kindle model profile and adjusts total capacity."""
    if model_key not in KINDLE_MODELS:
        return False
    model = KINDLE_MODELS[model_key]
    users = load_users()
    key = str(user_id)
    if key not in users:
        users[key] = {
            "kindle_email": None,
            "personal_email": None,
            "lang": "Spanish",
            "name": None,
            "kindle_model_key": model_key,
            "kindle_model": model["label"],
            "storage_total_mb": model["total_mb"],
            "storage_used_mb": 0.0,
            "books_sent_count": 0,
            "created_at": datetime.now().isoformat()
        }
    else:
        users[key]["kindle_model_key"] = model_key
        users[key]["kindle_model"] = model["label"]
        users[key]["storage_total_mb"] = model["total_mb"]
        # Ensure used space doesn't exceed new capacity
        current_used = float(users[key].get("storage_used_mb", 0.0))
        users[key]["storage_used_mb"] = min(current_used, model["total_mb"])
    return save_users(users)

@_locked
def set_kindle_free_space(user_id: int, free_mb: float) -> bool:
    """Calibrates Kindle remaining free space reported or selected by user."""
    users = load_users()
    key = str(user_id)
    if key not in users:
        default_model = KINDLE_MODELS.get(DEFAULT_KINDLE_MODEL_KEY, {})
        total_mb = DEFAULT_STORAGE_TOTAL_MB
        used_mb = max(0.0, total_mb - free_mb)
        users[key] = {
            "kindle_email": None,
            "personal_email": None,
            "lang": "Spanish",
            "name": None,
            "kindle_model_key": DEFAULT_KINDLE_MODEL_KEY,
            "kindle_model": default_model.get("label", "Kindle Básico (8 GB)"),
            "storage_total_mb": total_mb,
            "storage_used_mb": used_mb,
            "books_sent_count": 0,
            "created_at": datetime.now().isoformat()
        }
    else:
        total_mb = float(users[key].get("storage_total_mb", DEFAULT_STORAGE_TOTAL_MB))
        used_mb = max(0.0, total_mb - free_mb)
        users[key]["storage_used_mb"] = used_mb
    return save_users(users)

@_locked
def record_book_sent(
    user_id: int,
    size_bytes: int,
    is_kindle: bool = True,
    title: Optional[str] = None,
    author: Optional[str] = None,
    destination: str = "Kindle"
) -> dict:
    """Updates user stats, reading history, and accumulates Kindle storage consumption."""
    users = load_users()
    key = str(user_id)
    if key not in users:
        default_model = KINDLE_MODELS.get(DEFAULT_KINDLE_MODEL_KEY, {})
        users[key] = {
            "kindle_email": None,
            "personal_email": None,
            "lang": "Spanish",
            "name": None,
            "kindle_model_key": DEFAULT_KINDLE_MODEL_KEY,
            "kindle_model": default_model.get("label", "Kindle Básico (8 GB)"),
            "storage_total_mb": DEFAULT_STORAGE_TOTAL_MB,
            "storage_used_mb": 0.0,
            "books_sent_count": 0,
            "history": [],
            "created_at": datetime.now().isoformat()
        }

    user = users[key]
    user["books_sent_count"] = int(user.get("books_sent_count", 0)) + 1
    if is_kindle:
        size_mb = size_bytes / (1024 * 1024)
        current_used = float(user.get("storage_used_mb", 0.0))
        total_mb = float(user.get("storage_total_mb", DEFAULT_STORAGE_TOTAL_MB))
        user["storage_used_mb"] = min(total_mb, current_used + size_mb)

    if title:
        history = user.get("history", [])
        entry = {
            "title": title[:45],
            "author": author[:35] if author else "Autor desconocido",
            "destination": destination,
            "sent_at": datetime.now().strftime("%d/%m %H:%M")
        }
        history = [h for h in history if h.get("title") != entry["title"]]
        history.insert(0, entry)
        user["history"] = history[:5]

    save_users(users)
    return get_kindle_storage_info(user_id)

def get_user_history(user_id: int) -> list:
    """Retrieves the last 5 sent books for a user."""
    users = load_users()
    key = str(user_id)
    return users.get(key, {}).get("history", [])

def get_kindle_storage_info(user_id: int) -> dict:
    """
    Computes storage breakdown, remaining free megabytes, visual progress bar,
    and returns whether storage is critically low.
    """
    data = get_user_data(user_id)
    total_mb = data["storage_total_mb"]
    used_mb = data["storage_used_mb"]
    free_mb = max(0.0, total_mb - used_mb)
    percent_used = min(100.0, (used_mb / total_mb) * 100.0) if total_mb > 0 else 0.0

    # Build 10-block progress bar
    filled_blocks = min(10, max(0, int(round(percent_used / 10))))
    empty_blocks = 10 - filled_blocks
    progress_bar = f"[{'■' * filled_blocks}{'□' * empty_blocks}]"

    # Human-readable displays
    free_display = f"{free_mb / 1024:.1f} GB" if free_mb >= 1000 else f"{free_mb:.0f} MB"
    total_display = f"{total_mb / 1024:.1f} GB" if total_mb >= 1000 else f"{total_mb:.0f} MB"
    used_display = f"{used_mb / 1024:.1f} GB" if used_mb >= 1000 else f"{used_mb:.1f} MB"

    is_low = free_mb < LOW_STORAGE_THRESHOLD_MB

    return {
        "model": data["kindle_model"],
        "model_key": data["kindle_model_key"],
        "total_mb": total_mb,
        "used_mb": used_mb,
        "free_mb": free_mb,
        "percent_used": percent_used,
        "progress_bar": progress_bar,
        "free_display": free_display,
        "total_display": total_display,
        "used_display": used_display,
        "is_low": is_low
    }

@_locked
def set_amazon_authorized(user_id: int) -> bool:
    """Marks that the user has completed the Amazon email whitelist authorization."""
    users = load_users()
    key = str(user_id)
    if key not in users:
        return False
    users[key]["amazon_authorized"] = True
    return save_users(users)

@_locked
def set_user_lang(user_id: int, lang: Optional[str]) -> bool:
    """Sets or updates the user's default language."""
    users = load_users()
    key = str(user_id)
    if key not in users:
        default_model = KINDLE_MODELS.get(DEFAULT_KINDLE_MODEL_KEY, {})
        users[key] = {
            "kindle_email": None,
            "personal_email": None,
            "lang": lang,
            "name": None,
            "kindle_model_key": DEFAULT_KINDLE_MODEL_KEY,
            "kindle_model": default_model.get("label", "Kindle Básico (8 GB)"),
            "storage_total_mb": DEFAULT_STORAGE_TOTAL_MB,
            "storage_used_mb": 0.0,
            "books_sent_count": 0,
            "created_at": datetime.now().isoformat()
        }
    else:
        users[key]["lang"] = lang
    return save_users(users)
