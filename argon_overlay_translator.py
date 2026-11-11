import sys
import os
import json
import time
import threading
import subprocess
import requests
from PIL import Image
import mss
import pytesseract
import keyboard

from PyQt5.QtCore import (
    Qt, QRect, QRectF, QPoint, QTimer, QThread, pyqtSignal, QObject
)
from PyQt5.QtGui import (
    QPainter, QBrush, QColor, QPen, QFont, QFontMetrics, QPainterPath
)
from PyQt5.QtWidgets import (
    QApplication, QWidget, QPushButton, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QLineEdit, QSpinBox, QCheckBox, QFrame, QInputDialog,
    QListView
)

# High-DPI synchronization for 125% / 150% / 4K Windows displays
QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

DEFAULT_TESSERACT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
if os.path.exists(DEFAULT_TESSERACT):
    pytesseract.pytesseract.tesseract_cmd = DEFAULT_TESSERACT

APP_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))
CONFIG_FILE = os.path.join(APP_DIR, "config.json")
MAIN_SCRIPT_FILE = os.path.join(APP_DIR, "argon_overlay_translator.py")


def normalize_github_raw_url(url: str) -> str:
    """Convert standard GitHub repo or blob URLs into raw.githubusercontent.com URL."""
    url = url.strip()
    if not url:
        return ""
    # Convert https://github.com/user/repo/blob/branch/path -> https://raw.githubusercontent.com/user/repo/branch/path
    if "github.com/" in url and "/blob/" in url:
        return url.replace("github.com/", "raw.githubusercontent.com/").replace("/blob/", "/")
    # Convert https://github.com/user/repo -> https://raw.githubusercontent.com/user/repo/main/argon_overlay_translator.py
    if "github.com/" in url and "raw.githubusercontent.com" not in url:
        clean = url.rstrip("/")
        if clean.endswith(".git"):
            clean = clean[:-4]
        parts = clean.split("github.com/")[-1].split("/")
        if len(parts) == 2:
            owner, repo = parts[0], parts[1]
            return f"https://raw.githubusercontent.com/{owner}/{repo}/main/argon_overlay_translator.py"
    return url


