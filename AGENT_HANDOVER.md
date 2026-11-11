# PROJECT HANDOVER & MASTER SPECIFICATION: Argon Screen Overlay Translator

> **INSTRUCTIONS FOR AI AGENT (ANTIGRAVITY):**
> Read this entire specification carefully before proposing or executing any code modifications. This document contains the complete architectural history, strict technical invariants, UI/UX design tokens, future roadmap, and the full production-ready source code of the project.

---

## 1. Project Evolution & Context History

This project evolved through three distinct phases to solve real-time, context-aware screen translation on Windows:

1. **Phase 1: Offline Dictionary Translator (VietPhrase Clone)**
   - Built a Tkinter-based Chinese-to-Vietnamese translator using the **Longest Match (Maximum Matching)** sliding-window algorithm across three priority dictionaries (`Names.txt` -> `VietPhrase.txt` -> `HanViet.txt`).
   - *Limitation*: Word-by-word dictionary lookup lacks grammar and contextual awareness for multi-language applications, games, and modern media.

2. **Phase 2: Snipping Screen OCR + LLM Context Overlay**
   - Transitioned to `PyQt5` + `Tesseract OCR` + `LLM API` (with Google Translate fallback).
   - Captured user-selected screen regions, grouped OCR words by line, translated via AI, and rendered an overlay window directly on top of the original text coordinates.

3. **Phase 3: Argon Studio & Floating HUD (Current Production Architecture)**
   - Upgraded to a persistent, draggable, resizable **Floating HUD (`FloatingOverlayHUD`)** paired with a **High-Craft Dark UI Control Studio (`MainStudioWindow`)**.
   - Fixed 5 critical engineering bottlenecks (Self-OCR feedback loop, GUI thread freezing, High-DPI coordinate drift, fragmented per-line API context, and mouse input blocking).

---

## 2. Strict Architectural Invariants (DO NOT BREAK)

When refactoring or adding features to `argon_overlay_translator.py`, you **MUST preserve** these 5 core mechanisms:

### Invariant 1: 2-Phase Anti Self-OCR Capture Pipeline
- **Problem**: If `mss` grabs the screen while translated text boxes are visible on the HUD, Tesseract OCR reads the translated Vietnamese text instead of the underlying source text.
- **Implementation**:
  1. In `initiate_capture_and_translate()`, set `self.overlay_hud.is_capturing = True` and call `repaint()` + `QApplication.processEvents()`. This makes `paintEvent` return early, temporarily clearing the HUD.
  2. Wait `45ms` via `QTimer.singleShot(45, self._perform_screen_grab)` so the Windows DWM compositor flushes the clean underlying frame.
  3. Grab the physical screen region using `mss`.
  4. Immediately set `self.overlay_hud.is_capturing = False` and call `update()` so the HUD never visibly flickers.

### Invariant 2: Non-Blocking Multithreaded Execution (`QThread`)
- **Problem**: Running `pytesseract` and HTTP requests on the main Qt GUI thread freezes the window ("Not Responding") during scans and auto-timers.
- **Implementation**: All OCR processing and LLM/Google API network calls MUST remain encapsulated inside `TranslationWorker(QThread)` and communicate back to the GUI exclusively via `pyqtSignal`.

### Invariant 3: High-DPI Coordinate Synchronization
- **Problem**: On Windows displays with 125%–200% scaling, PyQt5 logical coordinates do not match `mss` physical pixel coordinates.
- **Implementation**:
  - Keep `Qt.AA_EnableHighDpiScaling` and `Qt.AA_UseHighDpiPixmaps` enabled prior to `QApplication` initialization.
  - Multiply widget logical geometry (`x, y, w, h`) by `screen.devicePixelRatio()` (`dpr`) before passing coordinates to `mss`.
  - Divide OCR bounding box coordinates by `dpr` inside `FloatingOverlayHUD.paintEvent()` when drawing overlays.

### Invariant 4: Batch Contextual LLM Translation
- **Problem**: Translating line-by-line in separate API requests destroys cross-line sentence context and multiplies latency/token cost.
- **Implementation**: Group OCR words by `(block_num, par_num, line_num)`. Send all detected lines in a single JSON array payload (`["line 1", "line 2", ...]`) to the LLM endpoint, instructing it to translate each line using the holistic context of the entire array and return an exact-length JSON string array.

### Invariant 5: Click-Through Mode (`F10` - Mouse Transparency)
- **Problem**: Users need to click game controls or browser elements beneath the translation overlay.
- **Implementation**: Toggling lock mode (`set_locked(True)`) applies `Qt.WindowTransparentForInput` to `FloatingOverlayHUD` and hides the HUD editing border/badge, leaving only the rounded dark translation pills visible.

---

## 3. UI/UX Design System (High-Craft Dark UI)

Maintain the established visual hierarchy and color tokens across all future UI components:

