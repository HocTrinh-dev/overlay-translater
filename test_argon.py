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


if __name__ == "__main__":
    unittest.main(verbosity=2)