# =====================================================================
# 1. BACKGROUND WORKER: OCR & BATCH CONTEXTUAL TRANSLATION (QTHREAD)
# =====================================================================
class TranslationWorker(QThread):
    finished_signal = pyqtSignal(object, str)  # (list_of_blocks_or_None, status_message)
    error_signal = pyqtSignal(str)

    def __init__(self, pil_img, tess_lang, target_lang, api_url, api_key, model_name, last_raw_text):
        super().__init__()
        self.pil_img = pil_img
        self.tess_lang = tess_lang
        self.target_lang = target_lang
        self.api_url = api_url.strip()
        self.api_key = api_key.strip()
        self.model_name = model_name.strip()
        self.last_raw_text = last_raw_text

    def run(self):
        try:
            data = pytesseract.image_to_data(
                self.pil_img, lang=self.tess_lang, output_type=pytesseract.Output.DICT
            )
        except Exception as e:
            self.error_signal.emit(f"Tesseract OCR Error: Check installation path ({e})")
            return

        # Group words into logical lines using (block_num, par_num, line_num)
        lines = []
        current_line = []
        last_line_id = None

        for i in range(len(data['text'])):
            word = data['text'][i].strip()
            conf = int(data['conf'][i]) if str(data['conf'][i]).lstrip('-').isdigit() else -1
            if word and conf > 25:
                bx, by, bw, bh = data['left'][i], data['top'][i], data['width'][i], data['height'][i]
                line_id = (data['block_num'][i], data['par_num'][i], data['line_num'][i])

                if line_id != last_line_id and current_line:
                    lines.append(current_line)
                    current_line = []

                current_line.append({'rect': (bx, by, bw, bh), 'text': word})
                last_line_id = line_id

        if current_line:
            lines.append(current_line)

        if not lines:
            self.finished_signal.emit([], "No text detected in capture region.")
            return

        line_entries = []
        for line_items in lines:
            sep = "" if self.tess_lang in ["chi_sim", "jpn"] else " "
            line_str = sep.join([item['text'] for item in line_items])
            min_x = min(item['rect'][0] for item in line_items)
            min_y = min(item['rect'][1] for item in line_items)
            max_x = max(item['rect'][0] + item['rect'][2] for item in line_items)
            max_y = max(item['rect'][1] + item['rect'][3] for item in line_items)
            line_entries.append({
                'rect': (min_x, min_y, max_x - min_x, max_y - min_y),
                'raw_text': line_str
            })

        combined_raw = "\n".join([entry['raw_text'] for entry in line_entries])
        if combined_raw == self.last_raw_text:
            self.finished_signal.emit(None, "Idle (Source text unchanged)")
            return

        raw_list = [entry['raw_text'] for entry in line_entries]
        translated_list = self.translate_batch_with_context(raw_list)

        overlay_blocks = []
        for idx, entry in enumerate(line_entries):
            trans_text = translated_list[idx] if idx < len(translated_list) else entry['raw_text']
            overlay_blocks.append({
                'rect': entry['rect'],
                'text': trans_text,
                'raw': combined_raw
            })

        timestamp = time.strftime('%H:%M:%S')
        self.finished_signal.emit(overlay_blocks, f"Translated {len(overlay_blocks)} lines at {timestamp}")

    def translate_batch_with_context(self, text_lines):
        if self.api_key:
            try:
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                }
                system_prompt = (
                    f"You are an expert context-aware translator. "
                    f"Receive a JSON array of text lines captured from a screen. "
                    f"Understand the full context across all lines, then translate each line naturally into {self.target_lang}. "
                    f"Return ONLY a valid JSON array of strings with the exact same number of elements ({len(text_lines)})."
                )
                payload = {
                    "model": self.model_name or "gpt-4o-mini",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": json.dumps(text_lines, ensure_ascii=False)}
                    ],
                    "temperature": 0.2
                }
                res = requests.post(self.api_url, headers=headers, json=payload, timeout=12).json()
                content = res["choices"][0]["message"]["content"].strip()
                if content.startswith("```"):
                    content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
                parsed = json.loads(content)
                if isinstance(parsed, list) and len(parsed) == len(text_lines):
                    return [str(x) for x in parsed]
            except Exception as e:
                print(f"LLM API Warning (falling back to Google Translate): {e}")

        # Free Fallback via Google Translate GTX endpoint
        try:
            tl_map = {"Vietnamese": "vi", "English": "en", "Japanese": "ja", "Korean": "ko", "French": "fr"}
            tl = tl_map.get(self.target_lang, "vi")
            joined_query = "\n".join(text_lines)
            url = (
                f"https://translate.googleapis.com/translate_a/single?client=gtx"
                f"&sl=auto&tl={tl}&dt=t&q={requests.utils.quote(joined_query)}"
            )
            res = requests.get(url, timeout=6).json()
            full_translated = "".join([part[0] for part in res[0] if part[0]])
            split_lines = [line.strip() for line in full_translated.split("\n") if line.strip()]
            if len(split_lines) == len(text_lines):
                return split_lines
            return full_translated.split("\n")
        except Exception:
            return text_lines


# =====================================================================
# 1B. BACKGROUND WORKER: HOT-UPDATE FROM GITHUB / GIT (QTHREAD)
# =====================================================================
class HotUpdateWorker(QThread):
    finished_signal = pyqtSignal(bool, str)  # (updated_and_should_restart, status_message)

    def __init__(self, update_url: str, target_script_path: str):
        super().__init__()
        self.update_url = normalize_github_raw_url(update_url)
        self.target_script_path = target_script_path

    def run(self):
        # 1. If a GitHub Raw URL is configured, download directly (< 0.5s, no git required on client)
        if self.update_url:
            try:
                cache_bust_url = (
                    f"{self.update_url}?t={int(time.time())}"
                    if "?" not in self.update_url
                    else f"{self.update_url}&t={int(time.time())}"
                )
                resp = requests.get(cache_bust_url, timeout=8)
                if resp.status_code != 200:
                    self.finished_signal.emit(False, f"Update Error: HTTP {resp.status_code} from GitHub.")
                    return

                new_code = resp.text
                if "MainStudioWindow" not in new_code:
                    self.finished_signal.emit(False, "Update Error: Downloaded file is not a valid Argon script.")
                    return

                old_code = ""
                if os.path.exists(self.target_script_path):
                    with open(self.target_script_path, "r", encoding="utf-8") as f:
                        old_code = f.read()

                if new_code.replace("\r\n", "\n") == old_code.replace("\r\n", "\n"):
                    self.finished_signal.emit(False, "✓ Already up to date with GitHub.")
                    return

                with open(self.target_script_path, "w", encoding="utf-8") as f:
                    f.write(new_code)

                self.finished_signal.emit(True, "✓ Updated from GitHub! Restarting app...")
                return
            except Exception as e:
                self.finished_signal.emit(False, f"Update failed: {e}")
                return

        # 2. Fallback: If inside a Git repository, run `git pull`
        git_dir = os.path.join(os.path.dirname(self.target_script_path), ".git")
        if os.path.isdir(git_dir):
            try:
                proc = subprocess.run(
                    ["git", "pull"],
                    cwd=os.path.dirname(self.target_script_path),
                    capture_output=True,
                    text=True,
                    timeout=12,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                )
                output = (proc.stdout or proc.stderr or "").strip()
                if proc.returncode == 0:
                    if "Already up to date" in output or "Already up-to-date" in output:
                        self.finished_signal.emit(False, "✓ Git: Already up to date.")
                    else:
                        self.finished_signal.emit(True, "✓ Git pull succeeded! Restarting app...")
                else:
                    self.finished_signal.emit(False, f"Git pull error: {output[:80]}")
                return
            except Exception as e:
                self.finished_signal.emit(False, f"Git update error: {e}")
                return

        self.finished_signal.emit(False, "NO_URL_CONFIGURED")


