#!/bin/sh
# Set PATH and library path
PATH="/mnt/SDCARD/System/bin:/mnt/SDCARD/System/usr/trimui/scripts/:$PATH"
export LD_LIBRARY_PATH="/mnt/SDCARD/System/lib:/usr/trimui/lib:$LD_LIBRARY_PATH"


current_device=$(cat /etc/trimui_device.txt 2>/dev/null)
if [ -z "$current_device" ]; then
    RES=$(fbset | awk '/geometry/ {print $2 "x" $3}')
    if [ "$RES" = "1280x720" ]; then
        current_device="tsp"
    else
        current_device="brick"
    fi
    echo -n $current_device >/etc/trimui_device.txt

fi

if [ "$current_device" != "tsp" ]; then
    echo "Unsupported device '$current_device': this CrossMix build supports TrimUI Smart Pro only."
    exit 1
fi

read -r last_device </mnt/SDCARD/System/etc/last_device.txt
if [ "$current_device" != "$last_device" ]; then
    echo -n $current_device >/mnt/SDCARD/System/etc/last_device.txt
    touch /tmp/device_changed
fi

################ check min Firmware version required ################

CrossMixFWfile="/mnt/SDCARD/trimui/firmwares/MinFwVersion.txt"

if [ ! -f "$CrossMixFWfile" ]; then
    echo "Configuration file $CrossMixFWfile not found, skipping firmware check."
    exit 0
fi

Current_FW_Revision=$(grep 'DISTRIB_DESCRIPTION' /etc/openwrt_release | cut -d '.' -f 3 | tr -d '\r')
Required_FW_Revision=$(sed -n '2{s/\r$//;p;}' "$CrossMixFWfile")
for firmware_revision in "$Current_FW_Revision" "$Required_FW_Revision"; do
    case "$firmware_revision" in
        ''|*[!0-9]*) echo "Invalid firmware revision metadata; canceling firmware check."; exit 1 ;;
    esac
done

# The minimum supported firmware and the bundled upgrade can be different.
# Prefer the exact minimum; only fall back to explicitly declared Smart Pro firmware.
select_firmware_archive() {
    printf '%s\n' "$Required_FW_Version" | grep -Eq '^[0-9]+\.[0-9]+\.[0-9]+$' || return 1
    FIRMWARE_VERSION="$Required_FW_Version"
    FIRMWARE_REVISION="$Required_FW_Revision"
    FIRMWARE_PATH="/mnt/SDCARD/trimui/firmwares/firmware_tsp_v${FIRMWARE_VERSION}_${FIRMWARE_REVISION}.7z.001"
    [ -f "$FIRMWARE_PATH" ] && return 0

    local bundled_config="/mnt/SDCARD/trimui/firmwares/BundledFwVersion.txt"
    [ -f "$bundled_config" ] || return 1
    local bundled_version=$(sed -n '1{s/\r$//;p;}' "$bundled_config")
    local bundled_revision=$(sed -n '2{s/\r$//;p;}' "$bundled_config")
    case "$bundled_revision" in ''|*[!0-9]*) return 1 ;; esac
    case "$bundled_version" in ''|*[!0-9.]*) return 1 ;; esac
    [ "$bundled_revision" -ge "$Required_FW_Revision" ] || return 1
    awk -v bundled="$bundled_version" -v required="$Required_FW_Version" 'BEGIN {
        if (bundled !~ /^[0-9]+\.[0-9]+\.[0-9]+$/ || required !~ /^[0-9]+\.[0-9]+\.[0-9]+$/) exit 1;
        split(bundled, b, "."); split(required, r, ".");
        for (i = 1; i <= 3; i++) {
            if (b[i] + 0 > r[i] + 0) exit 0;
            if (b[i] + 0 < r[i] + 0) exit 1;
        }
        exit 0;
    }' || return 1

    FIRMWARE_VERSION="$bundled_version"
    FIRMWARE_REVISION="$bundled_revision"
    FIRMWARE_PATH="/mnt/SDCARD/trimui/firmwares/firmware_tsp_v${FIRMWARE_VERSION}_${FIRMWARE_REVISION}.7z.001"
    [ -f "$FIRMWARE_PATH" ]
}

