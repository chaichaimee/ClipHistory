# __init__.py
# Copyright (C) 2026 Chai Chaimee
# Licensed under GNU General Public License. See COPYING.txt for details.

import addonHandler
import globalPluginHandler
import wx
import gui
import ui
import api
import core
import scriptHandler
import time
import logging
import ctypes
import ctypes.wintypes

from . import clipboard_utils
from .clip import ClipHistoryManager, ClipHistoryDialog

addonHandler.initTranslation()
log = logging.getLogger(__name__)

WM_CLIPBOARDUPDATE = 0x031D

WNDPROC = ctypes.WINFUNCTYPE(
	ctypes.c_int,
	ctypes.wintypes.HWND,
	ctypes.c_uint,
	ctypes.wintypes.WPARAM,
	ctypes.wintypes.LPARAM
)

class WNDCLASS(ctypes.Structure):
	_fields_ = [
		("style", ctypes.c_uint),
		("lpfnWndProc", ctypes.c_void_p),
		("cbClsExtra", ctypes.c_int),
		("cbWndExtra", ctypes.c_int),
		("hInstance", ctypes.wintypes.HINSTANCE),
		("hIcon", ctypes.c_void_p),
		("hCursor", ctypes.c_void_p),
		("hbrBackground", ctypes.c_void_p),
		("lpszMenuName", ctypes.wintypes.LPCWSTR),
		("lpszClassName", ctypes.wintypes.LPCWSTR),
	]

