# clipboard_utils.py

import ctypes
from ctypes import wintypes
import logging
import hashlib
import addonHandler

addonHandler.initTranslation()
log = logging.getLogger(__name__)

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

CF_UNICODETEXT = 13
_HTML_FORMAT_ID = None
MAX_CLIPBOARD_SIZE = 5 * 1024 * 1024

# Global memory flags required by SetClipboardData.
GMEM_MOVEABLE = 0x0002
GMEM_ZEROINIT = 0x0040
GHND = GMEM_MOVEABLE | GMEM_ZEROINIT


# ---------------------------------------------------------------------------
# Win32 function definitions
# ---------------------------------------------------------------------------

kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = wintypes.HGLOBAL

kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalLock.restype = ctypes.c_void_p

kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalUnlock.restype = wintypes.BOOL

kernel32.GlobalSize.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalSize.restype = ctypes.c_size_t

kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalFree.restype = wintypes.HGLOBAL

user32.OpenClipboard.argtypes = [wintypes.HWND]
user32.OpenClipboard.restype = wintypes.BOOL

user32.CloseClipboard.argtypes = []
user32.CloseClipboard.restype = wintypes.BOOL

user32.EmptyClipboard.argtypes = []
user32.EmptyClipboard.restype = wintypes.BOOL

user32.GetClipboardData.argtypes = [wintypes.UINT]
user32.GetClipboardData.restype = wintypes.HANDLE

user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
user32.SetClipboardData.restype = wintypes.HANDLE

user32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
user32.RegisterClipboardFormatW.restype = wintypes.UINT


# ---------------------------------------------------------------------------
# Clipboard format helpers
# ---------------------------------------------------------------------------

def _get_html_format_id():
	global _HTML_FORMAT_ID

	if _HTML_FORMAT_ID is None:
		format_id = user32.RegisterClipboardFormatW("HTML Format")

		if not format_id:
			log.warning("Failed to register HTML clipboard format")
			return None

		_HTML_FORMAT_ID = format_id

	return _HTML_FORMAT_ID


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------

def _read_unicode_text(handle):
	if not handle:
		return None

	size = kernel32.GlobalSize(handle)

	if size == 0:
		log.warning("GlobalSize returned 0 for CF_UNICODETEXT")
		return None

	if size > MAX_CLIPBOARD_SIZE:
		log.warning(
			f"Clipboard text too large ({size} bytes), "
			f"truncating to {MAX_CLIPBOARD_SIZE} bytes"
		)
		size = MAX_CLIPBOARD_SIZE

	# UTF-16 requires an even number of bytes.
	size -= size % 2

	if size == 0:
		return None

	ptr = kernel32.GlobalLock(handle)

	if not ptr:
		log.warning("GlobalLock returned NULL for CF_UNICODETEXT")
		return None

	try:
		data = ctypes.string_at(ptr, size)

		# Find the UTF-16LE null terminator on a code-unit boundary.
		end = len(data)

		for i in range(0, len(data) - 1, 2):
			if data[i:i + 2] == b"\x00\x00":
				end = i
				break

		data = data[:end]

		return data.decode("utf-16-le", errors="replace")

	except Exception as e:
		log.warning(f"Error reading CF_UNICODETEXT: {e}")
		return None

	finally:
		kernel32.GlobalUnlock(handle)


def _read_html(handle):
	if not handle:
		return None

	size = kernel32.GlobalSize(handle)

	if size == 0:
		log.warning("GlobalSize returned 0 for CF_HTML")
		return None

	if size > MAX_CLIPBOARD_SIZE:
		log.warning(
			f"Clipboard HTML too large ({size} bytes), skipping"
		)
		return None

	ptr = kernel32.GlobalLock(handle)

	if not ptr:
		log.warning("GlobalLock returned NULL for CF_HTML")
		return None

	try:
		data = ctypes.string_at(ptr, size)

	except Exception as e:
		log.warning(f"Error reading CF_HTML bytes: {e}")
		return None

	finally:
		kernel32.GlobalUnlock(handle)

	# Remove trailing null terminator if present.
	data = data.rstrip(b"\x00")

	start_marker = b"StartFragment:"
	end_marker = b"EndFragment:"

	start_idx = data.find(start_marker)
	end_idx = data.find(end_marker)

	if start_idx == -1 or end_idx == -1:
		log.warning(
			"HTML Format missing StartFragment/EndFragment markers"
		)
		return None

	try:
		start_line_start = start_idx + len(start_marker)
		start_line_end = data.find(b"\r\n", start_line_start)

		end_line_start = end_idx + len(end_marker)
		end_line_end = data.find(b"\r\n", end_line_start)

		if start_line_end == -1 or end_line_end == -1:
			raise ValueError("Malformed CF_HTML header")

		start_offset = int(
			data[start_line_start:start_line_end].strip()
		)

		end_offset = int(
			data[end_line_start:end_line_end].strip()
		)

	except (ValueError, TypeError) as e:
		log.warning(f"Failed to parse fragment offsets: {e}")
		return None

	# CF_HTML offsets are BYTE offsets, not character offsets.
	if not (0 <= start_offset <= end_offset <= len(data)):
		log.warning(
			f"Invalid fragment offsets: "
			f"start={start_offset}, "
			f"end={end_offset}, "
			f"length={len(data)}"
		)
		return None

	try:
		fragment_bytes = data[start_offset:end_offset]
		return fragment_bytes.decode("utf-8", errors="replace")

	except Exception as e:
		log.warning(f"Failed to decode HTML fragment: {e}")
		return None


