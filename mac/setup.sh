#!/usr/bin/env bash
# Runs the whole feed, YouTube recommendations included, privately on this Mac:
#   build  every hour (and at login): build_shelf.py with this browser's YouTube cookies
#   serve  http://<this Mac>:8765/shelf.json on the home network, from a folder holding only the feed
#
#   mac/setup.sh install [BROWSER]   default BROWSER: chrome:Default (as yt-dlp names it)
#   mac/setup.sh uninstall
#   mac/setup.sh status
#
# Needs yt-dlp (brew install yt-dlp). The first run asks macOS for "Chrome Safe Storage";
# choose Always Allow so the hourly runs don't ask again. The Mac must be awake to serve.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
DATA="$HOME/Library/Application Support/tigris-shelf"
WWW="$DATA/www"
LOG="$HOME/Library/Logs/tigris-shelf.log"
AGENTS="$HOME/Library/LaunchAgents"
PORT=8765
BUILD=com.tigris-shelf.build
SERVE=com.tigris-shelf.serve

plist() {  # label, extra XML, program arguments...
  local label=$1; shift
  local extra=$1; shift
  {
    echo '<?xml version="1.0" encoding="UTF-8"?>'
    echo '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">'
    echo '<plist version="1.0"><dict>'
    echo "  <key>Label</key><string>$label</string>"
    echo '  <key>ProgramArguments</key><array>'
    for a in "$@"; do printf '    <string>%s</string>\n' "$a"; done
    echo '  </array>'
    echo '  <key>EnvironmentVariables</key><dict><key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string></dict>'
    echo "  <key>StandardOutPath</key><string>$LOG</string>"
    echo "  <key>StandardErrorPath</key><string>$LOG</string>"
    echo "$extra"
    echo '</dict></plist>'
  } > "$AGENTS/$label.plist"
}

reload() { launchctl bootout "gui/$(id -u)/$1" 2>/dev/null || true; launchctl bootstrap "gui/$(id -u)" "$AGENTS/$1.plist"; }

case "${1:-}" in
  install)
    BROWSER=${2:-chrome:Default}
    command -v yt-dlp >/dev/null || { echo "Install yt-dlp first: brew install yt-dlp" >&2; exit 1; }
    mkdir -p "$WWW" "$AGENTS" "$(dirname "$LOG")"
    plist "$BUILD" '  <key>StartInterval</key><integer>3600</integer><key>RunAtLoad</key><true/>' \
      /usr/bin/python3 -I "$REPO/build_shelf.py" --out "$WWW/shelf.json" --youtube-cookies "$BROWSER"
    plist "$SERVE" '  <key>KeepAlive</key><true/><key>RunAtLoad</key><true/>' \
      /usr/bin/python3 -m http.server "$PORT" --bind 0.0.0.0 --directory "$WWW"
    reload "$BUILD"; reload "$SERVE"
    ip=$(ipconfig getifaddr en0 || ipconfig getifaddr en1 || echo "<this Mac's IP>")
    echo "Feed: http://$ip:$PORT/shelf.json  (log: $LOG)"
    echo "Give the Mac a fixed address in the router (DHCP reservation) so the TV's setting keeps working."
    ;;
  uninstall)
    for l in "$BUILD" "$SERVE"; do launchctl bootout "gui/$(id -u)/$l" 2>/dev/null || true; rm -f "$AGENTS/$l.plist"; done
    echo "Stopped. The feed folder is left at $DATA; delete it to remove the cached recommendations."
    ;;
  status)
    launchctl print "gui/$(id -u)/$BUILD" 2>/dev/null | grep -E "state|last exit" || echo "$BUILD not loaded"
    launchctl print "gui/$(id -u)/$SERVE" 2>/dev/null | grep -E "state|last exit" || echo "$SERVE not loaded"
    tail -5 "$LOG" 2>/dev/null || true
    ;;
  *) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
