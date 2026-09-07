# clip.py

import wx
import os
import json
import ui
import api
import core
import gui
import addonHandler
import globalVars
import logging
import html as html_lib
import time
import ctypes
import threading
import speech

from . import clipboard_utils

addonHandler.initTranslation()
log = logging.getLogger(__name__)

MAX_HISTORY_ITEMS = 500
SAVE_DEBOUNCE_MS = 500

class ClipHistoryManager:
	_is_saving = False
	_save_timer = None

	def __init__(self):
		self.data_path = self._get_data_path()
		self.items = []
		self._items_lock = threading.RLock()
		self._load_async()

	def _get_data_path(self):
		config_dir = os.path.join(globalVars.appArgs.configPath, "ChaiChaimee")
		if not os.path.exists(config_dir):
			os.makedirs(config_dir)
		return os.path.join(config_dir, "ClipHistory.json")

	def _load_async(self):
		def _do_load():
			try:
				if not os.path.exists(self.data_path):
					return
				file_size = os.path.getsize(self.data_path)
				if file_size > 1024 * 1024:
					log.warning(f"Large history file ({file_size} bytes), loading may be slow")
				with open(self.data_path, "r", encoding="utf-8") as f:
					loaded = json.load(f)

				if not isinstance(loaded, list):
					return

				loaded_items = []
				for entry in loaded:
					if isinstance(entry, str):
						loaded_items.append({"text": entry, "pinned": False, "html": None, "display_name": None})
					elif isinstance(entry, dict):
						item = {
							"text": entry.get("text", ""),
							"pinned": entry.get("pinned", False),
							"html": entry.get("html"),
							"display_name": entry.get("display_name")
						}
						if item["text"]:
							loaded_items.append(item)

				# Merge rather than overwrite: clipboard items captured on the
				# main thread while this background load was still running
				# must not be discarded. Anything already present in
				# self.items (inserted at index 0 by add_item) is kept in
				# front, followed by the items loaded from disk, skipping
				# duplicates by text.
				with self._items_lock:
					existing_texts = {item["text"] for item in self.items}
					merged = list(self.items)
					for item in loaded_items:
						if item["text"] not in existing_texts:
							merged.append(item)
							existing_texts.add(item["text"])
					self.items = merged
			except Exception as e:
				log.error(f"Failed to load: {e}")

		threading.Thread(target=_do_load, daemon=True).start()

	def _truncate_if_needed(self):
		if len(self.items) > MAX_HISTORY_ITEMS:
			non_pinned = [i for i in self.items if not i.get("pinned", False)]
			if len(non_pinned) > MAX_HISTORY_ITEMS // 2:
				excess = len(self.items) - MAX_HISTORY_ITEMS
				removed = 0
				new_items = []
				for item in self.items:
					if removed >= excess:
						new_items.append(item)
					elif not item.get("pinned", False):
						removed += 1
					else:
						new_items.append(item)
				self.items = new_items
				log.info(f"Truncated history to {len(self.items)} items")

	def save(self, immediate=False):
		if ClipHistoryManager._save_timer and ClipHistoryManager._save_timer.IsRunning():
			ClipHistoryManager._save_timer.Stop()

		if immediate:
			self._perform_save()
		else:
			ClipHistoryManager._save_timer = wx.CallLater(SAVE_DEBOUNCE_MS, self._perform_save)

	def _perform_save(self):
		if ClipHistoryManager._is_saving:
			log.debug("Save already in progress, skipping")
			return
		ClipHistoryManager._is_saving = True
		try:
			with self._items_lock:
				items_snapshot = list(self.items)
			unique_suffix = int(time.time() * 1000)
			temp_path = f"{self.data_path}.{unique_suffix}.tmp"
			with open(temp_path, "w", encoding="utf-8") as f:
				json.dump(items_snapshot, f, ensure_ascii=False, indent=2)
			os.replace(temp_path, self.data_path)
		except Exception as e:
			log.error(f"Async save failed: {e}")
		finally:
			ClipHistoryManager._is_saving = False

	def add_item(self, data):
		if not data or not data.get('text'):
			return
		text = data['text']
		html = data.get('html')

		with self._items_lock:
			for i, item in enumerate(self.items):
				if item["text"] == text:
					pinned = item["pinned"]
					display_name = item.get("display_name")
					del self.items[i]
					self.items.insert(0, {"text": text, "pinned": pinned, "html": html, "display_name": display_name})
					self._truncate_if_needed()
					break
			else:
				self.items.insert(0, {"text": text, "pinned": False, "html": html, "display_name": None})
				self._truncate_if_needed()
		self.save()

	def remove_item(self, index):
		with self._items_lock:
			if not (0 <= index < len(self.items)):
				return
			del self.items[index]
		self.save()

	def edit_item(self, index, new_text, new_display_name=None):
		with self._items_lock:
			if not (0 <= index < len(self.items) and new_text):
				return
			self.items[index]["text"] = new_text
			self.items[index]["html"] = None
			if new_display_name is not None:
				self.items[index]["display_name"] = new_display_name if new_display_name.strip() else None
		self.save()

	def toggle_pin(self, index):
		with self._items_lock:
			if not (0 <= index < len(self.items)):
				return
			self.items[index]["pinned"] = not self.items[index]["pinned"]
		self.save()

	def move_up(self, index):
		with self._items_lock:
			if not (0 < index < len(self.items)):
				return
			self.items[index], self.items[index - 1] = self.items[index - 1], self.items[index]
		self.save()

	def move_down(self, index):
		with self._items_lock:
			if not (0 <= index < len(self.items) - 1):
				return
			self.items[index], self.items[index + 1] = self.items[index + 1], self.items[index]
		self.save()

	def move_to_top(self, index):
		with self._items_lock:
			if index <= 0 or index >= len(self.items):
				return
			item = self.items.pop(index)
			self.items.insert(0, item)
		self.save()

	def clear_all(self):
		with self._items_lock:
			self.items.clear()
		self.save(immediate=True)

	def clear_non_pinned(self):
		with self._items_lock:
			self.items = [item for item in self.items if item.get("pinned", False)]
		self.save(immediate=True)