def get_clipboard_data():
	if not user32.OpenClipboard(0):
		log.debug("Failed to open clipboard")
		return None

	result = {
		"text": None,
		"html": None,
	}

	try:
		handle = user32.GetClipboardData(CF_UNICODETEXT)

		if handle:
			result["text"] = _read_unicode_text(handle)

		html_format = _get_html_format_id()

		if html_format:
			handle = user32.GetClipboardData(html_format)

			if handle:
				result["html"] = _read_html(handle)

	except Exception as e:
		log.warning(f"Error reading clipboard: {e}")

	finally:
		user32.CloseClipboard()

	if result["text"] is None and result["html"] is None:
		return None

	hash_input = (
		(result.get("text") or "")
		+ (result.get("html") or "")
	)

	result["hash"] = hashlib.sha256(
		hash_input.encode("utf-8")
	).hexdigest()

	return result


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def _set_unicode_text(text):
	if text is None:
		return False

	data = text.encode("utf-16-le") + b"\x00\x00"
	size = len(data)

	if size > MAX_CLIPBOARD_SIZE:
		log.warning(
			f"Clipboard text too large to write ({size} bytes)"
		)
		return False

	h_mem = kernel32.GlobalAlloc(GHND, size)

	if not h_mem:
		log.warning("GlobalAlloc failed for CF_UNICODETEXT")
		return False

	ptr = kernel32.GlobalLock(h_mem)

	if not ptr:
		log.warning("GlobalLock failed for CF_UNICODETEXT")
		kernel32.GlobalFree(h_mem)
		return False

	try:
		ctypes.memmove(ptr, data, size)

	finally:
		kernel32.GlobalUnlock(h_mem)

	# On success Windows owns h_mem.
	result = user32.SetClipboardData(
		CF_UNICODETEXT,
		h_mem,
	)

	if not result:
		log.warning("SetClipboardData failed for CF_UNICODETEXT")
		kernel32.GlobalFree(h_mem)
		return False

	return True


def _set_html(html):
	if html is None:
		return False

	html_bytes = html.encode("utf-8")

	# CF_HTML requires byte offsets into the complete clipboard payload.
	#
	# Keep the actual HTML document separate from the CF_HTML metadata.
	html_prefix = b"<html><body><!--StartFragment-->"
	html_suffix = b"<!--EndFragment--></body></html>"

	header_template = (
		b"Version:0.9\r\n"
		b"StartHTML:00000000\r\n"
		b"EndHTML:00000000\r\n"
		b"StartFragment:00000000\r\n"
		b"EndFragment:00000000\r\n"
	)

	start_html = len(header_template)
	start_fragment = start_html + len(html_prefix)
	end_fragment = start_fragment + len(html_bytes)
	end_html = end_fragment + len(html_suffix)

	header = (
		b"Version:0.9\r\n"
		+ f"StartHTML:{start_html:08d}\r\n".encode("ascii")
		+ f"EndHTML:{end_html:08d}\r\n".encode("ascii")
		+ f"StartFragment:{start_fragment:08d}\r\n".encode("ascii")
		+ f"EndFragment:{end_fragment:08d}\r\n".encode("ascii")
	)

	final_data = (
		header
		+ html_prefix
		+ html_bytes
		+ html_suffix
		+ b"\x00"
	)

	size = len(final_data)

	if size > MAX_CLIPBOARD_SIZE:
		log.warning(
			f"Clipboard HTML too large to write ({size} bytes)"
		)
		return False

	h_mem = kernel32.GlobalAlloc(GHND, size)

	if not h_mem:
		log.warning("GlobalAlloc failed for CF_HTML")
		return False

	ptr = kernel32.GlobalLock(h_mem)

	if not ptr:
		log.warning("GlobalLock failed for CF_HTML")
		kernel32.GlobalFree(h_mem)
		return False

	try:
		ctypes.memmove(ptr, final_data, size)

	finally:
		kernel32.GlobalUnlock(h_mem)

	html_format = _get_html_format_id()

	if not html_format:
		kernel32.GlobalFree(h_mem)
		return False

	# On success Windows takes ownership of h_mem.
	result = user32.SetClipboardData(
		html_format,
		h_mem,
	)

	if not result:
		log.warning("SetClipboardData failed for CF_HTML")
		kernel32.GlobalFree(h_mem)
		return False

	return True


def set_clipboard_data(text, html=None):
	if not user32.OpenClipboard(0):
		log.debug("Failed to open clipboard for writing")
		return False

	try:
		if not user32.EmptyClipboard():
			log.warning("EmptyClipboard failed")
			return False

		success = _set_unicode_text(text)

		if not success:
			return False

		if html is not None:
			if not _set_html(html):
				log.warning(
					"Failed to set HTML clipboard data; "
					"plain text was still written"
				)

		return True

	except Exception as e:
		log.warning(f"Error setting clipboard: {e}")
		return False

	finally:
		user32.CloseClipboard()
