"""Serialise in-process pdfium access.

pdfium is a C library and is not thread-safe. FastAPI runs synchronous
endpoints in a thread pool, so two requests rendering pages at the same time
corrupt its memory: the output shows garbled glyphs, or the process dies with
an access violation inside FPDF_RenderPageBitmap. The evidence pane requests
the SI and draft BL pages together on every case open, which makes the
collision routine rather than rare.

Every in-process pdfium call takes this lock. The helper-process reader pool
is unaffected: each worker is a separate process with its own pdfium.
"""
import threading

PDFIUM_LOCK = threading.RLock()
