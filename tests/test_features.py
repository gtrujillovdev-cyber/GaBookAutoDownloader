import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

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

    def test_parse_size_helpers(self):
        """Verify size parsing helper functions."""
        from gabook.bot import parse_size_to_mb, parse_storage_text_to_mb
        self.assertAlmostEqual(parse_size_to_mb("2.5 MB"), 2.5)
        self.assertAlmostEqual(parse_size_to_mb("1024 kB"), 1.0)
        self.assertAlmostEqual(parse_size_to_mb("1 GB"), 1024.0)
        self.assertAlmostEqual(parse_size_to_mb(None), 1.5)

        self.assertEqual(parse_storage_text_to_mb("500 MB"), 500.0)
        self.assertEqual(parse_storage_text_to_mb("2.5 GB"), 2560.0)
        self.assertEqual(parse_storage_text_to_mb("150"), 150.0)
        self.assertIsNone(parse_storage_text_to_mb("nada"))

    def test_user_manager_personal_email_and_storage(self):
        """Verify personal email and storage telemetry in user_manager."""
        test_uid = 999888777
        user_manager.set_kindle_email(test_uid, "kindle_test@kindle.com", "Test User")
        user_manager.set_personal_email(test_uid, "personal_test@gmail.com")

        data = user_manager.get_user_data(test_uid)
        self.assertEqual(data["personal_email"], "personal_test@gmail.com")
        self.assertEqual(data["kindle_email"], "kindle_test@kindle.com")

        # Test model change
        user_manager.set_kindle_model(test_uid, "pw_16gb")
        info = user_manager.get_kindle_storage_info(test_uid)
        self.assertEqual(info["total_mb"], 13500.0)
        self.assertFalse(info["is_low"])

        # Test calibrate space to 150 MB (should trigger is_low)
        user_manager.set_kindle_free_space(test_uid, 150.0)
        info_low = user_manager.get_kindle_storage_info(test_uid)
        self.assertAlmostEqual(info_low["free_mb"], 150.0)
        self.assertTrue(info_low["is_low"], "Should be marked as low storage (<300 MB)")
        self.assertIn("■", info_low["progress_bar"])

        # Test book recording
        user_manager.record_book_sent(test_uid, size_bytes=5 * 1024 * 1024, is_kindle=True)
        info_after = user_manager.get_kindle_storage_info(test_uid)
        self.assertAlmostEqual(info_after["free_mb"], 145.0)

        # Cleanup
        users = user_manager.load_users()
        users.pop(str(test_uid), None)
        user_manager.save_users(users)

    @patch("smtplib.SMTP_SSL")
    def test_kindle_mailer_regular_email(self, mock_smtp):
        """Verify kindle_mailer formats message differently for regular vs kindle emails."""
        from gabook.services import kindle_mailer
        import tempfile

        with tempfile.NamedTemporaryFile("wb", suffix=".epub", delete=False) as tf:
            tf.write(b"dummy epub data")
            tf_path = tf.name

        try:
            with patch.object(kindle_mailer, "GMAIL_USER", "test@gmail.com"), \
                 patch.object(kindle_mailer, "GMAIL_APP_PASSWORD", "secret123"):
                
                # Test regular email
                success = kindle_mailer.send_to_kindle(tf_path, book_title="Don Quijote", recipient_email="amigo@gmail.com")
                self.assertTrue(success)
                server_instance = mock_smtp.return_value.__enter__.return_value
                self.assertTrue(server_instance.send_message.called)
                sent_msg = server_instance.send_message.call_args[0][0]
                self.assertEqual(sent_msg["To"], "amigo@gmail.com")
                self.assertIn("Don Quijote", sent_msg["Subject"])
        finally:
            if os.path.exists(tf_path):
                os.remove(tf_path)

    @patch("requests.get")
    def test_get_book_synopsis(self, mock_get):
        """Verify get_book_synopsis extracts first sentence cleanly."""
        from gabook.services.book_client import get_book_synopsis

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "docs": [{
                "first_sentence": "En un lugar de la Mancha de cuyo nombre no quiero acordarme."
            }]
        }
        mock_get.return_value = mock_resp

        synopsis = get_book_synopsis("Don Quijote", "Cervantes")
        self.assertIn("En un lugar de la Mancha", synopsis)

    def test_user_history_tracking(self):
        """Verify user history saves and caps at 5 books."""
        from gabook.bot import build_history_markup
        test_uid = 777666555

        # Record 6 books
        for i in range(6):
            user_manager.record_book_sent(
                test_uid,
                size_bytes=1024 * 1024,
                is_kindle=True,
                title=f"Libro {i}",
                author=f"Autor {i}",
                destination="Kindle"
            )

        history = user_manager.get_user_history(test_uid)
        self.assertEqual(len(history), 5, "History should keep max 5 recent books")
        self.assertEqual(history[0]["title"], "Libro 5", "Most recent should be first")

        text, markup = build_history_markup(test_uid)
        self.assertIn("MIS LIBROS RECIENTES", text)
        self.assertEqual(len(markup.inline_keyboard), 6)  # 5 books + back button

        # Cleanup
        users = user_manager.load_users()
        users.pop(str(test_uid), None)
        user_manager.save_users(users)

    def test_amazon_whitelist_markup(self):
        """Verify the 1-touch Amazon whitelist assistant generates proper links and instructions."""
        from gabook.bot import build_amazon_whitelist_markup
        from gabook.config import GMAIL_SENDER

        text, markup = build_amazon_whitelist_markup()
        self.assertIn("AUTORIZAR", text)
        self.assertIn(GMAIL_SENDER, text)
        self.assertIn("amazon.es", markup.inline_keyboard[0][0].url)
        self.assertIn("amazon.com", markup.inline_keyboard[1][0].url)

    def test_guide_markup(self):
        """Verify the user onboarding guide generates properly."""
        from gabook.bot import build_guide_markup
        from gabook.config import GMAIL_SENDER

        text, markup = build_guide_markup()
        self.assertIn("GUÍA", text)
        self.assertIn(GMAIL_SENDER, text)
        self.assertTrue(len(markup.inline_keyboard) >= 3)

    def test_tutorial_markup_flow(self):
        """Verify the interactive onboarding tutorial markups."""
        from gabook.bot import (
            build_tutorial_start_markup,
            build_tutorial_mobile_markup,
            build_tutorial_kindle_step1_markup,
            build_tutorial_kindle_step2_markup
        )
        from gabook.config import GMAIL_SENDER

        # Step 0: Choice of device
        t0_text, t0_markup = build_tutorial_start_markup()
        self.assertIn("TUTORIAL DE INICIO", t0_text)
        self.assertEqual(len(t0_markup.inline_keyboard), 3)

        # Mobile path
        m_text, m_markup = build_tutorial_mobile_markup()
        self.assertIn("MÓVIL", m_text)
        self.assertTrue(len(m_markup.inline_keyboard) >= 3)

        # Kindle Step 1: Whitelist
        k1_text, k1_markup = build_tutorial_kindle_step1_markup()
        self.assertIn("Paso 1 de 2", k1_text)
        self.assertIn(GMAIL_SENDER, k1_text)
        self.assertIn("amazon.es", k1_markup.inline_keyboard[0][0].url)

        # Kindle Step 2: Link Kindle
        k2_text, k2_markup = build_tutorial_kindle_step2_markup()
        self.assertIn("Paso 2 de 2", k2_text)
        self.assertTrue(len(k2_markup.inline_keyboard) >= 3)
        # Ensure no personal family names leaked into tutorial
        self.assertNotIn("Papá", k2_text)
        self.assertNotIn("Gonzalo", k2_text)

    def test_streamlined_menus_and_zero_personal_data(self):
        """Verify streamlined keyboards and complete absence of hardcoded personal names."""
        from gabook.bot import (
            build_preset_keyboard,
            build_profile_markup,
            MAIN_KEYBOARD
        )
        # 1. build_preset_keyboard by default should not contain family presets
        kb = build_preset_keyboard()
        btn_texts = [btn.text for row in kb.inline_keyboard for btn in row]
        for t in btn_texts:
            self.assertNotIn("Papá", t)
            self.assertNotIn("Gonzalo", t)
            self.assertNotIn("familiar", t.lower())

        # 2. build_profile_markup structure
        test_uid = 123456789
        p_text, p_markup = build_profile_markup(test_uid)
        self.assertIn("MI PERFIL Y PREFERENCIAS", p_text)
        callbacks = [btn.callback_data for row in p_markup.inline_keyboard for btn in row]
        self.assertIn("menu:advanced_settings", callbacks)
        self.assertIn("menu:kindle", callbacks)
        self.assertIn("menu:set_personal_email", callbacks)

        # 3. Main bottom keyboard verification
        main_btns = [btn.text for row in MAIN_KEYBOARD.keyboard for btn in row]
        self.assertIn("🔍 Buscar Libro", main_btns)
        self.assertIn("📚 Explorar Temas", main_btns)
        self.assertIn("👤 Mi Perfil", main_btns)
        self.assertIn("📖 Cómo Funciona", main_btns)

    def test_start_command_single_clean_bubble(self):
        """Verify that /start command sends a single clean message with MAIN_KEYBOARD without duplicate bubbles."""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock
        from gabook.bot import start_command, MAIN_KEYBOARD

        mock_user = MagicMock()
        mock_user.id = 999999
        mock_user.first_name = "Gabriel"

        mock_message = MagicMock()
        mock_message.reply_text = AsyncMock()

        mock_update = MagicMock()
        mock_update.effective_user = mock_user
        mock_update.callback_query = None
        mock_update.message = mock_message

        mock_context = MagicMock()

        asyncio.run(start_command(mock_update, mock_context))

        # Exactly 1 message must be sent to the user
        self.assertEqual(mock_message.reply_text.call_count, 1)
        args, kwargs = mock_message.reply_text.call_args
        self.assertIn("¡Hola Gabriel! Bienvenido a GaBook", args[0])
        self.assertEqual(kwargs.get("reply_markup"), MAIN_KEYBOARD)

    def test_telegram_direct_download_execution(self):
        """Verify that direct Telegram download pipeline runs smoothly, cleans filenames, uploads document, and deletes temp file."""
        import asyncio
        import tempfile
        from gabook.bot import execute_book_send, SEARCH_SESSIONS

        test_sid = "test_tg_session"
        SEARCH_SESSIONS[test_sid] = {
            "books": [{
                "title": "El Señor de los Anillos: La Comunidad",
                "author": "J.R.R. Tolkien",
                "size": "2.5 MB",
                "lang": "Spanish"
            }],
            "created_at": time.time()
        }

        # Create real temp file to simulate downloaded epub
        with tempfile.NamedTemporaryFile("wb", suffix=".epub", delete=False) as tf:
            tf.write(b"dummy epub data" * 100)
            tf_path = tf.name

        mock_bot = MagicMock()
        mock_bot.send_chat_action = AsyncMock()
        mock_bot.send_document = AsyncMock()

        mock_target_msg = MagicMock()
        mock_target_msg.chat_id = 12345
        mock_target_msg.edit_text = AsyncMock()
        mock_target_msg.get_bot.return_value = mock_bot

        try:
            with patch("gabook.bot.download_epub", return_value=tf_path):
                asyncio.run(execute_book_send(
                    mock_target_msg,
                    user_id=888888,
                    session_id=test_sid,
                    idx=0,
                    target_email="telegram",
                    is_kindle=False
                ))

            # Verify send_document was called with cleaned filename
            self.assertTrue(mock_bot.send_document.called)
            doc_kwargs = mock_bot.send_document.call_args[1]
            self.assertEqual(doc_kwargs["filename"], "El Señor de los Anillos La Comunidad.epub")
            self.assertIn("El Señor de los Anillos", doc_kwargs["caption"])

            # Verify temp file was removed
            self.assertFalse(os.path.exists(tf_path), "Downloaded EPUB was not cleaned up!")

            # Verify completion message
            final_edit_args = mock_target_msg.edit_text.call_args[0][0]
            self.assertIn("¡Operación completada!", final_edit_args)
            self.assertIn("Libro subido con éxito y listo para leer en Telegram", final_edit_args)

        finally:
            SEARCH_SESSIONS.pop(test_sid, None)
            if os.path.exists(tf_path):
                os.remove(tf_path)

    def test_send_confirmed_fallback_kindle_email(self):
        """Verify send_confirmed callback resolves DEFAULT_KINDLE_EMAIL without NameError when profile has none."""
        import asyncio
        from gabook.bot import button_callback
        from gabook.config import DEFAULT_KINDLE_EMAIL

        mock_query = MagicMock()
        mock_query.data = "send_confirmed:test_sid:0:kindle"
        mock_query.answer = AsyncMock()
        mock_query.message = MagicMock()
        mock_query.message.edit_text = AsyncMock()

        mock_user = MagicMock()
        mock_user.id = 555444333
        mock_user.first_name = "UserWithoutKindle"

        mock_update = MagicMock()
        mock_update.callback_query = mock_query
        mock_update.effective_user = mock_user

        mock_context = MagicMock()

        with patch("gabook.bot.get_user_data", return_value={"kindle_email": None}), \
             patch("gabook.bot.execute_book_send", new_callable=AsyncMock) as mock_send:
            asyncio.run(button_callback(mock_update, mock_context))
            self.assertTrue(mock_send.called)
            self.assertEqual(mock_send.call_args[1]["target_email"], DEFAULT_KINDLE_EMAIL)

    def test_expired_session_callbacks(self):
        """Verify that clicking callbacks on expired sessions responds cleanly without unhandled crashes."""
        import asyncio
        from gabook.bot import button_callback, execute_book_send

        # Test execute_book_send with expired session
        target_msg = MagicMock()
        target_msg.edit_text = AsyncMock()
        asyncio.run(execute_book_send(target_msg, user_id=123, session_id="nonexistent_sess", idx=0, target_email="telegram", is_kindle=False))
        target_msg.edit_text.assert_called_once_with("⚠️ La sesión de búsqueda ha caducado. Vuelve a escribir el título.")

        # Test callbacks on expired session
        test_actions = [
            ("dl:nonexistent_sess:0", "⚠️ La sesión de búsqueda ha caducado"),
            ("send_choice:nonexistent_sess:0:telegram", "⚠️ La sesión de búsqueda ha caducado"),
            ("more_author:nonexistent_sess:0", "⚠️ La sesión de búsqueda ha caducado"),
            ("page:nonexistent_sess:1", "⚠️ Sesión caducada"),
            ("back:nonexistent_sess", "⚠️ Sesión caducada")
        ]

        for callback_data, expected_text in test_actions:
            mock_query = MagicMock()
            mock_query.data = callback_data
            mock_query.answer = AsyncMock()
            mock_query.edit_message_text = AsyncMock()

            mock_user = MagicMock()
            mock_user.id = 12345
            mock_user.first_name = "Tester"

            mock_update = MagicMock()
            mock_update.callback_query = mock_query
            mock_update.effective_user = mock_user

            mock_context = MagicMock()

            asyncio.run(button_callback(mock_update, mock_context))
            self.assertTrue(mock_query.edit_message_text.called, f"Failed for {callback_data}")
            call_text = mock_query.edit_message_text.call_args[0][0]
            self.assertIn(expected_text, call_text)

    def test_clean_filename_edge_cases(self):
        """Verify clean_filename handles path traversal, illegal characters, empty strings, and None."""
        self.assertEqual(clean_filename("../../etc/passwd"), "....etcpasswd")
        cleaned = clean_filename("Book / : * ? \" < > | Title")
        for bad_char in ['/', '\\', ':', '*', '?', '"', '<', '>', '|']:
            self.assertNotIn(bad_char, cleaned)
        self.assertIn("Book", cleaned)
        self.assertIn("Title", cleaned)
        self.assertEqual(clean_filename(""), "")
        self.assertEqual(clean_filename("   "), "")
        self.assertEqual(clean_filename(None), "")

    def test_is_valid_email_edge_cases(self):
        """Verify is_valid_email accurately identifies valid and invalid email inputs."""
        from gabook.bot import is_valid_email
        self.assertTrue(is_valid_email("test@gmail.com"))
        self.assertTrue(is_valid_email("lector@kindle.com"))
        self.assertTrue(is_valid_email("name+tag@sub.domain.org"))
        self.assertTrue(is_valid_email("  padded@kindle.com  "))

        self.assertFalse(is_valid_email(""))
        self.assertFalse(is_valid_email("   "))
        self.assertFalse(is_valid_email(None))
        self.assertFalse(is_valid_email("notanemail"))
        self.assertFalse(is_valid_email("user@"))
        self.assertFalse(is_valid_email("@kindle.com"))
        self.assertFalse(is_valid_email("user @domain.com"))

    def test_parse_storage_text_edge_cases(self):
        """Verify parse_storage_text_to_mb handles various formats and invalid inputs gracefully."""
        from gabook.bot import parse_storage_text_to_mb
        self.assertEqual(parse_storage_text_to_mb("500 MB"), 500.0)
        self.assertEqual(parse_storage_text_to_mb("2.5 GB"), 2560.0)
        self.assertEqual(parse_storage_text_to_mb("1,5 gb"), 1536.0)
        self.assertEqual(parse_storage_text_to_mb("100"), 100.0)
        self.assertIsNone(parse_storage_text_to_mb("no numbers here"))
        self.assertIsNone(parse_storage_text_to_mb(""))
        self.assertIsNone(parse_storage_text_to_mb(None))

    def test_kindle_models_telemetry_complete(self):
        """Verify all hardware models in KINDLE_MODELS are valid and compute storage telemetry accurately."""
        from gabook.config import KINDLE_MODELS
        test_uid = 11223344

        for model_key, spec in KINDLE_MODELS.items():
            self.assertIn("label", spec)
            self.assertIn("total_mb", spec)
            self.assertTrue(spec["total_mb"] > 0)

            user_manager.set_kindle_model(test_uid, model_key)
            info = user_manager.get_kindle_storage_info(test_uid)
            self.assertEqual(info["model_key"], model_key)
            self.assertEqual(info["total_mb"], spec["total_mb"])
            self.assertEqual(info["progress_bar"], "[□□□□□□□□□□]")

        # Cleanup
        users = user_manager.load_users()
        users.pop(str(test_uid), None)
        user_manager.save_users(users)

    def test_file_size_limit_guards(self):
        """Verify file size guard blocks oversized files (> 22 MB) both in mailer and execute_book_send."""
        import asyncio
        import tempfile
        from gabook.services import kindle_mailer
        from gabook.bot import execute_book_send, SEARCH_SESSIONS

        test_sid = "test_oversized"
        SEARCH_SESSIONS[test_sid] = {
            "books": [{"title": "Enciclopedia Gigante", "author": "Varios", "size": "30 MB", "lang": "Spanish"}],
            "created_at": time.time()
        }

        with tempfile.NamedTemporaryFile("wb", suffix=".epub", delete=False) as tf:
            tf.write(b"dummy")
            tf_path = tf.name

        try:
            # 1. Test kindle_mailer size guard
            with patch("os.path.getsize", return_value=25 * 1024 * 1024):
                result = kindle_mailer.send_to_kindle(tf_path, book_title="Oversized", recipient_email="test@kindle.com")
                self.assertFalse(result, "send_to_kindle should reject files > 22 MB")

            # 2. Test execute_book_send size guard
            mock_target_msg = MagicMock()
            mock_target_msg.edit_text = AsyncMock()

            with patch("gabook.bot.download_epub", return_value=tf_path), \
                 patch("os.path.getsize", return_value=25 * 1024 * 1024):
                asyncio.run(execute_book_send(
                    mock_target_msg,
                    user_id=123,
                    session_id=test_sid,
                    idx=0,
                    target_email="test@kindle.com",
                    is_kindle=True
                ))

            # Verify edit_text showed the oversized file warning
            self.assertTrue(mock_target_msg.edit_text.called)
            warning_text = mock_target_msg.edit_text.call_args[0][0]
            self.assertIn("El archivo es demasiado grande", warning_text)
            self.assertIn("25.0 MB", warning_text)

        finally:
            SEARCH_SESSIONS.pop(test_sid, None)
            if os.path.exists(tf_path):
                os.remove(tf_path)

    @patch("smtplib.SMTP_SSL")
    def test_kindle_mailer_smtp_failure_handling(self, mock_smtp):
        """Verify kindle_mailer catches SMTP exceptions gracefully without crashing."""
        import smtplib
        import tempfile
        from gabook.services import kindle_mailer

        mock_smtp.side_effect = smtplib.SMTPConnectError(421, "Connection refused")

        with tempfile.NamedTemporaryFile("wb", suffix=".epub", delete=False) as tf:
            tf.write(b"data")
            tf_path = tf.name

        try:
            with patch.object(kindle_mailer, "GMAIL_USER", "test@gmail.com"), \
                 patch.object(kindle_mailer, "GMAIL_APP_PASSWORD", "secret123"):
                success = kindle_mailer.send_to_kindle(tf_path, book_title="Test", recipient_email="test@kindle.com")
                self.assertFalse(success)
        finally:
            if os.path.exists(tf_path):
                os.remove(tf_path)

    @patch("imaplib.IMAP4_SSL")
    @patch("gabook.services.gmail_monitor.verify_amazon_link")
    def test_gmail_monitor_auto_verification(self, mock_verify, mock_imap_cls):
        """Verify monitor_kindle_delivery detects Amazon verification email and approves it."""
        from gabook.services.gmail_monitor import monitor_kindle_delivery

        mock_mail = MagicMock()
        mock_imap_cls.return_value = mock_mail
        mock_mail.search.side_effect = [
            ("OK", [b""]),          # initial check
            ("OK", [b"101"])        # loop detection: new email 101
        ]

        raw_email = (
            b"From: kindle-delivery@amazon.es\r\n"
            b"Subject: Verificar solicitud de documento de Kindle\r\n\r\n"
            b"Haz clic en el enlace para verificar tu documento:\r\n"
            b"https://www.amazon.es/gp/f.html?verification=xyz123\r\n"
        )
        mock_mail.fetch.return_value = ("OK", [(b"101 (RFC822 {150}", raw_email)])
        mock_verify.return_value = True

        with patch("gabook.services.gmail_monitor.GMAIL_USER", "user@gmail.com"), \
             patch("gabook.services.gmail_monitor.GMAIL_APP_PASSWORD", "pass123"):
            result = monitor_kindle_delivery(timeout_seconds=2, poll_interval=0.1)
            self.assertEqual(result["status"], "verified_auto")
            self.assertIn("aprobó automáticamente", result["message"])
            self.assertTrue(mock_mail.logout.called)

    @patch("imaplib.IMAP4_SSL")
    def test_gmail_monitor_rejection_detection(self, mock_imap_cls):
        """Verify monitor_kindle_delivery detects Amazon rejection email."""
        from gabook.services.gmail_monitor import monitor_kindle_delivery

        mock_mail = MagicMock()
        mock_imap_cls.return_value = mock_mail
        mock_mail.search.side_effect = [
            ("OK", [b""]),
            ("OK", [b"202"])
        ]

        raw_email = (
            b"From: kindle-delivery@amazon.es\r\n"
            b"Subject: Problema con el documento enviado a tu Kindle\r\n\r\n"
            b"El formato del documento no ha podido ser procesado.\r\n"
        )
        mock_mail.fetch.return_value = ("OK", [(b"202 (RFC822 {150}", raw_email)])

        with patch("gabook.services.gmail_monitor.GMAIL_USER", "user@gmail.com"), \
             patch("gabook.services.gmail_monitor.GMAIL_APP_PASSWORD", "pass123"):
            result = monitor_kindle_delivery(timeout_seconds=2, poll_interval=0.1)
            self.assertEqual(result["status"], "rejected")
            self.assertIn("rechazó el documento", result["message"])

    @patch("gabook.services.book_client.search_libgen")
    @patch("gabook.services.book_client.search_archive_org")
    @patch("gabook.services.book_client.search_openlibrary")
    @patch("gabook.services.book_client.search_gutenberg")
    def test_search_epubs_network_error_resilience(self, mock_gut, mock_ol, mock_ia, mock_lg):
        """Verify search_epubs handles source errors and timeouts gracefully without crashing."""
        mock_lg.side_effect = Exception("Libgen connection timeout")
        mock_ia.side_effect = Exception("Archive.org 503 Service Unavailable")
        mock_ol.return_value = []
        mock_gut.return_value = []

        matching, others = search_epubs("Error Prone Search", max_results=5, target_lang="Spanish")
        self.assertEqual(matching, [])
        self.assertEqual(others, [])

    def test_security_sanitization_and_ignore_rules(self):
        """Verify that .gitignore and .dockerignore contain all required exclusion rules and no real credentials leak."""
        from gabook.config import PROJECT_ROOT

        # 1. Check .gitignore
        gitignore_path = PROJECT_ROOT / ".gitignore"
        self.assertTrue(gitignore_path.exists())
        gitignore_content = gitignore_path.read_text(encoding="utf-8")
        self.assertIn(".env", gitignore_content)
        self.assertIn("users.json", gitignore_content)

        # 2. Check .dockerignore
        dockerignore_path = PROJECT_ROOT / ".dockerignore"
        self.assertTrue(dockerignore_path.exists())
        dockerignore_content = dockerignore_path.read_text(encoding="utf-8")
        self.assertIn(".env", dockerignore_content)
        self.assertIn("users.json", dockerignore_content)

        # 3. Check users.example.json contains only dummy data
        example_users_path = PROJECT_ROOT / "users.example.json"
        self.assertTrue(example_users_path.exists())
        example_users_text = example_users_path.read_text(encoding="utf-8")
        self.assertIn("ejemplo@kindle.com", example_users_text)
        self.assertIn("tu_correo@gmail.com", example_users_text)

        # 4. Check .env.example contains only placeholders
        env_example_path = PROJECT_ROOT / ".env.example"
        self.assertTrue(env_example_path.exists())
        env_example_text = env_example_path.read_text(encoding="utf-8")
        self.assertIn("tu_token_de_telegram_aqui", env_example_text)
        self.assertIn("tu_correo@gmail.com", env_example_text)

if __name__ == "__main__":
    unittest.main()
