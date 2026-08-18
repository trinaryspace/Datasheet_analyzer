"""Choosing a folder, when the browser is not allowed to tell you where it is.

A browser cannot hand a server an absolute path. `<input webkitdirectory>`
yields file contents under relative names and the File System Access API
yields an opaque handle; neither produces `C:\\work\radar`, which is what a
server that must open the PDFs itself actually needs. Typing the path works
and is what the screen did, but it is a poor first impression for a tool
whose first act is "point me at your folder".

This application is local by construction — one user, one machine, the server
and the browser the same computer — and that is the entire reason the first
endpoint below is defensible. `POST /api/browse/dialog` opens a *native*
folder picker on the machine running the server and returns what was chosen.
On any other deployment shape it would be nonsense: it would open a window on
a machine nobody is sitting at.

So it is offered, never depended on. `GET /api/browse/list` walks directories
server-side and is what the UI falls back to when the dialog cannot open —
headless, no display, no Tk. The dialog is a convenience; the listing is the
contract.
"""

from __future__ import annotations

import logging
import string
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from datasheet_analyzer.app.contracts import (
    API_PREFIX,
    BrowseEntry,
    BrowseListOut,
    BrowsePickOut,
)
from datasheet_analyzer.app.deps import get_settings_dep
from datasheet_analyzer.config import Settings

log = logging.getLogger(__name__)

router = APIRouter(prefix=API_PREFIX, tags=["browse"])

SettingsDep = Annotated[Settings, Depends(get_settings_dep)]

#: How long the native dialog may stay open before the request gives up. A
#: modal nobody notices — it opens behind the browser often enough — must not
#: hold a worker thread for the life of the process.
DIALOG_TIMEOUT_SECONDS = 300


@router.post("/browse/dialog", response_model=BrowsePickOut)
def open_dialog() -> BrowsePickOut:
    """Open a native folder picker on the server's machine.

    Returns `picked=False` rather than an error when the user cancels: not
    choosing is an ordinary outcome, not a failure. Returns
    `available=False` when no dialog can be opened at all, which is the
    signal for the client to fall back to the listing endpoint.
    """
    try:
        import tkinter
        from tkinter import filedialog
    except Exception as exc:  # noqa: BLE001 - absent Tk is a fallback, not a crash
        log.info("browse: no native dialog available: %s", exc)
        return BrowsePickOut(available=False, reason=f"no native dialog: {exc}")

    try:
        root = tkinter.Tk()
        root.withdraw()
        # Without this the dialog reliably opens *behind* the browser window,
        # which looks exactly like the button doing nothing.
        root.attributes("-topmost", True)
        try:
            chosen = filedialog.askdirectory(title="Open project folder", parent=root)
        finally:
            root.destroy()
    except Exception as exc:  # noqa: BLE001 - a display-less host lands here
        log.info("browse: native dialog failed: %s", exc)
        return BrowsePickOut(available=False, reason=f"dialog could not open: {exc}")

    if not chosen:
        return BrowsePickOut(available=True, picked=False)
    return BrowsePickOut(available=True, picked=True, directory=str(Path(chosen)))


@router.get("/browse/list", response_model=BrowseListOut)
def list_directory(path: str = "", settings: SettingsDep = None) -> BrowseListOut:
    """Sub-directories of `path`, for the in-app fallback browser.

    An empty `path` lists the roots to start from — drive letters on Windows,
    `/` elsewhere — plus the user's home, because that is where a shelf
    usually is. Files are not listed: this picks a *folder*, and showing two
    hundred PDFs the user cannot select is noise.
    """
    raw = (path or "").strip()
    if not raw:
        return BrowseListOut(path="", parent="", entries=_roots())

    here = Path(raw).expanduser()
    if not here.is_dir():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"not a directory: {raw}")

    entries: list[BrowseEntry] = []
    try:
        for child in sorted(here.iterdir(), key=lambda p: p.name.lower()):
            if not child.is_dir() or child.name.startswith("."):
                continue
            entries.append(BrowseEntry(name=child.name, path=str(child)))
    except OSError as exc:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=f"cannot read directory: {exc.strerror or exc}",
        ) from exc

    parent = "" if here.parent == here else str(here.parent)
    return BrowseListOut(path=str(here), parent=parent, entries=entries)


def _roots() -> list[BrowseEntry]:
    """Where a browse with no path starts."""
    found: list[BrowseEntry] = []
    home = Path.home()
    if home.is_dir():
        found.append(BrowseEntry(name=f"Home ({home.name})", path=str(home)))
    for letter in string.ascii_uppercase:
        drive = Path(f"{letter}:\\")
        if drive.exists():
            found.append(BrowseEntry(name=f"{letter}:", path=str(drive)))
    if not found:
        found.append(BrowseEntry(name="/", path="/"))
    return found
