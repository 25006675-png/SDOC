"""Concurrent page renders must not corrupt pdfium.

pdfium is not thread-safe. Before the lock, rendering the SI and draft BL
pages at the same time -- which the evidence pane does on every case open --
produced garbled glyphs or killed the process with an access violation inside
FPDF_RenderPageBitmap.
"""
import hashlib
import pathlib
import unittest
from concurrent.futures import ThreadPoolExecutor

from sdoc.api import _render_pdf_page

ATTACHMENTS = pathlib.Path(__file__).resolve().parents[1] / "demo-data" / "attachments"
DOCS = [ATTACHMENTS / "demo_003_SI.pdf", ATTACHMENTS / "demo_003_BL.pdf"]


def digest(path, scale):
    png, _, _ = _render_pdf_page.__wrapped__(str(path), path.stat().st_mtime_ns, 1, scale)
    return hashlib.sha256(png).hexdigest()


@unittest.skipUnless(all(p.exists() for p in DOCS), "demo PDFs not present")
class TestConcurrentRender(unittest.TestCase):
    def test_parallel_renders_match_sequential_renders(self):
        # Bypass the cache so every call really reaches pdfium.
        expected = {path: digest(path, 3.0) for path in DOCS}
        jobs = DOCS * 12
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda p: (p, digest(p, 3.0)), jobs))
        mismatched = [str(p.name) for p, h in results if h != expected[p]]
        self.assertEqual(mismatched, [], "concurrent renders diverged from sequential ones")

    def test_rendering_is_cached_by_modification_time(self):
        _render_pdf_page.cache_clear()
        path = DOCS[0]
        mtime = path.stat().st_mtime_ns
        _render_pdf_page(str(path), mtime, 1, 2.0)
        _render_pdf_page(str(path), mtime, 1, 2.0)
        self.assertEqual(_render_pdf_page.cache_info().hits, 1)


if __name__ == "__main__":
    unittest.main()
