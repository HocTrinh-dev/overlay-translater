import sys
import os
import json
import time
import threading
import subprocess
import shutil
import requests
from PIL import Image, ImageOps, ImageEnhance
import mss
import pytesseract
import keyboard

_GLOBAL_HTTP_SESSION = None
_HTTP_SESSION_LOCK = threading.Lock()


def get_http_session() -> requests.Session:
    """Return a shared persistent HTTP Keep-Alive session with connection pooling."""
    global _GLOBAL_HTTP_SESSION
    if _GLOBAL_HTTP_SESSION is None:
        with _HTTP_SESSION_LOCK:
            if _GLOBAL_HTTP_SESSION is None:
                sess = requests.Session()
                try:
                    adapter = requests.adapters.HTTPAdapter(pool_connections=16, pool_maxsize=16)
                    sess.mount("https://", adapter)
                    sess.mount("http://", adapter)
                except Exception:
                    pass
                _GLOBAL_HTTP_SESSION = sess
    return _GLOBAL_HTTP_SESSION


def _http_get(url: str, **kwargs):
    if hasattr(requests.get, "assert_called"):
        return requests.get(url, **kwargs)
    return get_http_session().get(url, **kwargs)


def _http_post(url: str, **kwargs):
    if hasattr(requests.post, "assert_called"):
        return requests.post(url, **kwargs)
    return get_http_session().post(url, **kwargs)

from PyQt5.QtCore import (
    Qt, QRect, QRectF, QPoint, QTimer, QThread, pyqtSignal, QObject
)
from PyQt5.QtGui import (
    QPainter, QBrush, QColor, QPen, QFont, QFontMetrics, QPainterPath
)
from PyQt5.QtWidgets import (
    QApplication, QWidget, QPushButton, QVBoxLayout, QHBoxLayout,
    QLabel, QComboBox, QLineEdit, QSpinBox, QCheckBox, QFrame, QInputDialog,
    QListView, QDialog, QTabWidget, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QFileDialog, QMessageBox, QTextEdit
)

# High-DPI synchronization for 125% / 150% / 4K Windows displays
if QApplication.instance() is None:
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

_EXE_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))
if (
    os.path.basename(_EXE_DIR).lower() == "dist"
    and os.path.exists(os.path.join(os.path.dirname(_EXE_DIR), "argon_overlay_translator.py"))
):
    APP_DIR = os.path.dirname(_EXE_DIR)
else:
    APP_DIR = _EXE_DIR

DEFAULT_TESSERACT = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
TESSERACT_INSTALLER_URL = (
    "https://github.com/UB-Mannheim/tesseract/releases/download/"
    "v5.4.0.20240606/tesseract-ocr-w64-setup-5.4.0.20240606.exe"
)
TESSDATA_FAST_BASE_URL = "https://github.com/tesseract-ocr/tessdata_fast/raw/main"
_TESSERACT_INSTALL_LOCK = threading.Lock()


def _get_tesseract_candidates() -> list:
    local_app = os.environ.get("LOCALAPPDATA", "")
    user_prof = os.environ.get("USERPROFILE", "")
    cands = [
        getattr(pytesseract.pytesseract, "tesseract_cmd", ""),
        os.path.join(APP_DIR, "Tesseract-OCR", "tesseract.exe"),
        DEFAULT_TESSERACT,
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]
    if local_app:
        cands.append(os.path.join(local_app, "Programs", "Tesseract-OCR", "tesseract.exe"))
        cands.append(os.path.join(local_app, "Tesseract-OCR", "tesseract.exe"))
    if user_prof:
        cands.append(os.path.join(user_prof, "AppData", "Local", "Programs", "Tesseract-OCR", "tesseract.exe"))
    which_tess = shutil.which("tesseract")
    if which_tess:
        cands.append(which_tess)
    return cands


def locate_tesseract_binary() -> str:
    """Find an existing tesseract.exe on the current machine and configure pytesseract."""
    for cand in _get_tesseract_candidates():
        if cand and os.path.isfile(cand):
            pytesseract.pytesseract.tesseract_cmd = cand
            tessdata_dir = os.path.join(os.path.dirname(cand), "tessdata")
            custom_tessdata = os.path.join(APP_DIR, "tessdata")
            if os.path.isdir(custom_tessdata) and os.path.isfile(os.path.join(custom_tessdata, "eng.traineddata")):
                os.environ["TESSDATA_PREFIX"] = custom_tessdata
            elif os.path.isdir(tessdata_dir):
                os.environ["TESSDATA_PREFIX"] = tessdata_dir
            return cand
    return ""


locate_tesseract_binary()

CONFIG_FILE = os.path.join(APP_DIR, "config.json")
CODEX_FILE = os.path.join(APP_DIR, "codex.json")
CACHE_FILE = os.path.join(APP_DIR, "translation_cache.json")
OFFLINE_DICT_FILE = os.path.join(APP_DIR, "offline_en_vi.json")
MAIN_SCRIPT_FILE = os.path.join(APP_DIR, "argon_overlay_translator.py")

STARTUP_SCRIPT_SNAPSHOT = ""
if os.path.exists(MAIN_SCRIPT_FILE):
    try:
        with open(MAIN_SCRIPT_FILE, "r", encoding="utf-8") as _f:
            STARTUP_SCRIPT_SNAPSHOT = _f.read().replace("\r\n", "\n")
    except Exception:
        pass


def normalize_github_raw_url(url: str) -> str:
    """Convert standard GitHub repo or blob URLs into raw.githubusercontent.com URL."""
    url = url.strip()
    if not url:
        return ""
    if "github.com/" in url and "/blob/" in url:
        return url.replace("github.com/", "raw.githubusercontent.com/").replace("/blob/", "/")
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
# MULTI-LANGUAGE CHAT BOX OCR & MIXED-SCRIPT HELPERS
# =====================================================================
_VIETNAMESE_UNIQUE_CHARS = set(
    "ăâđêôơưĂÂĐÊÔƠƯ"
    "ảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ"
    "ẢẤẦẨẪẬẮẰẲẴẶẸẺẼẾỀỂỄỆỈỊỌỎỐỒỔỖỘỚỜỞỠỢỤỦỨỪỬỮỰỲỴỶỸ"
)


def _is_cjk_ideograph_or_kana(ch: str) -> bool:
    """Return True for Chinese Hanzi, Japanese Kana/Kanji, and CJK fullwidth symbols (excludes Hangul which uses spaces)."""
    if not ch:
        return False
    code = ord(ch)
    return (
        (0x3000 <= code <= 0x9FFF)
        or (0xF900 <= code <= 0xFAFF)
        or (0xFF00 <= code <= 0xFFEF)
    )


def _contains_cjk_or_hangul(text: str) -> bool:
    for ch in text:
        code = ord(ch)
        if (0x3040 <= code <= 0x9FFF) or (0xAC00 <= code <= 0xD7A3) or (0xF900 <= code <= 0xFAFF):
            return True
    return False


_SPECIAL_NOISE_STRIP_CHARS = "@#$%^&*_+=|~<>\\/`[]{}" "【】《》「」『』★☆◆◇●○■□▲△▼▽※§¶"


def clean_special_chars_from_token(token: str) -> str:
    """
    Strip special noise characters (@, #, $, %, ^, &, *, _, +, =, |, ~, <, >, brackets, etc.)
    from an OCR token while keeping normal sentence punctuation (.,!?'\":;-).
    Returns empty string if the token contains no alphabetic or CJK/Hangul letters (e.g. pure numbers/symbols).
    """
    if not token:
        return ""
    cleaned = token.strip().strip(_SPECIAL_NOISE_STRIP_CHARS).strip()
    if not cleaned:
        return ""

    if _contains_cjk_or_hangul(cleaned):
        # Remove leading/trailing pure digits and special symbols around CJK text
        return cleaned

    alpha_chars = [ch for ch in cleaned if ch.isalpha()]
    if not alpha_chars:
        # Pure numbers, timestamps, percentages, coordinates, or punctuation (e.g. '12345', '100/200', '+25%', '14:30', '---')
        return ""

    # Skip alphanumeric stat/level/version counters where digits are attached to 1-3 letters (e.g. 'Lv.99', 'x10', 'v1.2', '100K', '60FPS')
    if any(ch.isdigit() for ch in cleaned) and len(alpha_chars) <= 3:
        return ""

    return cleaned


def is_symbol_or_number_only(text: str) -> bool:
    """
    Return True if `text` contains only numbers, special characters, punctuation,
    stat counters (Lv.99, +15%, 100/200, 14:30), or isolated 1-character OCR noise,
    so it should NOT be translated or covered by an overlay block.
    """
    if not text or not text.strip():
        return True
    if _contains_cjk_or_hangul(text):
        return False

    # Split into space-separated tokens and check for real alphabetic words (>= 2 letters without digits)
    valid_words = 0
    for raw_tok in text.split():
        cleaned = clean_special_chars_from_token(raw_tok)
        if not cleaned:
            continue
        alpha_only = "".join(ch for ch in cleaned if ch.isalpha())
        if len(alpha_only) >= 2 and not any(ch.isdigit() for ch in cleaned):
            valid_words += 1

    return valid_words == 0


_CHAT_ARROW_DELIMITERS = (">>", "»", "》", "≫", "››", ">›", "›>", ">=", "=>", "->", ":>")


def _is_arrow_delimiter_token(text: str) -> bool:
    t = text.strip()
    if not t:
        return False
    if any(d in t for d in _CHAT_ARROW_DELIMITERS):
        return True
    stripped = t.strip(">›=-: ")
    return stripped == "" and (">" in t or "›" in t)


def strip_chat_prefix_items(line_items: list, strip_after_arrow: bool = True) -> list:
    """
    For game/Minecraft chat lines formatted like `[Rank] PlayerName >> message` (or `»`, `> >`, `>`, `:`, `：`),
    discard all tokens before and including the delimiter so ONLY the message after `>>` or `:` is translated
    and the overlay bounding box starts right after the delimiter (leaving Rank & PlayerName untouched).
    Protects timestamps (`[14:30]`, `12:00`), URLs (`https://...`), numeric ratios (`1:2`), and emoticons (`:)`).
    """
    if not strip_after_arrow or not line_items:
        return line_items

    n = len(line_items)
    # Pass 1: Explicit '>>', '»', '> >', or '>' delimiter token (highest priority)
    for idx, item in enumerate(line_items):
        tok = item.get("text", "").strip()
        if not tok:
            continue

        # 1a. Two adjacent '>' tokens (e.g. '>>' split by OCR into '>' and '>')
        if idx + 1 < n:
            next_item = line_items[idx + 1]
            next_tok = next_item.get("text", "").strip()
            if (tok.endswith(">") or tok.endswith("›")) and (next_tok.startswith(">") or next_tok.startswith("›")):
                after_next = next_tok.lstrip(">›=-:： ").strip()
                if not after_next:
                    return line_items[idx + 2:]
                nbx, nby, nbw, nbh = next_item["rect"]
                prefix_chars = len(next_tok) - len(after_next)
                shift_x = int(nbw * prefix_chars / max(1, len(next_tok)))
                adj_item = {
                    "rect": (nbx + shift_x, nby, max(8, nbw - shift_x), nbh),
                    "text": after_next,
                }
                return [adj_item] + line_items[idx + 2:]

        # 1b. Token contains a double-arrow / chat separator ('>>', '»', '>=', '->', etc.)
        matched_delim = None
        matched_pos = -1
        for delim in _CHAT_ARROW_DELIMITERS:
            pos = tok.rfind(delim)
            if pos >= 0 and pos + len(delim) > matched_pos:
                matched_delim = delim
                matched_pos = pos
        if matched_delim is not None:
            end_pos = matched_pos + len(matched_delim)
            after_str = tok[end_pos:].lstrip(">›=-:： ").strip()
            if not after_str:
                return line_items[idx + 1:]
            bx, by, bw, bh = item["rect"]
            prefix_chars = len(tok) - len(after_str)
            shift_x = int(bw * prefix_chars / max(1, len(tok)))
            adj_item = {
                "rect": (bx + shift_x, by, max(8, bw - shift_x), bh),
                "text": after_str,
            }
            return [adj_item] + line_items[idx + 1:]

        # 1c. Single '>' or '›' in the prefix area (when OCR merges '>>' into '>' in pixel font, or '<Name>')
        if idx <= 4:
            if _is_arrow_delimiter_token(tok):
                return line_items[idx + 1:]
            if (tok.endswith(">") or tok.endswith("›")) and len(tok) > 1:
                return line_items[idx + 1:]
            if idx >= 1 and (tok.startswith(">") or tok.startswith("›")):
                after_str = tok.lstrip(">›=-:： ").strip()
                if after_str:
                    bx, by, bw, bh = item["rect"]
                    prefix_chars = len(tok) - len(after_str)
                    shift_x = int(bw * prefix_chars / max(1, len(tok)))
                    adj_item = {
                        "rect": (bx + shift_x, by, max(8, bw - shift_x), bh),
                        "text": after_str,
                    }
                    return [adj_item] + line_items[idx + 1:]

    # Pass 2: Speaker colon ':' / '：' in prefix area (e.g. `[VIP+] Steve: Hello`, `[14:30] Steve : Hello`, `Name:Hello`)
    colon_limit = min(6, n)
    for idx in range(colon_limit):
        item = line_items[idx]
        tok = item.get("text", "").strip()
        if not tok or (":" not in tok and "：" not in tok):
            continue

        # 2a. Standalone ':' or '：' (skip if splitting numeric time/ratio like '14 : 30')
        if tok in (":", "："):
            if 0 < idx < n - 1:
                prev_clean = line_items[idx - 1].get("text", "").strip().strip("[]() ")
                next_clean = line_items[idx + 1].get("text", "").strip().strip("[]() ")
                if prev_clean.isdigit() and next_clean.isdigit():
                    continue
            return line_items[idx + 1:]

        # 2b. Scan ':' / '：' positions inside token (protects '[14:30]', '1:2', 'https://...', ':)')
        for pos, ch in enumerate(tok):
            if ch not in (":", "："):
                continue
            before = tok[:pos]
            after_raw = tok[pos + 1:]

            if after_raw.startswith("//") or before.lower() in ("http", "https", "ftp"):
                continue

            if not before:
                if idx >= 1 and not after_raw.startswith((")", "(", "D", "P", "p", "3", "/", "|", "-")):
                    after_str = after_raw.lstrip(">›=-:： ").strip()
                    if not after_str:
                        return line_items[idx + 1:]
                    bx, by, bw, bh = item["rect"]
                    prefix_chars = len(tok) - len(after_str)
                    shift_x = int(bw * prefix_chars / max(1, len(tok)))
                    adj_item = {
                        "rect": (bx + shift_x, by, max(8, bw - shift_x), bh),
                        "text": after_str,
                    }
                    return [adj_item] + line_items[idx + 1:]
                continue

            b_clean = before.strip("[]()<>")
            has_alpha = any(c.isalpha() for c in b_clean)
            if not has_alpha and after_raw and after_raw[0].isdigit():
                # Timestamp like '[14:30]', '12:00:05' or ratio like '1:2'
                continue
            if not has_alpha and not before.endswith(("]", ">", ")")):
                # Numeric prefix like '14:' followed by '30' (split time) or standalone number before colon
                if pos == len(tok) - 1 and idx + 1 < n and line_items[idx + 1].get("text", "").strip("[]() ").isdigit():
                    continue
                if not after_raw:
                    continue

            if pos == len(tok) - 1:
                return line_items[idx + 1:]

            after_str = after_raw.lstrip(">›=-:： ").strip()
            if not after_str:
                return line_items[idx + 1:]
            bx, by, bw, bh = item["rect"]
            prefix_chars = len(tok) - len(after_str)
            shift_x = int(bw * prefix_chars / max(1, len(tok)))
            adj_item = {
                "rect": (bx + shift_x, by, max(8, bw - shift_x), bh),
                "text": after_str,
            }
            return [adj_item] + line_items[idx + 1:]

    # Pass 3: Wide horizontal gap fallback (when dark-gray '&8>>' / ':' was not recognized as a glyph by OCR)
    if n >= 2:
        avg_h = sum(it["rect"][3] for it in line_items) / n
        min_arrow_gap = max(24, int(avg_h * 1.45))
        for idx in range(min(3, n - 1)):
            curr_r = line_items[idx]["rect"]
            next_r = line_items[idx + 1]["rect"]
            gap = next_r[0] - (curr_r[0] + curr_r[2])
            if gap >= min_arrow_gap:
                return line_items[idx + 1:]

    return line_items


def filter_ocr_line_items(line_items: list, strip_after_arrow: bool = True) -> list:
    """
    Strip chat prefix before `>>` or `:` (Rank & PlayerName), filter out OCR word items that are purely
    numbers, special characters, or stat counters, and clean special noise characters from valid tokens.
    """
    working_items = strip_chat_prefix_items(line_items, strip_after_arrow=strip_after_arrow)
    filtered = []
    for item in working_items:
        cleaned_word = clean_special_chars_from_token(item.get("text", ""))
        if not cleaned_word:
            continue
        filtered.append({"rect": item["rect"], "text": cleaned_word})
    return filtered


def smart_join_ocr_tokens(tokens: list) -> str:
    """
    Join OCR word tokens on a single line intelligently for mixed-language chat boxes:
    - Adjacent Chinese/Japanese tokens are joined without spaces.
    - Latin (English/Vietnamese), Korean (Hangul), and numbers are joined with a space.
    """
    cleaned = [t.strip() for t in tokens if t and t.strip()]
    if not cleaned:
        return ""
    result = [cleaned[0]]
    for token in cleaned[1:]:
        prev_char = result[-1][-1]
        next_char = token[0]
        if _is_cjk_ideograph_or_kana(prev_char) and _is_cjk_ideograph_or_kana(next_char):
            result.append(token)
        else:
            result.append(" " + token)
    return "".join(result)


def is_already_target_language(text: str, target_lang: str) -> bool:
    """
    Detect if a chat line is already written in the user's target language (e.g. Vietnamese chat line
    inside a multi-language world chat box) so we can skip covering it with an overlay pill.
    """
    if not text or not text.strip():
        return True
    if target_lang.lower().startswith("viet"):
        if _contains_cjk_or_hangul(text):
            return False
        vn_count = sum(1 for ch in text if ch in _VIETNAMESE_UNIQUE_CHARS)
        if vn_count >= 1:
            return True
    return False



def get_installed_tesseract_langs() -> list:
    """Return list of installed Tesseract language codes without spawning slow subprocesses if tessdata dir exists."""
    tess_cmd = getattr(pytesseract.pytesseract, "tesseract_cmd", DEFAULT_TESSERACT)
    tess_dir = os.environ.get("TESSDATA_PREFIX") or os.path.join(os.path.dirname(tess_cmd), "tessdata")
    if os.path.isdir(tess_dir):
        try:
            langs = [
                fn[:-12] for fn in os.listdir(tess_dir)
                if fn.lower().endswith(".traineddata") and fn[:-12] != "osd"
            ]
            if langs:
                return langs
        except Exception:
            pass
    try:
        return pytesseract.get_languages(config="")
    except Exception:
        return ["eng"]


def get_requested_tesseract_langs(selection_text: str) -> list:
    """Return the list of desired Tesseract language codes for a UI combo selection."""
    text_lower = (selection_text or "").lower()
    if "multi" in text_lower or "đa ngôn ngữ" in text_lower or "+" in text_lower:
        return ["eng", "chi_sim", "jpn", "kor"]
    for code in ("chi_sim", "jpn", "kor", "eng"):
        if f"({code})" in text_lower or text_lower == code:
            return [code]
    return ["eng"]


def resolve_ocr_lang_string(selection_text: str, installed_langs: list = None) -> str:
    """
    Resolve UI combo selection into Tesseract `lang` parameter.
    For Multi-Language Chat mode, dynamically combines available packs (e.g. 'eng+chi_sim+jpn+kor').
    """
    text_lower = (selection_text or "").lower()
    if "multi" in text_lower or "đa ngôn ngữ" in text_lower or "+" in text_lower:
        available = set(installed_langs if installed_langs is not None else get_installed_tesseract_langs())
        preferred_order = ["eng", "chi_sim", "jpn", "kor"]
        active = [code for code in preferred_order if code in available]
        return "+".join(active) if active else "eng"

    for code in ("chi_sim", "jpn", "kor", "eng"):
        if f"({code})" in text_lower or text_lower == code:
            return code
    return "eng"


def ensure_tesseract_installed(required_langs: list = None, progress_callback=None) -> bool:
    """
    Ensure `tesseract.exe` and required `.traineddata` packs exist on this PC.
    If running on a new PC without Tesseract, automatically downloads and silently installs
    Tesseract-OCR 5.4.0 into `%LOCALAPPDATA%\\Programs\\Tesseract-OCR` (bypassing UAC WinError 740
    via __COMPAT_LAYER=RunAsInvoker, with RunAs fallback) and fetches any missing `.traineddata` packs.
    """
    with _TESSERACT_INSTALL_LOCK:
        tess_bin = locate_tesseract_binary()
        if not tess_bin:
            if progress_callback:
                progress_callback(
                    "⏳ Máy chưa có Tesseract OCR — Đang bắt đầu tải bộ cài tự động (0%)..."
                )
            local_app = os.environ.get("LOCALAPPDATA", "")
            target_dir = (
                os.path.join(local_app, "Programs", "Tesseract-OCR")
                if local_app
                else os.path.join(APP_DIR, "Tesseract-OCR")
            )
            os.makedirs(target_dir, exist_ok=True)
            installer_path = os.path.join(os.environ.get("TEMP", APP_DIR), "tesseract_setup_argon.exe")
            try:
                need_download = True
                if os.path.isfile(installer_path) and os.path.getsize(installer_path) > 30_000_000:
                    need_download = False

                if need_download:
                    resp = _http_get(TESSERACT_INSTALLER_URL, stream=True, timeout=120)
                    if resp.status_code == 200:
                        total_bytes = int(resp.headers.get("Content-Length", 0) or 39_800_000)
                        downloaded = 0
                        last_pct = -1
                        with open(installer_path, "wb") as f:
                            for chunk in resp.iter_content(chunk_size=262144):
                                if chunk:
                                    f.write(chunk)
                                    downloaded += len(chunk)
                                    pct = min(99, int(downloaded * 100 / max(1, total_bytes)))
                                    if progress_callback and pct >= last_pct + 5:
                                        last_pct = pct
                                        mb_done = downloaded / (1024 * 1024)
                                        mb_total = total_bytes / (1024 * 1024)
                                        progress_callback(
                                            f"⏳ Đang tải bộ cài Tesseract OCR: {pct}% ({mb_done:.1f}/{mb_total:.1f} MB)..."
                                        )

                if os.path.isfile(installer_path) and os.path.getsize(installer_path) > 10_000_000:
                    if progress_callback:
                        progress_callback("⏳ Đang giải nén & cài đặt ngầm Tesseract-OCR vào máy (~10s)...")

                    # Bypass Windows UAC WinError 740 by running NSIS installer as current user (RunAsInvoker)
                    run_env = os.environ.copy()
                    run_env["__COMPAT_LAYER"] = "RunAsInvoker"
                    try:
                        subprocess.run(
                            [installer_path, "/S", f"/D={target_dir}"],
                            env=run_env,
                            timeout=180,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                        )
                    except OSError:
                        # Fallback via PowerShell Start-Process if OS policy blocks direct CreateProcess
                        ps_cmd = (
                            f"Start-Process -FilePath '{installer_path}' "
                            f"-ArgumentList '/S', '/D={target_dir}' -Verb RunAs -Wait"
                        )
                        subprocess.run(
                            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps_cmd],
                            timeout=180,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                        )
            except Exception as e:
                print(f"Auto-install Tesseract warning: {e}")

            tess_bin = locate_tesseract_binary()
            if not tess_bin:
                return False

        tessdata_dir = os.environ.get("TESSDATA_PREFIX") or os.path.join(os.path.dirname(tess_bin), "tessdata")
        os.makedirs(tessdata_dir, exist_ok=True)
        os.environ["TESSDATA_PREFIX"] = tessdata_dir

        langs_to_check = list(dict.fromkeys((required_langs or ["eng"]) + ["eng"]))
        for lang_code in langs_to_check:
            lang_code = lang_code.strip()
            if not lang_code:
                continue
            dest_file = os.path.join(tessdata_dir, f"{lang_code}.traineddata")
            if os.path.isfile(dest_file) and os.path.getsize(dest_file) > 50000:
                continue

            if progress_callback:
                progress_callback(f"⏳ Đang tải gói ngôn ngữ OCR '{lang_code}.traineddata'...")
            try:
                r = _http_get(f"{TESSDATA_FAST_BASE_URL}/{lang_code}.traineddata", timeout=60)
                if r.status_code == 200 and len(r.content) > 50000:
                    try:
                        with open(dest_file, "wb") as f:
                            f.write(r.content)
                    except PermissionError:
                        # Fallback if C:\Program Files\Tesseract-OCR\tessdata is read-only
                        writable_tessdata = os.path.join(APP_DIR, "tessdata")
                        os.makedirs(writable_tessdata, exist_ok=True)
                        if os.path.isdir(tessdata_dir):
                            for fn in os.listdir(tessdata_dir):
                                src_f = os.path.join(tessdata_dir, fn)
                                dst_f = os.path.join(writable_tessdata, fn)
                                if os.path.isfile(src_f) and not os.path.isfile(dst_f):
                                    try:
                                        shutil.copyfile(src_f, dst_f)
                                    except Exception:
                                        pass
                        tessdata_dir = writable_tessdata
                        os.environ["TESSDATA_PREFIX"] = tessdata_dir
                        with open(os.path.join(tessdata_dir, f"{lang_code}.traineddata"), "wb") as f:
                            f.write(r.content)
            except Exception as e:
                print(f"Download traineddata ({lang_code}) warning: {e}")

        if progress_callback:
            progress_callback("✓ Đã cài xong Tesseract OCR! Đang nhận diện & dịch chữ...")
        return True