- **Primary Canvas Background**: Obsidian Slate `#0B0F19`
- **Elevated Card Surface**: Carbon `#111827` with `1px solid #1F2937` border (`border-radius: 10px`)
- **Interactive Input Surface**: Deep Slate `#1E293B` with `#334155` border (`#6366F1` on focus)
- **Primary Brand Accent**: Electric Indigo `#6366F1` (Hover: `#4F46E5`, Pressed: `#4338CA`)
- **Typography**: `Segoe UI` (UI controls) & `Consolas` (Telemetry status bar). Primary text `#F8FAFC`, secondary `#CBD5E1`, muted `#94A3B8`.
- **Overlay Text Pill**: `rgba(11, 15, 25, 238)` background with `rgba(99, 102, 241, 90)` `1px` border and dynamic font sizing (`9pt`–`14pt`) scaled to bounding box height.

---

## 4. Environment & Dependencies (`requirements.txt`)

```txt
PyQt5>=5.15.0
Pillow>=10.0.0
pytesseract>=0.3.10
requests>=2.31.0
mss>=9.0.1
keyboard>=0.13.5
pyinstaller>=6.0.0
```

**External Dependency Note (Current State)**:
Requires Tesseract-OCR installed at `C:\Program Files\Tesseract-OCR\tesseract.exe` with language packs (`eng`, `chi_sim`, `jpn`, `kor`).

**Build Command (Standalone `.exe`)**:
```bash
pyinstaller --onefile --noconsole --name "ArgonTranslator" argon_overlay_translator.py
```

---

## 5. Complete Reference Source Code (`argon_overlay_translator.py`)

```python
import sys
import os
import json
import time
import threading
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
    QLabel, QComboBox, QLineEdit, QSpinBox, QCheckBox, QFrame
)

# High-DPI synchronization for 125% / 150% / 4K Windows displays
QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

DEFAULT_TESSERACT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
if os.path.exists(DEFAULT_TESSERACT):
    pytesseract.pytesseract.tesseract_cmd = DEFAULT_TESSERACT


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
                f"[https://translate.googleapis.com/translate_a/single?client=gtx](https://translate.googleapis.com/translate_a/single?client=gtx)"
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


class MainStudioWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Argon Context Overlay Translator")
        self.setFixedSize(480, 520)

        self.overlay_hud = FloatingOverlayHUD()
        self.worker = None
        self.last_raw_text = ""

        self.hotkey_bridge = HotkeyBridge()
        self.hotkey_bridge.trigger_translate.connect(self.initiate_capture_and_translate)
        self.hotkey_bridge.trigger_lock.connect(self.toggle_lock_mode)

        self.auto_timer = QTimer(self)
        self.auto_timer.timeout.connect(self.initiate_capture_and_translate)

        self._apply_stylesheet()
        self._build_ui()
        self._register_global_hotkeys()

        self.overlay_hud.show()

    def _apply_stylesheet(self):
        self.setStyleSheet("""
            QWidget {
                background-color: #0B0F19;
                color: #F8FAFC;
                font-family: 'Segoe UI', system-ui, sans-serif;
                font-size: 13px;
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
                padding: 7px 10px;
                color: #F8FAFC;
                selection-background-color: #6366F1;
            }
            QComboBox:focus, QLineEdit:focus, QSpinBox:focus {
                border: 1px solid #6366F1;
            }
            QPushButton#PrimaryBtn {
                background-color: #6366F1;
                color: #FFFFFF;
                border: none;
                border-radius: 8px;
                font-weight: 700;
                font-size: 13px;
                padding: 11px 16px;
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
                padding: 9px 14px;
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

        header_box = QVBoxLayout()
        header_box.setSpacing(3)
        lbl_title = QLabel("Argon Screen Translator")
        lbl_title.setObjectName("HeaderTitle")
        lbl_sub = QLabel("Real-time Context Overlay • Anti Self-OCR • Click-Through HUD")
        lbl_sub.setObjectName("SubTitle")
        header_box.addWidget(lbl_title)
        header_box.addWidget(lbl_sub)
        root.addLayout(header_box)

        card_lang = QFrame()
        card_lang.setObjectName("Card")
        c1_layout = QVBoxLayout(card_lang)
        c1_layout.setContentsMargins(14, 14, 14, 14)
        c1_layout.setSpacing(10)

        lbl_sec1 = QLabel("LANGUAGE & CAPTURE CONFIGURATION")
        lbl_sec1.setObjectName("SectionLabel")
        c1_layout.addWidget(lbl_sec1)

        row_lang = QHBoxLayout()
        col_src = QVBoxLayout()
        lbl_s = QLabel("Source OCR Language:")
        lbl_s.setObjectName("FieldLabel")
        self.cb_src = QComboBox()
        self.cb_src.addItems([
            "English (eng)",
            "Simplified Chinese (chi_sim)",
            "Japanese (jpn)",
            "Korean (kor)"
        ])
        col_src.addWidget(lbl_s)
        col_src.addWidget(self.cb_src)

        col_dst = QVBoxLayout()
        lbl_d = QLabel("Target Overlay Language:")
        lbl_d.setObjectName("FieldLabel")
        self.cb_dst = QComboBox()
        self.cb_dst.addItems(["Vietnamese", "English", "Japanese", "Korean", "French"])
        col_dst.addWidget(lbl_d)
        col_dst.addWidget(self.cb_dst)

        row_lang.addLayout(col_src, 1)
        row_lang.addLayout(col_dst, 1)
        c1_layout.addLayout(row_lang)

        row_auto = QHBoxLayout()
        self.chk_auto = QCheckBox("Auto-scan & translate every:")
        self.chk_auto.stateChanged.connect(self.toggle_auto_timer)
        self.sp_interval = QSpinBox()
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
        c2_layout.setContentsMargins(14, 14, 14, 14)
        c2_layout.setSpacing(10)

        lbl_sec2 = QLabel("AI CONTEXT ENGINE (OPTIONAL)")
        lbl_sec2.setObjectName("SectionLabel")
        c2_layout.addWidget(lbl_sec2)

        row_model = QHBoxLayout()
        col_url = QVBoxLayout()
        lbl_u = QLabel("API Endpoint:")
        lbl_u.setObjectName("FieldLabel")
        self.txt_url = QLineEdit("[https://api.openai.com/v1/chat/completions](https://api.openai.com/v1/chat/completions)")
        col_url.addWidget(lbl_u)
        col_url.addWidget(self.txt_url)

        col_m = QVBoxLayout()
        lbl_m = QLabel("Model Name:")
        lbl_m.setObjectName("FieldLabel")
        self.txt_model = QLineEdit("gpt-4o-mini")
        col_m.addWidget(lbl_m)
        col_m.addWidget(self.txt_model)

        row_model.addLayout(col_url, 2)
        row_model.addLayout(col_m, 1)
        c2_layout.addLayout(row_model)

        lbl_k = QLabel("API Key (Leave blank for free Google Translate fallback):")
        lbl_k.setObjectName("FieldLabel")
        self.txt_key = QLineEdit()
        self.txt_key.setEchoMode(QLineEdit.Password)
        self.txt_key.setPlaceholderText("sk-...")
        c2_layout.addWidget(lbl_k)
        c2_layout.addWidget(self.txt_key)

        root.addWidget(card_ai)

        row_btns = QHBoxLayout()
        self.btn_lock = QPushButton("🔓 Click-Through Lock (F10)")
        self.btn_lock.setObjectName("SecondaryBtn")
        self.btn_lock.clicked.connect(self.toggle_lock_mode)

        self.btn_clear = QPushButton("Clear Overlay")
        self.btn_clear.setObjectName("SecondaryBtn")
        self.btn_clear.clicked.connect(self.clear_overlay_text)

        row_btns.addWidget(self.btn_lock, 1)
        row_btns.addWidget(self.btn_clear, 1)
        root.addLayout(row_btns)

        self.btn_translate = QPushButton("⚡ Scan & Translate Selected Region (F9)")
        self.btn_translate.setObjectName("PrimaryBtn")
        self.btn_translate.clicked.connect(self.initiate_capture_and_translate)
        root.addWidget(self.btn_translate)

        self.lbl_status = QLabel("Ready • Position the Indigo HUD over target text and press F9")
        self.lbl_status.setObjectName("StatusPill")
        root.addWidget(self.lbl_status)

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
        self.overlay_hud.close()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    studio = MainStudioWindow()
    studio.show()
    sys.exit(app.exec_())
```

