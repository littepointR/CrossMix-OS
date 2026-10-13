#!/bin/sh
# Compatibility entry point: scripts are shipped in verified releases.
# Do not replace installed code with a mutable branch or third-party URL.
SDCARD_ROOT=${CROSSMIX_SDCARD_ROOT:-/mnt/SDCARD}
for script in update_common.sh update_ota_release.sh crossmix_update.sh; do
    if [ ! -s "$SDCARD_ROOT/System/usr/trimui/scripts/$script" ]; then
        echo "Missing $script. Reinstall the fork release using the migration guide." >&2
        exit 1
    fi
done
exit 0