# A successful listing proves the split volumes can be opened. Select only the
# expected TG5040 image, rather than CRC or size fields from another archive entry.
check_firmware_archive() {
    local firmware_path="$1"
    local firmware_file="$2"
    local listing
    listing=$(/mnt/SDCARD/System/bin/7zz l "$firmware_path" -slt "$firmware_file") || return 1
    FW_Size=$(printf '%s\n' "$listing" | awk -F ' = ' -v image="$firmware_file" '
        /^Path = / { selected = ($2 == image) }
        selected && /^Size = / { print $2; exit }')
    ARCHIVE_CRC=$(printf '%s\n' "$listing" | awk -F ' = ' -v image="$firmware_file" '
        /^Path = / { selected = ($2 == image) }
        selected && /^CRC = / { print $2; exit }' | tr 'a-f' 'A-F')
    case "$FW_Size" in ''|*[!0-9]*) return 1 ;; esac
    [ "$FW_Size" -gt 0 ] || return 1
    [ "${#ARCHIVE_CRC}" -eq 8 ] || return 1
    case "$ARCHIVE_CRC" in *[!0-9A-F]*) return 1 ;; esac
}

# Function to check CRC and update message
check_firmware_crc() {
    local firmware_path="$1"
    local firmware_file="$2"

    message="${message}Checking firmware integrity........"
    /mnt/SDCARD/System/usr/trimui/scripts/infoscreen2.sh -m "$message" -fs 12 -fi 0 -p top-left -fb -sp -ff "/mnt/SDCARD/Themes/CrossMix - OS/wqy-microhei.ttf" -i "/mnt/SDCARD/trimui/firmwares/FW_Screen_Wait.jpg" &

    if ! check_firmware_archive "$firmware_path" "$firmware_file"; then
        echo "Cannot read the firmware image metadata from $firmware_path"
        message="${message}KO"
        return 1
    fi

    # Calculate CRC of the extracted file
    local extracted_crc_output
    extracted_crc_output=$(crc32 "/mnt/SDCARD/$firmware_file") || return 1
    EXTRACTED_CRC=$(printf '%s\n' "$extracted_crc_output" | awk '{print $1}' | tr 'a-f' 'A-F')

    # Compare the CRC values
    if [ -n "$ARCHIVE_CRC" ] && [ -n "$EXTRACTED_CRC" ] && [ "$ARCHIVE_CRC" = "$EXTRACTED_CRC" ]; then
        echo "FW CRC check passed: $EXTRACTED_CRC"
        message="${message}OK"
        return 0
    else
        echo "CRC check failed: Archive CRC = $ARCHIVE_CRC, Extracted CRC = $EXTRACTED_CRC"
        message="${message}KO"
        return 1
    fi
}

diagnose() {
    pkill presenter
    sleep 0.5
    message="${message}\nChecking filesystem..."
    /mnt/SDCARD/System/usr/trimui/scripts/infoscreen2.sh -m "$message" -fs 12 -fi 0 -p top-left -fb -sp -ff "/mnt/SDCARD/Themes/CrossMix - OS/wqy-microhei.ttf" -i "/mnt/SDCARD/trimui/firmwares/FW_Screen_Wait.jpg" &
    check_filesystem
    if ! check_firmware_archive "$FIRMWARE_PATH" "$FIRMWARE_FILE"; then
        echo "Cannot diagnose firmware archive: image metadata is unavailable."
        return 1
    fi

    FW_Size_MB=$(($FW_Size / 1024 / 1024))
    if ! check_available_space "$(($FW_Size_MB + 100))"; then
        echo "Insufficient space available."
        message="${message}done\nInsufficient space available.\nYou need at least $(($FW_Size_MB + 100)) MB free on SD Card."
        sleep 1.5
        pkill presenter
        sleep 0.5
        /mnt/SDCARD/System/usr/trimui/scripts/infoscreen2.sh -m "$message" -fs 12 -fi 0 -p top-left -fb -ff "/mnt/SDCARD/Themes/CrossMix - OS/wqy-microhei.ttf" -i "/mnt/SDCARD/trimui/firmwares/FW_Screen_Fail.jpg" -k rout A "Exit"
    else
        echo "Sufficient space available."
        message="${message}done\nSufficient space available.\nYou have enough space to update firmware."
        sleep 1.5
        pkill presenter
        sleep 0.5
        /mnt/SDCARD/System/usr/trimui/scripts/infoscreen2.sh -m "$message" -fs 12 -fi 0 -p top-left -fb -ff "/mnt/SDCARD/Themes/CrossMix - OS/wqy-microhei.ttf" -i "/mnt/SDCARD/trimui/firmwares/FW_Screen_Fail.jpg" -k rout A "Exit"
    fi
}