class GlobalPlugin(globalPluginHandler.GlobalPlugin):
	scriptCategory = "ClipHistory"

	def __init__(self):
		super().__init__()
		try:
			self.manager = ClipHistoryManager()
			self.last_clipboard_text = ""
			self.dialog = None
			self._clipboard_listener_disabled = False
			self._disable_timer = None
			self._last_clipboard_process_time = 0
			self._clipboard_throttle_ms = 50

			self._setup_api_types()

			self._hwnd = None
			self._wndclass = None
			self._wndproc_callback = None
			self._setup_clipboard_listener()

			self._tap_count = 0
			self._last_tap_time = 0
			self._tap_timer = None
			self._tap_threshold = 0.5

			log.info("ClipHistory plugin initialized")
		except Exception as e:
			log.error(f"ClipHistory initialization failed: {e}", exc_info=True)

	def _setup_api_types(self):
		user32 = ctypes.windll.user32

		user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASS)]
		user32.RegisterClassW.restype = ctypes.c_uint16

		user32.CreateWindowExW.argtypes = [
			ctypes.c_uint, ctypes.wintypes.LPCWSTR, ctypes.wintypes.LPCWSTR,
			ctypes.c_uint, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
			ctypes.wintypes.HWND, ctypes.wintypes.HMENU, ctypes.wintypes.HINSTANCE,
			ctypes.c_void_p
		]
		user32.CreateWindowExW.restype = ctypes.wintypes.HWND

		user32.AddClipboardFormatListener.argtypes = [ctypes.wintypes.HWND]
		user32.AddClipboardFormatListener.restype = ctypes.wintypes.BOOL

		user32.DefWindowProcW.argtypes = [
			ctypes.wintypes.HWND, ctypes.c_uint,
			ctypes.wintypes.WPARAM, ctypes.wintypes.LPARAM
		]
		user32.DefWindowProcW.restype = ctypes.c_int

		user32.RemoveClipboardFormatListener.argtypes = [ctypes.wintypes.HWND]
		user32.RemoveClipboardFormatListener.restype = ctypes.wintypes.BOOL

		user32.DestroyWindow.argtypes = [ctypes.wintypes.HWND]
		user32.DestroyWindow.restype = ctypes.wintypes.BOOL

		user32.UnregisterClassW.argtypes = [ctypes.wintypes.LPCWSTR, ctypes.wintypes.HINSTANCE]
		user32.UnregisterClassW.restype = ctypes.wintypes.BOOL

	def _setup_clipboard_listener(self):
		hinst = ctypes.windll.kernel32.GetModuleHandleW(None)
		self._className = "ClipHistoryListenerClass"

		self._wndproc_callback = WNDPROC(self._wnd_proc)

		wndclass = WNDCLASS()
		wndclass.lpszClassName = self._className
		wndclass.hInstance = hinst
		wndclass.lpfnWndProc = ctypes.cast(self._wndproc_callback, ctypes.c_void_p)

		register_result = ctypes.windll.user32.RegisterClassW(ctypes.byref(wndclass))
		if not register_result:
			error_code = ctypes.windll.kernel32.GetLastError()
			if error_code != 1410:
				raise ctypes.WinError(error_code)

		self._hwnd = ctypes.windll.user32.CreateWindowExW(
			0, self._className, "ClipHistory Listener",
			0, 0, 0, 0, 0, 0, 0, hinst, None
		)
		if not self._hwnd:
			raise ctypes.WinError()

		if not ctypes.windll.user32.AddClipboardFormatListener(self._hwnd):
			raise ctypes.WinError()

		self._wndclass = wndclass
		log.info("Clipboard listener registered")

	def _wnd_proc(self, hwnd, msg, wparam, lparam):
		if msg == WM_CLIPBOARDUPDATE:
			self._on_clipboard_update()
		return ctypes.windll.user32.DefWindowProcW(hwnd, msg, wparam, lparam)

	def _on_clipboard_update(self):
		if self._clipboard_listener_disabled:
			return

		current_time = time.time() * 1000
		if current_time - self._last_clipboard_process_time < self._clipboard_throttle_ms:
			return
		self._last_clipboard_process_time = current_time

		try:
			data = clipboard_utils.get_clipboard_data()
			if data and data.get('text') and data['text'] != self.last_clipboard_text:
				self.manager.add_item(data)
				self.last_clipboard_text = data['text']
				log.info(f"New clipboard item captured: {data['text'][:50]}")
				if self.dialog and self.dialog.IsShown():
					wx.CallAfter(self.dialog.update_list)
		except Exception as e:
			log.warning(f"Clipboard update error: {e}")

	def suppress_clipboard_next(self):
		if self._disable_timer and self._disable_timer.IsRunning():
			self._disable_timer.Stop()
		self._clipboard_listener_disabled = True
		self._disable_timer = core.callLater(500, self._enable_clipboard_listener)

	def _enable_clipboard_listener(self):
		self._clipboard_listener_disabled = False
		self._disable_timer = None

	def terminate(self):
		# Cancel the debounced clipboard re-enable timer so it cannot fire
		# against a plugin instance that no longer owns valid state.
		if self._disable_timer and self._disable_timer.IsRunning():
			self._disable_timer.Stop()
		self._disable_timer = None

		# Cancel the multi-tap gesture timer. Without this, a windows+v tap
		# pending at the moment of a reload would fire _execute_tap_action
		# against a dead instance.
		if self._tap_timer and self._tap_timer.IsRunning():
			self._tap_timer.Stop()
		self._tap_timer = None

		if self._hwnd:
			ctypes.windll.user32.RemoveClipboardFormatListener(self._hwnd)
			ctypes.windll.user32.DestroyWindow(self._hwnd)
			self._hwnd = None
		if self._wndclass:
			hinst = ctypes.windll.kernel32.GetModuleHandleW(None)
			ctypes.windll.user32.UnregisterClassW(self._className, hinst)
			self._wndclass = None
		self._wndproc_callback = None
		if self.dialog:
			self.dialog.Destroy()
		if hasattr(self, 'manager'):
			# Force an immediate, synchronous save on shutdown instead of the
			# debounced save. A debounced wx.CallLater scheduled here may
			# never fire once NVDA finishes unloading the add-on, silently
			# losing the most recent clipboard entry.
			self.manager.save(immediate=True)
		log.info("ClipHistory plugin terminated")

	def _execute_tap_action(self):
		log.debug(f"_execute_tap_action called with count: {self._tap_count}")
		try:
			if self._tap_count == 1:
				self.show_dialog()
			elif self._tap_count >= 2:
				# Count the number of items to be deleted (Only those that are not pinned)
				non_pinned_count = sum(1 for item in self.manager.items if not item.get("pinned", False))
				self.manager.clear_non_pinned()
				if non_pinned_count == 0:
					ui.message(_("No items to clear"))
				else:
					ui.message(_("Cleared {count} items").format(count=non_pinned_count))
				if self.dialog and self.dialog.IsShown():
					wx.CallAfter(self.dialog.update_list)
		except Exception as e:
			log.error(f"Error in tap action: {e}")
		finally:
			self._tap_count = 0
			self._tap_timer = None

	@scriptHandler.script(gesture="kb:windows+v", description=_("Opens clip history (single) clears all (double)"))
	def script_openClipHistory(self, gesture):
		current_time = time.time()
		if current_time - self._last_tap_time > self._tap_threshold:
			self._tap_count = 0
			if self._tap_timer and self._tap_timer.IsRunning():
				self._tap_timer.Stop()

		self._tap_count += 1
		self._last_tap_time = current_time

		if self._tap_timer and self._tap_timer.IsRunning():
			self._tap_timer.Stop()

		self._tap_timer = core.callLater(int(self._tap_threshold * 1000), self._execute_tap_action)

	def show_dialog(self):
		if self.dialog and self.dialog.IsShown():
			self.dialog.Raise()
			return
		self.dialog = ClipHistoryDialog(gui.mainFrame, self.manager, self)
		gui.mainFrame.prePopup()
		self.dialog.Show()
		self.dialog.CentreOnScreen()
		self.dialog.Raise()
		gui.mainFrame.postPopup()
		log.info("Dialog shown")