# =====================================================================
# 2. FLOATING HUD OVERLAY WINDOW (DRAGGABLE, RESIZABLE, CLICK-THROUGH)
# =====================================================================
class FloatingOverlayHUD(QWidget):
    def __init__(self):
        super().__init__()
        self.blocks = []
        self.is_locked = False
        self.is_capturing = False
        self.resizing = False
        self.drag_offset = None
        self.dpr = 1.0

        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setGeometry(350, 280, 560, 220)
        self.setMouseTracking(True)

    def set_locked(self, locked: bool):
        self.is_locked = locked
        pos = self.pos()
        size = self.size()
        if locked:
            self.setWindowFlags(
                Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowTransparentForInput
            )
        else:
            self.setWindowFlags(
                Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
            )
        self.setGeometry(pos.x(), pos.y(), size.width(), size.height())
        self.show()
        self.update()

    def paintEvent(self, event):
        if self.is_capturing:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)

        w, h = self.width(), self.height()

        if not self.is_locked:
            pen = QPen(QColor(99, 102, 241, 210), 1.5, Qt.SolidLine)
            painter.setPen(pen)
            painter.setBrush(QBrush(QColor(15, 23, 42, 25)))
            painter.drawRoundedRect(QRectF(1, 1, w - 2, h - 2), 8, 8)

            badge_rect = QRectF(8, 8, 235, 24)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor(15, 23, 42, 220)))
            painter.drawRoundedRect(badge_rect, 6, 6)

            painter.setPen(QColor(226, 232, 240))
            painter.setFont(QFont("Segoe UI", 8, QFont.DemiBold))
            painter.drawText(
                badge_rect.adjusted(10, 0, -6, 0),
                Qt.AlignVCenter | Qt.AlignLeft,
                "⚡ Drag to move  •  F9: Translate  •  F10: Lock"
            )

            grip_path = QPainterPath()
            grip_path.moveTo(w - 16, h - 3)
            grip_path.lineTo(w - 3, h - 16)
            grip_path.moveTo(w - 10, h - 3)
            grip_path.lineTo(w - 3, h - 10)
            painter.setPen(QPen(QColor(129, 140, 248, 230), 2, Qt.SolidLine, Qt.RoundCap))
            painter.drawPath(grip_path)

        for b in self.blocks:
            rx, ry, rw, rh = b['rect']
            lx = int(rx / self.dpr)
            ly = int(ry / self.dpr)
            lw = max(int(rw / self.dpr), 80)
            lh = max(int(rh / self.dpr), 24)

            text = b['text']

            font_size = max(9, min(14, int(lh * 0.52)))
            font = QFont("Segoe UI", font_size, QFont.DemiBold)
            painter.setFont(font)
            fm = QFontMetrics(font)

            text_rect = fm.boundingRect(QRect(lx, ly, lw + 120, lh + 20), Qt.TextWordWrap, text)
            box_w = max(lw, min(text_rect.width() + 16, w - lx - 6))
            box_h = max(lh, text_rect.height() + 8)

            bg_rect = QRectF(lx - 4, ly - 2, box_w + 8, box_h + 4)
            painter.setPen(QPen(QColor(99, 102, 241, 90), 1))
            painter.setBrush(QBrush(QColor(11, 15, 25, 238)))
            painter.drawRoundedRect(bg_rect, 5, 5)

            painter.setPen(QColor(248, 250, 252))
            painter.drawText(
                QRectF(lx + 2, ly, box_w - 4, box_h),
                Qt.AlignLeft | Qt.AlignVCenter | Qt.TextWordWrap,
                text
            )

    def mousePressEvent(self, event):
        if self.is_locked:
            return
        if event.button() == Qt.LeftButton:
            if event.x() >= self.width() - 20 and event.y() >= self.height() - 20:
                self.resizing = True
            else:
                self.drag_offset = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self.is_locked:
            return
        if event.x() >= self.width() - 20 and event.y() >= self.height() - 20:
            self.setCursor(Qt.SizeFDiagCursor)
        else:
            self.setCursor(Qt.SizeAllCursor)

        if self.resizing:
            new_w = max(220, event.x())
            new_h = max(90, event.y())
            self.resize(new_w, new_h)
        elif self.drag_offset and event.buttons() & Qt.LeftButton:
            self.move(event.globalPos() - self.drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event):
        self.resizing = False
        self.drag_offset = None