echo "Current FW Revision: $Current_FW_Revision"
echo "Required FW Revision: $Required_FW_Revision"

if [ -z "$Current_FW_Revision" ] || [ -z "$Required_FW_Revision" ]; then

    echo "Firmware check not possible."

else

    if [ "$Current_FW_Revision" -lt "$Required_FW_Revision" ]; then

        . /mnt/SDCARD/System/usr/trimui/scripts/common_functions.sh

        pgrep -f trimui_inputd >/dev/null || { cd "/mnt/SDCARD/trimui/app" && ./trimui_inputd & } # we need input

        CrossMix_version=$(cat /mnt/SDCARD/System/usr/trimui/crossmix-version.txt)
        Current_FW_Version="$(cat /etc/version)"
        Required_FW_Version=$(sed -n '1{s/\r$//;p;}' "$CrossMixFWfile")

        echo "Current firmware ($Current_FW_Version - $Current_FW_Revision) must be updated to $Required_FW_Version - $Required_FW_Revision to support CrossMix OS v$CrossMix_version."

        FIRMWARE_FILE="trimui_tg5040.awimg"
        message="Current   FW version: $Current_FW_Version - $Current_FW_Revision\nRequired FW version: $Required_FW_Version - $Required_FW_Revision\n \n \n"
        crc_verified=false

        # Validate the selected archive before changing the internal filesystem.
        if ! select_firmware_archive || ! check_firmware_archive "$FIRMWARE_PATH" "$FIRMWARE_FILE"; then
            echo "Compatible Smart Pro firmware archive is missing or unreadable: $FIRMWARE_PATH"
            pkill presenter
            sleep 0.5
            message="${message}Compatible firmware archive missing or invalid.\nCheck that all split archive volumes are present.\nCanceling update.\n"
            /mnt/SDCARD/System/usr/trimui/scripts/infoscreen2.sh -m "$message" -fs 12 -fi 0 -p top-left -fb -ff "/mnt/SDCARD/Themes/CrossMix - OS/wqy-microhei.ttf" -i "/mnt/SDCARD/trimui/firmwares/FW_Screen_Fail.jpg" -k rout A "Exit"
            exit 1
        fi
        echo "Selected Smart Pro firmware: $FIRMWARE_VERSION - $FIRMWARE_REVISION"
        message="${message}Upgrade FW version: $FIRMWARE_VERSION - $FIRMWARE_REVISION\n"

        # Install new busybox from PortMaster, credits : https://github.com/kloptops/TRIMUI_EX

        Current_busybox_crc=$(/mnt/SDCARD/System/usr/trimui/scripts/busybox crc32 "/bin/busybox" | awk '{print $1}')
        target_busybox_crc=$(/mnt/SDCARD/System/usr/trimui/scripts/busybox crc32 "/mnt/SDCARD/System/usr/trimui/scripts/busybox" | awk '{print $1}')

        echo "Current busybox CRC: $Current_busybox_crc"
        echo "Target busybox CRC: $target_busybox_crc"
        # fi values are different or not set

        if [ -z "$Current_busybox_crc" ] || [ -z "$target_busybox_crc" ] || [ "$Current_busybox_crc" != "$target_busybox_crc" ]; then

            # make some place
            rm -rf /usr/trimui/apps/zformatter_fat32/
            rm -rf /usr/trimui/res/sound/bgm2.mp3
            swapoff -a
            rm -rf /swapfile
            # cp "/mnt/SDCARD/trimui/res/skin/bg.png" "/usr/trimui/res/skin/"

            cp -vf /bin/busybox /mnt/SDCARD/System/bin/busybox.bak
            /mnt/SDCARD/System/bin/rsync /mnt/SDCARD/System/usr/trimui/scripts/busybox /bin/busybox
            ln -vs "/bin/busybox" "/bin/bash"

            # Create missing busybox commands
            for cmd in $(busybox --list); do
                # Skip if command already exists or if it's not suitable for linking
                if [ -e "/bin/$cmd" ] || [ -e "/usr/bin/$cmd" ] || [ "$cmd" = "sh" ]; then
                    continue
                fi

                # Create a symbolic link
                ln -vs "/bin/busybox" "/usr/bin/$cmd"
            done

            # Fix weird libSDL location
            for libname in /usr/trimui/lib/libSDL*; do
                linkname="/usr/lib/$(basename "$libname")"
                if [ -e "$linkname" ]; then
                    continue
                fi
                ln -vs "$libname" "$linkname"
            done
        fi

        sync

        if [ -f "/mnt/SDCARD/$FIRMWARE_FILE" ]; then
            echo "Firmware file already exists, checking CRC..."

            message="${message}A firmware file is already present.\n"

            if check_firmware_crc "$FIRMWARE_PATH" "$FIRMWARE_FILE"; then
                echo "CRC check on existing file is OK. Skipping extraction."
                crc_verified=true
            else
                echo "CRC check on existing file failed. Re-extracting."
                rm -f "/mnt/SDCARD/$FIRMWARE_FILE"
            fi
        fi

        if [ "$crc_verified" = false ]; then
            message="${message}\n \nExtracting new firmware v$FIRMWARE_VERSION..."
            pkill presenter
            sleep 0.5
            /mnt/SDCARD/System/usr/trimui/scripts/infoscreen2.sh -m "$message" -fs 12 -fi 0 -p top-left -fb -sp -ff "/mnt/SDCARD/Themes/CrossMix - OS/wqy-microhei.ttf" -i "/mnt/SDCARD/trimui/firmwares/FW_Screen_Wait.jpg" &

            /mnt/SDCARD/System/usr/trimui/scripts/cpufreq.sh ondemand 3 7
            if ! /mnt/SDCARD/System/bin/7zz x "$FIRMWARE_PATH" "$FIRMWARE_FILE" -o"/mnt/SDCARD" -y; then
                echo "Failed to extract firmware"
                pkill presenter
                sleep 0.5
                message="${message}\nFirmware extraction failed, canceling update.\n \nPress X to diagnose."
                /mnt/SDCARD/System/usr/trimui/scripts/infoscreen2.sh -m "$message" -fs 12 -fi 0 -p top-left -fb -ff "/mnt/SDCARD/Themes/CrossMix - OS/wqy-microhei.ttf" -i "/mnt/SDCARD/trimui/firmwares/FW_Screen_Fail.jpg" -k rout A "" -k rout X ""
                rm "/mnt/SDCARD/$FIRMWARE_FILE"
                diagnose
                exit 1
            fi
            message="${message}OK\n"
            pkill presenter
            sleep 0.5
            sync

            if check_firmware_crc "$FIRMWARE_PATH" "$FIRMWARE_FILE"; then
                crc_verified=true
            else
                message="${message}\nFirmware CRC check has failed, canceling update.\nPress X to diagnose."
                pkill presenter
                sleep 0.5
                /mnt/SDCARD/System/usr/trimui/scripts/infoscreen2.sh -m "$message" -fs 12 -fi 0 -p top-left -fb -ff "/mnt/SDCARD/Themes/CrossMix - OS/wqy-microhei.ttf" -i "/mnt/SDCARD/trimui/firmwares/FW_Screen_Fail.jpg" -k rout A "" -k rout X ""
                rm "/mnt/SDCARD/$FIRMWARE_FILE"
                diagnose
                exit 1
            fi
        fi

        if [ "$crc_verified" = true ]; then
            # Removing backup from previous FW update runs
            if [ -f "/mnt/SDCARD/trimui/firmwares/Last_Automatic_Backup.txt" ]; then
                Last_Automatic_Backup=$(cat /mnt/SDCARD/trimui/firmwares/Last_Automatic_Backup.txt)
                if [ -f "/mnt/SDCARD/System/backups/firmware_settings/$current_device/$Last_Automatic_Backup" ]; then
                    echo "Removing last automatic backup: $Last_Automatic_Backup"
                    rm "/mnt/SDCARD/System/backups/firmware_settings/$current_device/$Last_Automatic_Backup"
                fi
            fi
            # backup settings
            Backup_file=$("/mnt/SDCARD/Apps/SystemTools/Menu/TOOLS/FW Settings Save-Load.sh" --backup | tail -n 1)
            echo $Backup_file >/mnt/SDCARD/trimui/firmwares/Last_Automatic_Backup.txt
            pkill presenter
            sleep 0.5
            message="${message}\n \nFirmware settings saved:\n$Backup_file"
            /mnt/SDCARD/System/usr/trimui/scripts/infoscreen2.sh -m "$message" -fs 12 -fi 0 -p top-left -fb -ff "/mnt/SDCARD/Themes/CrossMix - OS/wqy-microhei.ttf" -i "/mnt/SDCARD/trimui/firmwares/FW_Screen_Ready.jpg" &
            sleep 1.5
            pkill presenter
            sleep 0.5
            message="${message}\nReady for update!\n \nPlease read instructions at the right\nto launch your firmware upgrade."
            /mnt/SDCARD/System/usr/trimui/scripts/infoscreen2.sh -m "$message" -fs 12 -fi 0 -p top-left -fb -ff "/mnt/SDCARD/Themes/CrossMix - OS/wqy-microhei.ttf" -i "/mnt/SDCARD/trimui/firmwares/FW_Screen_Ready.jpg" -k rout A "" -k rin B ""

            if [ "$?" -eq 14 ]; then # A has been pressed
                pkill presenter
                sync
                /usr/trimui/bin/kill_apps.sh
                sleep 30
                poweroff
                sleep 30
                exit
            else
                pkill presenter
                exit
            fi

        fi

    else
        echo "Firmware version $Current_FW_Revision OK."
        rm -f "/mnt/SDCARD/trimui_tg5040.awimg"

    fi
