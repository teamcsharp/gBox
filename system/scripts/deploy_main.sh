#!/usr/bin/env bash
# Deploy merged main onto the Spark's canonical copy (~/gBox/system) and refresh the service when it is safe.
#
#   deploy_main.sh            sync what main changed; restart only if runtime code changed and the runtime is idle
#   deploy_main.sh --no-restart
#
# Why: Hermes publishes PRs from worktrees and the operator merges them, but the Spark runs from a plain copy of
# the repository (no .git on the share), so merged work stayed undeployed until someone copied files by hand.
# Cron runs this every 15 minutes (see install below). Everything it overwrites is backed up first under
# gbox-data/deploy-backups/<stamp>-<commit>/, text files are written CRLF like the rest of the share, and
# the restart goes through the same idle check the bootstrap uses (gbox.hermes_activation --check-idle) with
# Hermes dispatch paused meanwhile so the idle window actually arrives. Runtime code = gbox/, adapters/,
# hermes/, profiles/, gbox.toml, pyproject.toml; client and doc changes are live without a restart.
#
# Install (once, on the Spark):   crontab -l | { cat; echo '*/15 * * * * $HOME/gBox/system/scripts/deploy_main.sh >> $HOME/gbox-deploy.log 2>&1'; } | crontab -
set -euo pipefail
REPO_URL="https://github.com/teamcsharp/gBox.git"
SRC="${GBOX_SRC:-$HOME/gBox-src}"
DST="${GBOX_DST:-$HOME/gBox/system}"
STATE="$DST/gbox-data/deployed-main.txt"
LOCK="/tmp/gbox-deploy.lock"
MIN_RESTART_GAP=$((2 * 3600))           # seconds between service restarts caused by deploys
IDLE_WAIT=$((45 * 60))                  # how long to wait for an idle window before giving up this round
RESTART="${1:-}"

exec 9>"$LOCK"
flock -n 9 || { echo "$(date -u +%FT%TZ) another deploy is running"; exit 0; }
log() { echo "$(date -u +%FT%TZ) $*"; }

if [ ! -d "$SRC/.git" ]; then
  git clone -q "$REPO_URL" "$SRC"
fi
git -C "$SRC" fetch -q origin main
git -C "$SRC" reset -q --hard origin/main
HEAD="$(git -C "$SRC" rev-parse HEAD)"
PREV="$(cat "$STATE" 2>/dev/null || true)"
if [ "$HEAD" = "$PREV" ]; then
  exit 0
fi

# Files to deploy: everything tracked under system/ that differs from the share (ignoring line endings).
# A share file that differs from BOTH the new main and the previously deployed main was edited on the share by
# someone else since the last deploy (the share has no .git): it is left alone and logged, never overwritten,
# until that edit reaches main. With no previous deploy recorded, only files identical to some main version are
# safe to replace, so a first run also skips files that differ from the new main and from HEAD~50..HEAD.
changed=(); kept=()
share_edited() {                                   # $1 = rel path: does the share copy match any known main version?
  local rel="$1" dst="$DST/$1" ref
  if [ -n "$PREV" ]; then
    git -C "$SRC" show "$PREV:system/$rel" 2>/dev/null | diff -q --strip-trailing-cr - "$dst" >/dev/null 2>&1 && return 1
    return 0
  fi
  for ref in $(git -C "$SRC" rev-list --max-count=50 HEAD -- "system/$rel"); do
    git -C "$SRC" show "$ref:system/$rel" 2>/dev/null | diff -q --strip-trailing-cr - "$dst" >/dev/null 2>&1 && return 1
  done
  return 0
}
while IFS= read -r f; do
  rel="${f#system/}"
  src="$SRC/system/$rel"
  dst="$DST/$rel"
  if [ ! -f "$dst" ]; then
    changed+=("$rel")
  elif ! diff -q --strip-trailing-cr "$src" "$dst" >/dev/null 2>&1; then
    if share_edited "$rel"; then kept+=("$rel"); else changed+=("$rel"); fi
  fi
done < <(git -C "$SRC" ls-files system)
if [ "${#kept[@]}" -gt 0 ]; then
  log "share-side edits kept, not on main yet (commit them to main to deploy): ${kept[*]}"
