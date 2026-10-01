"""
Fetch filed documents from the Companies House Document API.

The document endpoint answers with a 302 redirect to a pre-signed S3 URL. The
redirect must be followed WITHOUT the Companies House Authorization header --
S3 rejects a request carrying someone else's credentials, and Python's default
redirect handling re-sends every header it was given. Hence the custom opener
below, which is the whole reason this module exists.

Accounts are requested as `application/xhtml+xml`, which returns the iXBRL a
company actually filed. Where a filing predates iXBRL or was submitted on
paper, only `application/pdf` is available and the caller is told so rather
than being handed a silently empty result.
"""

from __future__ import annotations

import urllib.error
import urllib.request

import config
from ch_api import _limiter


class _NoAuthRedirect(urllib.request.HTTPRedirectHandler):
    """Follow redirects, but drop the Authorization header on the way."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None:
            new.headers = {
                k: v for k, v in new.headers.items() if k.lower() != "authorization"
            }
        return new


_opener = urllib.request.build_opener(_NoAuthRedirect)


def fetch_document(
    document_id: str,
    auth: str,
    content_type: str = "application/xhtml+xml",
    max_retries: int = 3,
) -> bytes | None:
    """Return the raw bytes of a filed document, or None if unavailable.

    Returns None rather than raising for anything the caller can do nothing
    about: a format that was never filed (404/406), and older documents that
    the archive answers with a 500. Those 500s are consistent per document, not
    transient -- some pre-2012 filings simply cannot be served -- so a failed
    fetch must not abort a run over thirty documents.
    """
    import time

    url = f"{config.CH_DOC_API_BASE}/document/{document_id}/content"
    for attempt in range(max_retries):
        _limiter.wait()
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Basic {auth}",
                "Accept": content_type,
                "User-Agent": (
                    config.USER_AGENT
                ),
            },
        )
        try:
            with _opener.open(req, timeout=120) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code in (404, 406, 500):
                return None
            if e.code == 429:
                time.sleep(float(e.headers.get("Retry-After", 30)))
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == max_retries - 1:
                return None
            time.sleep(5 * (attempt + 1))
    return None