fi

################ check if a CrossMix-OS update is available ################

crossmix_boot_handoff() {
    local sd="${CROSSMIX_SDCARD_ROOT:-/mnt/SDCARD}" archive temp rootfs_space button
    [ -f "$sd/System/updates/pending_release.json" ] || {
        echo "No verified pending CrossMix update."
        return 0
    }
    [ -f "$sd/System/usr/trimui/scripts/update_common.sh" ] || return 2
    # Use the installed helper before extracting or running any archive content.
    . "$sd/System/usr/trimui/scripts/update_common.sh"
    archive=$(crossmix_pending_archive) || return 2
    crossmix_install_preflight "$archive" || return 2
    crossmix_release_is_new || {
        echo "Pending CrossMix release is already installed or not newer."
        return 0
    }
    rootfs_space=$(df -Pk / | awk 'NR == 2 {print $4}')
    case "$rootfs_space" in ""|*[!0-9]*) return 2 ;; esac
    [ "$rootfs_space" -ge 20480 ] || {
        echo "Less than 20 MiB free on internal storage; update canceled." >&2
        return 2
    }
    if [ ! -x "$sd/System/usr/trimui/scripts/infoscreen.sh" ] || [ ! -x "$sd/System/bin/text_viewer" ]; then
        echo "Trusted update UI is missing. Follow the manual migration guide." >&2
        return 2
    fi
    "${CROSSMIX_INTERNAL_ROOT:-/usr/trimui}/bin/trimui_inputd" &
    button=$("$sd/System/usr/trimui/scripts/infoscreen.sh" -m "CrossMix $Release_Tag found. Press A to install, B to cancel." -k "A B")
    [ "$button" = "A" ] || return 0
    temp="${CROSSMIX_TMP_ROOT:-/tmp}/crossmix-update.$$"
    mkdir -p "$temp" || return 2
    "$sd/System/bin/7zz" e "$archive" "System/usr/trimui/scripts/crossmix_update.sh" "-o$temp" -y || return 2
    [ -s "$temp/crossmix_update.sh" ] && sh -n "$temp/crossmix_update.sh" || return 2
    chmod a+x "$temp/crossmix_update.sh"
    cp "$sd/System/bin/text_viewer" "$temp/text_viewer" || return 2
    "$sd/System/usr/trimui/scripts/infoscreen.sh" -m "Updating CrossMix to $Release_Tag" -t 1
    pkill -9 preload.sh
    pkill -9 runtrimui.sh
    "$temp/text_viewer" -s "$temp/crossmix_update.sh" -f 25 -t "CrossMix-OS Update $Release_Tag"
}

crossmix_boot_handoff
