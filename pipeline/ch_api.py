"""
A small, polite Companies House REST API client.

Design goals, in order:

  1. Never exceed the published rate limit. The limit is 600 requests per
     rolling five minutes. Exceeding it gets the key throttled, which would
     invalidate a long overnight run halfway through.
  2. Be resumable. Every long pull writes to disk as it goes and can be
     restarted without repeating completed work.
  3. Be reproducible. Every response is cached on disk under a deterministic
     path, so a reviewer re-running the analysis gets the same bytes the
     published figures were computed from, and re-running costs nothing.

The cache is the important part for peer review. Companies House data changes
continuously -- a company dissolved today did not exist as "dissolved"
yesterday -- so an uncached pipeline is not reproducible even in principle.
The cache freezes the observation.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import pathlib
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import config

log = logging.getLogger("ch_api")

CACHE_DIR = config.DATA_RAW / "api_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


class RateLimiter:
    """A simple thread-safe token bucket.

    Companies House measures over a rolling five-minute window, so a plain
    per-second delay is sufficient and much easier to reason about than a
    sliding-window counter: 1.8 req/s sustained is 540 requests per five
    minutes, comfortably under the 600 limit with headroom for retries.
    """

    def __init__(self, per_second: float = config.CH_RATE_LIMIT_PER_SECOND):
        self.interval = 1.0 / per_second
        self._lock = threading.Lock()
        self._next_at = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            if now < self._next_at:
                time.sleep(self._next_at - now)
                now = time.monotonic()
            self._next_at = max(now, self._next_at) + self.interval


_limiter = RateLimiter()


class CompaniesHouseClient:
    """Cached, rate-limited GET access to the Companies House REST API."""

    def __init__(self, use_cache: bool = True):
        key = config.companies_house_key()
        # Companies House uses HTTP Basic auth with the key as the username
        # and an empty password.
        self._auth = base64.b64encode(f"{key}:".encode()).decode()
        self.use_cache = use_cache
        self.stats = {"cache_hits": 0, "requests": 0, "errors": 0, "not_found": 0}

    # -- cache -------------------------------------------------------------

    @staticmethod
    def _cache_path(path: str, params: dict | None) -> pathlib.Path:
        """Deterministic cache location for a request.

        Grouped into a two-level directory by the first path segment and a
        hash prefix, because a single directory holding 200,000 files is
        painful on Windows.
        """
        canonical = path + "?" + urllib.parse.urlencode(sorted((params or {}).items()))
        digest = hashlib.sha256(canonical.encode()).hexdigest()
        group = path.strip("/").split("/")[0] or "root"
        return CACHE_DIR / group / digest[:2] / f"{digest}.json"

    # -- request -----------------------------------------------------------

    def get(
        self,
        path: str,
        params: dict | None = None,
        *,
        max_retries: int = 10,
        allow_404: bool = True,
    ) -> dict | None:
        """GET a JSON endpoint. Returns None on 404 when `allow_404`.

        Retries on 429 (rate limited) and 5xx with exponential backoff. A 404
        is a real answer for this dataset -- not every company has charges or
        persons with significant control -- so it is cached like any other
        response rather than retried.
        """
        cache_file = self._cache_path(path, params)
        if self.use_cache and cache_file.exists():
            self.stats["cache_hits"] += 1
            raw = json.loads(cache_file.read_text(encoding="utf-8"))
            return None if raw.get("__not_found__") else raw

        url = config.CH_API_BASE + path
        if params:
            url += "?" + urllib.parse.urlencode(params)

        delay = 2.0
        for attempt in range(max_retries):
            _limiter.wait()
            req = urllib.request.Request(
                url,
                headers={
                    "Authorization": f"Basic {self._auth}",
                    "User-Agent": (
                        config.USER_AGENT
                    ),
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                self.stats["requests"] += 1
                if self.use_cache:
                    cache_file.parent.mkdir(parents=True, exist_ok=True)
                    cache_file.write_text(json.dumps(data), encoding="utf-8")
                return data

            except urllib.error.HTTPError as e:
                if e.code == 404 and allow_404:
                    self.stats["not_found"] += 1
                    if self.use_cache:
                        cache_file.parent.mkdir(parents=True, exist_ok=True)
                        cache_file.write_text(
                            json.dumps({"__not_found__": True}), encoding="utf-8"
                        )
                    return None
                if e.code == 429:
                    # Companies House does not always send Retry-After, and a
                    # sustained throttle can last minutes. Back off hard and be
                    # patient: on a batch of 60,000 companies, waiting ten
                    # minutes costs far less than abandoning the run.
                    retry_after = float(e.headers.get("Retry-After", delay))
                    log.warning("Rate limited on %s, sleeping %.0fs (attempt %d/%d)",
                                path, retry_after, attempt + 1, max_retries)
                    time.sleep(retry_after)
                    delay = min(delay * 2, 900)
                    continue
                if 500 <= e.code < 600:
                    log.warning("HTTP %s on %s, retry %d", e.code, path, attempt + 1)
                    time.sleep(delay)
                    delay = min(delay * 2, 60)
                    continue
                self.stats["errors"] += 1
                log.error("HTTP %s on %s", e.code, path)
                raise

            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
                log.warning("%s on %s, retry %d", type(e).__name__, path, attempt + 1)
                time.sleep(delay)
                delay = min(delay * 2, 60)

        self.stats["errors"] += 1
        raise RuntimeError(f"Giving up on {path} after {max_retries} attempts")

    # -- paging ------------------------------------------------------------

    def get_all_items(
        self, path: str, params: dict | None = None, page_size: int = 100
    ) -> list[dict]:
        """Follow `items_per_page` / `start_index` paging to exhaustion.

        Used for filing history and charges, both of which return an `items` array and a
        `total_results` count.
        """
        params = dict(params or {})
        params["items_per_page"] = page_size
        collected: list[dict] = []
        start = 0
        while True:
            params["start_index"] = start
            page = self.get(path, params)
            if not page:
                break
            items = page.get("items") or []
            collected.extend(items)
            total = page.get("total_results", page.get("total_count", len(collected)))
            start += page_size
            if start >= total or not items:
                break
            # Companies House caps deep paging on some endpoints; stop before
            # the server does rather than looping on repeated final pages.
            if start > 10_000:
                log.warning("Paging cap reached on %s at %d items", path, len(collected))
                break
        return collected

    # -- typed helpers -----------------------------------------------------

    def company_profile(self, number: str) -> dict | None:
        return self.get(f"/company/{number}")

    def filing_history(self, number: str) -> list[dict]:
        return self.get_all_items(f"/company/{number}/filing-history")

    def charges(self, number: str) -> list[dict]:
        return self.get_all_items(f"/company/{number}/charges")

    # Officer and person-with-significant-control endpoints are deliberately
    # not wrapped here. This study analyses companies and premises, not
    # individuals, and person-level linkage is out of scope by choice.

    def advanced_search(self, **params) -> dict | None:
        """Advanced company search.

        Useful parameters: `sic_codes`, `company_status`, `incorporated_from`,
        `incorporated_to`, `dissolved_from`, `dissolved_to`, `size`,
        `start_index`. The endpoint caps at 5,000 results per query, so
        callers must slice their query finely enough to stay under it --
        see scripts/02_cohort_dissolved.py for the slicing strategy.
        """
        return self.get("/advanced-search/companies", params)


def setup_logging(name: str) -> logging.Logger:
    """Consistent logging to stderr and to a per-script log file."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(config.OUT / f"{name}.log", encoding="utf-8"),
        ],
    )
    return logging.getLogger(name)
