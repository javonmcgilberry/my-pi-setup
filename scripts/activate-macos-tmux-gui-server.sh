#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
label="com.javonmcgilberry.pi-tmux-gui-server"
plist="${HOME}/Library/LaunchAgents/${label}.plist"
domain="gui/$(id -u)"
auto=false

if [[ "${1:-}" == "--auto" ]]; then
  auto=true
  shift
fi
if (($#)); then
  echo "Usage: $0 [--auto]" >&2
  exit 2
fi

defer_or_fail() {
  local auto_message="$1"
  local failure_message="$2"
  if "$auto"; then
    echo "macOS tmux activation deferred: $auto_message"
    echo "The LaunchAgent will start the GUI-owned server automatically at the next macOS login."
    exit 0
  fi
  printf '%s\n' "$failure_message" >&2
  exit 1
}

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This activation helper is only for macOS." >&2
  exit 1
fi

if [[ -n "${TMUX:-}" || -n "${SSH_CLIENT:-}" || -n "${SSH_CONNECTION:-}" || -n "${SSH_TTY:-}" || -n "${MOSH_IP:-}" || -n "${MOSH_CONNECTION:-}" ]]; then
  defer_or_fail \
    "setup is running from tmux, SSH, or Mosh." \
    $'Refusing to activate from tmux, SSH, or Mosh.\nOpen a normal local macOS Terminal or Warp tab, close all default-server tmux\nsessions, and run this helper there. No password is required.'
fi

if ! security show-keychain-info "${HOME}/Library/Keychains/login.keychain-db" >/dev/null 2>&1; then
  defer_or_fail \
    "the login Keychain is not available to this shell." \
    $'The login Keychain is not available to this shell. Run this helper from the\nlogged-in Mac\'s local Terminal or Warp app, not a sanitized remote shell.'
fi

if [[ ! -f "$plist" || -L "$plist" ]]; then
  echo "Managed LaunchAgent is not installed at $plist. Run ./setup.sh first." >&2
  exit 1
fi

if ! cmp -s "$repo_dir/config/${label}.plist" "$plist"; then
  echo "Installed LaunchAgent differs from this checkout. Run ./setup.sh first." >&2
  exit 1
fi

existing_sessions="$(tmux list-sessions -F '#{session_name}' 2>/dev/null || true)"
if [[ -n "$existing_sessions" ]]; then
  defer_or_fail \
    "the default tmux server still has sessions." \
    $'The default tmux server still has sessions. Close them before activation; this\nhelper never kills active Moshi or tmux sessions for you.'
fi

# A sessionless server may be the old SSH-owned server with exit-empty disabled.
# It is safe to replace because no tmux sessions remain.
tmux kill-server >/dev/null 2>&1 || true
launchctl bootout "$domain/$label" >/dev/null 2>&1 || true
launchctl bootstrap "$domain" "$plist"
launchctl kickstart -k "$domain/$label"

for _attempt in {1..40}; do
  if [[ "$(tmux show-options -g -v exit-empty 2>/dev/null || true)" == "off" ]]; then
    echo "Activated GUI-owned default tmux server for Moshi and local tmux clients."
    echo "Run 'moshi .' normally; its directory session naming and attach behavior are unchanged."
    exit 0
  fi
  sleep 0.1
done

echo "LaunchAgent loaded, but the default tmux server did not become ready." >&2
exit 1
