import os
import sys
import json
import tempfile
import unittest
from unittest.mock import patch, MagicMock
from PIL import Image

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

import argon_overlay_translator as aot


app = QApplication.instance() or QApplication(sys.argv)


class TestArgonOverlayTranslator(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = os.path.join(self.temp_dir.name, "config.json")

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_github_url_normalization(self):
        """Verify GitHub repository URL converts cleanly to raw.githubusercontent.com URL."""
        repo_url = "https://github.com/HocTrinh-dev/overlay-translater.git"
        expected = "https://raw.githubusercontent.com/HocTrinh-dev/overlay-translater/main/argon_overlay_translator.py"
        self.assertEqual(aot.normalize_github_raw_url(repo_url), expected)

        blob_url = "https://github.com/HocTrinh-dev/overlay-translater/blob/main/argon_overlay_translator.py"
        self.assertEqual(aot.normalize_github_raw_url(blob_url), expected)

    @patch("argon_overlay_translator.keyboard.add_hotkey")
    def test_task1_persistent_config_save_and_load(self, mock_hotkey):
        """Verify Task 1: Saving and loading user settings and HUD geometry via config.json."""
        studio = aot.MainStudioWindow(config_path=self.config_path)
        studio.txt_url.setText("https://custom.llm.endpoint/v1/chat/completions")
        studio.txt_model.setText("gpt-4o")
        studio.txt_key.setText("sk-test-secret-123")
        studio.cb_src.setCurrentIndex(2)  # Japanese (jpn)
        studio.cb_dst.setCurrentIndex(1)  # English
        studio.sp_interval.setValue(7)
        studio.overlay_hud.setGeometry(120, 140, 640, 300)

        # Trigger closeEvent which saves config.json
        studio.close()
        self.assertTrue(os.path.exists(self.config_path))

        # Re-open new MainStudioWindow and verify all settings are restored
        studio2 = aot.MainStudioWindow(config_path=self.config_path)
        self.assertEqual(studio2.txt_url.text(), "https://custom.llm.endpoint/v1/chat/completions")
        self.assertEqual(studio2.txt_model.text(), "gpt-4o")
        self.assertEqual(studio2.txt_key.text(), "sk-test-secret-123")
        self.assertEqual(studio2.cb_src.currentText(), "Japanese (jpn)")
        self.assertEqual(studio2.cb_dst.currentText(), "English")
        self.assertEqual(studio2.sp_interval.value(), 7)
        geo = studio2.overlay_hud.geometry()
        self.assertEqual([geo.x(), geo.y(), geo.width(), geo.height()], [120, 140, 640, 300])
        self.assertEqual(studio2.update_url, aot.DEFAULT_UPDATE_URL)
        studio2.close()

    @patch("argon_overlay_translator.keyboard.add_hotkey")
    @patch("argon_overlay_translator.QTimer.singleShot")
    def test_invariant1_two_phase_anti_self_ocr_capture(self, mock_single_shot, mock_hotkey):
        """Verify Invariant 1: 2-Phase Anti Self-OCR sets is_capturing=True and waits 45ms."""
        studio = aot.MainStudioWindow(config_path=self.config_path)
        studio.initiate_capture_and_translate()

        self.assertTrue(studio.overlay_hud.is_capturing)
        mock_single_shot.assert_called_once_with(45, studio._perform_screen_grab)
        studio.close()

    def test_invariant4_batch_contextual_llm_translation(self):
        """Verify Invariant 4: OCR words group by line and translate as a single JSON array batch."""
        dummy_img = Image.new("RGB", (200, 80), color=(0, 0, 0))
        worker = aot.TranslationWorker(
            pil_img=dummy_img,
            tess_lang="eng",
            target_lang="Vietnamese",
            api_url="https://api.openai.com/v1/chat/completions",
            api_key="sk-mock",
            model_name="gpt-4o-mini",
            last_raw_text=""
        )

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": '["Xin chào", "Thế giới"]'}}]
        }
        with patch("argon_overlay_translator.requests.post", return_value=mock_resp) as mock_post:
            result = worker.translate_batch_with_context(["Hello", "World"])
            self.assertEqual(result, ["Xin chào", "Thế giới"])
            mock_post.assert_called_once()

    def test_invariant5_click_through_lock_mode(self):
        """Verify Invariant 5: Locking HUD enables Qt.WindowTransparentForInput."""
        hud = aot.FloatingOverlayHUD()
        hud.set_locked(True)
        self.assertTrue(hud.is_locked)
        self.assertTrue(bool(hud.windowFlags() & Qt.WindowTransparentForInput))

        hud.set_locked(False)
        self.assertFalse(hud.is_locked)
        self.assertFalse(bool(hud.windowFlags() & Qt.WindowTransparentForInput))
        hud.close()

    def test_hot_update_worker_downloads_and_detects_changes(self):
        """Verify HotUpdateWorker detects local/git changes and downloads from GitHub Raw."""
        target_script = os.path.join(self.temp_dir.name, "argon_overlay_translator.py")
        old_code = "# Old version\nclass MainStudioWindow:\n    pass\n"
        with open(target_script, "w", encoding="utf-8") as f:
            f.write(old_code)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "# New version v2\nclass MainStudioWindow:\n    pass\n"

        results = []
        worker = aot.HotUpdateWorker(aot.DEFAULT_UPDATE_URL, target_script, running_snapshot=old_code)
        worker.finished_signal.connect(lambda restart, msg: results.append((restart, msg)))

        with patch("argon_overlay_translator.requests.get", return_value=mock_resp):
            worker.run()

        self.assertEqual(len(results), 1)
        self.assertTrue(results[0][0])
        with open(target_script, "r", encoding="utf-8") as f:
            self.assertIn("# New version v2", f.read())

        # Also verify that if disk code was updated locally or via git pull, it triggers hot-restart
        # without needing raw.githubusercontent.com (supporting Private GitHub repos)
        results_local = []
        worker_local = aot.HotUpdateWorker(aot.DEFAULT_UPDATE_URL, target_script, running_snapshot=old_code)
        worker_local.finished_signal.connect(lambda restart, msg: results_local.append((restart, msg)))
        worker_local.run()
        self.assertEqual(len(results_local), 1)
        self.assertTrue(results_local[0][0])

    @patch("argon_overlay_translator.keyboard.add_hotkey")
    def test_ui_dropdown_and_input_heights(self, mock_hotkey):
        """Verify dropdowns and inputs have proper height (>= 36px) and QListView popup views."""
        studio = aot.MainStudioWindow(config_path=self.config_path)
        studio.show()
        self.assertGreaterEqual(studio.cb_src.height(), 36)
        self.assertGreaterEqual(studio.cb_dst.height(), 36)
        self.assertGreaterEqual(studio.cb_mode.height(), 36)
        self.assertGreaterEqual(studio.txt_url.height(), 36)
        self.assertGreaterEqual(studio.txt_model.height(), 36)
        self.assertGreaterEqual(studio.txt_key.height(), 36)
        self.assertIsInstance(studio.cb_src.view(), aot.QListView)
        self.assertIsInstance(studio.cb_dst.view(), aot.QListView)
        self.assertIsInstance(studio.cb_mode.view(), aot.QListView)
        studio.close()

    @patch("argon_overlay_translator.keyboard.add_hotkey")
    @patch("argon_overlay_translator.QTimer.singleShot")
    def test_fullscreen_and_snip_region_modes(self, mock_single_shot, mock_hotkey):
        """Verify switching between Full Screen and Region Box modes, and Snipping Region selection."""
        studio = aot.MainStudioWindow(config_path=self.config_path)
        custom_rect = aot.QRect(180, 210, 480, 200)
        studio.overlay_hud.setGeometry(custom_rect)

        # Switch to Full Screen mode (index 1)
        studio.cb_mode.setCurrentIndex(1)
        self.assertTrue(studio.overlay_hud.is_fullscreen)
        self.assertTrue(studio.overlay_hud.is_locked)
        screen_geo = QApplication.primaryScreen().geometry()
        self.assertEqual(studio.overlay_hud.geometry().width(), screen_geo.width())
        self.assertEqual(studio.overlay_hud.geometry().height(), screen_geo.height())

        # Switch back to Region Box mode (index 0) and verify custom_rect is restored
        studio.cb_mode.setCurrentIndex(0)
        self.assertFalse(studio.overlay_hud.is_fullscreen)
        self.assertEqual(studio.overlay_hud.geometry(), custom_rect)

        # Simulate snipping a new region via RegionSnipperOverlay
        snipped_rect = aot.QRect(250, 300, 500, 160)
        studio.cb_mode.setCurrentIndex(1)  # Even from Full Screen mode
        studio._on_region_snipped(snipped_rect)
        self.assertEqual(studio.cb_mode.currentIndex(), 0)
        self.assertFalse(studio.overlay_hud.is_fullscreen)
        self.assertEqual(studio.overlay_hud.geometry(), snipped_rect)
        studio.close()

    def test_codex_and_persistent_translation_cache(self):
        """Verify Game Codex lookup, Names.txt import, Persistent Cache, Fuzzy OCR match, and Partial Batch AI skip."""
        codex_path = os.path.join(self.temp_dir.name, "codex.json")
        cache_path = os.path.join(self.temp_dir.name, "translation_cache.json")
        names_file = os.path.join(self.temp_dir.name, "Names.txt")

        with open(names_file, "w", encoding="utf-8") as f:
            f.write("青云门=Thanh Vân Môn|Phe phái (Faction)|Môn phái chính đạo\n")

        mgr = aot.TranslationKnowledgeManager(codex_path=codex_path, cache_path=cache_path)
        self.assertEqual(len(mgr.codex_entries), 1)
        self.assertEqual(mgr.lookup_cached_translation("青云门", "Vietnamese"), "Thanh Vân Môn")

        # Add custom game codex entry with context note
        mgr.add_or_update_codex(
            "Crimson Blade",
            "Huyết Kiếm",
            "Vật phẩm (Item)",
            "Thanh kiếm cổ của nhân vật chính, xưng Ta - Ngươi"
        )
        matched = mgr.find_relevant_codex_entries(["He wields the Crimson Blade in battle."])
        self.assertEqual(len(matched), 1)
        self.assertEqual(matched[0]["target"], "Huyết Kiếm")

        # Store cached translation and verify both Exact Match and Fuzzy OCR Match
        mgr.store_cached_translations(
            ["Press F to interact with the ancient shrine."],
            ["Nhấn F để tương tác với ngôi đền cổ."],
            "Vietnamese"
        )
        # Exact match
        self.assertEqual(
            mgr.lookup_cached_translation("Press F to interact with the ancient shrine.", "Vietnamese"),
            "Nhấn F để tương tác với ngôi đền cổ."
        )
        # Fuzzy OCR jitter match (e.g., OCR read 'shrine!' instead of 'shrine.')
        self.assertEqual(
            mgr.lookup_cached_translation("Press F to interact with the ancient shrine!", "Vietnamese"),
            "Nhấn F để tương tác với ngôi đền cổ."
        )

        # Partial Batch Translation: 2 cached/codex lines + 1 brand-new line -> AI only receives 1 line!
        dummy_img = Image.new("RGB", (200, 80), color=(0, 0, 0))
        worker = aot.TranslationWorker(
            pil_img=dummy_img,
            tess_lang="eng",
            target_lang="Vietnamese",
            api_url="https://api.openai.com/v1/chat/completions",
            api_key="sk-mock",
            model_name="gpt-4o-mini",
            last_raw_text="",
            knowledge_mgr=mgr
        )

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": '["Anh ấy vung Huyết Kiếm trong trận chiến."]'}}]
        }
        with patch("argon_overlay_translator.requests.post", return_value=mock_resp) as mock_post:
            batch = [
                "青云门",
                "Press F to interact with the ancient shrine.",
                "He wields the Crimson Blade in battle."
            ]
            translations, cache_hits = worker.resolve_with_cache_and_translate(batch)
            self.assertEqual(cache_hits, 2)
            self.assertEqual(
                translations,
                [
                    "Thanh Vân Môn",
                    "Nhấn F để tương tác với ngôi đền cổ.",
                    "Anh ấy vung Huyết Kiếm trong trận chiến."
                ]
            )
            # Ensure only the 1 uncached line was sent to the LLM API, and Codex term was injected into prompt
            mock_post.assert_called_once()
            sent_payload = mock_post.call_args.kwargs["json"]
            self.assertEqual(json.loads(sent_payload["messages"][1]["content"]), ["He wields the Crimson Blade in battle."])
            self.assertIn("Huyết Kiếm", sent_payload["messages"][0]["content"])

    @patch("argon_overlay_translator.keyboard.add_hotkey")
    def test_codex_and_cache_dialog_live_overlay_update(self, mock_hotkey):
        """Verify editing a translation in CodexAndCacheDialog immediately updates visible HUD blocks."""
        studio = aot.MainStudioWindow(config_path=self.config_path)
        studio.knowledge_mgr.store_cached_translations(["Game Over"], ["Trò chơi kết thúc"], "Vietnamese")
        studio.overlay_hud.blocks = [
            {"rect": (10, 10, 120, 30), "text": "Trò chơi kết thúc", "raw": "Game Over", "raw_line": "Game Over"}
        ]

        studio.open_codex_and_cache_dialog()
        dlg = studio.codex_dialog
        self.assertIsNotNone(dlg)
        self.assertEqual(dlg.tbl_cache.rowCount(), 1)

        # Edit cached translation via dialog and verify live overlay HUD block updates immediately
        dlg.txt_cache_edit_src.setText("Game Over")
        dlg.txt_cache_edit_dst.setText("Bạn đã bại trận")
        dlg.txt_cache_edit_lang = "Vietnamese"
        dlg.save_edited_cache_entry()

        self.assertEqual(studio.overlay_hud.blocks[0]["text"], "Bạn đã bại trận")
        studio.close()

    def test_no_unbundled_imports_for_frozen_launcher(self):
        """Ensure argon_overlay_translator.py only imports modules bundled in launcher.py (.exe compatibility)."""
        import ast
        with open(aot.MAIN_SCRIPT_FILE, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read())

        allowed_top_modules = {
            "sys", "os", "json", "time", "threading", "subprocess", "runpy", "shutil",
            "requests", "PIL", "mss", "pytesseract", "keyboard", "PyQt5"
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top_mod = alias.name.split(".")[0]
                    self.assertIn(
                        top_mod,
                        allowed_top_modules,
                        f"Module '{top_mod}' is not bundled in ArgonTranslator.exe launcher.py!"
                    )
            elif isinstance(node, ast.ImportFrom) and node.module:
                top_mod = node.module.split(".")[0]
                self.assertIn(
                    top_mod,
                    allowed_top_modules,
                    f"Module '{top_mod}' is not bundled in ArgonTranslator.exe launcher.py!"
                )

    def test_multilang_chat_smart_join_and_vietnamese_skip(self):
        """Verify Multi-Language Chat OCR lang resolution, CJK+Latin token joiner, and skipping Vietnamese chat lines."""
        # 1. Dynamic OCR language string resolution
        resolved = aot.resolve_ocr_lang_string(
            "🌐 Multi-Language Chat (multi)",
            installed_langs=["eng", "chi_sim", "jpn", "kor", "osd"]
        )
        self.assertEqual(resolved, "eng+chi_sim+jpn+kor")

        # Fallback if only eng + chi_sim are installed
        partial = aot.resolve_ocr_lang_string(
            "🌐 Multi-Language Chat (multi)",
            installed_langs=["eng", "chi_sim"]
        )
        self.assertEqual(partial, "eng+chi_sim")

        # 2. Smart Mixed-Script Token Joining (no space between CJK, keep space for English/Korean)
        mixed_tokens = ["[World]", "龙傲", "天:", "Hello", "兄弟", "们", "party", "up!"]
        self.assertEqual(
            aot.smart_join_ocr_tokens(mixed_tokens),
            "[World] 龙傲天: Hello 兄弟们 party up!"
        )

        # 3. Skip lines already written in Vietnamese inside a mixed chat box
        self.assertTrue(
            aot.is_already_target_language("[Thế Giới] NamPro: Anh em đi phụ bản không?", "Vietnamese")
        )
        self.assertFalse(
            aot.is_already_target_language("[World] Dragon: Anyone going dungeon?", "Vietnamese")
        )
        self.assertFalse(
            aot.is_already_target_language("[World] 龙傲天: 组队刷副本", "Vietnamese")
        )

    @patch("argon_overlay_translator.keyboard.add_hotkey")
    @patch("argon_overlay_translator.keyboard.unhook_all")
    def test_in_process_hot_reload_and_clean_pyinstaller_env(self, mock_unhook, mock_hotkey):
        """Verify Hot Update reloads in-process without Qt platform plugin crash, and strips _MEIPASS/QT_PLUGIN_PATH."""
        with patch.dict(
            os.environ,
            {
                "_MEIPASS2": r"C:\Temp\_MEI12345",
                "QT_PLUGIN_PATH": r"C:\Temp\_MEI12345\PyQt5\Qt5\plugins",
                "QT_QPA_PLATFORM_PLUGIN_PATH": r"C:\Temp\_MEI12345\PyQt5\Qt5\plugins\platforms",
            },
        ):
            clean_env = aot.MainStudioWindow._build_clean_subprocess_env()
            self.assertNotIn("_MEIPASS2", clean_env)
            self.assertNotIn("QT_PLUGIN_PATH", clean_env)
            self.assertNotIn("QT_QPA_PLATFORM_PLUGIN_PATH", clean_env)

        studio = aot.MainStudioWindow(config_path=self.config_path)
        with patch("argon_overlay_translator.subprocess.Popen") as mock_popen:
            studio._restart_process()
            # In-process hot reload should succeed without spawning a child .exe process!
            mock_popen.assert_not_called()
            app = aot.QApplication.instance()
            self.assertIsNotNone(getattr(app, "_active_studio", None))
            app._active_studio.close()

    def test_massive_133k_offline_en_vi_dictionary_and_sentence_translator(self):
        """Verify 133,675-entry offline English-Vietnamese dictionary lookup, stemming, search, and offline sentence translation."""
        mgr = aot.TranslationKnowledgeManager(
            codex_path=os.path.join(self.temp_dir.name, "codex.json"),
            cache_path=os.path.join(self.temp_dir.name, "cache.json"),
        )
        self.assertGreater(mgr.get_offline_dict_total_count(), 100000)

        # 1. Exact and stemmed word lookup in 133K dictionary
        sword_info = mgr.lookup_offline_en_vi("swords")
        self.assertIsNotNone(sword_info)
        self.assertEqual(sword_info["source"], "sword")
        self.assertIn("kiếm", sword_info["concise"])

        # 2. Phrase lookup in 30K offline phrases
        phrase_info = mgr.lookup_offline_en_vi("to abandon a hope")
        self.assertIsNotNone(phrase_info)
        self.assertIn("từ bỏ hy vọng", phrase_info["concise"])

        # 3. 100% Offline sentence translation combining Codex + 133K dictionary
        mgr.add_or_update_codex("Crimson Blade", "Huyết Kiếm", "Vật phẩm (Item)")
        offline_sent = mgr.translate_sentence_offline("You can abandon a hope or wield the Crimson Blade!")
        self.assertIn("bạn", offline_sent.lower())
        self.assertIn("từ bỏ hy vọng", offline_sent.lower())
        self.assertIn("Huyết Kiếm", offline_sent)

        # 4. Searching in Codex returns matches from the 133K dictionary
        search_hits = mgr.search_codex("dragon")
        self.assertGreater(len(search_hits), 5)

    @patch("argon_overlay_translator.keyboard.add_hotkey")
    def test_chameleon_in_place_text_replacement_and_transparent_styles(self, mock_hotkey):
        """Verify chameleon background color sampling and switching between Replace, Transparent, and Glass overlay styles."""
        # Create a light parchment background image (240, 230, 200) with dark ink text pixels in the middle
        img = Image.new("RGB", (200, 60), color=(240, 230, 200))
        for x in range(30, 150):
            img.putpixel((x, 25), (20, 15, 10))
        bg_rgb, fg_rgb = aot.TranslationWorker.sample_rect_colors(img, (25, 15, 130, 22))
        self.assertEqual(bg_rgb, (240, 230, 200))
        self.assertLess(fg_rgb[0], 50)

        studio = aot.MainStudioWindow(config_path=self.config_path)
        studio.overlay_hud.blocks = [{
            "rect": (20, 20, 120, 24),
            "text": "Huyết Kiếm",
            "raw": "Crimson Blade",
            "raw_line": "Crimson Blade",
            "bg_color": bg_rgb,
            "fg_color": fg_rgb,
            "word_masks": [{"rect": (20, 20, 120, 24), "bg_color": bg_rgb}],
        }]

        for idx, expected_style in ((0, "replace"), (1, "transparent"), (2, "glass")):
            studio.cb_overlay_style.setCurrentIndex(idx)
            self.assertEqual(studio.overlay_hud.overlay_style, expected_style)
            studio.overlay_hud.repaint()

        # Verify live typography and appearance settings (font size, font family, color, opacity, bold, auto-fit)
        studio.cb_font_family.setCurrentText("Tahoma")
        studio.sp_font_size.setValue(20)
        studio.cb_text_color.setCurrentIndex(2)  # Vàng kim (#FACC15)
        studio.sp_bg_opacity.setValue(75)
        studio.chk_font_bold.setChecked(False)
        studio.chk_auto_font.setChecked(False)

        self.assertEqual(studio.overlay_hud.font_family, "Tahoma")
        self.assertEqual(studio.overlay_hud.font_size, 20)
        self.assertEqual(studio.overlay_hud.text_color_mode, "#FACC15")
        self.assertEqual(studio.overlay_hud.bg_opacity, 75)
        self.assertFalse(studio.overlay_hud.font_bold)
        self.assertFalse(studio.overlay_hud.auto_font_fit)

        studio.save_config()
        studio.close()

        # Reload in a new window and verify persistence
        studio2 = aot.MainStudioWindow(config_path=self.config_path)
        self.assertEqual(studio2.overlay_hud.font_family, "Tahoma")
        self.assertEqual(studio2.overlay_hud.font_size, 20)
        self.assertEqual(studio2.overlay_hud.text_color_mode, "#FACC15")
        self.assertEqual(studio2.overlay_hud.bg_opacity, 75)
        self.assertFalse(studio2.overlay_hud.font_bold)
        self.assertFalse(studio2.overlay_hud.auto_font_fit)
        studio2.close()


    def test_auto_install_tesseract_fallback_on_new_machine(self):
        """Verify TranslationWorker automatically triggers ensure_tesseract_installed and retries OCR on a new machine."""
        img = Image.new("RGB", (120, 40), color=(30, 30, 30))
        mgr = aot.TranslationKnowledgeManager(
            codex_path=os.path.join(self.temp_dir.name, "codex.json"),
            cache_path=os.path.join(self.temp_dir.name, "cache.json"),
        )
        mgr.add_or_update_codex("Victory", "Chiến Thắng")

        ocr_result = {
            "text": ["Victory"],
            "conf": ["95"],
            "left": [10],
            "top": [8],
            "width": [80],
            "height": [20],
            "block_num": [1],
            "par_num": [1],
            "line_num": [1],
        }
        worker = aot.TranslationWorker(
            pil_img=img,
            tess_lang="eng",
            target_lang="Vietnamese",
            api_url="",
            api_key="",
            model_name="",
            last_raw_text="",
            knowledge_mgr=mgr,
            src_selection_text="English (eng)",
        )
        results = []
        worker.finished_signal.connect(lambda blocks, msg: results.append((blocks, msg)))

        # First call raises TesseractNotFoundError, second call succeeds after ensure_tesseract_installed
        with patch(
            "argon_overlay_translator.pytesseract.image_to_data",
            side_effect=[RuntimeError("tesseract is not installed"), ocr_result],
        ) as mock_ocr, patch(
            "argon_overlay_translator.ensure_tesseract_installed", return_value=True
        ) as mock_ensure:
            worker.run()
            self.assertEqual(mock_ocr.call_count, 2)
            mock_ensure.assert_called_once()
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0][0][0]["text"], "Chiến Thắng")

    def test_skip_numbers_and_special_characters_in_ocr(self):
        """Verify numbers, percentages, stat counters, and special symbols are stripped and skipped."""
        self.assertTrue(aot.is_symbol_or_number_only("12345"))
        self.assertTrue(aot.is_symbol_or_number_only("1500 / 2000 +25%"))
        self.assertTrue(aot.is_symbol_or_number_only("Lv.99 x10 60FPS"))
        self.assertTrue(aot.is_symbol_or_number_only("@#$%^&* === --- ***"))
        self.assertFalse(aot.is_symbol_or_number_only("Crimson Blade"))
        self.assertFalse(aot.is_symbol_or_number_only("青云门"))

        img = Image.new("RGB", (240, 80), color=(30, 30, 30))
        mgr = aot.TranslationKnowledgeManager(
            codex_path=os.path.join(self.temp_dir.name, "codex.json"),
            cache_path=os.path.join(self.temp_dir.name, "cache.json"),
        )
        mgr.add_or_update_codex("Crimson Blade", "Huyết Kiếm")

        # Line 1 is pure numbers/stats ('1500/2000', '+99%'), Line 2 has special chars + numbers around 'Crimson Blade'
        ocr_result = {
            "text": ["1500/2000", "+99%", "[14:30]", "***Crimson", "Blade###", "9999"],
            "conf": ["95", "95", "95", "95", "95", "95"],
            "left": [10, 80, 10, 60, 120, 180],
            "top": [5, 5, 40, 40, 40, 40],
            "width": [60, 40, 40, 55, 55, 40],
            "height": [18, 18, 20, 20, 20, 20],
            "block_num": [1, 1, 2, 2, 2, 2],
            "par_num": [1, 1, 1, 1, 1, 1],
            "line_num": [1, 1, 1, 1, 1, 1],
        }
        worker = aot.TranslationWorker(
            pil_img=img,
            tess_lang="eng",
            target_lang="Vietnamese",
            api_url="",
            api_key="",
            model_name="",
            last_raw_text="",
            knowledge_mgr=mgr,
        )
        results = []
        worker.finished_signal.connect(lambda blocks, msg: results.append((blocks, msg)))

        with patch("argon_overlay_translator.pytesseract.image_to_data", return_value=ocr_result):
            worker.run()

        self.assertEqual(len(results), 1)
        blocks = results[0][0]
        # Line 1 ('1500/2000 +99%') was completely skipped; Line 2 stripped '[14:30]', '***', '###', '9999' -> 'Crimson Blade'
        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["raw_line"], "Crimson Blade")
        self.assertEqual(blocks[0]["text"], "Huyết Kiếm")
        # Bounding box x starts at 60 ('Crimson'), not 10 ('[14:30]'), and ends at 175 ('Blade'), not 220 ('9999')
        self.assertEqual(blocks[0]["rect"], (60, 40, 115, 20))

    def test_hud_8_direction_resize_edges_and_corners(self):
        """Verify FloatingOverlayHUD supports resizing from all 4 corners and all 4 edges."""
        hud = aot.FloatingOverlayHUD()
        hud.setGeometry(200, 200, 400, 200)

        # 1. Verify hit-testing for 4 corners and 4 edges + interior
        self.assertEqual(hud._hit_test_resize_edge(aot.QPoint(4, 4)), "top_left")
        self.assertEqual(hud._hit_test_resize_edge(aot.QPoint(396, 4)), "top_right")
        self.assertEqual(hud._hit_test_resize_edge(aot.QPoint(4, 196)), "bottom_left")
        self.assertEqual(hud._hit_test_resize_edge(aot.QPoint(396, 196)), "bottom_right")
        self.assertEqual(hud._hit_test_resize_edge(aot.QPoint(200, 3)), "top")
        self.assertEqual(hud._hit_test_resize_edge(aot.QPoint(200, 197)), "bottom")
        self.assertEqual(hud._hit_test_resize_edge(aot.QPoint(3, 100)), "left")
        self.assertEqual(hud._hit_test_resize_edge(aot.QPoint(397, 100)), "right")
        self.assertEqual(hud._hit_test_resize_edge(aot.QPoint(200, 100)), "")

        # 2. Verify resizing from top_left corner expands left & top while keeping bottom-right anchored
        hud.resizing = True
        hud.resize_edge = "top_left"
        hud.resize_start_rect = aot.QRect(200, 200, 400, 200)
        hud.resize_start_pos = aot.QPoint(200, 200)
        hud._apply_resize_drag(aot.QPoint(150, 160))
        self.assertEqual(hud.geometry(), aot.QRect(150, 160, 450, 240))

        # 3. Verify resizing from right edge expands width only
        hud.resize_edge = "right"
        hud.resize_start_rect = hud.geometry()
        hud.resize_start_pos = aot.QPoint(600, 280)
        hud._apply_resize_drag(aot.QPoint(680, 280))
        self.assertEqual(hud.geometry(), aot.QRect(150, 160, 530, 240))
        hud.close()

    def test_gaming_mode_features_antifocus_f7_compact_and_pixel_delta(self):
        """Verify anti-focus-steal HUD flags, F7 combat quick-hide, Compact Gaming Mode, and Pixel-Delta frame signatures."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = os.path.join(tmpdir, "gaming_config.json")
            studio = aot.MainStudioWindow(config_path=cfg_path)

            # 1. Verify WindowDoesNotAcceptFocus and WA_ShowWithoutActivating so games never Alt-Tab
            self.assertTrue(bool(studio.overlay_hud.windowFlags() & aot.Qt.WindowDoesNotAcceptFocus))
            self.assertTrue(studio.overlay_hud.testAttribute(aot.Qt.WA_ShowWithoutActivating))

            # 2. Verify F7 Combat Quick-Hide preserves existing blocks while hiding HUD
            studio.overlay_hud.blocks = [{"text": "Hồi sinh tại đền", "rect": (10, 10, 120, 25), "raw": "Respawn at shrine"}]
            self.assertFalse(studio.overlay_hud.is_hidden_by_user)
            studio.toggle_overlay_visibility()
            self.assertTrue(studio.overlay_hud.is_hidden_by_user)
            self.assertEqual(len(studio.overlay_hud.blocks), 1)
            studio.toggle_overlay_visibility()
            self.assertFalse(studio.overlay_hud.is_hidden_by_user)

            # 3. Verify Compact Gaming Mode collapses settings cards and locks HUD click-through
            self.assertFalse(studio.is_compact_gaming_mode)
            studio.toggle_compact_gaming_mode()
            self.assertTrue(studio.is_compact_gaming_mode)
            self.assertTrue(studio.card_lang.isHidden())
            self.assertTrue(studio.card_ai.isHidden())
            self.assertTrue(studio.overlay_hud.is_locked)
            studio.toggle_compact_gaming_mode()
            self.assertFalse(studio.is_compact_gaming_mode)
            self.assertFalse(studio.card_lang.isHidden())

            # 4. Verify Pixel-Delta Frame Signature comparison
            from PIL import Image
            img1 = Image.new("RGB", (200, 80), (20, 25, 35))
            img2 = Image.new("RGB", (200, 80), (20, 25, 35))
            img3 = Image.new("RGB", (200, 80), (220, 210, 190))
            sig1 = studio.compute_frame_signature(img1)
            sig2 = studio.compute_frame_signature(img2)
            sig3 = studio.compute_frame_signature(img3)
            self.assertEqual(studio.frame_signature_diff(sig1, sig2), 0.0)
            self.assertGreater(studio.frame_signature_diff(sig1, sig3), 100.0)

            # 5. Verify empty scene resets last_raw_text so repeated NPC dialogue re-translates
            studio.last_raw_text = "Hello Traveler"
            studio._on_translation_done([], "No text")
            self.assertEqual(studio.last_raw_text, "")
            studio.close()

    def test_auto_clear_overlay_on_tab_or_scene_switch(self):
        """Verify overlay automatically clears when switching tabs/windows or changing unmasked scene pixels."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = os.path.join(tmpdir, "autoclear_config.json")
            studio = aot.MainStudioWindow(config_path=cfg_path)
            self.assertTrue(studio.chk_auto_clear.isChecked())

            blocks = [{
                "text": "Nhiệm vụ chính",
                "rect": (30, 30, 100, 22),
                "painted_phys_rect": (25, 25, 115, 32),
                "raw": "Main Quest"
            }]
            studio.overlay_hud.blocks = list(blocks)
            studio.last_raw_text = "Main Quest"

            # 1. Verify compute_unmasked_scene_signature ignores changes inside painted_phys_rect
            from PIL import Image, ImageDraw
            img_tab1 = Image.new("RGB", (300, 160), (24, 30, 44))
            img_tab1_pill_drawn = img_tab1.copy()
            draw = ImageDraw.Draw(img_tab1_pill_drawn)
            draw.rectangle([28, 28, 130, 52], fill=(255, 255, 0))

            sig_before_pill = studio.compute_unmasked_scene_signature(img_tab1, blocks)
            sig_after_pill = studio.compute_unmasked_scene_signature(img_tab1_pill_drawn, blocks)
            self.assertEqual(studio.frame_signature_diff(sig_before_pill, sig_after_pill), 0.0)

            # 2. Verify switching to another tab (background/tab-bar changes) triggers automatic overlay clear
            img_tab2 = Image.new("RGB", (300, 160), (235, 240, 248))
            sig_tab2 = studio.compute_unmasked_scene_signature(img_tab2, blocks)
            self.assertGreater(studio.frame_signature_diff(sig_before_pill, sig_tab2), 100.0)

            studio.active_scene_sig = sig_before_pill
            with unittest.mock.patch.object(studio, "_grab_live_unmasked_signature", return_value=sig_tab2):
                studio._check_scene_or_tab_change()

            self.assertEqual(studio.overlay_hud.blocks, [])
            self.assertEqual(studio.last_raw_text, "")
            self.assertIsNone(studio.active_scene_sig)
            studio.close()

    def test_smart_auto_translate_only_translates_new_data(self):
        """Verify Auto-Translate skips old data without blinking/re-scanning and only translates genuinely new lines."""
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = os.path.join(tmpdir, "smart_auto_config.json")
            studio = aot.MainStudioWindow(config_path=cfg_path)

            # 1. Verify is_same_ocr_data handles exact and minor OCR jitter (>=92% similarity)
            self.assertTrue(aot.is_same_ocr_data("Welcome to the Dragon Temple!", "welcome to the dragon temple!"))
            self.assertTrue(aot.is_same_ocr_data("Welcome to the Dragon Temple!", "Welcome to the Dragon Temple."))
            self.assertFalse(aot.is_same_ocr_data("Welcome to the Dragon Temple!", "Defeat the Shadow Boss now!"))

            # 2. Verify _on_auto_timer_tick skips capture when active_scene_sig is unchanged (old data)
            prev_block = {
                "text": "Chào mừng đến Đền Rồng",
                "rect": (20, 20, 150, 24),
                "raw": "Welcome to the Dragon Temple",
                "raw_line": "Welcome to the Dragon Temple"
            }
            studio.overlay_hud.blocks = [prev_block]
            studio.last_valid_blocks = [prev_block]
            studio.active_scene_sig = (10, 20, 30, 40, 50, 60)

            with unittest.mock.patch.object(studio, "_grab_live_unmasked_signature", return_value=(10, 20, 30, 40, 50, 60)), \
                 unittest.mock.patch.object(studio, "initiate_capture_and_translate") as mock_cap:
                studio._on_auto_timer_tick()
                mock_cap.assert_not_called()

            # 3. Verify _on_auto_timer_tick triggers capture ONLY when scene signature changes (new data)
            with unittest.mock.patch.object(studio, "_grab_live_unmasked_signature", return_value=(200, 210, 220, 230, 240, 250)), \
                 unittest.mock.patch.object(studio, "initiate_capture_and_translate") as mock_cap:
                studio._on_auto_timer_tick()
                mock_cap.assert_called_once()

            # 4. Verify TranslationWorker reuses prev_blocks for old lines and only translates new lines
            worker = aot.TranslationWorker(
                pil_img=None,
                tess_lang="eng",
                target_lang="Vietnamese",
                api_url="",
                api_key="",
                model_name="",
                last_raw_text="Welcome to the Dragon Temple",
                knowledge_mgr=None,
                prev_blocks=[prev_block]
            )
            with unittest.mock.patch.object(worker, "translate_batch_with_context", return_value=["Hãy tiêu diệt Trùm Bóng Tối"]) as mock_batch:
                out_lines, hits = worker.resolve_with_cache_and_translate([
                    "Welcome to the Dragon Temple",
                    "Defeat the Shadow Boss"
                ])
                mock_batch.assert_called_once_with(["Defeat the Shadow Boss"])
                self.assertEqual(hits, 1)
                self.assertEqual(out_lines, ["Chào mừng đến Đền Rồng", "Hãy tiêu diệt Trùm Bóng Tối"])

            # 5. Verify Chat Box + Auto-Scan NEVER triggers auto-clear ("Đã tự xóa Overlay...") when chat scrolls/changes
            studio.chk_auto.setChecked(True)
            studio.chk_auto_clear.setChecked(True)
            studio.overlay_hud.blocks = [prev_block]
            studio.active_scene_sig = (10, 20, 30, 40, 50, 60)
            with unittest.mock.patch.object(studio, "_grab_live_unmasked_signature", return_value=(210, 220, 230, 240, 250, 255)):
                studio._check_scene_or_tab_change()
                # Existing chat lines MUST stay visible on screen (never wiped to [])!
                self.assertEqual(len(studio.overlay_hud.blocks), 1)
                self.assertNotIn("Đã tự xóa Overlay", studio.lbl_status.text())

            studio.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)


