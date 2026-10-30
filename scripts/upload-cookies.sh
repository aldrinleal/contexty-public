#!/usr/bin/env bash
# Uploads a cookies.txt file to a deployed contexty's PUT /cookies endpoint
# (app/api.py) — the one-command way to refresh YouTube auth from any
# already-logged-in machine, without SSH/redeploy.
#
# Getting a cookies.txt in the first place is a manual, out-of-band step:
# export one from a logged-in browser session via a "Get cookies.txt
# LOCALLY"-style extension (Netscape format). This script only handles
# getting that already-exported file onto the server.
#
# Usage:
#   scripts/upload-cookies.sh [cookies.txt] [--url URL] [--token TOKEN]
#
# URL and TOKEN default to $CONTEXTY_URL / $CONTEXTY_API_TOKEN if set.

set -euo pipefail

cookies_file="cookies.txt"
url="${CONTEXTY_URL:-http://localhost:8000}"
token="${CONTEXTY_API_TOKEN:-}"

while [ $# -gt 0 ]; do
  case "$1" in
    --url)
      url="$2"
      shift 2
      ;;
    --token)
      token="$2"
      shift 2
      ;;
    -h|--help)
      grep '^#' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      cookies_file="$1"
      shift
      ;;
  esac
done

if [ ! -s "$cookies_file" ]; then
  echo "error: $cookies_file doesn't exist or is empty" >&2
  exit 1
fi

if [ -z "$token" ]; then
  echo "error: no API token — pass --token or set \$CONTEXTY_API_TOKEN" >&2
  exit 1
fi

echo "uploading $cookies_file (-> $url/cookies)..." >&2
curl -fsS -X PUT \
  --data-binary "@${cookies_file}" \
  -H "Authorization: Bearer ${token}" \
  -H "Content-Type: text/plain" \
  "${url}/cookies"
echo