fi

if [ "${#changed[@]}" -eq 0 ]; then
  log "main $HEAD: share already matches"
  echo "$HEAD" > "$STATE"
  exit 0
fi

STAMP="$(date -u +%Y%m%d-%H%M%S)-${HEAD:0:7}"
BACKUP="$DST/gbox-data/deploy-backups/$STAMP"
runtime=0
for rel in "${changed[@]}"; do
  src="$SRC/system/$rel"; dst="$DST/$rel"
  if [ -f "$dst" ]; then
    mkdir -p "$BACKUP/$(dirname "$rel")"
    cp -p "$dst" "$BACKUP/$rel"
  fi
  mkdir -p "$(dirname "$dst")"
  case "$rel" in
    *.py|*.html|*.md|*.js|*.cjs|*.mjs|*.json|*.toml|*.txt|*.sh|*.ps1|*.css)
      # the share is CRLF; keep a file's existing convention, default CRLF for new files
      if [ -f "$dst" ] && ! grep -q $'\r' "$dst"; then cp "$src" "$dst"; else sed 's/\r$//; s/$/\r/' "$src" > "$dst"; fi ;;
    *) cp "$src" "$dst" ;;
  esac
  case "$rel" in gbox/*|adapters/*|hermes/*|profiles/*|gbox.toml|pyproject.toml) runtime=1 ;; esac
done
log "main $HEAD: deployed ${#changed[@]} file(s) (backup $BACKUP): ${changed[*]}"
echo "$HEAD" > "$STATE"

[ "$runtime" -eq 1 ] || { log "no runtime code changed; no restart needed"; exit 0; }
[ "$RESTART" = "--no-restart" ] && { log "runtime code changed; restart skipped (--no-restart)"; exit 0; }

LAST_RESTART="$(systemctl show gbox.service -p ActiveEnterTimestampMonotonic --value 2>/dev/null || echo 0)"
UP_NOW="$(awk '{print int($1*1000000)}' /proc/uptime)"
if [ -n "$LAST_RESTART" ] && [ "$LAST_RESTART" -gt 0 ] && [ $(( (UP_NOW - LAST_RESTART) / 1000000 )) -lt "$MIN_RESTART_GAP" ]; then
  log "runtime code changed; last restart was under $((MIN_RESTART_GAP / 60)) min ago, trying again next round"
  echo "$PREV" > "$STATE"              # keep this commit pending so the next round retries the restart
  exit 0
fi

cd "$DST"
PY="$DST/.venv-linux-$(uname -m)/bin/python"
T="$(cat "$DST/gbox-data/api_token")"; H="Authorization: Bearer $T"; C="Content-Type: application/json"
API="http://127.0.0.1:8765/api/hermes/task-mode"
was_enabled="$(curl -s -H "$H" "$API" | "$PY" -c 'import sys,json; print(json.load(sys.stdin).get("enabled"))' 2>/dev/null || echo unknown)"
resume() { [ "$was_enabled" = "True" ] && curl -s -X POST -H "$H" -H "$C" -d '{"enabled":true}' "$API" >/dev/null || true; }
trap resume EXIT
if [ "$was_enabled" = "True" ]; then
  curl -s -X POST -H "$H" -H "$C" -d '{"enabled":false}' "$API" >/dev/null && log "Hermes dispatch paused for the restart"
fi
deadline=$(( $(date +%s) + IDLE_WAIT ))
until "$PY" -m gbox.hermes_activation --check-idle "$DST" >/dev/null; do
  if [ "$(date +%s)" -ge "$deadline" ]; then
    log "no idle window in $((IDLE_WAIT / 60)) min; restart deferred to the next round"
    echo "$PREV" > "$STATE"
    exit 0
  fi
  sleep 60
done
sudo -n systemctl restart gbox.service
sleep 6
if curl -sf http://127.0.0.1:8765/api/health >/dev/null; then
  log "gbox.service restarted on main $HEAD; healthy"
  echo "$HEAD" > "$STATE"
else
  log "gbox.service restarted but /api/health did not answer; check journalctl -u gbox"
fi