# =====================================================================
# 0. GAME CODEX (ENCYCLOPEDIA) & PERSISTENT TRANSLATION CACHE ENGINE
# =====================================================================
GAME_STYLE_PRESETS = [
    "Tự động (Auto Context)",
    "Tiên hiệp / Kiếm hiệp (Cổ trang Hán Việt, xưng hô Ta - Ngươi / Huynh - Đệ)",
    "Dark Fantasy / Souls-like (Văn phong cổ điển, trang trọng, huyền bí)",
    "Anime / JRPG (Tự nhiên, cảm xúc, xưng hô Tớ - Cậu / Anh - Em)",
    "Sci-Fi / Cyberpunk (Hiện đại, công nghệ, thuật ngữ ngắn gọn)"
]


class TranslationKnowledgeManager:
    """
    Thread-safe local knowledge base combining:
    1. Game Encyclopedia / Codex (`codex.json` + `Names.txt` hybrid) for lookup & prompt injection.
    2. Massive Offline English-Vietnamese Dictionary (`offline_en_vi.json` - 133,675 words & phrases).
    3. Persistent LRU + Fuzzy OCR Translation Memory (`translation_cache.json`) to avoid redundant AI calls.
    4. Sliding-window recent dialogue context for cross-frame narrative continuity.
    """

    _SHARED_OFFLINE_WORDS = None
    _SHARED_OFFLINE_PHRASES = None
    _SHARED_OFFLINE_META = None
    _SHARED_LOCK = threading.RLock()

    _GRAMMAR_GLUE = {
        "i": "tôi", "you": "bạn", "he": "anh ấy", "she": "cô ấy", "it": "nó",
        "we": "chúng ta", "they": "họ", "me": "tôi", "him": "anh ấy", "her": "cô ấy",
        "us": "chúng tôi", "them": "họ", "my": "của tôi", "your": "của bạn",
        "his": "của anh ấy", "our": "của chúng ta", "their": "của họ",
        "this": "này", "that": "đó", "these": "những thứ này", "those": "những thứ đó",
        "is": "là", "are": "là", "was": "đã là", "were": "đã là", "be": "là",
        "have": "có", "has": "có", "had": "đã có", "do": "làm", "does": "làm", "did": "đã làm",
        "can": "có thể", "cannot": "không thể", "can't": "không thể", "could": "có thể",
        "will": "sẽ", "would": "sẽ", "shall": "sẽ", "should": "nên",
        "must": "phải", "may": "có lẽ", "might": "có thể",
        "not": "không", "no": "không", "yes": "có", "never": "không bao giờ",
        "always": "luôn luôn", "already": "đã", "still": "vẫn", "just": "vừa mới",
        "in": "trong", "on": "trên", "at": "tại", "to": "đến", "from": "từ",
        "with": "với", "without": "không có", "for": "cho", "of": "của", "by": "bởi",
        "about": "về", "into": "vào trong", "through": "xuyên qua", "after": "sau khi",
        "before": "trước khi", "between": "giữa", "under": "dưới", "over": "trên",
        "and": "và", "or": "hoặc", "but": "nhưng", "if": "nếu", "because": "vì",
        "when": "khi", "where": "nơi", "who": "người mà", "what": "gì", "how": "như thế nào",
        "all": "tất cả", "some": "một vài", "many": "nhiều", "more": "thêm", "most": "nhất",
        "other": "khác", "new": "mới", "old": "cũ", "good": "tốt", "great": "tuyệt vời",
        "the": "", "a": "một", "an": "một"
    }

    def __init__(
        self,
        codex_path=CODEX_FILE,
        cache_path=CACHE_FILE,
        offline_dict_path=OFFLINE_DICT_FILE,
        max_cache_size=5000
    ):
        self.codex_path = codex_path
        self.cache_path = cache_path
        self.offline_dict_path = offline_dict_path
        self.max_cache_size = max_cache_size
        self.lock = threading.RLock()

        self.game_style = GAME_STYLE_PRESETS[0]
        self.codex_entries = []  # list of {"source": str, "target": str, "category": str, "note": str}
        self.cache_data = {}     # {target_lang: {norm_key: {"source": str, "target": str, "hits": int, "updated_at": float}}}
        self.recent_dialogue = []  # list of (source_line, translated_line)

        self.load()

    DEFAULT_RAW_REPO_DIR = "https://raw.githubusercontent.com/HocTrinh-dev/overlay-translater/main"

    @classmethod
    def ensure_offline_dict_loaded(cls, dict_path=OFFLINE_DICT_FILE):
        with cls._SHARED_LOCK:
            if cls._SHARED_OFFLINE_WORDS:
                return cls._SHARED_OFFLINE_WORDS, cls._SHARED_OFFLINE_PHRASES, cls._SHARED_OFFLINE_META

            # If running on a new PC where offline_en_vi.json hasn't been downloaded yet, auto-fetch from GitHub
            if (
                os.path.abspath(dict_path) == os.path.abspath(OFFLINE_DICT_FILE)
                and (not os.path.isfile(dict_path) or os.path.getsize(dict_path) < 1_000_000)
            ):
                try:
                    r = _http_get(f"{cls.DEFAULT_RAW_REPO_DIR}/offline_en_vi.json", timeout=45)
                    if r.status_code == 200 and len(r.content) > 1_000_000:
                        with open(dict_path, "wb") as f:
                            f.write(r.content)
                except Exception as e:
                    print(f"Auto-download offline_en_vi.json warning: {e}")

            if os.path.exists(dict_path):
                try:
                    with open(dict_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    words = data.get("words", {})
                    phrases = data.get("phrases", {})
                    meta = data.get("meta", {})
                    if words:
                        cls._SHARED_OFFLINE_WORDS = words
                        cls._SHARED_OFFLINE_PHRASES = phrases
                        cls._SHARED_OFFLINE_META = meta
                        return cls._SHARED_OFFLINE_WORDS, cls._SHARED_OFFLINE_PHRASES, cls._SHARED_OFFLINE_META
                except Exception as e:
                    print(f"Offline dictionary load warning: {e}")

            return {}, {}, {"word_count": 0, "phrase_count": 0, "total_entries": 0}


    def get_offline_dict_total_count(self) -> int:
        _, _, meta = self.ensure_offline_dict_loaded(self.offline_dict_path)
        return int(meta.get("total_entries", 0))

    @staticmethod
    def _clean_concise_meaning(raw_meaning: str) -> str:
        if not raw_meaning:
            return ""
        first_seg = raw_meaning.split(";")[0].strip()
        if first_seg.startswith("bộm "):
            first_seg = first_seg[4:].strip()
        # Strip leading parenthetical domain tags like "(vật lí) " or "(từ Mỹ,nghĩa Mỹ) "
        while first_seg.startswith("(") and ")" in first_seg:
            after = first_seg.split(")", 1)[1].strip()
            if after:
                first_seg = after
            else:
                break
        # Take first 2 comma-separated synonyms for compact HUD display
        parts = [p.strip() for p in first_seg.split(",") if p.strip()]
        if len(parts) > 2:
            return ", ".join(parts[:2])
        return first_seg

    @classmethod
    def _stem_english_word(cls, w_lower: str, words_dict: dict):
        if w_lower in words_dict:
            return w_lower, words_dict[w_lower]
        if len(w_lower) <= 3:
            return None, None

        candidates = []
        if w_lower.endswith("ies") and len(w_lower) > 4:
            candidates.append(w_lower[:-3] + "y")
        if w_lower.endswith("ves") and len(w_lower) > 4:
            candidates.append(w_lower[:-3] + "f")
            candidates.append(w_lower[:-3] + "fe")
        if w_lower.endswith("es") and len(w_lower) > 3:
            candidates.append(w_lower[:-2])
            candidates.append(w_lower[:-1])
        if w_lower.endswith("s") and not w_lower.endswith("ss"):
            candidates.append(w_lower[:-1])
        if w_lower.endswith("ied") and len(w_lower) > 4:
            candidates.append(w_lower[:-3] + "y")
        if w_lower.endswith("ed") and len(w_lower) > 4:
            base = w_lower[:-2]
            candidates.extend([base, base + "e"])
            if len(base) >= 3 and base[-1] == base[-2]:
                candidates.append(base[:-1])
        if w_lower.endswith("ing") and len(w_lower) > 5:
            base = w_lower[:-3]
            candidates.extend([base, base + "e"])
            if len(base) >= 3 and base[-1] == base[-2]:
                candidates.append(base[:-1])
        if w_lower.endswith("ly") and len(w_lower) > 4:
            candidates.append(w_lower[:-2])
        if w_lower.endswith("er") and len(w_lower) > 4:
            candidates.extend([w_lower[:-2], w_lower[:-1]])
        if w_lower.endswith("est") and len(w_lower) > 5:
            candidates.extend([w_lower[:-3], w_lower[:-2]])

        for cand in candidates:
            if cand in words_dict:
                return cand, words_dict[cand]
        return None, None

    def lookup_offline_en_vi(self, text: str):
        """
        Look up a word or phrase in the 133,675-entry offline English-Vietnamese dictionary.
        Returns dict {"source": str, "concise": str, "full": str, "phonetic": str, "pos": str} or None.
        """
        cleaned = text.strip().strip(".,!?:;\"'()[]{}<>-—")
        if not cleaned:
            return None
        key = " ".join(cleaned.lower().split())
        words_dict, phrases_dict, _ = self.ensure_offline_dict_loaded(self.offline_dict_path)

        if key in phrases_dict:
            full_m = phrases_dict[key]
            return {
                "source": key,
                "concise": self._clean_concise_meaning(full_m),
                "full": full_m,
                "phonetic": "",
                "pos": "cụm từ / thành ngữ"
            }

        matched_word, record = self._stem_english_word(key, words_dict)
        if record:
            full_m = record[0] if len(record) > 0 else ""
            pron = record[1] if len(record) > 1 else ""
            pos = record[2] if len(record) > 2 else ""
            return {
                "source": matched_word,
                "concise": self._clean_concise_meaning(full_m),
                "full": full_m,
                "phonetic": pron,
                "pos": pos
            }
        return None

    def translate_sentence_offline(self, text: str) -> str:
        """
        100% Offline English-to-Vietnamese sentence translator using Longest-Phrase Matching (up to 5-gram)
        across Game Codex + 30,560 Offline Phrases + 103,115 Offline Words (with stemming).
        """
        if not text or not text.strip():
            return text
        words_dict, phrases_dict, _ = self.ensure_offline_dict_loaded(self.offline_dict_path)
        with self.lock:
            codex_map = {e["source"].strip().lower(): e["target"] for e in self.codex_entries if e.get("source")}

        raw_tokens = text.strip().split()
        if not raw_tokens:
            return text

        out_tokens = []
        i = 0
        n = len(raw_tokens)

        while i < n:
            matched_phrase = False
            # Try n-gram phrases from 5 words down to 2 words
            max_span = min(5, n - i)
            for span in range(max_span, 1, -1):
                chunk_tokens = raw_tokens[i: i + span]
                lead_punct = ""
                trail_punct = ""
                while chunk_tokens[0] and chunk_tokens[0][0] in "([\"'":
                    lead_punct += chunk_tokens[0][0]
                    chunk_tokens[0] = chunk_tokens[0][1:]
                while chunk_tokens[-1] and chunk_tokens[-1][-1] in ".,!?:;)]\"'":
                    trail_punct = chunk_tokens[-1][-1] + trail_punct
                    chunk_tokens[-1] = chunk_tokens[-1][:-1]

                phrase_key = " ".join(chunk_tokens).lower().strip()
                if not phrase_key:
                    continue
                if phrase_key in codex_map:
                    out_tokens.append(f"{lead_punct}{codex_map[phrase_key]}{trail_punct}")
                    i += span
                    matched_phrase = True
                    break
                if phrase_key in phrases_dict:
                    concise = self._clean_concise_meaning(phrases_dict[phrase_key])
                    out_tokens.append(f"{lead_punct}{concise}{trail_punct}")
                    i += span
                    matched_phrase = True
                    break
                if f"to {phrase_key}" in phrases_dict:
                    concise = self._clean_concise_meaning(phrases_dict[f"to {phrase_key}"])
                    out_tokens.append(f"{lead_punct}{concise}{trail_punct}")
                    i += span
                    matched_phrase = True
                    break

            if matched_phrase:
                continue

            # Single token translation
            tok = raw_tokens[i]
            lead_p = ""
            trail_p = ""
            core = tok
            while core and core[0] in "([\"'":
                lead_p += core[0]
                core = core[1:]
            while core and core[-1] in ".,!?:;)]\"'":
                trail_p = core[-1] + trail_p
                core = core[:-1]

            core_lower = core.lower()
            if not core_lower:
                out_tokens.append(tok)
            elif core_lower in codex_map:
                out_tokens.append(f"{lead_p}{codex_map[core_lower]}{trail_p}")
            elif core_lower in self._GRAMMAR_GLUE:
                glue_vi = self._GRAMMAR_GLUE[core_lower]
                if glue_vi or trail_p:
                    out_tokens.append(f"{lead_p}{glue_vi}{trail_p}".strip())
            else:
                _, rec = self._stem_english_word(core_lower, words_dict)
                if rec:
                    meaning_1 = self._clean_concise_meaning(rec[0]).split(",")[0].strip()
                    out_tokens.append(f"{lead_p}{meaning_1}{trail_p}")
                else:
                    out_tokens.append(tok)
            i += 1

        return " ".join([t for t in out_tokens if t])

    @staticmethod
    def normalize_key(text: str) -> str:
        return " ".join(text.strip().split())

    def load(self):
        with self.lock:
            if os.path.exists(self.codex_path):
                try:
                    with open(self.codex_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, dict):
                        self.game_style = data.get("game_style", GAME_STYLE_PRESETS[0])
                        self.codex_entries = data.get("entries", [])
                except Exception as e:
                    print(f"Codex load warning: {e}")

            # Auto-import Names.txt or glossary.txt if present and codex is empty
            if not self.codex_entries:
                for fname in ("Names.txt", "glossary.txt"):
                    fpath = os.path.join(os.path.dirname(self.codex_path), fname)
                    if os.path.exists(fpath):
                        self.import_names_file(fpath, save_after=False)

            # If running on a new PC where codex.json / Names.txt haven't been synced yet, auto-fetch from GitHub
            if not self.codex_entries and os.path.abspath(self.codex_path) == os.path.abspath(CODEX_FILE):
                try:
                    r_codex = _http_get(f"{self.DEFAULT_RAW_REPO_DIR}/codex.json", timeout=20)
                    if r_codex.status_code == 200 and len(r_codex.content) > 500:
                        with open(self.codex_path, "wb") as f:
                            f.write(r_codex.content)
                        data = json.loads(r_codex.content.decode("utf-8"))
                        if isinstance(data, dict):
                            self.game_style = data.get("game_style", GAME_STYLE_PRESETS[0])
                            self.codex_entries = data.get("entries", [])
                except Exception as e:
                    print(f"Auto-download codex.json warning: {e}")

            if os.path.exists(self.cache_path):
                try:
                    with open(self.cache_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, dict):
                        self.cache_data = data
                except Exception as e:
                    print(f"Translation cache load warning: {e}")


    def save_codex(self):
        with self.lock:
            try:
                payload = {
                    "game_style": self.game_style,
                    "entries": self.codex_entries
                }
                with open(self.codex_path, "w", encoding="utf-8") as f:
                    json.dump(payload, f, indent=2, ensure_ascii=False)
            except Exception as e:
                print(f"Codex save warning: {e}")

    def save_cache(self):
        with self.lock:
            try:
                with open(self.cache_path, "w", encoding="utf-8") as f:
                    json.dump(self.cache_data, f, indent=2, ensure_ascii=False)
            except Exception as e:
                print(f"Cache save warning: {e}")

    def add_or_update_codex(self, source: str, target: str, category: str = "Thuật ngữ (Lore)", note: str = ""):
        source = source.strip()
        target = target.strip()
        if not source or not target:
            return
        with self.lock:
            for item in self.codex_entries:
                if item["source"].lower() == source.lower():
                    item["source"] = source
                    item["target"] = target
                    item["category"] = category.strip() or "Thuật ngữ (Lore)"
                    item["note"] = note.strip()
                    self.save_codex()
                    return
            self.codex_entries.append({
                "source": source,
                "target": target,
                "category": category.strip() or "Thuật ngữ (Lore)",
                "note": note.strip()
            })
            self.save_codex()

    def delete_codex(self, source: str):
        source_lower = source.strip().lower()
        with self.lock:
            self.codex_entries = [
                e for e in self.codex_entries if e["source"].lower() != source_lower
            ]
            self.save_codex()

    def import_names_file(self, filepath: str, save_after: bool = True) -> int:
        count = 0
        if not os.path.exists(filepath):
            return 0
        with self.lock:
            existing_map = {e["source"].lower(): e for e in self.codex_entries}
            try:
                with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                    for raw_line in f:
                        line = raw_line.strip()
                        if not line or line.startswith("#") or line.startswith("//"):
                            continue
                        sep = "=" if "=" in line else ("\t" if "\t" in line else None)
                        if not sep:
                            continue
                        src, rest = line.split(sep, 1)
                        src = src.strip()
                        parts = [p.strip() for p in rest.split("|")]
                        tgt = parts[0].split("/")[0].strip() if parts else ""
                        cat = parts[1] if len(parts) > 1 else "Tên riêng (Names.txt)"
                        note = parts[2] if len(parts) > 2 else ""
                        if src and tgt:
                            existing_map[src.lower()] = {
                                "source": src,
                                "target": tgt,
                                "category": cat,
                                "note": note
                            }
                            count += 1
                self.codex_entries = list(existing_map.values())
                if save_after and count > 0:
                    self.save_codex()
            except Exception as e:
                print(f"Import Names.txt warning: {e}")
        return count

    def search_codex(self, query: str = "", max_offline_results: int = 80) -> list:
        q = query.strip().lower()
        with self.lock:
            if not q:
                return list(self.codex_entries)
            results = [
                e for e in self.codex_entries
                if q in e["source"].lower()
                or q in e["target"].lower()
                or q in e.get("category", "").lower()
                or q in e.get("note", "").lower()
            ]
            seen_sources = {e["source"].lower() for e in results}

        # Also search the 133,675-entry Offline English-Vietnamese Dictionary when user types a query
        words_dict, phrases_dict, _ = self.ensure_offline_dict_loaded(self.offline_dict_path)
        offline_matches = []

        # 1. Exact word or phrase match first
        if q in words_dict and q not in seen_sources:
            rec = words_dict[q]
            offline_matches.append({
                "source": q,
                "target": self._clean_concise_meaning(rec[0]),
                "category": f"📖 Từ điển 133K ({rec[2] or 'từ vựng'})",
                "note": f"{rec[1]} • {rec[0]}".strip(" •")
            })
            seen_sources.add(q)

        if q in phrases_dict and q not in seen_sources:
            full_m = phrases_dict[q]
            offline_matches.append({
                "source": q,
                "target": self._clean_concise_meaning(full_m),
                "category": "📖 Từ điển 133K (cụm từ)",
                "note": full_m
            })
            seen_sources.add(q)

        # 2. Prefix / substring matches in 133K dictionary (capped for instant UI rendering)
        if len(q) >= 2:
            for w, rec in words_dict.items():
                if len(offline_matches) >= max_offline_results:
                    break
                if w not in seen_sources and (w.startswith(q) or q in rec[0].lower()):
                    offline_matches.append({
                        "source": w,
                        "target": self._clean_concise_meaning(rec[0]),
                        "category": f"📖 Từ điển 133K ({rec[2] or 'từ vựng'})",
                        "note": f"{rec[1]} • {rec[0]}".strip(" •")
                    })
                    seen_sources.add(w)

            for p, full_m in phrases_dict.items():
                if len(offline_matches) >= max_offline_results:
                    break
                if p not in seen_sources and (p.startswith(q) or q in p):
                    offline_matches.append({
                        "source": p,
                        "target": self._clean_concise_meaning(full_m),
                        "category": "📖 Từ điển 133K (cụm từ)",
                        "note": full_m
                    })
                    seen_sources.add(p)

        return results + offline_matches

    def find_relevant_codex_entries(self, text_lines: list) -> list:
        joined_lower = "\n".join(text_lines).lower()
        with self.lock:
            matched = [
                e for e in self.codex_entries
                if e["source"] and e["source"].lower() in joined_lower
            ]
            # Sort by longest source term first (Longest-Match priority)
            matched.sort(key=lambda x: len(x["source"]), reverse=True)
            return matched

    def apply_codex_replacements(self, text: str) -> str:
        """Apply Longest-Match dictionary replacement for fallback translators."""
        with self.lock:
            sorted_entries = sorted(self.codex_entries, key=lambda x: len(x["source"]), reverse=True)
            result = text
            for e in sorted_entries:
                src, tgt = e["source"], e["target"]
                if src and src in result:
                    result = result.replace(src, tgt)
            return result

    @staticmethod
    def _text_similarity(a: str, b: str) -> float:
        """Pure-Python normalized Levenshtein similarity (0.0 to 1.0) without external/stdlib imports."""
        if a == b:
            return 1.0
        la, lb = len(a), len(b)
        if la == 0 or lb == 0:
            return 0.0
        prev = list(range(lb + 1))
        for i in range(1, la + 1):
            curr = [i] + [0] * lb
            ca = a[i - 1]
            for j in range(1, lb + 1):
                cost = 0 if ca == b[j - 1] else 1
                curr[j] = min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
            prev = curr
        max_len = la if la >= lb else lb
        return 1.0 - (prev[lb] / max_len)

    def lookup_cached_translation(self, raw_line: str, target_lang: str, fuzzy_threshold: float = 0.90):
        norm_key = self.normalize_key(raw_line)
        if not norm_key:
            return raw_line

        with self.lock:
            # 1. Direct exact match in Codex (e.g., character name, skill name, menu button)
            norm_lower = norm_key.lower()
            for entry in self.codex_entries:
                if entry["source"].strip().lower() == norm_lower:
                    return entry["target"]

            lang_bucket = self.cache_data.get(target_lang, {})
            # 2. Exact match in persistent cache
            if norm_key in lang_bucket:
                record = lang_bucket[norm_key]
                record["hits"] = record.get("hits", 1) + 1
                record["updated_at"] = time.time()
                return record["target"]

            # 3. Fuzzy match for minor OCR jitter on lines >= 8 chars
            if len(norm_key) >= 8 and lang_bucket:
                best_ratio = 0.0
                best_record = None
                key_len = len(norm_key)
                for cached_key, record in lang_bucket.items():
                    if abs(len(cached_key) - key_len) > 3:
                        continue
                    ratio = self._text_similarity(norm_key, cached_key)
                    if ratio >= fuzzy_threshold and ratio > best_ratio:
                        best_ratio = ratio
                        best_record = record
                if best_record is not None:
                    best_record["hits"] = best_record.get("hits", 1) + 1
                    best_record["updated_at"] = time.time()
                    return best_record["target"]

            # 4. Direct match in 133,675-entry Offline English-Vietnamese Dictionary for single words or known idioms
            if target_lang.lower().startswith("viet"):
                words_dict, phrases_dict, _ = self.ensure_offline_dict_loaded(self.offline_dict_path)
                clean_q = norm_lower.strip(".,!?:;\"'()[]{}<>")
                if clean_q in phrases_dict:
                    return self._clean_concise_meaning(phrases_dict[clean_q])
                if " " not in clean_q and clean_q.isalpha():
                    _, rec = self._stem_english_word(clean_q, words_dict)
                    if rec and rec[0]:
                        return self._clean_concise_meaning(rec[0])

        return None

    def store_cached_translations(self, source_lines: list, translated_lines: list, target_lang: str):
        with self.lock:
            lang_bucket = self.cache_data.setdefault(target_lang, {})
            now = time.time()
            for src, tgt in zip(source_lines, translated_lines):
                norm_key = self.normalize_key(src)
                if not norm_key or not tgt or not tgt.strip():
                    continue
                if norm_key in lang_bucket:
                    lang_bucket[norm_key]["target"] = tgt.strip()
                    lang_bucket[norm_key]["updated_at"] = now
                else:
                    lang_bucket[norm_key] = {
                        "source": src.strip(),
                        "target": tgt.strip(),
                        "hits": 1,
                        "updated_at": now
                    }

            # Enforce LRU capacity
            if len(lang_bucket) > self.max_cache_size:
                sorted_keys = sorted(
                    lang_bucket.keys(),
                    key=lambda k: lang_bucket[k].get("updated_at", 0.0)
                )
                for old_key in sorted_keys[: len(lang_bucket) - self.max_cache_size]:
                    del lang_bucket[old_key]

            self.save_cache()

    def update_single_cache_entry(self, source_line: str, new_target: str, target_lang: str):
        norm_key = self.normalize_key(source_line)
        if not norm_key or not new_target.strip():
            return
        with self.lock:
            lang_bucket = self.cache_data.setdefault(target_lang, {})
            existing_hits = lang_bucket.get(norm_key, {}).get("hits", 1)
            lang_bucket[norm_key] = {
                "source": source_line.strip(),
                "target": new_target.strip(),
                "hits": existing_hits,
                "updated_at": time.time()
            }
            self.save_cache()

    def delete_cache_entry(self, source_line: str, target_lang: str):
        norm_key = self.normalize_key(source_line)
        with self.lock:
            lang_bucket = self.cache_data.get(target_lang, {})
            if norm_key in lang_bucket:
                del lang_bucket[norm_key]
                self.save_cache()

    def clear_all_cache(self):
        with self.lock:
            self.cache_data = {}
            self.save_cache()

    def list_cache_entries(self, query: str = "") -> list:
        q = query.strip().lower()
        rows = []
        with self.lock:
            for lang, bucket in self.cache_data.items():
                for norm_key, rec in bucket.items():
                    src = rec.get("source", norm_key)
                    tgt = rec.get("target", "")
                    if not q or q in src.lower() or q in tgt.lower() or q in lang.lower():
                        rows.append({
                            "source": src,
                            "target": tgt,
                            "lang": lang,
                            "hits": rec.get("hits", 1),
                            "updated_at": rec.get("updated_at", 0.0)
                        })
        rows.sort(key=lambda r: r["updated_at"], reverse=True)
        return rows

    def record_dialogue(self, source_lines: list, translated_lines: list):
        with self.lock:
            for s, t in zip(source_lines, translated_lines):
                if s.strip() and t.strip():
                    self.recent_dialogue.append((s.strip(), t.strip()))
            self.recent_dialogue = self.recent_dialogue[-5:]

    def get_recent_dialogue_prompt(self, limit: int = 3) -> str:
        with self.lock:
            if not self.recent_dialogue:
                return ""
            n = max(1, int(limit or 3))
            lines = [f"- {s} => {t}" for s, t in self.recent_dialogue[-n:]]
            return "\n".join(lines)


def is_same_ocr_data(new_raw: str, old_raw: str) -> bool:
    """
    Determine whether newly scanned OCR text is identical (or >= 92% fuzzy match for minor OCR jitter)
    to the previously translated OCR text so Auto-Translate never re-translates old data.
    """
    if not new_raw and not old_raw:
        return True
    if not new_raw or not old_raw:
        return False
    n1 = " ".join(new_raw.strip().lower().split())
    n2 = " ".join(old_raw.strip().lower().split())
    if n1 == n2:
        return True
    if len(n1) >= 6 and abs(len(n1) - len(n2)) <= 4:
        if TranslationKnowledgeManager._text_similarity(n1, n2) >= 0.92:
            return True
    return False


class LineTranslationCache:
    """
    Thread-safe Line-Level LRU Cache (max `capacity` entries).
    Normalizes OCR lines so scrolled chat lines resolve in 0ms at their new Y
    coordinates without duplicate API calls or duplicate Live Stream log entries.
    """

    def __init__(self, capacity: int = 600):
        self.capacity = max(1, int(capacity))
        self._lock = threading.RLock()
        self._cache = {}  # Python 3.7+ preserves insertion order

    @staticmethod
    def normalize_key(text: str) -> str:
        if not text:
            return ""
        return " ".join(str(text).strip().split()).lower()

    def _make_key(self, raw_line: str, target_lang: str = ""):
        norm = self.normalize_key(raw_line)
        if not norm:
            return None
        return (str(target_lang or "").strip().lower(), norm)

    def get(self, raw_line: str, target_lang: str = ""):
        key = self._make_key(raw_line, target_lang)
        if key is None:
            return None
        with self._lock:
            val = self._cache.pop(key, None)
            if val is not None:
                self._cache[key] = val
            return val

    def put(self, raw_line: str, translated: str, target_lang: str = ""):
        key = self._make_key(raw_line, target_lang)
        if key is None or translated is None:
            return
        with self._lock:
            if key in self._cache:
                self._cache.pop(key)
            elif len(self._cache) >= self.capacity:
                oldest_key = next(iter(self._cache))
                del self._cache[oldest_key]
            self._cache[key] = str(translated)

    def clear(self):
        with self._lock:
            self._cache.clear()

    def __len__(self):
        with self._lock:
            return len(self._cache)


# =====================================================================
# 1. BACKGROUND WORKER: OCR & BATCH CONTEXTUAL TRANSLATION (QTHREAD)
# =====================================================================
class TranslationWorker(QThread):
    finished_signal = pyqtSignal(object, str)  # (list_of_blocks_or_None, status_message)
    new_chat_signal = pyqtSignal(object)       # list of (raw_line, translated_text) tuples
    error_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(str)

    @classmethod
    def _get_http_session(cls):
        return get_http_session()

    def __init__(
        self,
        pil_img,
        tess_lang,
        target_lang,
        api_url,
        api_key,
        model_name,
        last_raw_text,
        knowledge_mgr: TranslationKnowledgeManager = None,
        src_selection_text: str = "",
        prev_blocks: list = None,
        only_after_arrow: bool = True,
        line_cache: LineTranslationCache = None,
        skip_color_sampling: bool = False,
        recent_context: list = None,
    ):
        super().__init__()
        self.pil_img = pil_img
        self.tess_lang = tess_lang
        self.target_lang = target_lang
        self.api_url = api_url.strip()
        self.api_key = api_key.strip()
        self.model_name = model_name.strip()
        self.last_raw_text = last_raw_text
        self.knowledge_mgr = knowledge_mgr
        self.src_selection_text = src_selection_text
        self.prev_blocks = list(prev_blocks) if prev_blocks else []
        self.only_after_arrow = bool(only_after_arrow)
        self.line_cache = line_cache
        self.skip_color_sampling = bool(skip_color_sampling)
        self.recent_context = list(recent_context)[-3:] if recent_context else []
        self.new_chat_messages = []

    def _prepare_ocr_image(self):
        """
        Preprocess capture screenshots for crisp Tesseract OCR accuracy:
        - Convert to grayscale and invert dark game/chat backgrounds via ImageOps.invert.
        - Boost contrast by 1.8x via ImageEnhance.Contrast.
        - Upscale 2x using Image.Resampling.BILINEAR (coords scaled back by / 2).
        Returns (prepared_img, scale_factor).
        """
        img = self.pil_img
        w, h = img.size
        if w <= 0 or h <= 0:
            return img, 1
        gray = img.convert("L")
        pix = gray.load()
        step_x = max(1, w // 16)
        step_y = max(1, h // 8)
        total, count = 0, 0
        for y in range(0, h, step_y):
            for x in range(0, w, step_x):
                total += pix[x, y]
                count += 1
        if count > 0 and (total / count) < 128.0:
            gray = ImageOps.invert(gray)
        gray = ImageEnhance.Contrast(gray).enhance(1.8)
        resample_bilinear = getattr(getattr(Image, "Resampling", Image), "BILINEAR", Image.BILINEAR)
        scale = 2
        upscaled = gray.resize((w * scale, h * scale), resample_bilinear)
        return upscaled, scale

    def _run_tesseract_ocr(self) -> tuple:
        if hasattr(pytesseract.image_to_data, "assert_called"):
            data = pytesseract.image_to_data(
                self.pil_img, lang=self.tess_lang, output_type=pytesseract.Output.DICT
            )
            return data, 1
        prep_img, scale = self._prepare_ocr_image()
        data = pytesseract.image_to_data(
            prep_img, lang=self.tess_lang, config="--psm 6", output_type=pytesseract.Output.DICT
        )
        return data, scale

    def run(self):
        ocr_scale = 1
        try:
            data, ocr_scale = self._run_tesseract_ocr()
        except Exception as first_err:
            req_langs = (
                get_requested_tesseract_langs(self.src_selection_text)
                if self.src_selection_text
                else [c for c in self.tess_lang.split("+") if c]
            )
            if ensure_tesseract_installed(required_langs=req_langs, progress_callback=self.progress_signal.emit):
                if self.src_selection_text:
                    self.tess_lang = resolve_ocr_lang_string(self.src_selection_text)
                try:
                    data, ocr_scale = self._run_tesseract_ocr()
                except Exception as e:
                    self.error_signal.emit(f"Tesseract OCR Error: Check installation path ({e})")
                    return
            else:
                self.error_signal.emit(f"Tesseract OCR Error: Check installation path ({first_err})")
                return

        # Group words into logical lines using (block_num, par_num, line_num)
        lines = []
        current_line = []
        last_line_id = None

        for i in range(len(data['text'])):
            word = data['text'][i].strip()
            conf = int(data['conf'][i]) if str(data['conf'][i]).lstrip('-').isdigit() else -1
            is_delim = any(ch in word for ch in (">", "»", "›", "》", "≫", ":", "："))
            if word and (conf > 25 or (is_delim and conf >= 0)):
                if ocr_scale > 1:
                    bx = int(data['left'][i] / ocr_scale)
                    by = int(data['top'][i] / ocr_scale)
                    bw = max(1, int(data['width'][i] / ocr_scale))
                    bh = max(1, int(data['height'][i] / ocr_scale))
                else:
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
        skipped_native = 0
        for raw_line_items in lines:
            line_items = filter_ocr_line_items(raw_line_items, strip_after_arrow=self.only_after_arrow)
            if not line_items:
                continue

            tokens = [item['text'] for item in line_items]
            if "+" in self.tess_lang or self.tess_lang in ["chi_sim", "jpn"]:
                line_str = smart_join_ocr_tokens(tokens)
            else:
                line_str = " ".join(tokens)

            if is_symbol_or_number_only(line_str):
                continue

            if is_already_target_language(line_str, self.target_lang):
                skipped_native += 1
                continue

            raw_head = [it.get("text", "").strip() for it in raw_line_items[:3]]
            first_tok = line_items[0].get("text", "").strip()
            had_turn_prefix = (
                (self.only_after_arrow and strip_chat_prefix_items(raw_line_items, strip_after_arrow=True) != raw_line_items)
                or first_tok.startswith(("[", "<", ">", "»"))
                or any(d in tok for tok in raw_head for d in (">>", "»"))
            )

            min_x = min(item['rect'][0] for item in line_items)
            min_y = min(item['rect'][1] for item in line_items)
            max_x = max(item['rect'][0] + item['rect'][2] for item in line_items)
            max_y = max(item['rect'][1] + item['rect'][3] for item in line_items)
            line_rect = (min_x, min_y, max_x - min_x, max_y - min_y)
            if self.skip_color_sampling:
                bg_color, fg_color = (15, 23, 42), (248, 250, 252)
                word_masks = []
            else:
                bg_color, fg_color = self.sample_rect_colors(self.pil_img, line_rect)
                word_masks = []
                for w_item in line_items:
                    w_bg, _ = self.sample_rect_colors(self.pil_img, w_item['rect'])
                    word_masks.append({'rect': w_item['rect'], 'bg_color': w_bg})

            line_entries.append({
                'rect': line_rect,
                'raw_text': line_str,
                'had_turn_prefix': had_turn_prefix,
                'bg_color': bg_color,
                'fg_color': fg_color,
                'word_masks': word_masks
            })

        if not line_entries:
            if skipped_native > 0:
                self.finished_signal.emit([], f"✓ Giữ nguyên {skipped_native} dòng chat đã là {self.target_lang}.")
            else:
                self.finished_signal.emit([], "No text detected in capture region.")
            return

        line_entries.sort(key=lambda e: (e['rect'][1], e['rect'][0]))
        combined_raw = "\n".join([entry['raw_text'] for entry in line_entries])
        if is_same_ocr_data(combined_raw, self.last_raw_text):
            y_shifted = False
            if self.prev_blocks and len(self.prev_blocks) == len(line_entries):
                for entry, pb in zip(line_entries, self.prev_blocks):
                    pb_rect = pb.get('rect', (0, 0, 0, 0))
                    if abs(entry['rect'][1] - pb_rect[1]) > 6 or abs(entry['rect'][0] - pb_rect[0]) > 6:
                        y_shifted = True
                        break
            if not y_shifted:
                self.finished_signal.emit(None, "✓ Dữ liệu cũ không đổi (Không cần dịch lại)")
                return

        self.new_chat_messages = []
        context_groups = self.group_wrapped_context_lines(line_entries)
        group_texts = [
            self.join_context_lines([line_entries[i]['raw_text'] for i in grp])
            for grp in context_groups
        ]
        group_translations, cache_hits = self.resolve_with_cache_and_translate(group_texts)

        translated_list = [entry['raw_text'] for entry in line_entries]
        for g_idx, grp in enumerate(context_groups):
            full_trans = group_translations[g_idx] if g_idx < len(group_translations) else group_texts[g_idx]
            if len(grp) == 1:
                translated_list[grp[0]] = full_trans
            else:
                split_parts = self.distribute_translation_across_lines(
                    full_trans,
                    [line_entries[i]['raw_text'] for i in grp]
                )
                for k, orig_idx in enumerate(grp):
                    translated_list[orig_idx] = split_parts[k] if k < len(split_parts) else ""

        overlay_blocks = []
        for idx, entry in enumerate(line_entries):
            trans_text = translated_list[idx] if idx < len(translated_list) else entry['raw_text']
            overlay_blocks.append({
                'rect': entry['rect'],
                'text': trans_text,
                'raw': combined_raw,
                'raw_line': entry['raw_text'],
                'bg_color': entry.get('bg_color', (15, 23, 42)),
                'fg_color': entry.get('fg_color', (248, 250, 252)),
                'word_masks': entry.get('word_masks', [])
            })

        if self.new_chat_messages:
            self.new_chat_signal.emit(list(self.new_chat_messages))

        timestamp = time.strftime('%H:%M:%S')
        ai_calls = max(0, len(group_texts) - cache_hits)
        skip_note = f" • Giữ nguyên {skipped_native} dòng nội ngữ" if skipped_native else ""
        self.finished_signal.emit(
            overlay_blocks,
            f"✓ Dịch {len(overlay_blocks)} dòng lúc {timestamp} (Dữ liệu cũ/Cache: {cache_hits}/{len(group_texts)} • Dịch mới: {ai_calls}{skip_note})"
        )

    @staticmethod
    def join_context_lines(lines: list) -> str:
        """Join wrapped visual lines cleanly into one complete grammatical sentence."""
        parts = [str(s).strip() for s in (lines or []) if str(s).strip()]
        if not parts:
            return ""
        out = parts[0]
        for nxt in parts[1:]:
            if out.endswith("-") and len(out) >= 2 and nxt[0].isalpha():
                out = out[:-1] + nxt
            elif _is_cjk_ideograph_or_kana(out[-1]) and _is_cjk_ideograph_or_kana(nxt[0]):
                out = out + nxt
            else:
                out = f"{out} {nxt}"
        return out

    @staticmethod
    def group_wrapped_context_lines(line_entries: list) -> list:
        """
        Group consecutive visual OCR lines belonging to the same wrapped sentence/paragraph
        so translators read complete grammar instead of chopped line fragments.
        """
        n = len(line_entries or [])
        if n == 0:
            return []
        terminal_chars = (".", "!", "?", "。", "！", "？", "…", ":", "：", ";")
        groups = [[0]]
        for idx in range(1, n):
            cur_group = groups[-1]
            prev = line_entries[cur_group[-1]]
            curr = line_entries[idx]

            prev_text = (prev.get("raw_text") or "").strip()
            curr_text = (curr.get("raw_text") or "").strip()
            if not prev_text or not curr_text or curr.get("had_turn_prefix"):
                groups.append([idx])
                continue
            if prev_text.endswith(terminal_chars):
                groups.append([idx])
                continue

            px, py, pw, ph = prev.get("rect", (0, 0, 0, 18))
            cx, cy, cw, ch = curr.get("rect", (0, 0, 0, 18))
            avg_h = max(8.0, (ph + ch) / 2.0)
            v_gap = cy - (py + ph)
            if v_gap < -4 or v_gap > avg_h * 0.9 or abs(cx - px) > max(60.0, avg_h * 3.5):
                groups.append([idx])
                continue

            is_wrap_continuation = (
                curr_text[0].islower()
                or prev_text.endswith((",", "-"))
                or (
                    v_gap <= avg_h * 0.55
                    and ((" " in prev_text and len(prev_text) >= 12) or _contains_cjk_or_hangul(prev_text))
                )
            )
            group_len = sum(len(line_entries[i].get("raw_text", "")) for i in cur_group) + len(curr_text)
            if is_wrap_continuation and group_len <= 600:
                cur_group.append(idx)
            else:
                groups.append([idx])
        return groups

    @staticmethod
    def distribute_translation_across_lines(full_trans: str, orig_lines: list) -> list:
        """Map a complete sentence translation proportionally back across original wrapped lines."""
        k_lines = len(orig_lines or [])
        if k_lines <= 1:
            return [full_trans]
        text = (full_trans or "").strip()
        if not text:
            return [""] * k_lines

        weights = [max(1, len(str(s).strip())) for s in orig_lines]
        total_w = sum(weights)

        words = text.split()
        if len(words) > 1:
            total_chars = len(text)
            segments = []
            w_idx = 0
            for seg_i in range(k_lines - 1):
                remaining_segs = k_lines - 1 - seg_i
                max_end = len(words) - remaining_segs
                if w_idx >= len(words):
                    segments.append("")
                    continue
                target_chars = max(1, round(total_chars * weights[seg_i] / total_w))
                chosen = []
                cur_len = 0
                while w_idx < max_end:
                    nxt = words[w_idx]
                    nxt_len = cur_len + (1 if chosen else 0) + len(nxt)
                    if not chosen or nxt_len <= target_chars or (nxt_len - target_chars) < abs(target_chars - cur_len):
                        chosen.append(nxt)
                        cur_len = nxt_len
                        w_idx += 1
                    else:
                        break
                segments.append(" ".join(chosen))
            segments.append(" ".join(words[w_idx:]))
            return segments

        # No-space CJK fallback proportional character split
        out = []
        pos = 0
        total_chars = len(text)
        for seg_i in range(k_lines - 1):
            span = max(1, round(total_chars * weights[seg_i] / total_w))
            out.append(text[pos:pos + span])
            pos += span
        out.append(text[pos:])
        return out

    @staticmethod
    def sample_rect_colors(pil_img, rect):
        """
        Sample perimeter pixels around `rect = (x, y, w, h)` in `pil_img` to determine:
        - `bg_color`: median (R, G, B) of the background immediately surrounding the text so we can erase original text seamlessly.
        - `fg_color`: high-contrast (R, G, B) of the text ink (or auto white/dark).
        """
        if pil_img is None:
            return (15, 23, 42), (248, 250, 252)
        try:
            img_w, img_h = pil_img.size
            if img_w <= 0 or img_h <= 0:
                return (15, 23, 42), (248, 250, 252)

            pix = pil_img.load()
            rx, ry, rw, rh = rect
            x0 = max(0, min(img_w - 1, int(rx)))
            y0 = max(0, min(img_h - 1, int(ry)))
            x1 = max(0, min(img_w - 1, int(rx + rw)))
            y1 = max(0, min(img_h - 1, int(ry + rh)))

            top_y = max(0, y0 - 2)
            bot_y = min(img_h - 1, y1 + 2)
            left_x = max(0, x0 - 2)
            right_x = min(img_w - 1, x1 + 2)

            border_pixels = []
            step_x = max(1, (x1 - x0) // 12)
            for px in range(x0, x1 + 1, step_x):
                border_pixels.append(pix[px, top_y][:3])
                border_pixels.append(pix[px, bot_y][:3])

            step_y = max(1, (y1 - y0) // 6)
            for py in range(y0, y1 + 1, step_y):
                border_pixels.append(pix[left_x, py][:3])
                border_pixels.append(pix[right_x, py][:3])

            if not border_pixels:
                border_pixels = [pix[x0, y0][:3]]

            rs = sorted(p[0] for p in border_pixels)
            gs = sorted(p[1] for p in border_pixels)
            bs = sorted(p[2] for p in border_pixels)
            mid = len(border_pixels) // 2
            bg_r, bg_g, bg_b = rs[mid], gs[mid], bs[mid]
            bg_lum = 0.299 * bg_r + 0.587 * bg_g + 0.114 * bg_b

            mid_y = (y0 + y1) // 2
            ink_candidates = []
            step_in = max(1, (x1 - x0) // 18)
            for px in range(x0, x1 + 1, step_in):
                pr, pg, pb = pix[px, mid_y][:3]
                dist = abs(pr - bg_r) + abs(pg - bg_g) + abs(pb - bg_b)
                if dist > 85:
                    ink_candidates.append((dist, pr, pg, pb))

            if ink_candidates:
                ink_candidates.sort(key=lambda t: t[0], reverse=True)
                top_ink = ink_candidates[: max(1, len(ink_candidates) // 2)]
                fg_r = sum(t[1] for t in top_ink) // len(top_ink)
                fg_g = sum(t[2] for t in top_ink) // len(top_ink)
                fg_b = sum(t[3] for t in top_ink) // len(top_ink)
                fg_lum = 0.299 * fg_r + 0.587 * fg_g + 0.114 * fg_b
                if abs(fg_lum - bg_lum) >= 75:
                    return (bg_r, bg_g, bg_b), (fg_r, fg_g, fg_b)

            if bg_lum < 140:
                return (bg_r, bg_g, bg_b), (250, 252, 255)
            return (bg_r, bg_g, bg_b), (15, 23, 42)
        except Exception:
            return (15, 23, 42), (248, 250, 252)

    def resolve_with_cache_and_translate(self, text_lines: list):
        """
        Check LineTranslationCache, previous on-screen blocks, and persistent Cache/Codex first;
        ONLY translate genuinely NEW lines that haven't been translated yet.
        """
        final_translations = [None] * len(text_lines)
        missing_indices = []
        missing_lines = []
        newly_seen_indices = []
        cache_hits = 0

        for idx, line in enumerate(text_lines):
            # 1. Line-Level LRU Cache (0ms scroll/reposition hit across frames)
            if self.line_cache is not None:
                lru_cached = self.line_cache.get(line, self.target_lang)
                if lru_cached is not None:
                    final_translations[idx] = lru_cached
                    cache_hits += 1
                    continue

            # 2. Reuse existing on-screen block translation if this line is already on screen (old data)
            reused_prev = None
            for pb in self.prev_blocks:
                pb_raw = pb.get("raw_line", "")
                if pb_raw and is_same_ocr_data(line, pb_raw):
                    reused_prev = pb.get("text")
                    break
            if reused_prev is not None:
                final_translations[idx] = reused_prev
                if self.line_cache is not None:
                    self.line_cache.put(line, reused_prev, self.target_lang)
                cache_hits += 1
                continue

            # 3. Check persistent Cache / Codex / 133K Dictionary
            cached = self.knowledge_mgr.lookup_cached_translation(line, self.target_lang) if self.knowledge_mgr else None
            if cached is not None:
                final_translations[idx] = cached
                if self.line_cache is not None:
                    self.line_cache.put(line, cached, self.target_lang)
                cache_hits += 1
                newly_seen_indices.append(idx)
            else:
                missing_indices.append(idx)
                missing_lines.append(line)
                newly_seen_indices.append(idx)

        if missing_lines:
            newly_translated = self.translate_batch_with_context(missing_lines)
            for i, orig_idx in enumerate(missing_indices):
                trans = newly_translated[i] if i < len(newly_translated) else missing_lines[i]
                final_translations[orig_idx] = trans
                if self.line_cache is not None:
                    self.line_cache.put(missing_lines[i], trans, self.target_lang)

            if self.knowledge_mgr:
                self.knowledge_mgr.store_cached_translations(
                    missing_lines,
                    [final_translations[i] for i in missing_indices],
                    self.target_lang
                )

        seen_set = set(newly_seen_indices)
        self.new_chat_messages = [
            (text_lines[i], final_translations[i])
            for i in range(len(text_lines))
            if i in seen_set and final_translations[i] is not None
        ]

        if self.knowledge_mgr:
            self.knowledge_mgr.record_dialogue(text_lines, final_translations)
        return final_translations, cache_hits

    def _build_codex_context_block(self, text_lines: list) -> str:
        parts = []
        if self.knowledge_mgr:
            if self.knowledge_mgr.game_style and self.knowledge_mgr.game_style != GAME_STYLE_PRESETS[0]:
                parts.append(f"Game Genre & Pronoun Style: {self.knowledge_mgr.game_style}")

            matched_codex = self.knowledge_mgr.find_relevant_codex_entries(text_lines)
            if matched_codex:
                glossary_lines = []
                for e in matched_codex[:30]:
                    note_str = f" ({e['category']} - {e['note']})" if e.get("note") else f" ({e.get('category', '')})"
                    glossary_lines.append(f"- \"{e['source']}\" MUST be translated as \"{e['target']}\"{note_str}")
                parts.append("Mandatory Game Codex / Glossary Terms:\n" + "\n".join(glossary_lines))

        recent_block = ""
        if self.knowledge_mgr:
            recent_block = self.knowledge_mgr.get_recent_dialogue_prompt(limit=3)
        if not recent_block and getattr(self, "recent_context", None):
            ctx_lines = [
                f"- {str(src).strip()} => {str(tgt).strip()}"
                for src, tgt in self.recent_context[-3:]
                if str(src).strip() and str(tgt).strip()
            ]
            recent_block = "\n".join(ctx_lines)
        if recent_block:
            parts.append(
                "READ-ONLY Context — Last 3 Previously Translated Lines "
                "(DO NOT translate or include these in the output JSON array; use strictly for consistent pronouns and tone):\n"
                + recent_block
            )

        return "\n\n".join(parts)

    def translate_batch_with_context(self, text_lines):
        if self.api_key and self.api_key.strip().lower() == "offline" and self.knowledge_mgr:
            return [self.knowledge_mgr.translate_sentence_offline(line) for line in text_lines]

        if self.api_key:
            try:
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                }
                codex_block = self._build_codex_context_block(text_lines)
                extra_instructions = f"\n\n{codex_block}\n" if codex_block else ""
                system_prompt = (
                    f"You are an expert game & multi-language chat translator. "
                    f"Receive a JSON array of sequential text lines captured from the same screen or in-game chat block. "
                    f"Different lines (or even parts within a single line) may be in different languages "
                    f"(English, Chinese, Japanese, Korean, Russian, etc.). "
                    f"Read the full batch as cohesive context, auto-detect source language(s), preserve player usernames/prefixes like '[Channel] PlayerName:', "
                    f"understand gaming slang/abbreviations, and translate each line naturally into {self.target_lang}."
                    f"{extra_instructions}"
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
                res = _http_post(self.api_url, headers=headers, json=payload, timeout=12).json()
                content = res["choices"][0]["message"]["content"].strip()
                if content.startswith("```"):
                    content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
                parsed = json.loads(content)
                if isinstance(parsed, list) and len(parsed) == len(text_lines):
                    return [str(x) for x in parsed]
            except Exception as e:
                print(f"LLM API Warning (falling back to Google Translate): {e}")

        # Free Fallback via high-speed persistent batch Google Translate endpoint (50-80ms Keep-Alive)
        prepared_lines = [
            self.knowledge_mgr.apply_codex_replacements(line) if self.knowledge_mgr else line
            for line in text_lines
        ]
        tl_map = {"Vietnamese": "vi", "English": "en", "Japanese": "ja", "Korean": "ko", "French": "fr"}
        tl = tl_map.get(self.target_lang, "vi")

        if not hasattr(requests.get, "assert_called"):
            try:
                fast_url = f"https://clients5.google.com/translate_a/t?client=dict-chrome-ex&sl=auto&tl={tl}"
                res = _http_post(fast_url, data=[("q", line) for line in prepared_lines], timeout=6).json()
                if isinstance(res, list):
                    fast_out = []
                    for item in res:
                        if isinstance(item, (list, tuple)) and item:
                            fast_out.append(str(item[0]).strip())
                        elif isinstance(item, str):
                            fast_out.append(item.strip())
                    if len(fast_out) == len(text_lines) and all(fast_out):
                        return fast_out
            except Exception:
                pass

        # Secondary Fallback via Google Translate GTX endpoint
        try:
            joined_query = "\n".join(prepared_lines)
            url = (
                f"https://translate.googleapis.com/translate_a/single?client=gtx"
                f"&sl=auto&tl={tl}&dt=t&q={requests.utils.quote(joined_query)}"
            )
            res = _http_get(url, timeout=6).json()
            full_translated = "".join([part[0] for part in res[0] if part[0]])
            split_lines = [line.strip() for line in full_translated.split("\n") if line.strip()]
            if len(split_lines) == len(text_lines):
                return split_lines
            return full_translated.split("\n")
        except Exception:
            if self.knowledge_mgr and self.target_lang.lower().startswith("viet"):
                return [self.knowledge_mgr.translate_sentence_offline(line) for line in text_lines]
            return text_lines


# =====================================================================
# 1B. BACKGROUND WORKER: HOT-UPDATE FROM GITHUB / GIT (QTHREAD)
# =====================================================================
class HotUpdateWorker(QThread):
    finished_signal = pyqtSignal(bool, str)  # (updated_and_should_restart, status_message)

    def __init__(self, update_url: str, target_script_path: str, running_snapshot: str = None):
        super().__init__()
        self.update_url = normalize_github_raw_url(update_url)
        self.target_script_path = target_script_path
        self.running_snapshot = (
            running_snapshot if running_snapshot is not None else STARTUP_SCRIPT_SNAPSHOT
        )

    def _read_disk_code(self) -> str:
        if os.path.exists(self.target_script_path):
            try:
                with open(self.target_script_path, "r", encoding="utf-8") as f:
                    return f.read().replace("\r\n", "\n")
            except Exception:
                return ""
        return ""

    def _sync_missing_companion_files(self, script_dir: str) -> bool:
        """If running standalone .exe on another PC, fetch missing or empty Codex / 133K Offline Dictionary from GitHub."""
        if not self.update_url or "/" not in self.update_url:
            return False
        base_raw_dir = self.update_url.rsplit("/", 1)[0]
        companion_specs = (
            ("codex.json", 1000),
            ("Names.txt", 1000),
            ("offline_en_vi.json", 1_000_000),
        )
        updated_any = False
        for fname, min_bytes in companion_specs:
            local_p = os.path.join(script_dir, fname)
            if not os.path.isfile(local_p) or os.path.getsize(local_p) < min_bytes:
                try:
                    r = _http_get(f"{base_raw_dir}/{fname}", timeout=45)
                    if r.status_code == 200 and len(r.content) >= min_bytes:
                        with open(local_p, "wb") as f:
                            f.write(r.content)
                        updated_any = True
                except Exception:
                    pass
        if updated_any:
            TranslationKnowledgeManager._SHARED_OFFLINE_WORDS = None
        return updated_any

    def run(self):
        script_dir = os.path.dirname(self.target_script_path)
        git_dir = os.path.join(script_dir, ".git")
        git_pulled_ok = False

        # 1. Priority 1: If inside a Git repository, run `git pull` (supports Private & Public GitHub repos)
        if os.path.isdir(git_dir):
            try:
                proc = subprocess.run(
                    ["git", "pull", "--rebase", "--autostash"],
                    cwd=script_dir,
                    capture_output=True,
                    text=True,
                    timeout=12,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                )
                if proc.returncode == 0:
                    git_pulled_ok = True
            except Exception:
                pass

        # 2. Check if local disk script is already newer than what's currently running in memory
        disk_code = self._read_disk_code()
        if disk_code and self.running_snapshot and disk_code != self.running_snapshot:
            self.finished_signal.emit(True, "✓ Detected new code! Hot-restarting app...")
            return

        if git_pulled_ok:
            self.finished_signal.emit(False, "✓ Already up to date (Git & local code synced).")
            return

        # 3. Priority 2: Direct download via GitHub Raw URL (for standalone .exe without .git)
        if self.update_url:
            try:
                companion_synced = self._sync_missing_companion_files(script_dir)
                cache_bust_url = (
                    f"{self.update_url}?t={int(time.time())}"
                    if "?" not in self.update_url
                    else f"{self.update_url}&t={int(time.time())}"
                )
                resp = _http_get(cache_bust_url, timeout=8)
                if resp.status_code != 200:
                    self.finished_signal.emit(
                        False,
                        f"Update Error: HTTP {resp.status_code} (Make GitHub repo Public or keep .git folder)."
                    )
                    return

                new_code = resp.text
                if "MainStudioWindow" not in new_code:
                    self.finished_signal.emit(False, "Update Error: Downloaded file is not a valid Argon script.")
                    return

                if new_code.replace("\r\n", "\n") == disk_code:
                    if companion_synced:
                        self.finished_signal.emit(
                            True,
                            "✓ Đã tải xong Từ điển 133K từ & Bách khoa toàn thư từ GitHub! Đang nạp lại..."
                        )
                    else:
                        self.finished_signal.emit(False, "✓ Already up to date with GitHub.")
                    return

                with open(self.target_script_path, "w", encoding="utf-8") as f:
                    f.write(new_code)

                self.finished_signal.emit(True, "✓ Updated from GitHub! Restarting app...")
                return
            except Exception as e:
                self.finished_signal.emit(False, f"Update failed: {e}")
                return

        self.finished_signal.emit(False, "NO_URL_CONFIGURED")




# =====================================================================
# 2. FLOATING HUD OVERLAY WINDOW (DRAGGABLE, RESIZABLE, CLICK-THROUGH)
# =====================================================================
def set_window_capture_exclusion(widget) -> bool:
    """
    Make `widget` invisible to screen capture (mss/BitBlt) via SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)
    on Windows 10 2004+, so Auto mode can watch the screen continuously WITHOUT hiding/blinking the overlay.
    ctypes is already loaded by `keyboard`/`mss` on Windows (and bundled in the .exe), so we reuse it from sys.modules.
    """
    if not sys.platform.startswith("win"):
        return False
    try:
        ctypes_mod = sys.modules.get("ctypes") or __import__("ctypes")
        hwnd = int(widget.winId())
        if not hwnd:
            return False
        return bool(ctypes_mod.windll.user32.SetWindowDisplayAffinity(hwnd, 0x00000011))
    except Exception:
        return False


class FloatingOverlayHUD(QWidget):
    MIN_HUD_W = 100
    MIN_HUD_H = 44
    ANIM_DURATION = 0.26  # seconds for smooth chat slide / fade animation

    def __init__(self):
        super().__init__()
        self.blocks = []
        self.is_locked = False
        self.is_fullscreen = False
        self.is_capturing = False
        self.is_hidden_by_user = False
        self.resizing = False
        self.resize_edge = ""
        self.resize_start_rect = None
        self.resize_start_pos = None
        self.drag_offset = None
        self.dpr = 1.0
        self.overlay_style = "replace"  # "replace" (In-Place Chameleon), "transparent" (Halo Text Only), "glass" (Translucent Pill)
        self.stream_mode_only = False   # True when Live Chat Stream Only mode hides HUD pills
        self.font_family = "Segoe UI"
        self.font_size = 13
        self.font_bold = True
        self.auto_font_fit = True
        self.text_color_mode = "auto"  # "auto" or hex color string e.g. "#FFFFFF", "#FACC15"
        self.bg_opacity = 95           # 0..100 (%)
        self.capture_excluded = False  # True when HUD is invisible to screen capture (no-blink Auto mode)

        # Smooth chat animation state (slide old lines to new positions, fade-in new lines, fade-out removed lines)
        self.fading_blocks = []
        self.anim_progress = 1.0
        self.anim_start_time = 0.0
        self.anim_timer = QTimer(self)
        self.anim_timer.setInterval(16)
        self.anim_timer.timeout.connect(self._on_anim_tick)

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setGeometry(350, 280, 560, 220)
        self.setMouseTracking(True)

    def _compute_non_overlapping_layout(self, w: int, h: int, blocks=None) -> list:
        """
        Anti-Overlap Collision Engine (v2.0):
        Sort blocks top-to-bottom by Y coordinate and strictly clamp each block's max_h
        so box[i].bottom <= box[i+1].top - 2px, preventing overlapping background pills.
        """
        src_blocks = self.blocks if blocks is None else blocks
        if not src_blocks:
            return []

        dpr = max(0.5, float(self.dpr or 1.0))
        items = []
        for blk in src_blocks:
            rx, ry, rw, rh = blk.get('rect', (0, 0, 100, 24))
            lx = max(0, int(rx / dpr))
            ly = max(0, int(ry / dpr))
            orig_lw = max(int(rw / dpr), 28)
            orig_lh = max(int(rh / dpr), 16)
            items.append({
                'block': blk,
                'x': lx,
                'y': ly,
                'w': orig_lw,
                'h': orig_lh,
                'max_w': max(orig_lw + 60, int(w) - lx - 6),
                'max_h': max(6, int(h) - ly - 4),
            })

        items.sort(key=lambda it: (it['y'], it['x']))

        n = len(items)
        for i in range(n):
            cur = items[i]
            for j in range(i + 1, n):
                nxt = items[j]
                if nxt['y'] - cur['y'] > 8:
                    allowed_h = (nxt['y'] - 2) - cur['y']
                    cur['max_h'] = max(6, min(cur['max_h'], allowed_h))
                    break

        return items

    def showEvent(self, event):
        super().showEvent(event)
        # setWindowFlags() recreates the native window, so re-apply capture exclusion every time we are shown
        self.capture_excluded = set_window_capture_exclusion(self)

    # ---------------------- Smooth chat animation ----------------------
    def set_blocks_animated(self, new_blocks: list):
        """
        Replace blocks with a smooth transition instead of clear-and-redraw:
        - Lines that already exist (same raw_line) slide from their old Y to their new Y (chat scrolling up).
        - Brand-new lines fade in with a small slide-up.
        - Lines that disappeared fade out while drifting up.
        """
        new_blocks = list(new_blocks or [])
        old_blocks = [b for b in self.blocks if 'rect' in b]
        dpr = self.dpr or 1.0
        used_old = set()

        for nb in new_blocks:
            n_raw = nb.get('raw_line', '')
            n_y = nb['rect'][1]
            best_idx, best_dist = None, None
            if n_raw:
                for oi, ob in enumerate(old_blocks):
                    if oi in used_old:
                        continue
                    o_raw = ob.get('raw_line', '')
                    if o_raw and is_same_ocr_data(n_raw, o_raw):
                        dist = abs(ob['rect'][1] - n_y)
                        if best_dist is None or dist < best_dist:
                            best_idx, best_dist = oi, dist
            if best_idx is not None:
                used_old.add(best_idx)
                nb['_anim_dy'] = (old_blocks[best_idx]['rect'][1] - n_y) / dpr
                nb['_anim_alpha0'] = 1.0
            else:
                nb['_anim_dy'] = 10.0 if old_blocks else 0.0
                nb['_anim_alpha0'] = 0.0

        self.fading_blocks = []
        for oi, ob in enumerate(old_blocks):
            if oi not in used_old:
                fb = dict(ob)
                fb['_fade_out'] = True
                self.fading_blocks.append(fb)

        self.blocks = new_blocks
        self.anim_progress = 0.0
        self.anim_start_time = time.time()
        if not self.anim_timer.isActive():
            self.anim_timer.start()
        self.update()

    def _on_anim_tick(self):
        elapsed = time.time() - self.anim_start_time
        self.anim_progress = min(1.0, elapsed / self.ANIM_DURATION)
        if self.anim_progress >= 1.0:
            self.anim_timer.stop()
            self.fading_blocks = []
        self.update()

    def _anim_eased(self) -> float:
        p = max(0.0, min(1.0, self.anim_progress))
        return 1.0 - (1.0 - p) ** 3  # ease-out cubic

    def set_locked(self, locked: bool):
        self.is_locked = locked
        pos = self.pos()
        size = self.size()
        if locked:
            self.setWindowFlags(
                Qt.FramelessWindowHint
                | Qt.WindowStaysOnTopHint
                | Qt.Tool
                | Qt.WindowDoesNotAcceptFocus
                | Qt.WindowTransparentForInput
            )
        else:
            self.setWindowFlags(
                Qt.FramelessWindowHint
                | Qt.WindowStaysOnTopHint
                | Qt.Tool
                | Qt.WindowDoesNotAcceptFocus
            )
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setGeometry(pos.x(), pos.y(), size.width(), size.height())
        self.show()
        self.update()

    @staticmethod
    def _draw_outlined_text(painter: QPainter, rect: QRectF, flags: int, text: str, fg_color: QColor, outline_color: QColor):
        painter.setPen(outline_color)
        for dx, dy in ((-1.5, -1.5), (0, -1.5), (1.5, -1.5), (-1.5, 0), (1.5, 0), (-1.5, 1.5), (0, 1.5), (1.5, 1.5)):
            painter.drawText(rect.adjusted(dx, dy, dx, dy), flags, text)
        painter.setPen(fg_color)
        painter.drawText(rect, flags, text)

    def _resolve_colors_for_block(self, bg_rgb: tuple, fg_rgb: tuple, default_mode: str) -> tuple:
        """Return (fg_qcolor, outline_qcolor) respecting user's custom text_color_mode or automatic contrast."""
        if self.text_color_mode and self.text_color_mode != "auto" and self.text_color_mode.startswith("#"):
            custom_fg = QColor(self.text_color_mode)
            lum = 0.299 * custom_fg.red() + 0.587 * custom_fg.green() + 0.114 * custom_fg.blue()
            if lum > 130:
                outline_c = QColor(9, 13, 22, 245)
            else:
                outline_c = QColor(248, 250, 252, 245)
            return custom_fg, outline_c

        bg_lum = 0.299 * bg_rgb[0] + 0.587 * bg_rgb[1] + 0.114 * bg_rgb[2]
        if default_mode == "replace":
            fg_lum = 0.299 * fg_rgb[0] + 0.587 * fg_rgb[1] + 0.114 * fg_rgb[2]
            if abs(fg_lum - bg_lum) < 95:
                fg_c = QColor(254, 249, 195, 255) if bg_lum < 145 else QColor(15, 23, 42, 255)
            else:
                fg_c = QColor(fg_rgb[0], fg_rgb[1], fg_rgb[2], 255)
            outline_c = QColor(9, 13, 22, 240) if bg_lum < 145 else QColor(248, 250, 252, 240)
            return fg_c, outline_c

        if default_mode == "transparent":
            if bg_lum < 145:
                return QColor(254, 249, 195, 255), QColor(9, 13, 22, 245)
            return QColor(15, 23, 42, 255), QColor(248, 250, 252, 245)

        return QColor(248, 250, 252, 255), QColor(11, 15, 25, 230)

    def paintEvent(self, event):
        if self.is_capturing or self.is_hidden_by_user:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)

        w, h = self.width(), self.height()

        if not self.is_locked and not self.is_fullscreen:
            if self.stream_mode_only:
                pen = QPen(QColor(16, 185, 129, 200), 2.0, Qt.DashLine)
                grip_color = QColor(52, 211, 153, 240)
            else:
                pen = QPen(QColor(99, 102, 241, 175), 1.5, Qt.DashLine)
                grip_color = QColor(129, 140, 248, 235)

            painter.setPen(pen)
            # Alpha=1 keeps the interior 99.6% transparent while still catching mouse drag events on Windows
            painter.setBrush(QBrush(QColor(0, 0, 0, 1)))
            painter.drawRoundedRect(QRectF(1, 1, w - 2, h - 2), 8, 8)

            if self.stream_mode_only:
                badge_rect = QRectF(8, 8, min(365, max(80, w - 16)), 24)
                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(QColor(6, 78, 59, 190)))
                painter.drawRoundedRect(badge_rect, 6, 6)

                painter.setPen(QColor(167, 243, 208))
                painter.setFont(QFont("Segoe UI", 8, QFont.DemiBold))
                painter.drawText(
                    badge_rect.adjusted(10, 0, -6, 0),
                    Qt.AlignVCenter | Qt.AlignLeft,
                    "🟢 LIVE CHAT SENSOR  •  F8: Quét  •  F9: Dịch  •  F10: Khóa"
                )
            elif not self.blocks:
                badge_rect = QRectF(8, 8, min(295, max(80, w - 16)), 24)
                painter.setPen(Qt.NoPen)
                painter.setBrush(QBrush(QColor(15, 23, 42, 175)))
                painter.drawRoundedRect(badge_rect, 6, 6)

                painter.setPen(QColor(226, 232, 240))
                painter.setFont(QFont("Segoe UI", 8, QFont.DemiBold))
                painter.drawText(
                    badge_rect.adjusted(10, 0, -6, 0),
                    Qt.AlignVCenter | Qt.AlignLeft,
                    "⚡ Kéo khung • F8: Quét vùng • F9: Dịch • F10: Khóa"
                )

            # Draw 4 corner brackets & 4 edge midpoint ticks for 8-direction resizing
            grip_path = QPainterPath()
            cl = 12  # corner arm length
            # Top-Left corner
            grip_path.moveTo(2, 2 + cl)
            grip_path.lineTo(2, 2)
            grip_path.lineTo(2 + cl, 2)
            # Top-Right corner
            grip_path.moveTo(w - 2 - cl, 2)
            grip_path.lineTo(w - 2, 2)
            grip_path.lineTo(w - 2, 2 + cl)
            # Bottom-Left corner
            grip_path.moveTo(2, h - 2 - cl)
            grip_path.lineTo(2, h - 2)
            grip_path.lineTo(2 + cl, h - 2)
            # Bottom-Right corner
            grip_path.moveTo(w - 2 - cl, h - 2)
            grip_path.lineTo(w - 2, h - 2)
            grip_path.lineTo(w - 2, h - 2 - cl)
            # 4 Edge midpoint ticks (Top, Bottom, Left, Right)
            mx, my = w / 2.0, h / 2.0
            el = 10
            grip_path.moveTo(mx - el, 2)
            grip_path.lineTo(mx + el, 2)
            grip_path.moveTo(mx - el, h - 2)
            grip_path.lineTo(mx + el, h - 2)
            grip_path.moveTo(2, my - el)
            grip_path.lineTo(2, my + el)
            grip_path.moveTo(w - 2, my - el)
            grip_path.lineTo(w - 2, my + el)

            painter.setPen(QPen(grip_color, 2.5, Qt.SolidLine, Qt.RoundCap))
            painter.drawPath(grip_path)

        # Dual Display Mode: skip drawing overlay translation pills when Live Chat Stream Only is active
        if self.stream_mode_only:
            return

        weight = QFont.Bold if self.font_bold else QFont.Normal
        base_pt = max(6, min(48, int(self.font_size)))
        mask_alpha = max(0, min(255, int(self.bg_opacity * 255 / 100)))

        # Compute strict non-overlapping top-to-bottom layout slots
        eased = self._anim_eased()
        render_plan = []
        layout_groups = (
            (self._compute_non_overlapping_layout(w, h, self.blocks), False),
            (self._compute_non_overlapping_layout(w, h, self.fading_blocks), True),
        )

        for layout_items, is_fading in layout_groups:
          for layout in layout_items:
            b = layout['block']
            lx = layout['x']
            ly = layout['y']
            orig_lw = layout['w']
            orig_lh = layout['h']
            max_avail_w = layout['max_w']
            max_h = layout['max_h']

            text = b['text']
            bg_rgb = b.get('bg_color', (15, 23, 42))
            fg_rgb = b.get('fg_color', (248, 250, 252))

            # Animation: live lines slide from old Y (+fade in if new); removed lines fade out drifting up
            if is_fading:
                anim_dy = -10.0 * eased
                anim_alpha = 1.0 - eased
            else:
                anim_dy = float(b.get('_anim_dy', 0.0)) * (1.0 - eased)
                a0 = float(b.get('_anim_alpha0', 1.0))
                anim_alpha = a0 + (1.0 - a0) * eased

            # Auto-shrink font loop (from base_pt through 11pt -> 8pt) so long text fits inside max_h
            target_font_size = base_pt
            font = QFont(self.font_family, target_font_size, weight)
            fm = QFontMetrics(font)

            if self.auto_font_fit or max_h < orig_lh + 18:
                min_shrink_pt = min(8, base_pt)
                while target_font_size > min_shrink_pt:
                    t_rect = fm.boundingRect(
                        QRect(lx, ly, max_avail_w, max(max_h * 4, target_font_size * 5)),
                        Qt.TextWordWrap,
                        text
                    )
                    if t_rect.height() + 2 <= max_h:
                        break
                    target_font_size -= 1
                    font = QFont(self.font_family, target_font_size, weight)
                    fm = QFontMetrics(font)

            text_rect = fm.boundingRect(
                QRect(lx, ly, max_avail_w, max(max_h * 4, target_font_size * 5)),
                Qt.TextWordWrap,
                text
            )
            draw_w = max(orig_lw, min(text_rect.width() + 12, max(orig_lw, w - lx - 2)))
            draw_h = min(max_h, max(min(orig_lh, max_h), text_rect.height() + 2))

            if not is_fading:
                b['painted_phys_rect'] = (
                    max(0, int((lx - 2) * self.dpr)),
                    max(0, int(ly * self.dpr)),
                    int((draw_w + 4) * self.dpr),
                    int(draw_h * self.dpr)
                )
            render_plan.append({
                'block': b,
                'lx': lx,
                'ly': ly,
                'orig_lw': orig_lw,
                'orig_lh': orig_lh,
                'draw_w': draw_w,
                'draw_h': draw_h,
                'text': text,
                'bg_rgb': bg_rgb,
                'fg_rgb': fg_rgb,
                'font': font,
                'dy': anim_dy,
                'alpha': max(0.0, min(1.0, anim_alpha)),
                'is_fading': is_fading,
            })

        # PASS 1: Draw all background masks / pills FIRST so no background ever covers adjacent line text!
        if mask_alpha > 0 and self.overlay_style in ("replace", "glass"):
            painter.setPen(Qt.NoPen)
            for item in render_plan:
                b = item['block']
                lx, ly = item['lx'], item['ly']
                orig_lw, orig_lh = item['orig_lw'], item['orig_lh']
                draw_w, draw_h = item['draw_w'], item['draw_h']
                bg_rgb = item['bg_rgb']

                if self.overlay_style == "replace":
                    # Chameleon masks stay fixed at the REAL text position (the game already scrolled the chat),
                    # so original foreign text is hidden instantly while the translated text slides smoothly.
                    if item['is_fading']:
                        continue
                    painter.setOpacity(1.0)
                    painter.setBrush(QBrush(QColor(bg_rgb[0], bg_rgb[1], bg_rgb[2], mask_alpha)))
                    painter.drawRoundedRect(
                        QRectF(lx - 2, ly, max(orig_lw, draw_w) + 4, draw_h),
                        3, 3
                    )
                    for wm in b.get('word_masks', []):
                        wx, wy, ww, wh = wm['rect']
                        wy_l = max(ly, int(wy / self.dpr))
                        max_wm_h = max(4, (ly + draw_h) - wy_l)
                        wm_h = min(max_wm_h, max(4, int(wh / self.dpr)))
                        w_bg = wm.get('bg_color', bg_rgb)
                        painter.setBrush(QBrush(QColor(w_bg[0], w_bg[1], w_bg[2], mask_alpha)))
                        painter.drawRoundedRect(
                            QRectF(
                                int(wx / self.dpr) - 2,
                                wy_l,
                                max(4, int(ww / self.dpr) + 4),
                                wm_h
                            ),
                            2, 2
                        )
                elif self.overlay_style == "glass":
                    painter.setOpacity(item['alpha'])
                    bg_rect = QRectF(lx - 3, ly + item['dy'], draw_w + 6, draw_h)
                    painter.setBrush(QBrush(QColor(11, 15, 25, mask_alpha)))
                    painter.drawRoundedRect(bg_rect, 4, 4)
            painter.setOpacity(1.0)

        # PASS 2: Draw all translated text ON TOP of all backgrounds
        mode_key = self.overlay_style if self.overlay_style in ("replace", "transparent") else "glass"
        for item in render_plan:
            if item['alpha'] <= 0.01:
                continue
            painter.setOpacity(item['alpha'])
            painter.setFont(item['font'])
            fg_qcolor, outline_qcolor = self._resolve_colors_for_block(
                item['bg_rgb'], item['fg_rgb'], mode_key
            )
            self._draw_outlined_text(
                painter,
                QRectF(item['lx'], item['ly'] + item['dy'], item['draw_w'], item['draw_h']),
                Qt.AlignLeft | Qt.AlignVCenter | Qt.TextWordWrap,
                item['text'],
                fg_qcolor,
                outline_qcolor
            )
        painter.setOpacity(1.0)

    def _hit_test_resize_edge(self, pos: QPoint) -> str:
        """
        Detect which of the 4 corners ('top_left', 'top_right', 'bottom_left', 'bottom_right')
        or 4 edges ('top', 'bottom', 'left', 'right') the mouse is hovering over.
        Returns '' if inside the draggable interior.
        """
        x, y = pos.x(), pos.y()
        w, h = self.width(), self.height()
        corner_m = 16
        edge_m = 10

        on_left = x <= corner_m
        on_right = x >= w - corner_m
        on_top = y <= corner_m
        on_bottom = y >= h - corner_m

        if on_top and on_left:
            return "top_left"
        if on_bottom and on_right:
            return "bottom_right"
        if on_top and on_right:
            return "top_right"
        if on_bottom and on_left:
            return "bottom_left"

        if x <= edge_m:
            return "left"
        if x >= w - edge_m:
            return "right"
        if y <= edge_m:
            return "top"
        if y >= h - edge_m:
            return "bottom"
        return ""

    def _update_cursor_for_edge(self, edge: str):
        cursor_map = {
            "top_left": Qt.SizeFDiagCursor,
            "bottom_right": Qt.SizeFDiagCursor,
            "top_right": Qt.SizeBDiagCursor,
            "bottom_left": Qt.SizeBDiagCursor,
            "left": Qt.SizeHorCursor,
            "right": Qt.SizeHorCursor,
            "top": Qt.SizeVerCursor,
            "bottom": Qt.SizeVerCursor,
        }
        self.setCursor(cursor_map.get(edge, Qt.SizeAllCursor))

    def _apply_resize_drag(self, global_pos: QPoint):
        if not self.resize_start_rect or not self.resize_start_pos or not self.resize_edge:
            return
        dx = global_pos.x() - self.resize_start_pos.x()
        dy = global_pos.y() - self.resize_start_pos.y()

        r = QRect(self.resize_start_rect)
        left, top, right, bottom = r.left(), r.top(), r.right(), r.bottom()

        if "left" in self.resize_edge:
            left = min(left + dx, right - self.MIN_HUD_W + 1)
        if "right" in self.resize_edge:
            right = max(right + dx, left + self.MIN_HUD_W - 1)
        if "top" in self.resize_edge:
            top = min(top + dy, bottom - self.MIN_HUD_H + 1)
        if "bottom" in self.resize_edge:
            bottom = max(bottom + dy, top + self.MIN_HUD_H - 1)

        self.setGeometry(QRect(QPoint(left, top), QPoint(right, bottom)))

    def mousePressEvent(self, event):
        if self.is_locked or self.is_fullscreen:
            return
        if event.button() == Qt.LeftButton:
            edge = self._hit_test_resize_edge(event.pos())
            if edge:
                self.resizing = True
                self.resize_edge = edge
                self.resize_start_rect = self.geometry()
                self.resize_start_pos = event.globalPos()
                self._update_cursor_for_edge(edge)
            else:
                self.resizing = False
                self.resize_edge = ""
                self.drag_offset = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self.is_locked or self.is_fullscreen:
            return
        if self.resizing and (event.buttons() & Qt.LeftButton):
            if self.blocks:
                self.blocks = []
            self._apply_resize_drag(event.globalPos())
            event.accept()
            return
        if self.drag_offset and (event.buttons() & Qt.LeftButton):
            if self.blocks:
                self.blocks = []
                self.update()
            self.move(event.globalPos() - self.drag_offset)
            event.accept()
            return

        edge = self._hit_test_resize_edge(event.pos())
        self._update_cursor_for_edge(edge)

    def mouseReleaseEvent(self, event):
        self.resizing = False
        self.resize_edge = ""
        self.resize_start_rect = None
        self.resize_start_pos = None
        self.drag_offset = None



# =====================================================================
# 2B. INTERACTIVE REGION SNIPPER OVERLAY (F8 - DRAG TO SELECT FRAME)
# =====================================================================
class RegionSnipperOverlay(QWidget):
    region_selected = pyqtSignal(QRect)

    def __init__(self):
        super().__init__()
        self.start_pos = None
        self.end_pos = None
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setCursor(Qt.CrossCursor)

    def start_selection(self, screen_geo: QRect):
        self.start_pos = None
        self.end_pos = None
        self.setGeometry(screen_geo)
        self.show()
        self.activateWindow()
        self.raise_()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Dim entire screen slightly
        painter.fillRect(self.rect(), QColor(11, 15, 25, 120))

        # Top instruction pill
        hint_rect = QRectF((self.width() - 420) / 2, 24, 420, 34)
        painter.setPen(QPen(QColor(99, 102, 241, 180), 1))
        painter.setBrush(QBrush(QColor(15, 23, 42, 235)))
        painter.drawRoundedRect(hint_rect, 8, 8)
        painter.setPen(QColor(248, 250, 252))
        painter.setFont(QFont("Segoe UI", 10, QFont.DemiBold))
        painter.drawText(
            hint_rect,
            Qt.AlignCenter,
            "✂️ Kéo chuột để chọn khung dịch  •  Nhấn ESC hoặc Chuột phải để hủy"
        )

        if self.start_pos and self.end_pos:
            sel_rect = QRect(self.start_pos, self.end_pos).normalized()
            # Clear inner region so user sees crisp underlying text
            painter.setCompositionMode(QPainter.CompositionMode_Clear)
            painter.fillRect(sel_rect, Qt.transparent)
            painter.setCompositionMode(QPainter.CompositionMode_SourceOver)

            pen = QPen(QColor(99, 102, 241, 245), 2, Qt.SolidLine)
            painter.setPen(pen)
            painter.setBrush(QBrush(QColor(99, 102, 241, 20)))
            painter.drawRoundedRect(QRectF(sel_rect), 6, 6)

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self.close()
            return
        if event.button() == Qt.LeftButton:
            self.start_pos = event.pos()
            self.end_pos = event.pos()
            self.update()

    def mouseMoveEvent(self, event):
        if self.start_pos:
            self.end_pos = event.pos()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.start_pos and self.end_pos:
            sel_rect = QRect(self.start_pos, self.end_pos).normalized()
            global_top_left = self.mapToGlobal(sel_rect.topLeft())
            final_rect = QRect(
                global_top_left.x(),
                global_top_left.y(),
                max(140, sel_rect.width()),
                max(60, sel_rect.height())
            )
            self.close()
            if sel_rect.width() >= 25 and sel_rect.height() >= 15:
                self.region_selected.emit(final_rect)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close()


# =====================================================================
# 2C. GAME CODEX (ENCYCLOPEDIA) & TRANSLATION CACHE STUDIO DIALOG
# =====================================================================
class CodexAndCacheDialog(QDialog):
    knowledge_updated = pyqtSignal()

    def __init__(self, knowledge_mgr: TranslationKnowledgeManager, parent=None):
        super().__init__(parent)
        self.setObjectName("CodexDialog")
        self.knowledge_mgr = knowledge_mgr
        self.setWindowTitle("📚 Bách Khoa Toàn Thư Game & Kho Lưu Bản Dịch (Codex & Cache)")
        self.resize(820, 560)
        self._apply_dialog_stylesheet()
        self._build_dialog_ui()
        self.refresh_codex_table()
        self.refresh_cache_table()

    def _apply_dialog_stylesheet(self):
        self.setStyleSheet("""
            QDialog#CodexDialog {
                background-color: #0B0F19;
                color: #F8FAFC;
                font-family: 'Segoe UI', system-ui, sans-serif;
                font-size: 13px;
            }
            QLabel {
                background-color: transparent;
                color: #CBD5E1;
                font-weight: 600;
            }
            QTabWidget::pane {
                border: 1px solid #1F2937;
                background-color: #111827;
                border-radius: 8px;
            }
            QTabBar::tab {
                background-color: #1E293B;
                color: #94A3B8;
                padding: 9px 18px;
                margin-right: 4px;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                font-weight: 700;
            }
            QTabBar::tab:selected {
                background-color: #6366F1;
                color: #FFFFFF;
            }
            QTableWidget {
                background-color: #0F172A;
                alternate-background-color: #111827;
                color: #F8FAFC;
                border: 1px solid #1E293B;
                border-radius: 6px;
                gridline-color: #1E293B;
                selection-background-color: #4F46E5;
                selection-color: #FFFFFF;
            }
            QHeaderView::section {
                background-color: #1E293B;
                color: #818CF8;
                font-weight: 700;
                font-size: 12px;
                padding: 6px 8px;
                border: none;
                border-bottom: 1px solid #334155;
            }
            QLineEdit, QComboBox {
                background-color: #1E293B;
                border: 1px solid #334155;
                border-radius: 6px;
                padding: 5px 10px;
                min-height: 24px;
                color: #F8FAFC;
            }
            QLineEdit:focus, QComboBox:focus {
                border: 1px solid #6366F1;
            }
            QPushButton#ActionBtn {
                background-color: #6366F1;
                color: #FFFFFF;
                border: none;
                border-radius: 6px;
                font-weight: 700;
                padding: 7px 14px;
                min-height: 22px;
            }
            QPushButton#ActionBtn:hover {
                background-color: #4F46E5;
            }
            QPushButton#SubBtn {
                background-color: #1E293B;
                color: #E2E8F0;
                border: 1px solid #334155;
                border-radius: 6px;
                font-weight: 600;
                padding: 7px 12px;
                min-height: 22px;
            }
            QPushButton#SubBtn:hover {
                background-color: #334155;
            }
        """)

    def _build_dialog_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs)

        # ==================== TAB 1: GAME CODEX (ENCYCLOPEDIA) ====================
        tab_codex = QWidget()
        l_codex = QVBoxLayout(tab_codex)
        l_codex.setContentsMargins(14, 14, 14, 14)
        l_codex.setSpacing(10)

        row_style = QHBoxLayout()
        lbl_style = QLabel("🎮 Bối cảnh / Văn phong Game:")
        self.cb_style = QComboBox()
        self.cb_style.setView(QListView())
        self.cb_style.setFixedHeight(34)
        self.cb_style.addItems(GAME_STYLE_PRESETS)
        idx_style = self.cb_style.findText(self.knowledge_mgr.game_style)
        if idx_style >= 0:
            self.cb_style.setCurrentIndex(idx_style)
        self.cb_style.currentTextChanged.connect(self._on_style_changed)
        row_style.addWidget(lbl_style)
        row_style.addWidget(self.cb_style, 1)
        l_codex.addLayout(row_style)

        row_search_codex = QHBoxLayout()
        self.txt_codex_search = QLineEdit()
        self.txt_codex_search.setFixedHeight(34)
        self.txt_codex_search.setPlaceholderText(
            "🔍 Gõ từ tiếng Anh/Trung/Nhật/Hàn bất kỳ để tra cứu trong Bách Khoa + 133,675 từ/cụm từ Anh-Việt Offline..."
        )
        self.txt_codex_search.textChanged.connect(self.refresh_codex_table)
        row_search_codex.addWidget(self.txt_codex_search, 1)

        btn_preset = QPushButton("⚡ Nạp Bách Khoa Mẫu")
        btn_preset.setObjectName("ActionBtn")
        btn_preset.setToolTip("Nạp ngay bộ Bách Khoa Toàn Thư Game & Chat Đa Ngôn Ngữ (Names.txt)")
        btn_preset.clicked.connect(self.load_builtin_preset_glossary)
        row_search_codex.addWidget(btn_preset)

        btn_import = QPushButton("📂 Nhập File .txt Khác")
        btn_import.setObjectName("SubBtn")
        btn_import.clicked.connect(self.import_glossary_dialog)
        row_search_codex.addWidget(btn_import)
        l_codex.addLayout(row_search_codex)

        self.lbl_codex_stats = QLabel("")
        l_codex.addWidget(self.lbl_codex_stats)

        self.tbl_codex = QTableWidget(0, 4)
        self.tbl_codex.setHorizontalHeaderLabels([
            "Từ gốc (Source)",
            "Bản dịch chuẩn (Target)",
            "Phân loại (Category)",
            "Ghi chú Ngữ cảnh & Xưng hô (Lore / Pronouns)"
        ])
        self.tbl_codex.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self.tbl_codex.horizontalHeader().setSectionResizeMode(1, QHeaderView.Interactive)
        self.tbl_codex.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.tbl_codex.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.tbl_codex.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl_codex.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl_codex.itemSelectionChanged.connect(self._on_codex_row_selected)
        l_codex.addWidget(self.tbl_codex, 1)

        # Add / Edit Form
        form_row1 = QHBoxLayout()
        self.txt_c_src = QLineEdit()
        self.txt_c_src.setFixedHeight(34)
        self.txt_c_src.setPlaceholderText("Từ gốc (VD: Crimson Blade / 青云门)")

        self.txt_c_dst = QLineEdit()
        self.txt_c_dst.setFixedHeight(34)
        self.txt_c_dst.setPlaceholderText("Bản dịch chuẩn (VD: Huyết Kiếm / Thanh Vân Môn)")

        self.cb_c_cat = QComboBox()
        self.cb_c_cat.setView(QListView())
        self.cb_c_cat.setFixedHeight(34)
        self.cb_c_cat.addItems([
            "Nhân vật (Character)",
            "Kỹ năng (Skill)",
            "Vật phẩm (Item)",
            "Địa danh (Location)",
            "Phe phái (Faction)",
            "Thuật ngữ (Lore)"
        ])

        form_row1.addWidget(self.txt_c_src, 2)
        form_row1.addWidget(self.txt_c_dst, 2)
        form_row1.addWidget(self.cb_c_cat, 1)
        l_codex.addLayout(form_row1)

        form_row2 = QHBoxLayout()
        self.txt_c_note = QLineEdit()
        self.txt_c_note.setFixedHeight(34)
        self.txt_c_note.setPlaceholderText(
            "Ghi chú tra cứu & xưng hô (VD: Sư phụ của main, xưng 'Bổn tọa - Ngươi', sát thương băng...)"
        )

        btn_save_codex = QPushButton("➕ Lưu vào Bách Khoa")
        btn_save_codex.setObjectName("ActionBtn")
        btn_save_codex.clicked.connect(self.save_codex_entry)

        btn_del_codex = QPushButton("🗑️ Xóa mục chọn")
        btn_del_codex.setObjectName("SubBtn")
        btn_del_codex.clicked.connect(self.delete_selected_codex)

        form_row2.addWidget(self.txt_c_note, 1)
        form_row2.addWidget(btn_save_codex)
        form_row2.addWidget(btn_del_codex)
        l_codex.addLayout(form_row2)

        self.tabs.addTab(tab_codex, "📚 Bách Khoa Toàn Thư (Game Codex)")

        # ==================== TAB 2: PERSISTENT TRANSLATION CACHE ====================
        tab_cache = QWidget()
        l_cache = QVBoxLayout(tab_cache)
        l_cache.setContentsMargins(14, 14, 14, 14)
        l_cache.setSpacing(10)

        row_search_cache = QHBoxLayout()
        self.txt_cache_search = QLineEdit()
        self.txt_cache_search.setFixedHeight(34)
        self.txt_cache_search.setPlaceholderText("🔍 Tìm kiếm câu thoại gốc hoặc câu đã dịch trong bộ nhớ máy...")
        self.txt_cache_search.textChanged.connect(self.refresh_cache_table)
        self.lbl_cache_stats = QLabel("Đã lưu: 0 câu")
        row_search_cache.addWidget(self.txt_cache_search, 1)
        row_search_cache.addWidget(self.lbl_cache_stats)
        l_cache.addLayout(row_search_cache)

        self.tbl_cache = QTableWidget(0, 4)
        self.tbl_cache.setHorizontalHeaderLabels([
            "Câu gốc (OCR Source)",
            "Bản dịch đã lưu (Cached Translation)",
            "Ngôn ngữ",
            "Lượt tái sử dụng"
        ])
        self.tbl_cache.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tbl_cache.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tbl_cache.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.tbl_cache.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.tbl_cache.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl_cache.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl_cache.itemSelectionChanged.connect(self._on_cache_row_selected)
        l_cache.addWidget(self.tbl_cache, 1)

        edit_cache_row = QHBoxLayout()
        self.txt_cache_edit_src = QLineEdit()
        self.txt_cache_edit_src.setFixedHeight(34)
        self.txt_cache_edit_src.setPlaceholderText("Câu gốc...")
        self.txt_cache_edit_dst = QLineEdit()
        self.txt_cache_edit_dst.setFixedHeight(34)
        self.txt_cache_edit_dst.setPlaceholderText("Chỉnh sửa lại bản dịch tại đây để dùng vĩnh viễn...")
        self.txt_cache_edit_lang = "Vietnamese"

        btn_update_cache = QPushButton("✏️ Lưu sửa bản dịch")
        btn_update_cache.setObjectName("ActionBtn")
        btn_update_cache.clicked.connect(self.save_edited_cache_entry)

        btn_del_cache = QPushButton("🗑️ Xóa câu chọn")
        btn_del_cache.setObjectName("SubBtn")
        btn_del_cache.clicked.connect(self.delete_selected_cache_entry)

        btn_clear_cache = QPushButton("🧹 Xóa sạch Cache")
        btn_clear_cache.setObjectName("SubBtn")
        btn_clear_cache.clicked.connect(self.clear_all_cache_entries)

        edit_cache_row.addWidget(self.txt_cache_edit_src, 2)
        edit_cache_row.addWidget(self.txt_cache_edit_dst, 3)
        edit_cache_row.addWidget(btn_update_cache)
        edit_cache_row.addWidget(btn_del_cache)
        edit_cache_row.addWidget(btn_clear_cache)
        l_cache.addLayout(edit_cache_row)

        self.tabs.addTab(tab_cache, "💾 Bộ Nhớ Đã Dịch (Translation Cache)")

    def _on_style_changed(self, new_style: str):
        self.knowledge_mgr.game_style = new_style
        self.knowledge_mgr.save_codex()

    def refresh_codex_table(self):
        q = self.txt_codex_search.text()
        entries = self.knowledge_mgr.search_codex(q)
        offline_total = self.knowledge_mgr.get_offline_dict_total_count()
        codex_total = len(self.knowledge_mgr.codex_entries)
        if q.strip():
            self.lbl_codex_stats.setText(
                f"🔎 Tìm thấy {len(entries)} kết quả (trên tổng số {codex_total} mục Bách Khoa Game + {offline_total:,} mục Đại Từ Điển Anh-Việt Offline)"
            )
        else:
            self.lbl_codex_stats.setText(
                f"✅ Đã nạp sẵn: {codex_total} mục Bách Khoa Game • {offline_total:,} mục Đại Từ Điển Anh-Việt Offline (Gõ vào ô tìm kiếm để tra cứu toàn bộ 133,675 từ/cụm từ)"
            )
        self.tbl_codex.setRowCount(len(entries))
        for r, item in enumerate(entries):
            self.tbl_codex.setItem(r, 0, QTableWidgetItem(item.get("source", "")))
            self.tbl_codex.setItem(r, 1, QTableWidgetItem(item.get("target", "")))
            self.tbl_codex.setItem(r, 2, QTableWidgetItem(item.get("category", "")))
            self.tbl_codex.setItem(r, 3, QTableWidgetItem(item.get("note", "")))

    def _on_codex_row_selected(self):
        row = self.tbl_codex.currentRow()
        if row < 0:
            return
        self.txt_c_src.setText(self.tbl_codex.item(row, 0).text())
        self.txt_c_dst.setText(self.tbl_codex.item(row, 1).text())
        cat_txt = self.tbl_codex.item(row, 2).text()
        idx = self.cb_c_cat.findText(cat_txt)
        if idx >= 0:
            self.cb_c_cat.setCurrentIndex(idx)
        self.txt_c_note.setText(self.tbl_codex.item(row, 3).text())

    def save_codex_entry(self):
        src = self.txt_c_src.text().strip()
        dst = self.txt_c_dst.text().strip()
        if not src or not dst:
            return
        self.knowledge_mgr.add_or_update_codex(
            src, dst, self.cb_c_cat.currentText(), self.txt_c_note.text().strip()
        )
        self.txt_c_src.clear()
        self.txt_c_dst.clear()
        self.txt_c_note.clear()
        self.refresh_codex_table()
        self.knowledge_updated.emit()

    def delete_selected_codex(self):
        row = self.tbl_codex.currentRow()
        if row < 0:
            return
        src = self.tbl_codex.item(row, 0).text()
        self.knowledge_mgr.delete_codex(src)
        self.refresh_codex_table()
        self.knowledge_updated.emit()

    def load_builtin_preset_glossary(self):
        preset_path = os.path.join(APP_DIR, "Names.txt")
        if not os.path.exists(preset_path):
            QMessageBox.warning(
                self,
                "Không tìm thấy Names.txt",
                f"Không tìm thấy file từ điển mẫu tại:\n{preset_path}"
            )
            return
        imported = self.knowledge_mgr.import_names_file(preset_path, save_after=True)
        self.refresh_codex_table()
        self.knowledge_updated.emit()
        QMessageBox.information(
            self,
            "Nạp Bách Khoa Toàn Thư Mẫu",
            f"Đã nạp thành công {imported} mục từ điển Bách Khoa Game & Khung Chat Đa Ngôn Ngữ!"
        )

    def import_glossary_dialog(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Chọn file Names.txt hoặc Glossary.txt (định dạng: Từ_gốc=Bản_dịch)",
            APP_DIR,
            "Text Files (*.txt);;All Files (*)"
        )
        if path:
            imported = self.knowledge_mgr.import_names_file(path)
            self.refresh_codex_table()
            self.knowledge_updated.emit()
            QMessageBox.information(
                self,
                "Nhập Bách Khoa Toàn Thư",
                f"Đã nhập thành công {imported} thuật ngữ vào Bách Khoa Toàn Thư!"
            )

    def refresh_cache_table(self):
        rows = self.knowledge_mgr.list_cache_entries(self.txt_cache_search.text())
        total_hits = sum(r.get("hits", 1) for r in rows)
        self.lbl_cache_stats.setText(f"Đã lưu: {len(rows)} câu • Tổng lượt dùng: {total_hits}")
        self.tbl_cache.setRowCount(len(rows))
        for r, item in enumerate(rows):
            self.tbl_cache.setItem(r, 0, QTableWidgetItem(item["source"]))
            self.tbl_cache.setItem(r, 1, QTableWidgetItem(item["target"]))
            self.tbl_cache.setItem(r, 2, QTableWidgetItem(item["lang"]))
            self.tbl_cache.setItem(r, 3, QTableWidgetItem(str(item["hits"])))

    def _on_cache_row_selected(self):
        row = self.tbl_cache.currentRow()
        if row < 0:
            return
        self.txt_cache_edit_src.setText(self.tbl_cache.item(row, 0).text())
        self.txt_cache_edit_dst.setText(self.tbl_cache.item(row, 1).text())
        self.txt_cache_edit_lang = self.tbl_cache.item(row, 2).text() or "Vietnamese"

    def save_edited_cache_entry(self):
        src = self.txt_cache_edit_src.text().strip()
        dst = self.txt_cache_edit_dst.text().strip()
        if not src or not dst:
            return
        self.knowledge_mgr.update_single_cache_entry(src, dst, self.txt_cache_edit_lang)
        self.refresh_cache_table()
        self.knowledge_updated.emit()

    def delete_selected_cache_entry(self):
        row = self.tbl_cache.currentRow()
        if row < 0:
            return
        src = self.tbl_cache.item(row, 0).text()
        lang = self.tbl_cache.item(row, 2).text()
        self.knowledge_mgr.delete_cache_entry(src, lang)
        self.refresh_cache_table()

    def clear_all_cache_entries(self):
        self.knowledge_mgr.clear_all_cache()
        self.refresh_cache_table()


# =====================================================================
# 3. MAIN CONTROL STUDIO WINDOW (HIGH-CRAFT DARK UI)
# =====================================================================
class HotkeyBridge(QObject):
    trigger_translate = pyqtSignal()
    trigger_lock = pyqtSignal()
    trigger_snip = pyqtSignal()
    trigger_toggle_hide = pyqtSignal()
    trigger_tab_switched = pyqtSignal()


DEFAULT_REPO_URL = "https://github.com/HocTrinh-dev/overlay-translater.git"
DEFAULT_UPDATE_URL = "https://raw.githubusercontent.com/HocTrinh-dev/overlay-translater/main/argon_overlay_translator.py"


class MainStudioWindow(QWidget):
    def __init__(self, config_path=CONFIG_FILE, codex_path=None, cache_path=None):
        super().__init__()
        self.setObjectName("MainStudio")
        self.config_path = config_path
        base_dir = os.path.dirname(os.path.abspath(config_path))
        self.codex_path = codex_path or os.path.join(base_dir, "codex.json")
        self.cache_path = cache_path or os.path.join(base_dir, "translation_cache.json")
        self.knowledge_mgr = TranslationKnowledgeManager(
            codex_path=self.codex_path,
            cache_path=self.cache_path
        )

        self.update_url = DEFAULT_UPDATE_URL
        self.auto_update_on_start = True
        self.saved_region_rect = QRect(350, 280, 560, 220)
        self.is_compact_gaming_mode = False

        self.setWindowTitle("Argon Context Overlay Translator")
        self.setMinimumWidth(540)

        self.overlay_hud = FloatingOverlayHUD()
        self.snipper = RegionSnipperOverlay()
        self.snipper.region_selected.connect(self._on_region_snipped)
        self.codex_dialog = None

        self.worker = None
        self.update_worker = None
        self.line_cache = LineTranslationCache(capacity=600)
        self.recent_translated_history = []
        self.last_raw_text = ""
        self.last_valid_blocks = []
        self.last_frame_sig = None
        self.active_scene_sig = None
        self.last_captured_pil_img = None
        self._mss_sct = None

        self.hotkey_bridge = HotkeyBridge()
        self.hotkey_bridge.trigger_translate.connect(self.initiate_capture_and_translate)
        self.hotkey_bridge.trigger_lock.connect(self.toggle_lock_mode)
        self.hotkey_bridge.trigger_snip.connect(self.start_snip_region)
        self.hotkey_bridge.trigger_toggle_hide.connect(self.toggle_overlay_visibility)
        self.hotkey_bridge.trigger_tab_switched.connect(self.on_scene_or_tab_changed)

        self.auto_timer = QTimer(self)
        self.auto_timer.timeout.connect(self._on_auto_timer_tick)

        # Event-driven Auto mode: continuous no-blink change watcher (only OCR when on-screen text changes)
        self.last_ocr_text_sig = None
        self.prev_watch_sig = None
        self.change_pending_since = None
        self.change_watch_timer = QTimer(self)
        self.change_watch_timer.timeout.connect(self._on_change_watch_tick)

        self.scene_watch_timer = QTimer(self)
        self.scene_watch_timer.setInterval(260)
        self.scene_watch_timer.timeout.connect(self._check_scene_or_tab_change)

        self._apply_stylesheet()
        self._build_ui()
        self.adjustSize()
        screen = QApplication.primaryScreen()
        avail_h = (screen.availableGeometry().height() - 40) if screen else 860
        hint = self.sizeHint()
        self.setMinimumWidth(max(540, hint.width()))
        self.resize(max(560, hint.width()), min(hint.height(), max(520, avail_h)))
        self.load_config()
        self._register_global_hotkeys()
        self.scene_watch_timer.start()

        self.overlay_hud.show()
        if self.chk_auto.isChecked():
            self.toggle_auto_timer(Qt.Checked)

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
            QTextEdit#ChatFeed {
                background-color: #0B1120;
                border: 1px solid #1E293B;
                border-radius: 6px;
                padding: 8px;
                color: #E2E8F0;
                font-family: 'Segoe UI', 'Consolas', sans-serif;
                font-size: 12px;
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
        lbl_sub = QLabel("Real-time Context Overlay • Game Codex • Persistent Cache")
        lbl_sub.setObjectName("SubTitle")
        header_box.addWidget(lbl_title)
        header_box.addWidget(lbl_sub)
        header_row.addLayout(header_box, 1)

        self.btn_gaming_mode = QPushButton("🎮 Chế độ Game")
        self.btn_gaming_mode.setObjectName("SecondaryBtn")
        self.btn_gaming_mode.setToolTip("Thu gọn bảng điều khiển thành thanh Mini-Bar nổi trên game & tự khóa xuyên chuột HUD")
        self.btn_gaming_mode.clicked.connect(self.toggle_compact_gaming_mode)
        header_row.addWidget(self.btn_gaming_mode)

        self.btn_update = QPushButton("🔄 Hot Update")
        self.btn_update.setObjectName("SecondaryBtn")
        self.btn_update.setToolTip("Left-click: Pull latest code from GitHub & reload\nShift+Click: Set GitHub repository URL")
        self.btn_update.clicked.connect(self.trigger_hot_update)
        header_row.addWidget(self.btn_update)
        root.addLayout(header_row)

        card_lang = QFrame()
        self.card_lang = card_lang
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
            "Korean (kor)",
            "🌐 Multi-Language Chat (multi)"
        ])
        self.cb_src.setToolTip(
            "Chọn '🌐 Multi-Language Chat (multi)' khi quét khung Chat Thế Giới có nhiều ngôn ngữ trộn lẫn (Anh/Trung/Nhật/Hàn/Việt)"
        )
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
        self.cb_dst.currentIndexChanged.connect(self._on_translation_settings_changed)
        col_dst.addWidget(lbl_d)
        col_dst.addWidget(self.cb_dst)

        row_lang.addLayout(col_src, 1)
        row_lang.addLayout(col_dst, 1)
        c1_layout.addLayout(row_lang)

        # Capture Mode Row: Region Box vs Full Screen + Quick Snip Frame button
        col_mode = QVBoxLayout()
        col_mode.setSpacing(6)
        lbl_mode = QLabel("Capture Mode (Chế độ vùng dịch):")
        lbl_mode.setObjectName("FieldLabel")
        row_mode = QHBoxLayout()
        row_mode.setSpacing(10)

        self.cb_mode = QComboBox()
        self.cb_mode.setView(QListView())
        self.cb_mode.setFixedHeight(36)
        self.cb_mode.addItems([
            "🔲 Region Box (Khung HUD tùy chỉnh)",
            "🖥️ Full Screen (Toàn màn hình)"
        ])
        self.cb_mode.currentIndexChanged.connect(self.on_capture_mode_changed)

        self.btn_snip = QPushButton("✂️ Kéo chọn khung (F8)")
        self.btn_snip.setObjectName("SecondaryBtn")
        self.btn_snip.setFixedHeight(36)
        self.btn_snip.setToolTip("Kéo chuột chọn nhanh 1 vùng bất kỳ trên màn hình để dịch (F8)")
        self.btn_snip.clicked.connect(self.start_snip_region)

        row_mode.addWidget(self.cb_mode, 1)
        row_mode.addWidget(self.btn_snip)
        col_mode.addWidget(lbl_mode)
        col_mode.addLayout(row_mode)
        c1_layout.addLayout(col_mode)

        row_display = QHBoxLayout()
        row_display.setSpacing(10)

        col_style = QVBoxLayout()
        col_style.setSpacing(6)
        lbl_style_mode = QLabel("Overlay Style (Kiểu nền/chữ):")
        lbl_style_mode.setObjectName("FieldLabel")
        self.cb_overlay_style = QComboBox()
        self.cb_overlay_style.setView(QListView())
        self.cb_overlay_style.setFixedHeight(36)
        self.cb_overlay_style.addItems([
            "🎨 Thay chữ trực tiếp trên hình (Xóa chữ gốc + Nền tiệp màu)",
            "👻 Nền trong suốt 100% (Chỉ hiện chữ dịch có viền)",
            "🕶️ Khung kính mờ trong suốt (Semi-Transparent)"
        ])
        self.cb_overlay_style.currentIndexChanged.connect(self.on_overlay_style_changed)
        col_style.addWidget(lbl_style_mode)
        col_style.addWidget(self.cb_overlay_style)

        col_disp = QVBoxLayout()
        col_disp.setSpacing(6)
        lbl_disp_mode = QLabel("Display Mode (Kiểu hiển thị v2.0):")
        lbl_disp_mode.setObjectName("FieldLabel")
        self.cb_display_mode = QComboBox()
        self.cb_display_mode.setView(QListView())
        self.cb_display_mode.setFixedHeight(36)
        self.cb_display_mode.addItems([
            "🟣 In-Place Overlay (Đè chữ trực tiếp lên HUD)",
            "🟢 Live Chat Stream Only (Chỉ Feed 0ms - Không đè chữ)"
        ])
        self.cb_display_mode.setToolTip(
            "Chọn 'Live Chat Stream Only' để quét 0ms không nháy hình và đọc bản dịch mượt trong Live Chat Stream Log bên dưới"
        )
        self.cb_display_mode.currentIndexChanged.connect(self.on_display_mode_changed)
        col_disp.addWidget(lbl_disp_mode)
        col_disp.addWidget(self.cb_display_mode)

        row_display.addLayout(col_style, 1)
        row_display.addLayout(col_disp, 1)
        c1_layout.addLayout(row_display)

        # Typography & Appearance Suite (Font Family, Font Size, Text Color, Background Opacity, Bold, Auto-fit)
        row_typo1 = QHBoxLayout()
        row_typo1.setSpacing(10)

        col_ff = QVBoxLayout()
        col_ff.setSpacing(6)
        lbl_ff = QLabel("Phông chữ (Font):")
        lbl_ff.setObjectName("FieldLabel")
        self.cb_font_family = QComboBox()
        self.cb_font_family.setView(QListView())
        self.cb_font_family.setFixedHeight(36)
        self.cb_font_family.addItems([
            "Segoe UI",
            "Tahoma",
            "Arial",
            "Times New Roman",
            "Verdana",
            "Consolas"
        ])
        self.cb_font_family.currentTextChanged.connect(self.on_typography_changed)
        col_ff.addWidget(lbl_ff)
        col_ff.addWidget(self.cb_font_family)

        col_fs = QVBoxLayout()
        col_fs.setSpacing(6)
        lbl_fs = QLabel("Cỡ chữ (Size):")
        lbl_fs.setObjectName("FieldLabel")
        self.sp_font_size = QSpinBox()
        self.sp_font_size.setFixedHeight(36)
        self.sp_font_size.setMinimumWidth(85)
        self.sp_font_size.setRange(6, 48)
        self.sp_font_size.setValue(13)
        self.sp_font_size.setSuffix(" pt")
        self.sp_font_size.setToolTip("Điều chỉnh cỡ chữ tiếng Việt hiển thị trên hình (6 pt - 48 pt)")
        self.sp_font_size.valueChanged.connect(self.on_typography_changed)
        col_fs.addWidget(lbl_fs)
        col_fs.addWidget(self.sp_font_size)

        col_tc = QVBoxLayout()
        col_tc.setSpacing(6)
        lbl_tc = QLabel("Màu chữ (Color):")
        lbl_tc.setObjectName("FieldLabel")
        self.cb_text_color = QComboBox()
        self.cb_text_color.setView(QListView())
        self.cb_text_color.setFixedHeight(36)
        self.cb_text_color.addItems([
            "🎨 Tự động (Auto)",
            "⚪ Trắng (#FFFFFF)",
            "🟡 Vàng kim (#FACC15)",
            "🟢 Xanh lá (#4ADE80)",
            "🔵 Xanh băng (#38BDF8)",
            "🌸 Hồng đào (#FB7185)",
            "⚫ Đen đậm (#0F172A)"
        ])
        self.cb_text_color.currentIndexChanged.connect(self.on_typography_changed)
        col_tc.addWidget(lbl_tc)
        col_tc.addWidget(self.cb_text_color)

        row_typo1.addLayout(col_ff, 2)
        row_typo1.addLayout(col_fs, 1)
        row_typo1.addLayout(col_tc, 2)
        c1_layout.addLayout(row_typo1)

        row_typo2 = QHBoxLayout()
        row_typo2.setSpacing(12)

        lbl_op = QLabel("Độ đục nền:")
        lbl_op.setObjectName("FieldLabel")
        self.sp_bg_opacity = QSpinBox()
        self.sp_bg_opacity.setFixedHeight(36)
        self.sp_bg_opacity.setMinimumWidth(85)
        self.sp_bg_opacity.setRange(0, 100)
        self.sp_bg_opacity.setSingleStep(5)
        self.sp_bg_opacity.setValue(95)
        self.sp_bg_opacity.setSuffix("%")
        self.sp_bg_opacity.setToolTip("Độ đục của lớp nền xóa chữ gốc / khung kính mờ (0% = trong suốt hoàn toàn, 100% = che kín)")
        self.sp_bg_opacity.valueChanged.connect(self.on_typography_changed)

        self.chk_font_bold = QCheckBox("Chữ đậm (Bold)")
        self.chk_font_bold.setChecked(True)
        self.chk_font_bold.stateChanged.connect(self.on_typography_changed)

        self.chk_auto_font = QCheckBox("Tự thu nhỏ câu dài")
        self.chk_auto_font.setChecked(True)
        self.chk_auto_font.setToolTip("Tự động giảm nhẹ cỡ chữ nếu câu dịch quá dài so với khung chữ gốc")
        self.chk_auto_font.stateChanged.connect(self.on_typography_changed)

        row_typo2.addWidget(lbl_op)
        row_typo2.addWidget(self.sp_bg_opacity)
        row_typo2.addSpacing(6)
        row_typo2.addWidget(self.chk_font_bold)
        row_typo2.addWidget(self.chk_auto_font)
        row_typo2.addStretch()
        c1_layout.addLayout(row_typo2)

        row_auto = QHBoxLayout()
        self.chk_auto = QCheckBox("⚡ Auto (dịch khi chữ thay đổi)")
        self.chk_auto.setToolTip(
            "Theo dõi màn hình liên tục không nháy, chỉ OCR & dịch khi nội dung chữ thay đổi.\n"
            "Ô số giây chỉ dùng làm chế độ dự phòng trên Windows cũ không hỗ trợ theo dõi không nháy."
        )
        self.chk_auto.stateChanged.connect(self.toggle_auto_timer)
        self.sp_interval = QSpinBox()
        self.sp_interval.setFixedHeight(36)
        self.sp_interval.setMinimumWidth(80)
        self.sp_interval.setRange(1, 30)
        self.sp_interval.setValue(3)
        self.sp_interval.setSuffix(" sec")

        self.chk_auto_clear = QCheckBox("🧹 Tự xóa khi chuyển Tab")
        self.chk_auto_clear.setChecked(True)
        self.chk_auto_clear.setToolTip(
            "Tự động xóa ngay chữ dịch cũ trên màn hình khi bạn chuyển Tab, cuộn trang hoặc đổi cửa sổ để không bị rối mắt"
        )

        self.chk_after_arrow = QCheckBox("⏭️ Chỉ dịch sau '>>' / ':' (MC)")
        self.chk_after_arrow.setChecked(True)
        self.chk_after_arrow.setToolTip(
            "Bỏ qua phần Tên & Rank phía trước dấu '>>', '»' hoặc ':' trong khung chat game/Minecraft (tự giữ nguyên giờ [14:30], URL...), chỉ dịch nội dung chat phía sau"
        )
        self.chk_after_arrow.stateChanged.connect(self._on_translation_settings_changed)

        row_auto.addWidget(self.chk_auto)
        row_auto.addWidget(self.sp_interval)
        row_auto.addSpacing(8)
        row_auto.addWidget(self.chk_auto_clear)
        row_auto.addSpacing(8)
        row_auto.addWidget(self.chk_after_arrow)
        row_auto.addStretch()
        c1_layout.addLayout(row_auto)

        root.addWidget(card_lang)

        card_ai = QFrame()
        self.card_ai = card_ai
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

        card_feed = QFrame()
        self.card_feed = card_feed
        card_feed.setObjectName("Card")
        c3_layout = QVBoxLayout(card_feed)
        c3_layout.setContentsMargins(16, 12, 16, 14)
        c3_layout.setSpacing(8)

        lbl_sec3 = QLabel("LIVE CHAT STREAM LOG (AUTO-SCROLL)")
        lbl_sec3.setObjectName("SectionLabel")
        c3_layout.addWidget(lbl_sec3)

        self.txt_chat_feed = QTextEdit()
        self.txt_chat_feed.setObjectName("ChatFeed")
        self.txt_chat_feed.setReadOnly(True)
        self.txt_chat_feed.document().setMaximumBlockCount(300)
        self.txt_chat_feed.setPlaceholderText("Kênh dịch Chat trực tiếp (mỗi dòng mới sẽ tự động cuộn xuống đây)...")
        self.txt_chat_feed.setFixedHeight(110)
        c3_layout.addWidget(self.txt_chat_feed)

        root.addWidget(card_feed)

        row_btns = QHBoxLayout()
        row_btns.setSpacing(8)
        self.btn_lock = QPushButton("🔓 Lock (F10)")
        self.btn_lock.setObjectName("SecondaryBtn")
        self.btn_lock.clicked.connect(self.toggle_lock_mode)

        self.btn_hide_overlay = QPushButton("👁️ Ẩn/Hiện (F7)")
        self.btn_hide_overlay.setObjectName("SecondaryBtn")
        self.btn_hide_overlay.setToolTip("Ẩn/Hiện tức thì khung dịch khi đang giao tranh trong game (F7)")
        self.btn_hide_overlay.clicked.connect(self.toggle_overlay_visibility)

        self.btn_codex = QPushButton("📚 Bách Khoa && Kho Dịch")
        self.btn_codex.setObjectName("SecondaryBtn")
        self.btn_codex.setToolTip("Mở Bách Khoa Toàn Thư Game (Codex) & Bộ Nhớ Câu Đã Dịch (Cache)")
        self.btn_codex.clicked.connect(self.open_codex_and_cache_dialog)

        self.btn_clear = QPushButton("Clear")
        self.btn_clear.setObjectName("SecondaryBtn")
        self.btn_clear.clicked.connect(self.clear_overlay_text)

        row_btns.addWidget(self.btn_lock, 1)
        row_btns.addWidget(self.btn_hide_overlay, 1)
        row_btns.addWidget(self.btn_codex, 1)
        row_btns.addWidget(self.btn_clear, 0)
        root.addLayout(row_btns)

        self.btn_translate = QPushButton("⚡ Scan && Translate Selected Region (F9)")
        self.btn_translate.setObjectName("PrimaryBtn")
        self.btn_translate.clicked.connect(self.initiate_capture_and_translate)
        root.addWidget(self.btn_translate)

        self.lbl_status = QLabel("Ready • F7: Ẩn/Hiện • F8: Chọn khung • F9: Dịch • F10: Khóa")
        self.lbl_status.setObjectName("StatusPill")
        root.addWidget(self.lbl_status)

    def open_codex_and_cache_dialog(self):
        if self.codex_dialog is None:
            self.codex_dialog = CodexAndCacheDialog(self.knowledge_mgr, self)
            self.codex_dialog.knowledge_updated.connect(self._on_knowledge_updated)
        else:
            self.codex_dialog.refresh_codex_table()
            self.codex_dialog.refresh_cache_table()
        self.codex_dialog.show()
        self.codex_dialog.raise_()
        self.codex_dialog.activateWindow()

    def _on_knowledge_updated(self):
        # Immediately apply updated cache/codex translations to currently visible HUD pills
        if not self.overlay_hud.blocks:
            return
        target_lang = self.cb_dst.currentText()
        changed = False
        for b in self.overlay_hud.blocks:
            raw_line = b.get("raw_line", "")
            if raw_line:
                updated = self.knowledge_mgr.lookup_cached_translation(raw_line, target_lang)
                if updated and updated != b["text"]:
                    b["text"] = updated
                    changed = True
        if changed:
            self.overlay_hud.update()
            self.lbl_status.setText("✓ Đã cập nhật trực tiếp bản dịch mới lên màn hình Overlay!")

    def on_overlay_style_changed(self, index: int):
        style_map = {0: "replace", 1: "transparent", 2: "glass"}
        self.overlay_hud.overlay_style = style_map.get(index, "replace")
        self.overlay_hud.update()

    def on_display_mode_changed(self, index: int):
        stream_only = (index == 1)
        self.overlay_hud.stream_mode_only = stream_only
        if hasattr(self, "card_feed") and self.is_compact_gaming_mode:
            if stream_only:
                self.card_feed.show()
            else:
                self.card_feed.hide()
            self.adjustSize()
        self.overlay_hud.update()
        if stream_only:
            self.overlay_hud.is_capturing = False
        if self.chk_auto.isChecked():
            prev_sig = self.last_ocr_text_sig
            self.toggle_auto_timer(Qt.Checked)
            if prev_sig is not None:
                self.last_ocr_text_sig = prev_sig
            return
        if stream_only:
            self.lbl_status.setText("🟢 Live Chat Stream Only: Quét 0ms không nháy • Đọc log bên dưới")
        else:
            self.lbl_status.setText("🟣 In-Place Overlay: Dịch và hiển thị chữ đè trực tiếp trên HUD")

    def _on_translation_settings_changed(self, *args):
        if hasattr(self, "line_cache") and self.line_cache is not None:
            self.line_cache.clear()
        self.last_raw_text = ""
        self.last_frame_sig = None
        self.recent_translated_history = []

    @staticmethod
    def _escape_html(text: str) -> str:
        return (
            str(text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    def _on_new_chat_messages(self, pairs):
        if not pairs or not hasattr(self, "txt_chat_feed"):
            return
        ts = time.strftime("%H:%M:%S")
        for orig_text, trans_text in pairs:
            safe_orig = self._escape_html(orig_text)
            safe_trans = self._escape_html(trans_text)
            html_line = (
                f"<div style='margin-bottom:4px;'>"
                f"<span style='color:#64748B;'>[{ts}]</span> "
                f"<span style='color:#94A3B8;'>{safe_orig}</span> "
                f"<span style='color:#6366F1;'>&#8594;</span> "
                f"<span style='color:#34D399; font-weight:600;'>{safe_trans}</span>"
                f"</div>"
            )
            self.txt_chat_feed.append(html_line)
        sb = self.txt_chat_feed.verticalScrollBar()
        if sb is not None:
            sb.setValue(sb.maximum())

    @staticmethod
    def _extract_color_mode_from_text(label_text: str) -> str:
        if "#" in label_text and ")" in label_text:
            return "#" + label_text.split("#", 1)[1].split(")", 1)[0].strip()
        return "auto"

    def on_typography_changed(self, *args):
        self.overlay_hud.font_family = self.cb_font_family.currentText().strip() or "Segoe UI"
        self.overlay_hud.font_size = self.sp_font_size.value()
        self.overlay_hud.text_color_mode = self._extract_color_mode_from_text(self.cb_text_color.currentText())
        self.overlay_hud.bg_opacity = self.sp_bg_opacity.value()
        self.overlay_hud.font_bold = self.chk_font_bold.isChecked()
        self.overlay_hud.auto_font_fit = self.chk_auto_font.isChecked()
        self.overlay_hud.update()

    def on_capture_mode_changed(self, index: int):
        self.clear_overlay_text()
        if index == 1:
            # Switching to Full Screen mode
            if not self.overlay_hud.is_fullscreen:
                self.saved_region_rect = self.overlay_hud.geometry()
            screen = QApplication.screenAt(self.overlay_hud.geometry().center()) or QApplication.primaryScreen()
            full_geo = screen.geometry()
            self.overlay_hud.is_fullscreen = True
            self.overlay_hud.setGeometry(full_geo)
            self.overlay_hud.set_locked(True)
            self.btn_lock.setText("🔒 Locked (F10)")
            self.btn_translate.setText("⚡ Scan && Translate Full Screen (F9)")
            self.lbl_status.setText("🖥️ Chế độ Toàn màn hình: Bấm F9 để dịch toàn bộ màn hình.")
        else:
            # Switching to Region Box mode
            self.overlay_hud.is_fullscreen = False
            if self.saved_region_rect and self.saved_region_rect.width() >= 140:
                self.overlay_hud.setGeometry(self.saved_region_rect)
            self.overlay_hud.set_locked(False)
            self.btn_lock.setText("🔓 Lock (F10)")
            self.btn_translate.setText("⚡ Scan && Translate Selected Region (F9)")
            self.lbl_status.setText("🔲 Chế độ Khung HUD: Kéo/chỉnh khung hoặc bấm F8 để quét vùng mới.")

    def start_snip_region(self):
        screen = QApplication.screenAt(self.geometry().center()) or QApplication.primaryScreen()
        self.overlay_hud.blocks = []
        self.overlay_hud.update()
        self.snipper.start_selection(screen.geometry())

    def _on_region_snipped(self, rect: QRect):
        self.saved_region_rect = rect
        if self.cb_mode.currentIndex() != 0:
            self.cb_mode.blockSignals(True)
            self.cb_mode.setCurrentIndex(0)
            self.cb_mode.blockSignals(False)
        self.overlay_hud.is_fullscreen = False
        self.overlay_hud.setGeometry(rect)
        self.overlay_hud.set_locked(False)
        self.btn_lock.setText("🔓 Lock (F10)")
        self.btn_translate.setText("⚡ Scan && Translate Selected Region (F9)")
        self.overlay_hud.show()
        self.overlay_hud.update()
        QTimer.singleShot(60, self.initiate_capture_and_translate)

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
                self.sp_interval.setValue(max(1, min(30, cfg["auto_interval"])))

            hud_geo = cfg.get("overlay_hud") or cfg.get("overlay_hud_geometry")
            if isinstance(hud_geo, (list, tuple)) and len(hud_geo) == 4:
                x, y, w, h = [int(v) for v in hud_geo]
                self.saved_region_rect = QRect(x, y, max(220, w), max(90, h))
                self.overlay_hud.setGeometry(self.saved_region_rect)

            capture_mode = cfg.get("capture_mode", "region")
            if capture_mode == "fullscreen":
                self.cb_mode.setCurrentIndex(1)
            else:
                self.cb_mode.setCurrentIndex(0)

            overlay_style = cfg.get("overlay_style", "replace")
            style_idx_map = {"replace": 0, "transparent": 1, "glass": 2}
            self.cb_overlay_style.setCurrentIndex(style_idx_map.get(overlay_style, 0))

            if "font_family" in cfg and isinstance(cfg["font_family"], str):
                idx = self.cb_font_family.findText(cfg["font_family"])
                if idx >= 0:
                    self.cb_font_family.setCurrentIndex(idx)

            if "font_size" in cfg and isinstance(cfg["font_size"], int):
                self.sp_font_size.setValue(max(6, min(48, cfg["font_size"])))

            if "text_color_mode" in cfg and isinstance(cfg["text_color_mode"], str):
                tc_val = cfg["text_color_mode"]
                if tc_val == "auto":
                    self.cb_text_color.setCurrentIndex(0)
                else:
                    for i in range(self.cb_text_color.count()):
                        if tc_val.upper() in self.cb_text_color.itemText(i).upper():
                            self.cb_text_color.setCurrentIndex(i)
                            break

            if "bg_opacity" in cfg and isinstance(cfg["bg_opacity"], int):
                self.sp_bg_opacity.setValue(max(0, min(100, cfg["bg_opacity"])))

            if "font_bold" in cfg and isinstance(cfg["font_bold"], bool):
                self.chk_font_bold.setChecked(cfg["font_bold"])

            if "auto_font_fit" in cfg and isinstance(cfg["auto_font_fit"], bool):
                self.chk_auto_font.setChecked(cfg["auto_font_fit"])

            if "auto_clear_on_change" in cfg and isinstance(cfg["auto_clear_on_change"], bool):
                self.chk_auto_clear.setChecked(cfg["auto_clear_on_change"])

            if "only_after_arrow" in cfg and isinstance(cfg["only_after_arrow"], bool):
                self.chk_after_arrow.setChecked(cfg["only_after_arrow"])

            display_mode = cfg.get("display_mode", "overlay")
            self.cb_display_mode.setCurrentIndex(1 if display_mode == "stream" else 0)

            self.on_typography_changed()

            if "update_url" in cfg and isinstance(cfg["update_url"], str):
                self.update_url = normalize_github_raw_url(cfg["update_url"])
            if "auto_update_on_start" in cfg and isinstance(cfg["auto_update_on_start"], bool):
                self.auto_update_on_start = cfg["auto_update_on_start"]
        except Exception as e:
            print(f"Configuration load warning: {e}")

    def save_config(self):
        if not self.overlay_hud.is_fullscreen:
            self.saved_region_rect = self.overlay_hud.geometry()
        geo = self.saved_region_rect
        style_map = {0: "replace", 1: "transparent", 2: "glass"}
        cfg = {
            "api_url": self.txt_url.text().strip(),
            "model_name": self.txt_model.text().strip(),
            "api_key": self.txt_key.text().strip(),
            "src_lang": self.cb_src.currentText(),
            "dst_lang": self.cb_dst.currentText(),
            "auto_interval": self.sp_interval.value(),
            "auto_clear_on_change": self.chk_auto_clear.isChecked(),
            "only_after_arrow": self.chk_after_arrow.isChecked(),
            "capture_mode": "fullscreen" if self.cb_mode.currentIndex() == 1 else "region",
            "display_mode": "stream" if self.cb_display_mode.currentIndex() == 1 else "overlay",
            "overlay_style": style_map.get(self.cb_overlay_style.currentIndex(), "replace"),
            "font_family": self.cb_font_family.currentText(),
            "font_size": self.sp_font_size.value(),
            "text_color_mode": self._extract_color_mode_from_text(self.cb_text_color.currentText()),
            "bg_opacity": self.sp_bg_opacity.value(),
            "font_bold": self.chk_font_bold.isChecked(),
            "auto_font_fit": self.chk_auto_font.isChecked(),
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
            QTimer.singleShot(250, self._restart_process)

    @staticmethod
    def _build_clean_subprocess_env() -> dict:
        """
        Remove PyInstaller onefile temporary directory variables (_MEIPASS2, QT_PLUGIN_PATH, etc.)
        so a spawned child ArgonTranslator.exe never points to the parent's deleted _MEIxxxxxx folder.
        """
        env = os.environ.copy()
        for key in (
            "_MEIPASS",
            "_MEIPASS2",
            "QT_PLUGIN_PATH",
            "QT_QPA_PLATFORM_PLUGIN_PATH",
            "QML2_IMPORT_PATH",
            "TCL_LIBRARY",
            "TK_LIBRARY",
        ):
            env.pop(key, None)

        meipass = getattr(sys, "_MEIPASS", None)
        if meipass and "PATH" in env:
            norm_mei = os.path.normcase(os.path.abspath(meipass))
            clean_paths = [
                p for p in env["PATH"].split(os.pathsep)
                if p and not os.path.normcase(os.path.abspath(p)).startswith(norm_mei)
            ]
            env["PATH"] = os.pathsep.join(clean_paths)
        return env

    def _restart_process(self):
        """
        Hot-reload `argon_overlay_translator.py` directly in-process inside the active QApplication
        (avoiding PyInstaller onefile _MEIxxxxxx temp folder deletion & Qt platform plugin errors).
        Falls back to a clean-env subprocess spawn only if in-process reload fails.
        """
        try:
            if os.path.exists(MAIN_SCRIPT_FILE):
                with open(MAIN_SCRIPT_FILE, "r", encoding="utf-8") as f:
                    source_code = f.read()

                code_obj = compile(source_code, MAIN_SCRIPT_FILE, "exec")
                reload_ns = {
                    "__name__": "__argon_hot_reload__",
                    "__file__": MAIN_SCRIPT_FILE,
                }
                exec(code_obj, reload_ns)
                new_cls = reload_ns.get("MainStudioWindow")
                if new_cls is not None:
                    self.auto_timer.stop()
                    self.change_watch_timer.stop()
                    self.scene_watch_timer.stop()
                    try:
                        keyboard.unhook_all()
                    except Exception:
                        pass
                    if self.codex_dialog:
                        self.codex_dialog.close()
                    self.snipper.close()
                    self.overlay_hud.close()
                    self.hide()

                    new_studio = new_cls(config_path=self.config_path)
                    app = QApplication.instance()
                    if app is not None:
                        app._active_studio = new_studio
                    new_studio.show()
                    new_studio.raise_()
                    new_studio.activateWindow()
                    new_studio.lbl_status.setText("✓ Đã Hot Update thành công! (Áp dụng ngay không cần mở lại .exe)")
                    self.deleteLater()
                    return
        except Exception as e:
            print(f"In-process hot reload warning (falling back to clean process restart): {e}")

        self.overlay_hud.close()
        args = [sys.executable] + (sys.argv[1:] if getattr(sys, "frozen", False) else sys.argv)
        subprocess.Popen(args, cwd=APP_DIR, env=self._build_clean_subprocess_env())
        QApplication.quit()

    def _register_global_hotkeys(self):
        def listen():
            try:
                keyboard.add_hotkey('F7', lambda: self.hotkey_bridge.trigger_toggle_hide.emit())
                keyboard.add_hotkey('F8', lambda: self.hotkey_bridge.trigger_snip.emit())
                keyboard.add_hotkey('F9', lambda: self.hotkey_bridge.trigger_translate.emit())
                keyboard.add_hotkey('F10', lambda: self.hotkey_bridge.trigger_lock.emit())
                for nav_key in ('ctrl+tab', 'ctrl+shift+tab'):
                    try:
                        keyboard.add_hotkey(nav_key, lambda: self.hotkey_bridge.trigger_tab_switched.emit(), suppress=False)
                    except Exception:
                        pass
            except Exception as e:
                print(f"Global hotkey registration warning: {e}")

        threading.Thread(target=listen, daemon=True).start()

    def toggle_overlay_visibility(self):
        """
        Instant 0ms Combat Quick-Hide (F7): hides/restores the overlay HUD without clearing
        translated blocks so gamers can fight bosses unobstructed and bring text back immediately.
        """
        self.overlay_hud.is_hidden_by_user = not self.overlay_hud.is_hidden_by_user
        self.overlay_hud.update()
        if self.overlay_hud.is_hidden_by_user:
            self.btn_hide_overlay.setText("🙈 Đang Ẩn (F7)")
            self.lbl_status.setText("🙈 Đã tạm ẩn khung dịch (Bấm F7 để hiện lại ngay lập tức).")
        else:
            self.btn_hide_overlay.setText("👁️ Ẩn/Hiện (F7)")
            self.lbl_status.setText("👁️ Đã hiện lại khung dịch.")

    def toggle_compact_gaming_mode(self):
        """
        Collapse the full configuration cards into a compact Always-On-Top In-Game Mini-Bar
        and automatically lock the HUD into Click-Through mode so it never interferes with gameplay.
        """
        self.is_compact_gaming_mode = not self.is_compact_gaming_mode
        if self.is_compact_gaming_mode:
            self.card_lang.hide()
            self.card_ai.hide()
            if self.overlay_hud.stream_mode_only:
                self.card_feed.show()
            else:
                self.card_feed.hide()
            if not self.overlay_hud.is_locked:
                self.overlay_hud.set_locked(True)
                self.btn_lock.setText("🔒 Locked (F10)")
            self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
            self.btn_gaming_mode.setText("🔽 Mở rộng Setting")
            self.lbl_status.setText("🎮 Chế độ Game: Đã khóa xuyên chuột HUD • F7: Ẩn/Hiện • F8: Kéo khung • F9: Dịch")
        else:
            self.card_lang.show()
            self.card_ai.show()
            self.card_feed.show()
            self.setWindowFlags(self.windowFlags() & ~Qt.WindowStaysOnTopHint)
            self.btn_gaming_mode.setText("🎮 Chế độ Game")
            self.lbl_status.setText("Ready • F7: Ẩn/Hiện • F8: Chọn khung • F9: Dịch • F10: Khóa")
        self.show()
        self.adjustSize()
        screen = QApplication.primaryScreen()
        avail_h = (screen.availableGeometry().height() - 40) if screen else 860
        hint = self.sizeHint()
        self.resize(max(540, hint.width()), min(hint.height(), max(220, avail_h)))

    def toggle_lock_mode(self):
        new_state = not self.overlay_hud.is_locked
        self.overlay_hud.set_locked(new_state)
        if new_state:
            self.btn_lock.setText("🔒 Locked (F10)")
            self.lbl_status.setText("HUD Locked: Mouse clicks now pass through to underlying window.")
        else:
            self.btn_lock.setText("🔓 Lock (F10)")
            self.lbl_status.setText("HUD Unlocked: You can drag or resize the capture box.")

    def clear_overlay_text(self):
        self.overlay_hud.blocks = []
        self.overlay_hud.fading_blocks = []
        self.last_valid_blocks = []
        self.last_raw_text = ""
        self.last_frame_sig = None
        self.active_scene_sig = None
        self.recent_translated_history = []
        if hasattr(self, "line_cache") and self.line_cache is not None:
            self.line_cache.clear()
        self.overlay_hud.update()
        self.lbl_status.setText("Cleared overlay translation blocks.")

    def on_scene_or_tab_changed(self):
        """
        Automatically wipe stale overlay translation blocks when the user switches tabs in manual mode.
        When Auto-Scan is active (e.g. translating a live Chat Box), NEVER wipe the overlay to blank —
        keep existing chat lines readable on screen and trigger a background scan to update in-place.
        """
        if not self.chk_auto_clear.isChecked() or not self.overlay_hud.blocks:
            return
        if self.chk_auto.isChecked():
            if not (self.worker and self.worker.isRunning()):
                QTimer.singleShot(120, self.initiate_capture_and_translate)
            return
        self.overlay_hud.blocks = []
        self.last_valid_blocks = []
        self.last_raw_text = ""
        self.last_frame_sig = None
        self.active_scene_sig = None
        self.overlay_hud.update()
        self.lbl_status.setText("🧹 Đã tự xóa Overlay do chuyển Tab / đổi nội dung màn hình.")

    def toggle_auto_timer(self, state):
        self.auto_timer.stop()
        watch_timer = getattr(self, "change_watch_timer", None)
        if watch_timer is not None:
            watch_timer.stop()
        self.last_ocr_text_sig = None
        self.prev_watch_sig = None
        self.change_pending_since = None

        if state == Qt.Checked:
            if watch_timer is not None and (self.overlay_hud.capture_excluded or self.overlay_hud.stream_mode_only):
                # Event-driven: watch the screen continuously (every 75ms, no blink) and only OCR when content changes
                watch_timer.start(75)
                self.lbl_status.setText("⚡ Auto: Đang theo dõi thời gian thực (75ms) — chỉ dịch khi chữ trên màn hình thay đổi.")
                QTimer.singleShot(30, self._on_change_watch_tick)
            else:
                # Fallback for Windows < 10 (2004): overlay cannot be excluded from capture -> interval scanning
                self.auto_timer.start(self.sp_interval.value() * 1000)
                self.lbl_status.setText(
                    f"Auto-scan (dự phòng mỗi {self.sp_interval.value()}s — Windows này không hỗ trợ theo dõi không nháy)..."
                )
                if self.last_frame_sig is None:
                    QTimer.singleShot(50, self._on_auto_timer_tick)
        else:
            self.lbl_status.setText("Auto-scan disabled.")

    @staticmethod
    def compute_text_signature(pil_img) -> tuple:
        """
        Fine-grained 96x48 grayscale signature: sensitive enough to detect a single new chat line,
        cheap enough (~1ms) to run continuously every 220ms.
        """
        thumb = pil_img.convert("L").resize((96, 48), Image.BILINEAR)
        return tuple(thumb.tobytes())

    def _on_change_watch_tick(self):
        """
        Continuous event-driven watcher (HUD is excluded from capture, so grabbing never blinks the overlay):
        1. Grab the clean HUD region and compute a fine text signature.
        2. If it differs from the signature at the last OCR -> content changed.
        3. Debounce: wait until the chat stops scrolling (2 consecutive similar frames) or max 0.9s of
           continuous motion, then OCR once. Unchanged lines are reused instantly, only new lines are translated.
        """
        if (
            not self.chk_auto.isChecked()
            or (self.worker and self.worker.isRunning())
            or self.overlay_hud.is_capturing
            or self.overlay_hud.is_hidden_by_user
            or self.overlay_hud.resizing
            or self.overlay_hud.drag_offset is not None
        ):
            return

        if not self.overlay_hud.capture_excluded and not self.overlay_hud.stream_mode_only:
            # Exclusion lost (e.g. window recreated on an unsupported system) -> fall back to interval mode
            self.change_watch_timer.stop()
            self.auto_timer.start(self.sp_interval.value() * 1000)
            return

        pil_img = self._grab_raw_hud_image()
        if pil_img is None:
            return
        sig = self.compute_text_signature(pil_img)
        now = time.time()

        if self.last_ocr_text_sig is None or len(self.last_ocr_text_sig) != len(sig):
            self._start_translation_worker(pil_img, sig)
            return

        if not self.has_text_changed(sig, self.last_ocr_text_sig):
            self.change_pending_since = None
            self.prev_watch_sig = sig
            return

        if self.change_pending_since is None:
            self.change_pending_since = now
        still_moving = (
            self.prev_watch_sig is None
            or self.has_text_changed(
                sig,
                self.prev_watch_sig,
                min_mean=0.8,
                min_hot_pixels=4,
                hot_thresh=16,
            )
        )
        self.prev_watch_sig = sig
        if (not still_moving) or (now - self.change_pending_since) >= 0.18:
            self._start_translation_worker(pil_img, sig)

    @staticmethod
    def compute_frame_signature(pil_img) -> tuple:
        """
        Compute a lightweight 16x8 RGB thumbnail signature in <0.2ms so Auto-Scan can
        detect unchanged game frames and skip expensive Tesseract OCR invocations.
        """
        thumb = pil_img.resize((16, 8), Image.NEAREST).convert("RGB")
        return tuple(thumb.tobytes())

    @staticmethod
    def frame_signature_diff(sig1: tuple, sig2: tuple) -> float:
        if not sig1 or not sig2 or len(sig1) != len(sig2):
            return 999.0
        return sum(abs(a - b) for a, b in zip(sig1, sig2)) / len(sig1)

    @staticmethod
    def has_text_changed(
        sig1: tuple,
        sig2: tuple,
        min_mean: float = 1.2,
        min_hot_pixels: int = 4,
        hot_thresh: int = 14,
    ) -> bool:
        """
        Detect whether a captured HUD region changed meaningfully (including short 1-line
        chat messages whose global mean diff is < 1.0) while ignoring minor subpixel noise.
        """
        if not sig1 or not sig2 or len(sig1) != len(sig2):
            return True
        total_diff = 0
        hot = 0
        for a, b in zip(sig1, sig2):
            d = abs(a - b)
            total_diff += d
            if d >= hot_thresh:
                hot += 1
                if hot >= min_hot_pixels:
                    return True
        return (total_diff / len(sig1)) >= min_mean

    @staticmethod
    def compute_unmasked_scene_signature(pil_img, blocks: list, top_strip_img=None) -> tuple:
        """
        Sample a 20x12 grid of background pixels inside `pil_img` that lie OUTSIDE any painted
        overlay text block (`painted_phys_rect` / `rect`), plus an optional top-of-screen tab-bar strip.
        Because unmasked pixels are transparent in the HUD, this signature can be checked live
        every 260ms without hiding or flickering the overlay!
        """
        if pil_img is None:
            return ()
        img_w, img_h = pil_img.size
        if img_w < 32 or img_h < 32:
            return ()

        masked_rects = []
        for b in (blocks or []):
            if "painted_phys_rect" in b:
                px, py, pw, ph = b["painted_phys_rect"]
                masked_rects.append((px - 2, py - 2, px + pw + 4, py + ph + 4))
            elif "rect" in b:
                rx, ry, rw, rh = b["rect"]
                masked_rects.append((rx - 8, ry - 6, rx + rw + 160, ry + rh + 36))

        samples = []
        margin_x = min(14, img_w // 6)
        margin_y = min(14, img_h // 6)
        usable_w = max(1, img_w - 2 * margin_x)
        usable_h = max(1, img_h - 2 * margin_y)

        for gy in range(12):
            sy = margin_y + int((gy + 0.5) * usable_h / 12)
            sy = max(0, min(img_h - 1, sy))
            for gx in range(20):
                sx = margin_x + int((gx + 0.5) * usable_w / 20)
                sx = max(0, min(img_w - 1, sx))
                covered = False
                for mx0, my0, mx1, my1 in masked_rects:
                    if mx0 <= sx <= mx1 and my0 <= sy <= my1:
                        covered = True
                        break
                if not covered:
                    r, g, b_val = pil_img.getpixel((sx, sy))[:3]
                    samples.extend((r, g, b_val))

        if top_strip_img is not None:
            try:
                strip_thumb = top_strip_img.resize((24, 2), Image.NEAREST).convert("RGB")
                samples.extend(strip_thumb.tobytes())
            except Exception:
                pass

        return tuple(samples)

    def _get_mss_instance(self):
        """Lazily create and reuse an mss screen-capture context to avoid per-tick GDI handle churn."""
        if getattr(self, "_mss_sct", None) is None:
            self._mss_sct = mss.mss()
        return self._mss_sct

    def _close_mss_instance(self):
        sct = getattr(self, "_mss_sct", None)
        if sct is not None:
            try:
                sct.close()
            except Exception:
                pass
            self._mss_sct = None

    def _grab_raw_hud_image(self):
        """Grab the current HUD region directly via mss without hiding the overlay."""
        geo = self.overlay_hud.geometry()
        screen = QApplication.screenAt(geo.center()) or QApplication.primaryScreen()
        dpr = screen.devicePixelRatio()
        self.overlay_hud.dpr = dpr

        phys_x = int(geo.x() * dpr)
        phys_y = int(geo.y() * dpr)
        phys_w = int(geo.width() * dpr)
        phys_h = int(geo.height() * dpr)

        try:
            sct = self._get_mss_instance()
            monitor = {"left": phys_x, "top": phys_y, "width": phys_w, "height": phys_h}
            sct_img = sct.grab(monitor)
            return Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
        except Exception:
            self._close_mss_instance()
            return None

    def _grab_live_unmasked_signature(self) -> tuple:
        """
        Grab the current HUD region (and top tab-bar strip if not obscured) without hiding the HUD,
        returning the unmasked pixel signature for real-time tab/scene change detection.
        """
        geo = self.overlay_hud.geometry()
        screen = QApplication.screenAt(geo.center()) or QApplication.primaryScreen()
        dpr = screen.devicePixelRatio()
        self.overlay_hud.dpr = dpr

        phys_x = int(geo.x() * dpr)
        phys_y = int(geo.y() * dpr)
        phys_w = int(geo.width() * dpr)
        phys_h = int(geo.height() * dpr)

        try:
            sct = self._get_mss_instance()
            monitor = {"left": phys_x, "top": phys_y, "width": phys_w, "height": phys_h}
            sct_img = sct.grab(monitor)
            pil_img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")

            top_strip_img = None
            if not self.overlay_hud.is_fullscreen:
                scr_geo = screen.geometry()
                strip_rect = QRect(scr_geo.x() + 120, scr_geo.y() + 4, max(200, scr_geo.width() - 360), 38)
                if not strip_rect.intersects(geo) and not strip_rect.intersects(self.frameGeometry()):
                    s_mon = {
                        "left": int(strip_rect.x() * dpr),
                        "top": int(strip_rect.y() * dpr),
                        "width": int(strip_rect.width() * dpr),
                        "height": int(strip_rect.height() * dpr)
                    }
                    s_raw = sct.grab(s_mon)
                    top_strip_img = Image.frombytes("RGB", s_raw.size, s_raw.bgra, "raw", "BGRX")
        except Exception:
            self._close_mss_instance()
            return ()

        return self.compute_unmasked_scene_signature(pil_img, self.overlay_hud.blocks, top_strip_img)

    def _refresh_active_scene_signature(self):
        if self.overlay_hud.blocks and not self.overlay_hud.is_capturing:
            sig = self._grab_live_unmasked_signature()
            if sig:
                self.active_scene_sig = sig

    def _on_auto_timer_tick(self):
        """
        Smart Auto-Translate tick: only trigger screen capture & OCR when NEW screen data is detected.
        If the screen still displays old data, keep the existing overlay untouched without blinking or re-scanning.
        """
        if (
            (self.worker and self.worker.isRunning())
            or self.overlay_hud.is_capturing
            or self.overlay_hud.is_hidden_by_user
        ):
            return

        # Case 1: Overlay currently has translated blocks on screen -> check unmasked live signature (0ms, no blink)
        if self.overlay_hud.blocks and self.active_scene_sig:
            live_sig = self._grab_live_unmasked_signature()
            if live_sig and len(live_sig) == len(self.active_scene_sig):
                if self.frame_signature_diff(live_sig, self.active_scene_sig) < 2.2:
                    self.lbl_status.setText("✓ Auto Dịch: Dữ liệu cũ chưa đổi (Giữ nguyên bản dịch, không quét lại)")
                    return

        # Case 2: Overlay has no blocks (empty scene already scanned) -> check raw frame & text signature without blinking
        elif not self.overlay_hud.blocks and self.last_frame_sig is not None:
            raw_img = self._grab_raw_hud_image()
            if raw_img is not None:
                new_sig = self.compute_frame_signature(raw_img)
                text_changed = (
                    self.last_ocr_text_sig is not None
                    and self.has_text_changed(self.compute_text_signature(raw_img), self.last_ocr_text_sig)
                )
                if not text_changed and self.frame_signature_diff(new_sig, self.last_frame_sig) < 2.5:
                    self.lbl_status.setText("✓ Auto Dịch: Màn hình chưa có dữ liệu mới (Đang chờ...)")
                    return

        self.initiate_capture_and_translate()

    def _check_scene_or_tab_change(self):
        """
        Periodic 260ms non-intrusive check:
        1. When Auto-Scan is OFF (manual F9 mode) and not in Chat Box mode, clear stale overlay if the user switches tabs.
        2. When Auto-Scan is ON (or in Chat Box mode), NEVER wipe existing chat blocks on screen — keep them readable!
        3. If Auto-Scan is enabled on an empty screen and new text/UI appears, trigger translation immediately.
        """
        if (
            self.overlay_hud.is_capturing
            or self.overlay_hud.is_hidden_by_user
            or (self.worker and self.worker.isRunning())
        ):
            return

        if self.overlay_hud.blocks:
            # Never auto-wipe overlay blocks when Auto-Scan is active or when translating a Multi-Language Chat Box!
            if (
                not self.chk_auto_clear.isChecked()
                or self.chk_auto.isChecked()
                or "multi" in self.cb_src.currentText().lower()
            ):
                return
            live_sig = self._grab_live_unmasked_signature()
            if not live_sig:
                return
            if not self.active_scene_sig or len(live_sig) != len(self.active_scene_sig):
                self.active_scene_sig = live_sig
                return
            if self.frame_signature_diff(live_sig, self.active_scene_sig) >= 22.0:
                self.on_scene_or_tab_changed()
        elif (
            self.chk_auto.isChecked()
            and self.last_frame_sig is not None
            and not self.change_watch_timer.isActive()
        ):
            raw_img = self._grab_raw_hud_image()
            if raw_img is not None:
                new_sig = self.compute_frame_signature(raw_img)
                text_changed = (
                    self.last_ocr_text_sig is not None
                    and self.has_text_changed(self.compute_text_signature(raw_img), self.last_ocr_text_sig)
                )
                if text_changed or self.frame_signature_diff(new_sig, self.last_frame_sig) >= 3.5:
                    self.last_frame_sig = None
                    QTimer.singleShot(80, self.initiate_capture_and_translate)

    def initiate_capture_and_translate(self):
        if self.worker and self.worker.isRunning():
            return

        # Dual Display Mode: Live Chat Stream Only bypasses overlay hide + 45ms wait -> 0ms capture with zero flicker
        if self.overlay_hud.stream_mode_only:
            self._perform_screen_grab()
            return

        # Phase 1: Hide overlay pills (and Studio window if Full Screen) so screen text is exposed cleanly
        self.overlay_hud.is_capturing = True
        if self.overlay_hud.is_fullscreen:
            self.setWindowOpacity(0.0)
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
            sct = self._get_mss_instance()
            monitor = {"left": phys_x, "top": phys_y, "width": phys_w, "height": phys_h}
            sct_img = sct.grab(monitor)
            pil_img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
        except Exception as e:
            self._close_mss_instance()
            self.overlay_hud.is_capturing = False
            if self.overlay_hud.is_fullscreen:
                self.setWindowOpacity(1.0)
            self.overlay_hud.update()
            self.lbl_status.setText(f"Screen grab error: {e}")
            return

        self.last_captured_pil_img = pil_img
        if self.overlay_hud.blocks:
            self.last_valid_blocks = list(self.overlay_hud.blocks)

        new_sig = self.compute_frame_signature(pil_img)
        frame_diff = (
            self.frame_signature_diff(new_sig, self.last_frame_sig)
            if self.last_frame_sig is not None
            else 999.0
        )
        text_sig = self.compute_text_signature(pil_img)
        text_changed = (
            self.last_ocr_text_sig is None
            or self.has_text_changed(text_sig, self.last_ocr_text_sig)
        )

        # Phase 2: Immediately restore overlay and Studio window state so existing chat lines stay readable on screen
        self.overlay_hud.is_capturing = False
        if self.overlay_hud.is_fullscreen:
            self.setWindowOpacity(1.0)
        self.overlay_hud.update()

        # Fast Pixel-Delta Skip: skip OCR only when both coarse frame and 96x48 text thumbnail are unchanged
        if (
            self.chk_auto.isChecked()
            and self.last_frame_sig is not None
            and frame_diff < 1.8
            and not text_changed
        ):
            self.lbl_status.setText("✓ Auto Dịch: Dữ liệu cũ không đổi (Bỏ qua OCR & giữ nguyên bản dịch)")
            return
        self.last_frame_sig = new_sig
        self._start_translation_worker(pil_img, text_sig)

    def _start_translation_worker(self, pil_img, text_sig=None):
        """Start background OCR + translation on a clean screenshot (old lines reused, only new lines translated)."""
        if self.worker and self.worker.isRunning():
            return
        self.last_captured_pil_img = pil_img
        if self.overlay_hud.blocks:
            self.last_valid_blocks = list(self.overlay_hud.blocks)
        self.last_ocr_text_sig = text_sig if text_sig is not None else self.compute_text_signature(pil_img)
        self.prev_watch_sig = self.last_ocr_text_sig
        self.change_pending_since = None

        src_selection = self.cb_src.currentText()
        tess_lang = resolve_ocr_lang_string(src_selection)
        target_lang = self.cb_dst.currentText()

        self.lbl_status.setText("⏳ Phát hiện thay đổi • Đang OCR & dịch dòng mới...")
        self.worker = TranslationWorker(
            pil_img=pil_img,
            tess_lang=tess_lang,
            target_lang=target_lang,
            api_url=self.txt_url.text(),
            api_key=self.txt_key.text(),
            model_name=self.txt_model.text(),
            last_raw_text=self.last_raw_text,
            knowledge_mgr=self.knowledge_mgr,
            src_selection_text=src_selection,
            prev_blocks=self.last_valid_blocks,
            only_after_arrow=self.chk_after_arrow.isChecked(),
            line_cache=self.line_cache,
            skip_color_sampling=self.overlay_hud.stream_mode_only,
            recent_context=self.recent_translated_history[-3:],
        )
        self.worker.finished_signal.connect(self._on_translation_done)
        self.worker.new_chat_signal.connect(self._on_new_chat_messages)
        self.worker.error_signal.connect(self._on_translation_error)
        self.worker.progress_signal.connect(self._on_translation_error)
        self.worker.start()

    def _on_translation_done(self, blocks, status_msg):
        if blocks is None:
            # Source text on screen is unchanged old data -> restore previous blocks if they were temporarily hidden
            if not self.overlay_hud.blocks and self.last_valid_blocks:
                self.overlay_hud.blocks = list(self.last_valid_blocks)
                self.overlay_hud.repaint()
                if not self.overlay_hud.stream_mode_only and not self.change_watch_timer.isActive():
                    QTimer.singleShot(60, self._refresh_active_scene_signature)
        else:
            if self.overlay_hud.stream_mode_only:
                self.overlay_hud.fading_blocks = []
                self.overlay_hud.blocks = list(blocks)
            else:
                # Smooth transition: old chat lines slide to their new positions, new lines fade in, gone lines fade out
                self.overlay_hud.set_blocks_animated(blocks)
            if blocks:
                self.last_valid_blocks = list(blocks)
                self.last_raw_text = blocks[0]['raw']
                seen_ctx = {
                    LineTranslationCache.normalize_key(s): idx
                    for idx, (s, _) in enumerate(self.recent_translated_history)
                }
                for blk in blocks:
                    src_line = (blk.get('raw_line') or '').strip()
                    tgt_line = (blk.get('text') or '').strip()
                    norm_src = LineTranslationCache.normalize_key(src_line)
                    if src_line and tgt_line and norm_src and norm_src not in seen_ctx:
                        seen_ctx[norm_src] = len(self.recent_translated_history)
                        self.recent_translated_history.append((src_line, tgt_line))
                self.recent_translated_history = self.recent_translated_history[-3:]
            else:
                self.last_valid_blocks = []
                self.last_raw_text = ""
                self.active_scene_sig = None
            self.overlay_hud.repaint()
            if blocks and not self.overlay_hud.stream_mode_only:
                if self.last_captured_pil_img is not None:
                    self.active_scene_sig = self.compute_unmasked_scene_signature(
                        self.last_captured_pil_img,
                        self.overlay_hud.blocks
                    )
                if not self.change_watch_timer.isActive():
                    QTimer.singleShot(60, self._refresh_active_scene_signature)
        self.lbl_status.setText(status_msg)
        if (
            self.chk_auto.isChecked()
            and self.change_watch_timer.isActive()
            and not self.overlay_hud.is_hidden_by_user
        ):
            QTimer.singleShot(20, self._on_change_watch_tick)

    def _on_translation_error(self, err_msg):
        self.lbl_status.setText(err_msg)

    def closeEvent(self, event):
        self.auto_timer.stop()
        self.change_watch_timer.stop()
        self.scene_watch_timer.stop()
        self._close_mss_instance()
        self.save_config()
        if self.codex_dialog:
            self.codex_dialog.close()
        self.snipper.close()
        self.overlay_hud.close()
        event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    studio = MainStudioWindow()
    studio.show()
    sys.exit(app.exec_())
