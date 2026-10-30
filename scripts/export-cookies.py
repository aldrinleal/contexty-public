#!/usr/bin/env python3
"""Exports YouTube cookies from a local browser into a Netscape-format
cookies.txt, via the `browser_cookie3` package — an alternative to manually
exporting via a browser extension (see README.md's "Cookies" section).

Local-machine-only, same as `--cookies-from-browser` (main.py): reads a real
browser's cookie jar off disk, so it only makes sense to run this on your own
machine, not the deployed server. The output cookies.txt is what actually
gets shipped to the server, via:

    pip install browser_cookie3   # not in Pipfile — dev-machine-only tool
    python scripts/export-cookies.py --browser edge
    make upload-cookies ARGS="cookies.txt"

Close the browser first if the cookie database read fails — some browsers
(Chrome/Edge included) lock their cookie sqlite file while running.
"""

import argparse
import http.cookiejar
import sys

try:
    import browser_cookie3
except ImportError:
    print(
        "error: browser_cookie3 not installed — pip install browser_cookie3",
        file=sys.stderr,
    )
    sys.exit(1)

BROWSERS = {
    "edge": browser_cookie3.edge,
    "chrome": browser_cookie3.chrome,
    "chromium": browser_cookie3.chromium,
    "brave": browser_cookie3.brave,
    "firefox": browser_cookie3.firefox,
    "opera": browser_cookie3.opera,
    "safari": browser_cookie3.safari,
    "vivaldi": browser_cookie3.vivaldi,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--browser", default="edge", choices=sorted(BROWSERS), help="default: edge"
    )
    parser.add_argument(
        "--domain",
        default="youtube.com",
        help="cookie domain filter (default: youtube.com; pass '' for every domain)",
    )
    parser.add_argument("-o", "--output", default="cookies.txt")
    args = parser.parse_args(argv)

    load = BROWSERS[args.browser]
    try:
        src_jar = load(domain_name=args.domain)
    except Exception as exc:  # browser_cookie3 raises varied, browser-specific errors
        print(
            f"error: could not read cookies from {args.browser}: {exc}", file=sys.stderr
        )
        print(
            "(close the browser first — it may be locking the cookie database)",
            file=sys.stderr,
        )
        return 1

    count = len(src_jar)
    if count == 0:
        print(
            f"no cookies found for domain {args.domain!r} in {args.browser} "
            "— are you logged into YouTube there?",
            file=sys.stderr,
        )
        return 1

    # MozillaCookieJar.save() is what actually writes Netscape format —
    # browser_cookie3's own jar doesn't know how to serialize itself.
    out_jar = http.cookiejar.MozillaCookieJar(args.output)
    for cookie in src_jar:
        out_jar.set_cookie(cookie)
    out_jar.save(ignore_discard=True, ignore_expires=True)

    print(f"wrote {count} cookies -> {args.output}")
    print(f'next: make upload-cookies ARGS="{args.output}"')
    return 0


if __name__ == "__main__":
    sys.exit(main())
