import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add src to sys.path so tests can run cleanly from any directory
SRC_DIR = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC_DIR))

from gabook.config import (
    TOPICS,
    TOPICS_PAGE_SIZE,
    DOWNLOADS_DIR
)
from gabook.bot import (
    build_topics_markup,
    cleanup_downloads_dir,
    escape_md,
    cleanup_expired_sessions,
    SEARCH_SESSIONS
)
from gabook.services.book_client import (
    search_epubs,
    parse_query_and_language,
    clean_filename
)
from gabook.services import user_manager

from gabook.services.health_server import start_health_server
import urllib.request
import json

class TestBotFeatures(unittest.TestCase):
    def test_topics_structure(self):
        """Verify that TOPICS has 24 categories and valid fields."""
        self.assertEqual(len(TOPICS), 24, "Should have exactly 24 topics")
        self.assertEqual(TOPICS_PAGE_SIZE, 8, "Page size should be 8")

        for idx, t in enumerate(TOPICS):
            self.assertIn("label", t, f"Topic {idx} missing label")
            self.assertIn("query", t, f"Topic {idx} missing query")
            self.assertIn("title", t, f"Topic {idx} missing title")
            self.assertTrue(len(t["label"]) > 0)
            self.assertTrue(len(t["query"]) > 0)

    def test_topics_pagination(self):
        """Verify pagination produces 3 pages with correct button counts."""
        for page in range(3):
            text, markup = build_topics_markup(page)
            self.assertIn("Explorador por Temáticas", text)
            self.assertIn(f"Página {page + 1} de 3", text)
            self.assertIn("24 géneros disponibles", text)
            # 8 buttons arranged in 4 rows of 2, plus nav row, plus cancel row = 6 rows
            self.assertEqual(len(markup.inline_keyboard), 6, f"Page {page} should have 6 rows")

    def test_cleanup_downloads(self):
        """Verify that stale digital waste in downloads/ is deleted."""
        os.makedirs(DOWNLOADS_DIR, exist_ok=True)
        test_file = os.path.join(DOWNLOADS_DIR, "test_garbage_delete_me.epub")
        with open(test_file, "w") as f:
            f.write("fake epub data")
        self.assertTrue(os.path.exists(test_file))

        cleanup_downloads_dir()
        self.assertFalse(os.path.exists(test_file), "Stale epub was not deleted!")

    def test_escape_md(self):
        """Verify that escape_md properly escapes Telegram Markdown v1 entities."""
        self.assertEqual(escape_md("Dune"), "Dune")
        self.assertEqual(escape_md("Don_Quijote"), "Don\\_Quijote")
        self.assertEqual(escape_md("C++ [Guía]"), "C++ \\[Guía]")
        self.assertEqual(escape_md("*Negrita* y `codigo`"), "\\*Negrita\\* y \\`codigo\\`")
        self.assertEqual(escape_md(""), "")
        self.assertEqual(escape_md(None), "")

    def test_session_cleanup(self):
        """Verify cleanup_expired_sessions removes expired sessions."""
        SEARCH_SESSIONS["old_session"] = {
            "books": [],
            "created_at": 1000  # Far in the past
        }
        SEARCH_SESSIONS["new_session"] = {
            "books": [],
            "created_at": 9999999999  # Far in the future
        }
        cleanup_expired_sessions()
        self.assertNotIn("old_session", SEARCH_SESSIONS)
        self.assertIn("new_session", SEARCH_SESSIONS)
        SEARCH_SESSIONS.pop("new_session", None)

    def test_clean_filename(self):
        """Verify clean_filename sanitizes invalid characters."""
        self.assertEqual(clean_filename("Libro / Test : 123 *?"), "Libro  Test  123")
        self.assertEqual(clean_filename("Dune.epub"), "Dune.epub")

    def test_parse_query_and_language(self):
        """Verify natural language language detection."""
        q, lang = parse_query_and_language("1984 en inglés", default_lang="Spanish")
        self.assertEqual(q, "1984")
        self.assertEqual(lang, "English")

        q2, lang2 = parse_query_and_language("El principito [fr]", default_lang="Spanish")
        self.assertEqual(q2, "El principito")
        self.assertEqual(lang2, "French")

    def test_user_manager_atomic_roundtrip(self):
        """Verify user_manager load and atomic save."""
        users = user_manager.load_users()
        self.assertIsInstance(users, dict)
        user_manager.save_users(users)
        users_after = user_manager.load_users()
        self.assertEqual(users, users_after)

    @patch("gabook.services.book_client.search_libgen")
    @patch("gabook.services.book_client.search_archive_org")
    @patch("gabook.services.book_client.search_openlibrary")
    @patch("gabook.services.book_client.search_gutenberg")
    def test_search_epubs_integration(self, mock_gut, mock_ol, mock_ia, mock_lg):
        """Verify search_epubs merges results and handles deduplication."""
        mock_lg.return_value = [{"title": "Historia de Roma", "author": "Mommsen", "lang": "Spanish", "size": "1 MB"}]
        mock_ia.return_value = [{"title": "Historia de Roma", "author": "Mommsen", "lang": "Spanish", "size": "1 MB"}]
        mock_ol.return_value = []
        mock_gut.return_value = []

        matching, others = search_epubs("Roma", max_results=5, target_lang="Spanish")
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["title"], "Historia de Roma")

    def test_health_server_unit(self):
        """Verify the health check HTTP server handler works hermetically."""
        from gabook.services.health_server import HealthCheckHandler, start_health_server
        import io

        # 1. Without port or PORT env, should return None
        with patch.dict(os.environ, {}, clear=True):
            server = start_health_server(port=None)
            self.assertIsNone(server)

        # 2. Test HealthCheckHandler do_GET logic directly
        handler = HealthCheckHandler.__new__(HealthCheckHandler)
        handler.wfile = io.BytesIO()
        handler.send_response = MagicMock()
        handler.send_header = MagicMock()
        handler.end_headers = MagicMock()

        handler.do_GET()

        handler.send_response.assert_called_once_with(200)
        payload = json.loads(handler.wfile.getvalue().decode("utf-8"))
        self.assertEqual(payload.get("status"), "healthy")
        self.assertEqual(payload.get("service"), "GaBookAutoDownloader")

if __name__ == "__main__":
    unittest.main()
