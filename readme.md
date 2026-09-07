<div align="center">
  <img src="https://www.nvaccess.org/files/nvda/documentation/userGuide/images/nvda.ico" alt="NVDA Logo" width="120">

  # ClipHistory

  Never lose what you copied — a fully accessible clipboard history manager for NVDA.

  <br>

  **author:** chai chaimee<br>
  **url:** [https://github.com/chaichaimee/ClipHistory](https://github.com/chaichaimee/ClipHistory)
</div>

<br>

## Introduction

ClipHistory quietly watches your Windows clipboard in the background and automatically keeps a running history of everything you copy — plain text as well as rich HTML content.

Instead of losing a piece of text the moment you copy something new over it, you can open your clipboard history at any time, arrow through previous entries, and paste any one of them back into your document. You can also pin important items so they are never cleared, give pinned items your own custom names so they're easy to recognize, reorder items, and edit their content directly.

Everything is saved to disk automatically, so your history is still there the next time you start NVDA.

<br>

### Hot Keys

> **Windows+V**
> * Single Tap : Open the Clip History dialog
> * Double Tap : Clear all non-pinned items from the history

> ClipHistory listens for how many times you press Windows+V within a short time window (half a second). If you press it once and then pause, the Clip History dialog opens. If you press it twice in quick succession, all history items that are not pinned are immediately cleared and NVDA announces how many items were removed (or reports "No items to clear" if there was nothing to remove). Pinned items are always kept safe from this action.

<br>

## Features

### Automatic Clipboard Capture

ClipHistory registers a hidden, invisible listener window with Windows itself, so it is notified the instant the system clipboard changes — there is no need to poll or check repeatedly. Each time new content is copied:

1. Windows sends a clipboard-changed notification to the add-on.
2. ClipHistory reads both the plain text (CF_UNICODETEXT) and, if present, the rich HTML fragment (CF_HTML) from the clipboard.
3. If the copied text is different from the last captured text, it is added to the top of your history.
4. If the Clip History dialog happens to be open at that moment, its list updates live to show the new item.

To avoid overload from applications that update the clipboard rapidly, captures are throttled so that clipboard changes occurring less than 50 milliseconds apart are ignored.

<br>

### Persistent History Storage

Your clipboard history is stored as a JSON file in your NVDA configuration folder, under a ChaiChaimee subfolder. History is loaded in the background when NVDA starts (so startup is never delayed), and any items copied while that background load is still running are safely merged in rather than lost.

Saving is debounced: rather than writing to disk on every single change, ClipHistory waits briefly and bundles changes together, writing to a temporary file first and then swapping it into place. This protects your history file from becoming corrupted if NVDA is closed unexpectedly. On shutdown, ClipHistory always performs one final, immediate save so the very latest item is never lost.

<br>

### History Size Limit

The history holds up to 500 items. Once that limit is exceeded, ClipHistory automatically removes the oldest non-pinned items to make room for new ones — pinned items are always protected from this automatic cleanup.

<br>

### The Clip History Dialog

Opened with a single tap of Windows+V, this dialog presents your entire clipboard history as a list, with the most recently copied item at the top.

* Each entry shows a preview of its text (truncated to 200 characters), or, for a pinned item with a custom name, that name along with a character count.
* The list receives focus automatically as soon as the dialog opens, with the first item selected, so you can start arrowing through your history immediately.
* Pressing Escape, or activating the Close button, closes the dialog.

<br>

### Pasting an Item

You can paste the selected history item by pressing Enter, double-clicking it, or activating the Paste button.

1. If the item is not already at the top of the list, it is moved to the top first, just as if you had just copied it again.
2. ClipHistory temporarily suppresses its own clipboard listener for half a second so that placing the item back on the clipboard is not re-captured as a "new" copy.
3. The item's text (and HTML formatting, if it has any) is written to the Windows clipboard.
4. The dialog hides itself, and shortly afterward NVDA sends a Ctrl+V keystroke to paste into whatever field or document you were last working in.
5. NVDA announces "Paste" to confirm the action.

If the normal method of sending Ctrl+V is unavailable for any reason, ClipHistory automatically falls back to simulating the Control and V key presses directly at the system level.

<br>

### Pinning Items and Custom Display Names

Any item can be pinned from the right-click (or Applications key) context menu. Pinned items are never removed by the "double tap to clear" hotkey action, by the "Clear All" context menu command, or by automatic size-limit cleanup.

Once an item is pinned, you can edit it to give it your own short, memorable display name (for example, "Email signature" instead of the full text). The dialog list will then show that name and a character count instead of the raw copied text, making long-standing pinned items much easier to identify at a glance.

<br>

### Editing an Item

Choosing Edit from the context menu opens a dedicated edit window containing the full text of the item. For pinned items, a Display Name field is also shown so you can set or change its custom name at the same time. Confirming with OK saves your changes back into the history immediately.

<br>

### Reordering Items

Move Up and Move Down, available from the context menu, let you manually reposition an item within the history list, one place at a time, with NVDA confirming each move.

<br>

### Deleting Items

Pressing the Delete key while an item is selected in the list, or choosing Delete from the context menu, permanently removes that single item from the history, with NVDA confirming the deletion.

<br>

### Clearing History

There are two ways to clear your history, and both always leave pinned items untouched:

* **Double-tapping Windows+V** anywhere in Windows instantly clears all non-pinned items.
* **Clear All** in the dialog's context menu does the same thing from within the Clip History window.

<br>

> **Note:** ClipHistory relies on low-level Windows clipboard APIs and is designed for use on Windows with NVDA. Very large clipboard content (over 5 MB) is automatically truncated or skipped to keep the add-on responsive.

<br>

## Support Me

If this tool has made your life easier, consider fueling the next update with a small donation.

[![Support me](https://img.shields.io/badge/Donate-Support%20Me-blue?style=for-the-badge&logo=stripe)](https://buy.stripe.com/dRm9AU1xQ3Ds22N6VK1VK01)

Your support means the world. Let's build something great together.

<br>

&copy; 2026 Chai Chaimee NVDA Add-on Released under GNU GPL