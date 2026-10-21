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
# hermes/, profiles/, gbox.toml, pyproject.toml; client and doc changes are live without a restart. A share file
# whose content (line endings ignored) matches no version of that path in main's last 200 commits was edited on the
# share by someone else: it is kept and logged, never overwritten, until that edit reaches main. A share file equal
# to any older main version is a stale copy and is overwritten (with the usual backup). A deferred restart is remembered in
# gbox-data/deploy-restart-pending and retried on later rounds even when no further file changes.
#
# Install (once, on the Spark):   crontab -l | { cat; echo '*/15 * * * * $HOME/bin/deploy_main.sh >> $HOME/gBox_alt/logs/gbox-deploy.log 2>&1'; } | crontab -
set -euo pipefail
REPO_URL="https://github.com/teamcsharp/gBox.git"
SRC="${GBOX_SRC:-$HOME/gBox_alt/gBox-src}"         # the deploy clone lives in ~/gBox_alt (out of the home root)
[ -n "${GBOX_SRC:-}" ] || [ -d "$SRC/.git" ] || [ ! -d "$HOME/gBox-src/.git" ] || SRC="$HOME/gBox-src"   # not moved yet
DST="${GBOX_DST:-$HOME/gBox/system}"
STATE="$DST/gbox-data/deployed-main.txt"
PENDING="$DST/gbox-data/deploy-restart-pending"    # runtime code was deployed but the service has not been refreshed yet
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
if [ "$HEAD" = "$PREV" ] && [ ! -f "$PENDING" ]; then
  exit 0
fi

runtime=0
if [ -f "$PENDING" ]; then
  runtime=1
fi

# Files to deploy: everything tracked under system/ that differs from the share (ignoring line endings).
# A differing share file is a genuine share-side edit only when its CR-stripped content matches NO version of that
# path in main's recent history. Comparing only with the previously deployed main kept stale copies of OLDER main
# commits as "edits" whenever a share copy fell behind (gbox/characters.py sat at main 90433ea for 18 hours, hiding
# a /api/characters fix and every reader registered after it); a copy of any earlier main version is now overwritten.
HISTORY_DEPTH="${GBOX_DEPLOY_HISTORY:-200}"        # main commits touching a path that count as "known versions"
changed=(); kept=(); stale=()
share_edited() {                                   # $1 = rel path: 0 = genuine share edit (keep), 1 = a main version
  local rel="$1" dst="$DST/$1" have commit blob seen=" "
  have="$(tr -d '\r' < "$dst" | git -C "$SRC" hash-object --stdin)"
  while IFS= read -r commit; do
    blob="$(git -C "$SRC" rev-parse -q --verify "$commit:system/$rel" 2>/dev/null)" || continue   # deleted there
    case "$seen" in *" $blob "*) continue ;; esac
    seen="$seen$blob "
    if [ "$(git -C "$SRC" cat-file blob "$blob" | tr -d '\r' | git -C "$SRC" hash-object --stdin)" = "$have" ]; then
      GUARD_RULE="stale copy of main ${commit:0:7}"
      return 1
    fi
  done < <(git -C "$SRC" log --max-count="$HISTORY_DEPTH" --format=%H HEAD -- "system/$rel")
  GUARD_RULE="share edit: matches none of the last $HISTORY_DEPTH main versions of this path"
  return 0
}
classify() {                                       # $1 = rel path -> ACTION new|same|stale|edit, GUARD_RULE says why
  local rel="$1" src="$SRC/system/$1" dst="$DST/$1"
  GUARD_RULE=""
  if [ ! -f "$dst" ]; then
    ACTION=new; GUARD_RULE="not on the share yet"
  elif diff -q --strip-trailing-cr "$src" "$dst" >/dev/null 2>&1; then
    ACTION=same
  elif share_edited "$rel"; then
    ACTION=edit
    # a share-side edit of a Python module that does not even compile is a broken edit, not work to keep: main's
    # version replaces it (backed up) - 2026-10-19 a Hermes run left gbox/toohuman_inventory.py mis-indented there
    if [ "${rel%.py}" != "$rel" ] && ! python3 -c 'import sys; compile(open(sys.argv[1], "rb").read(), sys.argv[1], "exec")' "$dst" 2>/dev/null; then
      ACTION=stale; GUARD_RULE="share edit does not compile"
    fi
  else
    ACTION=stale
  fi
}
if [ "$HEAD" != "$PREV" ]; then
  while IFS= read -r f; do
    rel="${f#system/}"
    classify "$rel"
    case "$ACTION" in
      new) changed+=("$rel") ;;
      stale) changed+=("$rel"); stale+=("$rel ($GUARD_RULE)") ;;
      edit) kept+=("$rel") ;;
    esac
  done < <(git -C "$SRC" ls-files system)
  if [ "${#stale[@]}" -gt 0 ]; then
    log "rule 'older main version': stale share copies overwritten (backed up): ${stale[*]}"
  fi
  if [ "${#kept[@]}" -gt 0 ]; then
    log "rule 'share edit' (matches no version in the last $HISTORY_DEPTH main commits of the path): kept, not on main yet (commit them to main to deploy): ${kept[*]}"
  fi
fi

if [ "${#changed[@]}" -gt 0 ]; then
  STAMP="$(date -u +%Y%m%d-%H%M%S)-${HEAD:0:7}"
  BACKUP="$DST/gbox-data/deploy-backups/$STAMP"
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
elif [ "$HEAD" != "$PREV" ]; then
  log "main $HEAD: share already matches"
fi
echo "$HEAD" > "$STATE"

[ "$runtime" -eq 1 ] || { log "no runtime code changed; no restart needed"; exit 0; }
if [ "$RESTART" = "--no-restart" ]; then
  touch "$PENDING"
  log "runtime code changed; restart skipped (--no-restart), remembered for the next round"
  exit 0
fi

LAST_RESTART="$(systemctl show gbox.service -p ActiveEnterTimestampMonotonic --value 2>/dev/null || echo 0)"
UP_NOW="$(awk '{print int($1*1000000)}' /proc/uptime)"
if [ -n "$LAST_RESTART" ] && [ "$LAST_RESTART" -gt 0 ] && [ $(( (UP_NOW - LAST_RESTART) / 1000000 )) -lt "$MIN_RESTART_GAP" ]; then
  touch "$PENDING"
  log "runtime code changed; last restart was under $((MIN_RESTART_GAP / 60)) min ago, trying again next round"
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
    touch "$PENDING"
    log "no idle window in $((IDLE_WAIT / 60)) min; restart deferred to the next round"
    exit 0
  fi
  sleep 60
done
sudo -n systemctl restart gbox.service
sleep 6
if curl -sf http://127.0.0.1:8765/api/health >/dev/null; then
  rm -f "$PENDING"
  log "gbox.service restarted on main $HEAD; healthy"
else
  log "gbox.service restarted but /api/health did not answer; check journalctl -u gbox"
fi