class EditTextDialog(wx.Dialog):
	def __init__(self, parent, title, initial_text, is_pinned=False, current_display_name=None):
		super().__init__(parent, title=title, size=(650, 500),
						 style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		self.initial_text = initial_text
		self.is_pinned = is_pinned
		self.current_display_name = current_display_name
		self.result_text = None
		self.result_display_name = None
		self.init_ui()
		self.CentreOnParent()

	def init_ui(self):
		panel = wx.Panel(self)
		sizer = wx.BoxSizer(wx.VERTICAL)

		self.display_name_ctrl = None
		# Fixed: If pinned, always show the display name field.
		if self.is_pinned:
			display_label = wx.StaticText(panel, label=_("Display name (optional):"))
			sizer.Add(display_label, 0, wx.ALL | wx.ALIGN_LEFT, 5)
			self.display_name_ctrl = wx.TextCtrl(panel)
			# If you have the original name to be displayed in the box
			if self.current_display_name:
				self.display_name_ctrl.SetValue(self.current_display_name)
			sizer.Add(self.display_name_ctrl, 0, wx.EXPAND | wx.ALL, 5)

		text_label = wx.StaticText(panel, label=_("Text content:"))
		sizer.Add(text_label, 0, wx.ALL | wx.ALIGN_LEFT, 5)

		self.text_ctrl = wx.TextCtrl(panel, value=self.initial_text,
									 style=wx.TE_MULTILINE | wx.TE_PROCESS_ENTER)
		self.text_ctrl.Bind(wx.EVT_SET_FOCUS, self.on_focus)
		sizer.Add(self.text_ctrl, 1, wx.EXPAND | wx.ALL, 5)

		btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
		ok_btn = wx.Button(panel, wx.ID_OK, label=_("&OK"))
		cancel_btn = wx.Button(panel, wx.ID_CANCEL, label=_("&Cancel"))
		btn_sizer.Add(ok_btn, 0, wx.ALL, 5)
		btn_sizer.Add(cancel_btn, 0, wx.ALL, 5)
		sizer.Add(btn_sizer, 0, wx.ALIGN_RIGHT | wx.ALL, 5)

		panel.SetSizer(sizer)

		self.Bind(wx.EVT_BUTTON, self.on_ok, id=wx.ID_OK)
		self.Bind(wx.EVT_BUTTON, self.on_cancel, id=wx.ID_CANCEL)

	def on_focus(self, event):
		wx.CallAfter(self.text_ctrl.SelectAll)
		event.Skip()

	def on_ok(self, event):
		self.result_text = self.text_ctrl.GetValue()
		if self.display_name_ctrl:
			self.result_display_name = self.display_name_ctrl.GetValue()
		else:
			self.result_display_name = None
		self.EndModal(wx.ID_OK)

	def on_cancel(self, event):
		self.result_text = None
		self.result_display_name = None
		self.EndModal(wx.ID_CANCEL)


class ClipHistoryDialog(wx.Dialog):
	def __init__(self, parent, manager, plugin):
		super().__init__(parent, title=_("Clip History"), size=(600, 400),
						 style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER | wx.STAY_ON_TOP)
		self.manager = manager
		self.plugin = plugin
		self.init_ui()
		self.update_list()
		self.Centre()
		self.Bind(wx.EVT_CLOSE, self.on_close)
		self.Bind(wx.EVT_CHAR_HOOK, self.on_char)
		self.Bind(wx.EVT_SHOW, self.on_show)

	def init_ui(self):
		panel = wx.Panel(self)
		sizer = wx.BoxSizer(wx.VERTICAL)

		self.list_ctrl = wx.ListCtrl(panel, style=wx.LC_REPORT | wx.LC_SINGLE_SEL)
		self.list_ctrl.InsertColumn(0, _("Text"), width=550)
		sizer.Add(self.list_ctrl, 1, wx.EXPAND | wx.ALL, 5)

		btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
		self.paste_btn = wx.Button(panel, label=_("&Paste"))
		self.paste_btn.Bind(wx.EVT_BUTTON, self.on_paste)
		self.close_btn = wx.Button(panel, wx.ID_CANCEL, label=_("&Close"))
		btn_sizer.Add(self.paste_btn, 0, wx.ALL, 5)
		btn_sizer.Add(self.close_btn, 0, wx.ALL, 5)
		sizer.Add(btn_sizer, 0, wx.ALIGN_RIGHT | wx.ALL, 5)

		panel.SetSizer(sizer)

		self.list_ctrl.Bind(wx.EVT_LIST_ITEM_RIGHT_CLICK, self.on_context_menu)
		self.list_ctrl.Bind(wx.EVT_CONTEXT_MENU, self.on_context_menu)
		self.list_ctrl.Bind(wx.EVT_LIST_ITEM_ACTIVATED, self.on_paste)

	def update_list(self):
		selected_data_idx = self.get_selected_index()
		self.list_ctrl.DeleteAllItems()
		for idx, item in enumerate(self.manager.items):
			if item.get("pinned") and item.get("display_name"):
				display_name = item["display_name"]
				char_count = len(item['text'])
				display_text = f"{display_name} {char_count} characters"
			else:
				if item.get('html'):
					raw = item['html']
				else:
					raw = item['text']
				display_text = html_lib.unescape(raw)
				if len(display_text) > 200:
					display_text = display_text[:200] + "..."

			list_idx = self.list_ctrl.InsertItem(self.list_ctrl.GetItemCount(), display_text)
			self.list_ctrl.SetItemData(list_idx, idx)

		if selected_data_idx is not None and selected_data_idx < len(self.manager.items):
			for pos in range(self.list_ctrl.GetItemCount()):
				if self.list_ctrl.GetItemData(pos) == selected_data_idx:
					self.list_ctrl.Select(pos)
					self.list_ctrl.Focus(pos)
					self.list_ctrl.EnsureVisible(pos)
					break
		elif self.list_ctrl.GetItemCount() > 0:
			self.list_ctrl.Select(0)
			self.list_ctrl.Focus(0)

	def on_show(self, event):
		if event.IsShown():
			wx.CallAfter(self._focus_first_item)
		event.Skip()

	def _focus_first_item(self):
		if self.list_ctrl.GetItemCount() > 0:
			self.list_ctrl.SetFocus()
			self.list_ctrl.Select(0)
			self.list_ctrl.Focus(0)

	def get_selected_index(self):
		selected = self.list_ctrl.GetFirstSelected()
		if selected == -1:
			return None
		return self.list_ctrl.GetItemData(selected)

	def _restore_selection(self, idx):
		if 0 <= idx < self.list_ctrl.GetItemCount():
			self.list_ctrl.Select(idx)
			self.list_ctrl.Focus(idx)
			self.list_ctrl.EnsureVisible(idx)

	def on_paste(self, event):
		idx = self.get_selected_index()
		if idx is None:
			return

		if idx != 0:
			self.manager.move_to_top(idx)
			self.update_list()
			self.list_ctrl.Select(0)
			idx = 0

		item = self.manager.items[idx]
		text = item["text"]
		html = item.get("html")

		self.plugin.suppress_clipboard_next()
		self.plugin.last_clipboard_text = text
		clipboard_utils.set_clipboard_data(text, html)

		self.Hide()
		core.callLater(50, self._paste_and_close)

	def _paste_and_close(self):
		speech.cancelSpeech()
		try:
			from keyboardHandler import KeyboardInputGesture
			gesture = KeyboardInputGesture.fromName("control+v")
			gesture.send()
			ui.message(_("Paste"))
			log.debug("Ctrl+V sent via KeyboardInputGesture")
		except Exception as e:
			log.warning(f"KeyboardInputGesture failed: {e}, using fallback")
			user32 = ctypes.windll.user32
			VK_CONTROL = 0x11
			VK_V = 0x56
			KEYEVENTF_KEYUP = 0x0002
			user32.keybd_event(VK_CONTROL, 0, 0, 0)
			user32.keybd_event(VK_V, 0, 0, 0)
			user32.keybd_event(VK_V, 0, KEYEVENTF_KEYUP, 0)
			user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
			ui.message(_("Pasted"))
		wx.CallAfter(self.Close)

	def on_delete(self, event):
		idx = self.get_selected_index()
		if idx is not None:
			self.manager.remove_item(idx)
			self.update_list()
			ui.message(_("Deleted"))

	def on_edit(self, event):
		idx = self.get_selected_index()
		if idx is None:
			return
		item = self.manager.items[idx]
		current_text = item["text"]
		is_pinned = item.get("pinned", False)
		# Retrieve the current display name (if any) and display it in the dialog
		current_display_name = item.get("display_name") if is_pinned else None
		dlg = EditTextDialog(self, _("Edit Item"), current_text, is_pinned, current_display_name)
		# prePopup/postPopup must bracket ShowModal, otherwise EVT_CHAR_HOOK
		# can silently fail to fire and the dialog looks open but does not
		# respond to keyboard input, with no visual cue for a blind user.
		gui.mainFrame.prePopup()
		try:
			result = dlg.ShowModal()
		finally:
			gui.mainFrame.postPopup()
		if result == wx.ID_OK and dlg.result_text is not None:
			self.manager.edit_item(idx, dlg.result_text, dlg.result_display_name)
			self.update_list()
			ui.message(_("Item edited"))
		dlg.Destroy()

	def on_pin(self, event):
		idx = self.get_selected_index()
		if idx is None:
			return
		current_idx = idx
		self.manager.toggle_pin(current_idx)
		self.update_list()
		wx.CallAfter(self._restore_selection, current_idx)
		is_pinned = self.manager.items[current_idx].get("pinned", False)
		ui.message(_("Pinned") if is_pinned else _("Unpinned"))

	def on_move_up(self, event):
		idx = self.get_selected_index()
		if idx is not None:
			self.manager.move_up(idx)
			self.update_list()
			new_idx = idx - 1
			if new_idx >= 0:
				self.list_ctrl.Select(new_idx)
				self.list_ctrl.Focus(new_idx)
				self.list_ctrl.EnsureVisible(new_idx)
			ui.message(_("Moved up"))

	def on_move_down(self, event):
		idx = self.get_selected_index()
		if idx is not None:
			self.manager.move_down(idx)
			self.update_list()
			new_idx = idx + 1
			if new_idx < len(self.manager.items):
				self.list_ctrl.Select(new_idx)
				self.list_ctrl.Focus(new_idx)
				self.list_ctrl.EnsureVisible(new_idx)
			ui.message(_("Moved down"))

	def on_clear_all(self, event):
		self.manager.clear_non_pinned()
		self.update_list()
		ui.message(_("Cleared all non-pinned items"))

	def on_context_menu(self, event):
		idx = self.get_selected_index()
		menu = wx.Menu()

		clear_all_item = menu.Append(wx.ID_ANY, _("Clear All"))
		self.Bind(wx.EVT_MENU, self.on_clear_all, clear_all_item)

		if idx is not None:
			menu.AppendSeparator()
			is_pinned = self.manager.items[idx].get("pinned", False)
			pin_label = _("Unpin") if is_pinned else _("Pin")
			pin_item = menu.Append(wx.ID_ANY, pin_label)
			menu.AppendSeparator()
			move_up_item = menu.Append(wx.ID_ANY, _("Move Up"))
			move_down_item = menu.Append(wx.ID_ANY, _("Move Down"))
			menu.AppendSeparator()
			edit_item = menu.Append(wx.ID_ANY, _("Edit"))
			delete_item = menu.Append(wx.ID_ANY, _("Delete"))

			self.Bind(wx.EVT_MENU, self.on_pin, pin_item)
			self.Bind(wx.EVT_MENU, self.on_move_up, move_up_item)
			self.Bind(wx.EVT_MENU, self.on_move_down, move_down_item)
			self.Bind(wx.EVT_MENU, self.on_edit, edit_item)
			self.Bind(wx.EVT_MENU, self.on_delete, delete_item)

		self.list_ctrl.PopupMenu(menu)
		menu.Destroy()

	def on_char(self, event):
		key = event.GetKeyCode()
		if key == wx.WXK_DELETE:
			self.on_delete(event)
		elif key == wx.WXK_ESCAPE:
			self.Close()
		else:
			event.Skip()

	def on_close(self, event):
		self.Destroy()
