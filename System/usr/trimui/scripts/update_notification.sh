#!/bin/sh
# Boot-time checker shares the interactive client's repository, channel and manifest.
. "${CROSSMIX_SDCARD_ROOT:-/mnt/SDCARD}/System/usr/trimui/scripts/update_common.sh"

LOG_FILE="$SDCARD_ROOT/System/logs/update_check.log"
RELEASE_META="$updatedir/available_release.json"
STAMP_FILE="$updatedir/update_check_last_run.txt"
mkdir -p "$updatedir" "$(dirname "$LOG_FILE")"

log() { printf '%s - %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG_FILE"; }

main() {
    crossmix_load_settings || exit 2
    TODAY="$(date +%Y-%m-%d) $GITHUB_REPOSITORY $UPDATE_CHANNEL"
    if [ "$1" != "--force" ] && [ "$(cat "$STAMP_FILE" 2>/dev/null)" = "$TODAY" ]; then exit 0; fi
    if [ -z "$(ip route get 1 2>/dev/null | awk '/src/ {print $NF; exit}')" ]; then
        log "No IP; skipping update check."
        exit 1
    fi
    # All fork fixes arrive through a validated release on the chosen channel.
    rm -f "$updatedir/available_hotfix.json"
    if ! crossmix_fetch_release || ! crossmix_release_is_new; then
        rm -f "$RELEASE_META" "$updatedir/.CrossMixUpdateAvailable"
        log "No validated newer release on $GITHUB_REPOSITORY ($UPDATE_CHANNEL)."
        exit 1
    fi
    jq --arg repo "$GITHUB_REPOSITORY" --arg channel "$UPDATE_CHANNEL" --arg name "$Release_Name" \
        --arg url "https://github.com/$GITHUB_REPOSITORY/releases/tag/$Release_Tag" --argjson size "$Release_size" \
        '{name: $name, url: $url, size: $size, created_at: .published_at,
          tag: .tag_name, repository: $repo, channel: $channel}' "$Release_JSON" > "$RELEASE_META.tmp" || exit 2
    mv "$RELEASE_META.tmp" "$RELEASE_META"
    printf '%s\n' "$TODAY" > "$STAMP_FILE"
    touch "$updatedir/.CrossMixUpdateAvailable"
    log "Update available: $Local_CrossMixVersion -> $Release_Tag ($UPDATE_CHANNEL)."
    if [ -d /tmp/trimui_osd ]; then
        jq -nc --arg message "CrossMix $Release_Tag available ($UPDATE_CHANNEL)." \
            '{type:"info",size:2,duration:5000,x:670,y:640,message:$message,icon:""}' > /tmp/trimui_osd/osd_toast_msg
    fi
    sync
}

main "$@"