# =====================================================================
# 3. MAIN CONTROL STUDIO WINDOW (HIGH-CRAFT DARK UI)
# =====================================================================
class HotkeyBridge(QObject):
    trigger_translate = pyqtSignal()
    trigger_lock = pyqtSignal()


DEFAULT_REPO_URL = "https://github.com/HocTrinh-dev/overlay-translater.git"
DEFAULT_UPDATE_URL = "https://raw.githubusercontent.com/HocTrinh-dev/overlay-translater/main/argon_overlay_translator.py"


class MainStudioWindow(QWidget):
    def __init__(self, config_path=CONFIG_FILE):
        super().__init__()
        self.setObjectName("MainStudio")
        self.config_path = config_path
        self.update_url = DEFAULT_UPDATE_URL
        self.auto_update_on_start = True

        self.setWindowTitle("Argon Context Overlay Translator")
        self.setMinimumWidth(520)

        self.overlay_hud = FloatingOverlayHUD()
        self.worker = None
        self.update_worker = None
        self.last_raw_text = ""

        self.hotkey_bridge = HotkeyBridge()
        self.hotkey_bridge.trigger_translate.connect(self.initiate_capture_and_translate)
        self.hotkey_bridge.trigger_lock.connect(self.toggle_lock_mode)

        self.auto_timer = QTimer(self)
        self.auto_timer.timeout.connect(self.initiate_capture_and_translate)

        self._apply_stylesheet()
        self._build_ui()
        self.adjustSize()
        self.setFixedSize(self.sizeHint().width(), self.sizeHint().height())
        self.load_config()
        self._register_global_hotkeys()

        self.overlay_hud.show()

    def _apply_stylesheet(self):
        self.setStyleSheet("""
            QWidget {
                color: #F8FAFC;
                font-family: 'Segoe UI', system-ui, sans-serif;
                font-size: 13px;
            }
            QWidget#MainStudio {
                background-color: #0B0F19;
            }
            QLabel, QCheckBox {
                background-color: transparent;
            }
            QFrame#Card {
                background-color: #111827;
                border: 1px solid #1F2937;
                border-radius: 10px;
            }
            QLabel#HeaderTitle {
                font-size: 17px;
                font-weight: 700;
                color: #F8FAFC;
            }
            QLabel#SubTitle {
                font-size: 12px;
                color: #94A3B8;
            }
            QLabel#SectionLabel {
                font-size: 11px;
                font-weight: 700;
                color: #818CF8;
                text-transform: uppercase;
                letter-spacing: 0.8px;
            }
            QLabel#FieldLabel {
                color: #CBD5E1;
                font-size: 12px;
                font-weight: 600;
            }
            QComboBox, QLineEdit, QSpinBox {
                background-color: #1E293B;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 5px 10px;
                min-height: 24px;
                color: #F8FAFC;
                selection-background-color: #6366F1;
            }
            QComboBox:focus, QLineEdit:focus, QSpinBox:focus {
                border: 1px solid #6366F1;
            }
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 26px;
                border-left: 1px solid #334155;
                border-top-right-radius: 6px;
                border-bottom-right-radius: 6px;
                background-color: #1E293B;
            }
            QComboBox QAbstractItemView {
                background-color: #1E293B;
                color: #F8FAFC;
                border: 1px solid #475569;
                selection-background-color: #6366F1;
                selection-color: #FFFFFF;
                outline: 0;
                padding: 4px;
            }
            QComboBox QAbstractItemView::item {
                min-height: 28px;
                padding: 4px 10px;
                border-radius: 4px;
            }
            QPushButton#PrimaryBtn {
                background-color: #6366F1;
                color: #FFFFFF;
                border: none;
                border-radius: 8px;
                font-weight: 700;
                font-size: 13px;
                padding: 11px 16px;
                min-height: 22px;
            }
            QPushButton#PrimaryBtn:hover {
                background-color: #4F46E5;
            }
            QPushButton#PrimaryBtn:pressed {
                background-color: #4338CA;
            }
            QPushButton#SecondaryBtn {
                background-color: #1E293B;
                color: #E2E8F0;
                border: 1px solid #334155;
                border-radius: 8px;
                font-weight: 600;
                padding: 8px 12px;
                min-height: 20px;
            }
            QPushButton#SecondaryBtn:hover {
                background-color: #334155;
                border-color: #475569;
            }
            QCheckBox {
                color: #E2E8F0;
                font-weight: 500;
                spacing: 8px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border-radius: 4px;
                border: 1px solid #475569;
                background-color: #1E293B;
            }
            QCheckBox::indicator:checked {
                background-color: #6366F1;
                border-color: #6366F1;
            }
            QLabel#StatusPill {
                background-color: #0F172A;
                border: 1px solid #1E293B;
                border-radius: 6px;
                padding: 8px 12px;
                color: #94A3B8;
                font-family: 'Consolas', monospace;
                font-size: 11px;
            }
        """)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(14)

        header_row = QHBoxLayout()
        header_box = QVBoxLayout()
        header_box.setSpacing(4)
        lbl_title = QLabel("Argon Screen Translator")
        lbl_title.setObjectName("HeaderTitle")
        lbl_sub = QLabel("Real-time Context Overlay • Anti Self-OCR • Click-Through HUD")
        lbl_sub.setObjectName("SubTitle")
        header_box.addWidget(lbl_title)
        header_box.addWidget(lbl_sub)
        header_row.addLayout(header_box, 1)

        self.btn_update = QPushButton("🔄 Hot Update")
        self.btn_update.setObjectName("SecondaryBtn")
        self.btn_update.setToolTip("Left-click: Pull latest code from GitHub & reload\nShift+Click: Set GitHub repository URL")
        self.btn_update.clicked.connect(self.trigger_hot_update)
        header_row.addWidget(self.btn_update)
        root.addLayout(header_row)

        card_lang = QFrame()
        card_lang.setObjectName("Card")
        c1_layout = QVBoxLayout(card_lang)
        c1_layout.setContentsMargins(16, 14, 16, 16)
        c1_layout.setSpacing(12)

        lbl_sec1 = QLabel("LANGUAGE & CAPTURE CONFIGURATION")
        lbl_sec1.setObjectName("SectionLabel")
        c1_layout.addWidget(lbl_sec1)

        row_lang = QHBoxLayout()
        row_lang.setSpacing(12)
        col_src = QVBoxLayout()
        col_src.setSpacing(6)
        lbl_s = QLabel("Source OCR Language:")
        lbl_s.setObjectName("FieldLabel")
        self.cb_src = QComboBox()
        self.cb_src.setView(QListView())
        self.cb_src.setFixedHeight(36)
        self.cb_src.addItems([
            "English (eng)",
            "Simplified Chinese (chi_sim)",
            "Japanese (jpn)",
            "Korean (kor)"
        ])
        col_src.addWidget(lbl_s)
        col_src.addWidget(self.cb_src)

        col_dst = QVBoxLayout()
        col_dst.setSpacing(6)
        lbl_d = QLabel("Target Overlay Language:")
        lbl_d.setObjectName("FieldLabel")
        self.cb_dst = QComboBox()
        self.cb_dst.setView(QListView())
        self.cb_dst.setFixedHeight(36)
        self.cb_dst.addItems(["Vietnamese", "English", "Japanese", "Korean", "French"])
        col_dst.addWidget(lbl_d)
        col_dst.addWidget(self.cb_dst)

        row_lang.addLayout(col_src, 1)
        row_lang.addLayout(col_dst, 1)
        c1_layout.addLayout(row_lang)

        row_auto = QHBoxLayout()
        self.chk_auto = QCheckBox("Auto-scan && translate every:")
        self.chk_auto.stateChanged.connect(self.toggle_auto_timer)
        self.sp_interval = QSpinBox()
        self.sp_interval.setFixedHeight(36)
        self.sp_interval.setMinimumWidth(85)
        self.sp_interval.setRange(2, 30)
        self.sp_interval.setValue(3)
        self.sp_interval.setSuffix(" sec")
        row_auto.addWidget(self.chk_auto)
        row_auto.addStretch()
        row_auto.addWidget(self.sp_interval)
        c1_layout.addLayout(row_auto)

        root.addWidget(card_lang)

        card_ai = QFrame()
        card_ai.setObjectName("Card")
        c2_layout = QVBoxLayout(card_ai)
        c2_layout.setContentsMargins(16, 14, 16, 16)
        c2_layout.setSpacing(12)

        lbl_sec2 = QLabel("AI CONTEXT ENGINE (OPTIONAL)")
        lbl_sec2.setObjectName("SectionLabel")
        c2_layout.addWidget(lbl_sec2)

        row_model = QHBoxLayout()
        row_model.setSpacing(12)
        col_url = QVBoxLayout()
        col_url.setSpacing(6)
        lbl_u = QLabel("API Endpoint:")
        lbl_u.setObjectName("FieldLabel")
        self.txt_url = QLineEdit("https://api.openai.com/v1/chat/completions")
        self.txt_url.setFixedHeight(36)
        col_url.addWidget(lbl_u)
        col_url.addWidget(self.txt_url)

        col_m = QVBoxLayout()
        col_m.setSpacing(6)
        lbl_m = QLabel("Model Name:")
        lbl_m.setObjectName("FieldLabel")
        self.txt_model = QLineEdit("gpt-4o-mini")
        self.txt_model.setFixedHeight(36)
        col_m.addWidget(lbl_m)
        col_m.addWidget(self.txt_model)

        row_model.addLayout(col_url, 2)
        row_model.addLayout(col_m, 1)
        c2_layout.addLayout(row_model)

        col_k = QVBoxLayout()
        col_k.setSpacing(6)
        lbl_k = QLabel("API Key (Leave blank for free Google Translate fallback):")
        lbl_k.setObjectName("FieldLabel")
        self.txt_key = QLineEdit()
        self.txt_key.setFixedHeight(36)
        self.txt_key.setEchoMode(QLineEdit.Password)
        self.txt_key.setPlaceholderText("sk-...")
        col_k.addWidget(lbl_k)
        col_k.addWidget(self.txt_key)
        c2_layout.addLayout(col_k)

        root.addWidget(card_ai)

        row_btns = QHBoxLayout()
        row_btns.setSpacing(12)
        self.btn_lock = QPushButton("🔓 Click-Through Lock (F10)")
        self.btn_lock.setObjectName("SecondaryBtn")
        self.btn_lock.clicked.connect(self.toggle_lock_mode)

        self.btn_clear = QPushButton("Clear Overlay")
        self.btn_clear.setObjectName("SecondaryBtn")
        self.btn_clear.clicked.connect(self.clear_overlay_text)

        row_btns.addWidget(self.btn_lock, 1)
        row_btns.addWidget(self.btn_clear, 1)
        root.addLayout(row_btns)

        self.btn_translate = QPushButton("⚡ Scan && Translate Selected Region (F9)")
        self.btn_translate.setObjectName("PrimaryBtn")
        self.btn_translate.clicked.connect(self.initiate_capture_and_translate)
        root.addWidget(self.btn_translate)

        self.lbl_status = QLabel("Ready • Position the Indigo HUD over target text and press F9")
        self.lbl_status.setObjectName("StatusPill")
        root.addWidget(self.lbl_status)

    def load_config(self):
        if not os.path.exists(self.config_path):
            return
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)

            if "api_url" in cfg and isinstance(cfg["api_url"], str):
                self.txt_url.setText(cfg["api_url"])
            if "model_name" in cfg and isinstance(cfg["model_name"], str):
                self.txt_model.setText(cfg["model_name"])
            if "api_key" in cfg and isinstance(cfg["api_key"], str):
                self.txt_key.setText(cfg["api_key"])

            if "src_lang" in cfg:
                src_val = cfg["src_lang"]
                if isinstance(src_val, int) and 0 <= src_val < self.cb_src.count():
                    self.cb_src.setCurrentIndex(src_val)
                elif isinstance(src_val, str):
                    idx = self.cb_src.findText(src_val)
                    if idx >= 0:
                        self.cb_src.setCurrentIndex(idx)
                    else:
                        for i in range(self.cb_src.count()):
                            if f"({src_val})" in self.cb_src.itemText(i):
                                self.cb_src.setCurrentIndex(i)
                                break

            if "dst_lang" in cfg:
                dst_val = cfg["dst_lang"]
                if isinstance(dst_val, int) and 0 <= dst_val < self.cb_dst.count():
                    self.cb_dst.setCurrentIndex(dst_val)
                elif isinstance(dst_val, str):
                    idx = self.cb_dst.findText(dst_val)
                    if idx >= 0:
                        self.cb_dst.setCurrentIndex(idx)

            if "auto_interval" in cfg and isinstance(cfg["auto_interval"], int):
                self.sp_interval.setValue(max(2, min(30, cfg["auto_interval"])))

            hud_geo = cfg.get("overlay_hud") or cfg.get("overlay_hud_geometry")
            if isinstance(hud_geo, (list, tuple)) and len(hud_geo) == 4:
                x, y, w, h = [int(v) for v in hud_geo]
                self.overlay_hud.setGeometry(x, y, max(220, w), max(90, h))

            if "update_url" in cfg and isinstance(cfg["update_url"], str):
                self.update_url = normalize_github_raw_url(cfg["update_url"])
            if "auto_update_on_start" in cfg and isinstance(cfg["auto_update_on_start"], bool):
                self.auto_update_on_start = cfg["auto_update_on_start"]
        except Exception as e:
            print(f"Configuration load warning: {e}")

    def save_config(self):
        geo = self.overlay_hud.geometry()
        cfg = {
            "api_url": self.txt_url.text().strip(),
            "model_name": self.txt_model.text().strip(),
            "api_key": self.txt_key.text().strip(),
            "src_lang": self.cb_src.currentText(),
            "dst_lang": self.cb_dst.currentText(),
            "auto_interval": self.sp_interval.value(),
            "overlay_hud": [geo.x(), geo.y(), geo.width(), geo.height()],
            "update_url": self.update_url,
            "auto_update_on_start": self.auto_update_on_start
        }
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"Configuration save warning: {e}")

    def prompt_update_url(self) -> bool:
        url, ok = QInputDialog.getText(
            self,
            "Configure GitHub Hot-Update URL",
            "Paste your GitHub Repository URL or Raw File URL:\n"
            "(e.g. https://github.com/username/repo)",
            QLineEdit.Normal,
            self.update_url
        )
        if ok and url.strip():
            self.update_url = normalize_github_raw_url(url.strip())
            self.save_config()
            return True
        return False

    def trigger_hot_update(self):
        if self.update_worker and self.update_worker.isRunning():
            return

        modifiers = QApplication.keyboardModifiers()
        if modifiers & Qt.ShiftModifier:
            if not self.prompt_update_url():
                return

        git_dir = os.path.join(APP_DIR, ".git")
        if not self.update_url and not os.path.isdir(git_dir):
            if not self.prompt_update_url():
                self.lbl_status.setText("Hot-update cancelled (no GitHub URL set).")
                return

        self.btn_update.setEnabled(False)
        self.lbl_status.setText("⏳ Checking GitHub for latest argon_overlay_translator.py...")
        self.update_worker = HotUpdateWorker(self.update_url, MAIN_SCRIPT_FILE)
        self.update_worker.finished_signal.connect(self._on_hot_update_done)
        self.update_worker.start()

    def _on_hot_update_done(self, should_restart: bool, message: str):
        self.btn_update.setEnabled(True)
        if message == "NO_URL_CONFIGURED":
            if self.prompt_update_url():
                self.trigger_hot_update()
            return

        self.lbl_status.setText(message)
        if should_restart:
            self.save_config()
            self.overlay_hud.close()
            QTimer.singleShot(350, self._restart_process)

    def _restart_process(self):
        args = [sys.executable] + (sys.argv[1:] if getattr(sys, "frozen", False) else sys.argv)
        subprocess.Popen(args, cwd=APP_DIR)
        QApplication.quit()

    def _register_global_hotkeys(self):
        def listen():
            try:
                keyboard.add_hotkey('F9', lambda: self.hotkey_bridge.trigger_translate.emit())
                keyboard.add_hotkey('F10', lambda: self.hotkey_bridge.trigger_lock.emit())
            except Exception as e:
                print(f"Global hotkey registration warning: {e}")

        threading.Thread(target=listen, daemon=True).start()

    def toggle_lock_mode(self):
        new_state = not self.overlay_hud.is_locked
        self.overlay_hud.set_locked(new_state)
        if new_state:
            self.btn_lock.setText("🔒 Locked Click-Through (F10)")
            self.lbl_status.setText("HUD Locked: Mouse clicks now pass through to underlying window.")
        else:
            self.btn_lock.setText("🔓 Click-Through Lock (F10)")
            self.lbl_status.setText("HUD Unlocked: You can drag or resize the capture box.")

    def clear_overlay_text(self):
        self.overlay_hud.blocks = []
        self.last_raw_text = ""
        self.overlay_hud.update()
        self.lbl_status.setText("Cleared overlay translation blocks.")

    def toggle_auto_timer(self, state):
        if state == Qt.Checked:
            self.auto_timer.start(self.sp_interval.value() * 1000)
            self.lbl_status.setText(f"Auto-scan active (every {self.sp_interval.value()}s)...")
        else:
            self.auto_timer.stop()
            self.lbl_status.setText("Auto-scan disabled.")

    def initiate_capture_and_translate(self):
        if self.worker and self.worker.isRunning():
            return

        # Phase 1: Hide overlay pills so underlying screen text is exposed cleanly
        self.overlay_hud.is_capturing = True
        self.overlay_hud.repaint()
        QApplication.processEvents()

        # Wait 45ms for OS compositor to flush clean frame before grabbing pixels
        QTimer.singleShot(45, self._perform_screen_grab)

    def _perform_screen_grab(self):
        geo = self.overlay_hud.geometry()
        screen = QApplication.screenAt(geo.center()) or QApplication.primaryScreen()
        dpr = screen.devicePixelRatio()
        self.overlay_hud.dpr = dpr

        phys_x = int(geo.x() * dpr)
        phys_y = int(geo.y() * dpr)
        phys_w = int(geo.width() * dpr)
        phys_h = int(geo.height() * dpr)

        try:
            with mss.mss() as sct:
                monitor = {"left": phys_x, "top": phys_y, "width": phys_w, "height": phys_h}
                sct_img = sct.grab(monitor)
                pil_img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
        except Exception as e:
            self.overlay_hud.is_capturing = False
            self.overlay_hud.update()
            self.lbl_status.setText(f"Screen grab error: {e}")
            return

        # Phase 2: Immediately restore overlay state
        self.overlay_hud.is_capturing = False
        self.overlay_hud.update()

        lang_map = ["eng", "chi_sim", "jpn", "kor"]
        tess_lang = lang_map[self.cb_src.currentIndex()]
        target_lang = self.cb_dst.currentText()

        self.lbl_status.setText("⏳ Running OCR & contextual batch translation...")
        self.worker = TranslationWorker(
            pil_img=pil_img,
            tess_lang=tess_lang,
            target_lang=target_lang,
            api_url=self.txt_url.text(),
            api_key=self.txt_key.text(),
            model_name=self.txt_model.text(),
            last_raw_text=self.last_raw_text
        )
        self.worker.finished_signal.connect(self._on_translation_done)
        self.worker.error_signal.connect(self._on_translation_error)
        self.worker.start()

    def _on_translation_done(self, blocks, status_msg):
        if blocks is not None:
            self.overlay_hud.blocks = blocks
            if blocks:
                self.last_raw_text = blocks[0]['raw']
            self.overlay_hud.update()
        self.lbl_status.setText(status_msg)

    def _on_translation_error(self, err_msg):
        self.lbl_status.setText(err_msg)

    def closeEvent(self, event):
        self.save_config()
        self.overlay_hud.close()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    studio = MainStudioWindow()
    studio.show()
    sys.exit(app.exec_())
