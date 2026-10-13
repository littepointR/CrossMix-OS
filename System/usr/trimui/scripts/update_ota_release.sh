#!/bin/sh
. "${CROSSMIX_SDCARD_ROOT:-/mnt/SDCARD}/System/usr/trimui/scripts/update_common.sh"
mkdir -p "$updatedir"
OTA_RESULT="$updatedir/ota_release_result"

get_release_info() {
    printf 'Retrieving release from %s...\n' "$GITHUB_REPOSITORY"
    crossmix_fetch_release
    local result=$?
    if [ "$result" -ne 0 ]; then
        rm -f "$updatedir/.CrossMixUpdateAvailable"
        if [ "$result" -eq 1 ]; then
            echo "No release available on $UPDATE_CHANNEL channel."
            echo "no release" > "$OTA_RESULT"
        else
            echo "Release metadata could not be downloaded or validated." >&2
            echo "download failed" > "$OTA_RESULT"
        fi
        return "$result"
    fi
    printf '\nInstalled: %s\nAvailable: %s\nRepository: %s\nChannel: %s\nArchive: %s (%s MiB)\nDate: %s\n\n' \
        "$Local_CrossMixVersion" "$Release_Tag" "$GITHUB_REPOSITORY" "$UPDATE_CHANNEL" "$Release_Name" "$Release_size_MB" "$Release_Date"
    crossmix_release_is_new || {
        rm -f "$updatedir/.CrossMixUpdateAvailable"
        echo "No newer release for this installation."
        echo "no release" > "$OTA_RESULT"
        return 1
    }
    touch "$updatedir/.CrossMixUpdateAvailable"
}

confirm_action() {
    local choice
    choice=$(printf 'No\nYes\n' | "$SDCARD_ROOT/System/usr/trimui/scripts/shellect.sh" -t "$1" -b "Press A to validate your choice.")
    [ "$choice" = "Yes" ]
}

main() {
    get_release_info || exit $?
    [ "$1" = "check" ] && exit 0
    if [ "$1" != "--download-only" ] && ! confirm_action "Download $Release_Tag ($Release_size_MB MiB)?"; then
        echo "user cancel" > "$OTA_RESULT"
        exit 0
    fi
    if ! crossmix_download_release; then
        echo "download failed" > "$OTA_RESULT"
        exit 2
    fi
    [ "$1" = "--download-only" ] && exit 0
    if ! confirm_action "Apply verified update $Release_Tag?"; then
        echo "user cancel" > "$OTA_RESULT"
        exit 0
    fi
    if ! crossmix_stage_release; then
        echo "download failed" > "$OTA_RESULT"
        exit 2
    fi
    echo "success" > "$OTA_RESULT"
    echo "Verified update staged. Rebooting to run installation..."
    sync
    sleep 5
    reboot
}

main "$@"
