import ctypes
from ctypes import wintypes
import logging
import hashlib
import re
import html as html_lib
import addonHandler

addonHandler.initTranslation()
log = logging.getLogger(__name__)

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

CF_UNICODETEXT = 13
_HTML_FORMAT_ID = None
MAX_CLIPBOARD_SIZE = 5 * 1024 * 1024
_HTML_TAG_RE = re.compile(r"<[^>]+>")

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

def _get_html_format_id():
	global _HTML_FORMAT_ID
	if _HTML_FORMAT_ID is None:
		_HTML_FORMAT_ID = user32.RegisterClipboardFormatW("HTML Format")
	return _HTML_FORMAT_ID

def _read_unicode_text(handle):
	if not handle:
		return None
	size = kernel32.GlobalSize(handle)
	if size == 0:
		log.warning("GlobalSize returned 0 for CF_UNICODETEXT")
		return None

	if size > MAX_CLIPBOARD_SIZE:
		log.warning(f"Clipboard text too large ({size} bytes), truncating to {MAX_CLIPBOARD_SIZE} bytes")
		size = MAX_CLIPBOARD_SIZE

	ptr = kernel32.GlobalLock(handle)
	if not ptr:
		log.warning("GlobalLock returned NULL for CF_UNICODETEXT")
		return None
	try:
		num_chars = size // 2
		text = ctypes.wstring_at(ptr, num_chars)
		return text
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
		log.warning(f"Clipboard HTML too large ({size} bytes), skipping")
		return None

	ptr = kernel32.GlobalLock(handle)
	if not ptr:
		log.warning("GlobalLock returned NULL for CF_HTML")
		return None
	try:
		data = ctypes.string_at(ptr, size)
		raw = data.decode('utf-8', errors='replace')
	except Exception as e:
		log.warning(f"Error reading CF_HTML bytes: {e}")
		return None
	finally:
		kernel32.GlobalUnlock(handle)

	start_marker = "StartFragment:"
	end_marker = "EndFragment:"
	start_idx = raw.find(start_marker)
	end_idx = raw.find(end_marker)
	if start_idx == -1 or end_idx == -1:
		log.warning("HTML Format missing StartFragment/EndFragment markers")
		return None

	try:
		start_line = raw[start_idx + len(start_marker):].split('\r\n')[0]
		end_line = raw[end_idx + len(end_marker):].split('\r\n')[0]
		start_offset = int(start_line.strip())
		end_offset = int(end_line.strip())
	except (IndexError, ValueError) as e:
		log.warning(f"Failed to parse fragment offsets: {e}")
		return None

	if not (0 <= start_offset < end_offset <= len(raw)):
		log.warning(f"Invalid fragment offsets: start={start_offset}, end={end_offset}, length={len(raw)}")
		return None

	fragment = raw[start_offset:end_offset]
	return fragment

def html_to_text(fragment_html):
	# Best-effort plain-text fallback for clipboard sources that only ever
	# populate the HTML format (no CF_UNICODETEXT), such as some websites'
	# "Copy" buttons on a code block. Strips tags and unescapes entities;
	# not a full HTML parse, just enough to keep the item capturable and
	# readable in the history list.
	if not fragment_html:
		return None
	try:
		stripped = _HTML_TAG_RE.sub("", fragment_html)
		text = html_lib.unescape(stripped).strip()
		return text or None
	except Exception as e:
		log.warning(f"Error converting HTML fragment to text: {e}")
		return None

def get_clipboard_data():
	if not user32.OpenClipboard(0):
		log.debug("Failed to open clipboard")
		return None

	result = {'text': None, 'html': None}
	try:
		handle = user32.GetClipboardData(CF_UNICODETEXT)
		if handle:
			result['text'] = _read_unicode_text(handle)

		html_format = _get_html_format_id()
		handle = user32.GetClipboardData(html_format)
		if handle:
			result['html'] = _read_html(handle)
	except Exception as e:
		log.warning(f"Error reading clipboard: {e}")
	finally:
		user32.CloseClipboard()

	if result['text'] is None and result['html'] is None:
		return None

	hash_input = (result.get('text') or '') + (result.get('html') or '')
	result['hash'] = hashlib.sha256(hash_input.encode('utf-8')).hexdigest()
	return result

def _set_unicode_text(text):
	if not text:
		return False
	size = (len(text) + 1) * 2
	h_mem = kernel32.GlobalAlloc(0x0042, size)
	if not h_mem:
		return False
	ptr = kernel32.GlobalLock(h_mem)
	if not ptr:
		kernel32.GlobalFree(h_mem)
		return False
	try:
		ctypes.memmove(ptr, text.encode('utf-16-le'), size - 2)
	finally:
		kernel32.GlobalUnlock(h_mem)
	user32.SetClipboardData(CF_UNICODETEXT, h_mem)
	return True

def _set_html(html):
	if not html:
		return False
	header = (
		"Version:0.9\r\n"
		"StartHTML:XXXXXXXX\r\n"
		"EndHTML:XXXXXXXX\r\n"
		"StartFragment:XXXXXXXX\r\n"
		"EndFragment:XXXXXXXX\r\n"
	)
	fragment = html
	data_bytes = (header + fragment).encode('utf-8')
	start_html = 0
	start_fragment = header.find("StartFragment:") + len("StartFragment:")
	start_fragment = header.find("\r\n", start_fragment) + 2
	end_fragment = start_fragment + len(fragment)
	end_html = len(data_bytes)

	start_html_str = f"{start_html:08d}"
	end_html_str = f"{end_html:08d}"
	start_frag_str = f"{start_fragment:08d}"
	end_frag_str = f"{end_fragment:08d}"

	header = header.replace("XXXXXXXX", start_html_str, 1)
	header = header.replace("XXXXXXXX", end_html_str, 1)
	header = header.replace("XXXXXXXX", start_frag_str, 1)
	header = header.replace("XXXXXXXX", end_frag_str, 1)

	final_data = (header + fragment).encode('utf-8')
	size = len(final_data)

	h_mem = kernel32.GlobalAlloc(0x0042, size)
	if not h_mem:
		return False
	ptr = kernel32.GlobalLock(h_mem)
	if not ptr:
		kernel32.GlobalFree(h_mem)
		return False
	try:
		ctypes.memmove(ptr, final_data, size)
	finally:
		kernel32.GlobalUnlock(h_mem)

	html_format = _get_html_format_id()
	user32.SetClipboardData(html_format, h_mem)
	return True

def set_clipboard_data(text, html=None):
	if not user32.OpenClipboard(0):
		return False
	try:
		user32.EmptyClipboard()
		success = _set_unicode_text(text)
		if html:
			_set_html(html)
	except Exception as e:
		log.warning(f"Error setting clipboard: {e}")
		success = False
	finally:
		user32.CloseClipboard()
	return success

def clear_clipboard():
	# Used by "Clear"/"Clear All" so clearing the history also empties the
	# real Windows clipboard, instead of leaving whatever was last pasted
	# sitting there after the in-dialog/JSON history has been wiped.
	if not user32.OpenClipboard(0):
		log.warning("Failed to open clipboard for clearing")
		return False
	try:
		user32.EmptyClipboard()
	except Exception as e:
		log.warning(f"Error clearing clipboard: {e}")
		return False
	finally:
		user32.CloseClipboard()
	return True