---

## 6. Prioritized Engineering Roadmap (Next Tasks for Agent)

When asked to continue development, implement these tasks in order while respecting all 5 Architectural Invariants:

1. **Task 1: Persistent User Configuration (`config.json`)**
   - Automatically load and save user settings (`api_url`, `model_name`, `api_key`, `src_lang`, `dst_lang`, `auto_interval`, and `overlay_hud` geometry `[x, y, w, h]`) on startup and `closeEvent`.
2. **Task 2: Zero-Install OCR Engine Option (`RapidOCR` / `Windows Media OCR`)**
   - Add an OCR Engine selector allowing users to switch between `Tesseract OCR` and `RapidOCR (ONNX Runtime)` or `winocr` so the compiled `.exe` works out-of-the-box without external Tesseract installation.
3. **Task 3: Smart Background Color Sampling (Adaptive Inpainting Pill)**
   - Before drawing each overlay pill in `FloatingOverlayHUD.paintEvent`, sample the dominant edge pixel color `(R, G, B)` of each line's bounding box from `pil_img` and compute a contrasting text color (Luminance check) so the overlay blends seamlessly into game dialog boxes or manga pages.
4. **Task 4: LRU Translation Cache & Custom Glossary (`Names.txt` Hybrid)**
   - Implement an in-memory LRU cache to avoid re-translating recurring UI strings or game menus.
   - Allow loading a custom glossary file (`glossary.txt` / `Names.txt`) injected into the LLM system prompt for consistent character/skill terminology.