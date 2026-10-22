import os
import json
import tempfile
import logging
from typing import Dict, Optional
from datetime import datetime
from gabook.config import USERS_FILE

logger = logging.getLogger(__name__)

def load_users() -> Dict[str, dict]:
    """Loads all registered users from USERS_FILE."""
    if not os.path.exists(USERS_FILE):
        return {}
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Error loading {USERS_FILE}: {e}")
        return {}

def save_users(users: Dict[str, dict]):
    """Saves users dictionary to USERS_FILE atomically to prevent file corruption."""
    dir_name = os.path.dirname(USERS_FILE) or "."
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile("w", dir=dir_name, delete=False, encoding="utf-8") as tf:
            json.dump(users, tf, indent=2, ensure_ascii=False)
            temp_name = tf.name
        os.replace(temp_name, USERS_FILE)
    except Exception as e:
        logger.error(f"Error saving {USERS_FILE}: {e}")
        if temp_name and os.path.exists(temp_name):
            try:
                os.remove(temp_name)
            except OSError:
                pass

def get_user_data(user_id: int) -> dict:
    """Retrieves configuration for a specific Telegram user."""
    users = load_users()
    key = str(user_id)
    if key not in users:
        return {
            "kindle_email": None,
            "lang": "Spanish",
            "name": None
        }
    return users[key]

def set_kindle_email(user_id: int, email: str, name: Optional[str] = None) -> bool:
    """Sets or updates the user's Kindle email address."""
    users = load_users()
    key = str(user_id)
    if key not in users:
        users[key] = {
            "kindle_email": email.strip().lower(),
            "lang": "Spanish",
            "name": name,
            "created_at": datetime.now().isoformat()
        }
    else:
        users[key]["kindle_email"] = email.strip().lower()
        if name:
            users[key]["name"] = name
    save_users(users)
    return True

def set_user_lang(user_id: int, lang: Optional[str]) -> bool:
    """Sets or updates the user's default language."""
    users = load_users()
    key = str(user_id)
    if key not in users:
        users[key] = {
            "kindle_email": None,
            "lang": lang,
            "name": None,
            "created_at": datetime.now().isoformat()
        }
    else:
        users[key]["lang"] = lang
    save_users(users)
    return True
