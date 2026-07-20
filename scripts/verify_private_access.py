#!/usr/bin/env python3
"""Verify that the private dashboard URL is not anonymously accessible."""
from __future__ import annotations

import argparse
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_URL = "https://command.vaelinya.uk/private/project-status-engine/"
REDIRECT_STATUSES = {301, 302, 303, 307, 308}
BLOCK_STATUSES = {401, 403}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


def access_is_blocked(status: int, location: str, requested_url: str) -> bool:
    if status in BLOCK_STATUSES:
        return True
    if status not in REDIRECT_STATUSES or not location:
        return False
    target = urllib.parse.urljoin(requested_url, location)
    requested = urllib.parse.urlsplit(requested_url)
    redirected = urllib.parse.urlsplit(target)
    if not redirected.scheme.startswith("http") or not redirected.netloc:
        return False
    # Cloudflare Access redirects away from the protected application origin.
    return redirected.netloc.lower() != requested.netloc.lower()


def verify(url: str = DEFAULT_URL) -> tuple[int, str]:
    opener = urllib.request.build_opener(NoRedirect)
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "text/html",
            "User-Agent": "project-status-engine-access-check",
        },
    )
    try:
        response = opener.open(request, timeout=30)
        status = response.status
        location = response.headers.get("Location", "")
    except urllib.error.HTTPError as exc:
        status = exc.code
        location = exc.headers.get("Location", "")
    if not access_is_blocked(status, location, url):
        raise RuntimeError(
            f"private URL did not present an anonymous access boundary: status={status}"
        )
    return status, location


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("url", nargs="?", default=DEFAULT_URL)
    args = parser.parse_args()
    status, location = verify(args.url)
    suffix = f" redirect={location}" if location else ""
    print(f"Anonymous private-dashboard request blocked: status={status}{suffix}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
