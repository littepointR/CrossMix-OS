#!/bin/sh
. "${CROSSMIX_SDCARD_ROOT:-/mnt/SDCARD}/System/usr/trimui/scripts/update_common.sh"

main() {
    crossmix_load_settings || exit 2
    mkdir -p "$updatedir"
    choice=$(printf 'Stable\nPrerelease (device tests)\nCancel\n' | \
        "$SDCARD_ROOT/System/usr/trimui/scripts/shellect.sh" -t "Update channel (current: $UPDATE_CHANNEL)" \
        -b "Prereleases require device testing. Press A to choose.")
    case "$choice" in
        Stable) echo stable > "$updatedir/ota_channel.txt" ;;
        "Prerelease (device tests)") echo prerelease > "$updatedir/ota_channel.txt" ;;
        *) exit 0 ;;
    esac
    # Execute only the updater included with this installation.
    printf '\n%s\n' "$timestamp" >> "$updatedir/ota_release.log"
    sh "$SDCARD_ROOT/System/usr/trimui/scripts/update_ota_release.sh" 2>&1 | tee -a "$updatedir/ota_release.log"
    printf '\nPress A to exit.\n'
    read -r -n 1 answer
    killall -2 SimpleTerminal
}

main "$@"
