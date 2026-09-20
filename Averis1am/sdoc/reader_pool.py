"""Reusable helper-process document reading.

Option A from the v2 addendum: protect the main process from parser crashes and
hangs by running document extraction in a disposable helper process with a
per-document wall-clock timeout. This is not a security sandbox; it is crash and
freeze containment.
"""
from __future__ import annotations

import json
import multiprocessing as mp
import time
import threading
from multiprocessing.context import TimeoutError as MpTimeoutError


class ReaderTimeoutError(RuntimeError):
    pass


class ReaderCrashError(RuntimeError):
    pass


def _plain(value):
    try:
        json.dumps(value)
        return value
    except TypeError:
        return None


def plain_reader_cfg(cfg):
    """Drop callables/clients before sending config to a helper process."""
    cfg = dict(cfg or {})
    blocked = {"reader_pool", "verifier", "llm_extractor", "ai_email_classifier"}
    out = {}
    for key, value in cfg.items():
        if key in blocked:
            continue
        clean = _plain(value)
        if clean is not None:
            out[key] = clean
    return out


def _extract_task(data, att_path, cfg, problems=None):
    if cfg.get("_test_sleep_seconds"):
        time.sleep(float(cfg["_test_sleep_seconds"]))
    from .extractors import extract_document
    return extract_document(data, att_path, cfg, problems=problems)


class ReaderPool:
    def __init__(self, workers=2, timeout=8):
        self.workers = max(1, int(workers or 1))
        self.timeout = max(1, float(timeout or 8))
        self._pool = None
        self._lock = threading.Lock()

    def _ensure_pool(self):
        if self._pool is None:
            ctx = mp.get_context("spawn")
            self._pool = ctx.Pool(processes=self.workers)

    def close(self):
        with self._lock:
            if self._pool is not None:
                self._pool.close()
                self._pool.join()
                self._pool = None

    def terminate(self):
        if self._pool is not None:
            self._pool.terminate()
            self._pool.join()
            self._pool = None

    def extract(self, data, att_path, cfg=None, problems=None):
        safe_cfg = plain_reader_cfg(cfg)
        with self._lock:
            self._ensure_pool()
            result = self._pool.apply_async(_extract_task, (data, att_path, safe_cfg, problems))
            try:
                return result.get(timeout=self.timeout)
            except MpTimeoutError as exc:
                self.terminate()
                raise ReaderTimeoutError(f"document reader timed out after {self.timeout:g}s: {att_path}") from exc
            except Exception as exc:
                self.terminate()
                raise ReaderCrashError(f"document reader helper failed for {att_path}: {exc}") from exc

    def __enter__(self):
        self._ensure_pool()
        return self

    def __exit__(self, *_):
        self.close()
