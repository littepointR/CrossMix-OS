#!/bin/sh
UPDATE_VERSION=1.1.0
SDCARD_ROOT=${CROSSMIX_SDCARD_ROOT:-/mnt/SDCARD}
export PATH="$SDCARD_ROOT/System/bin:$SDCARD_ROOT/System/usr/trimui/scripts:$PATH"
export LD_LIBRARY_PATH="$SDCARD_ROOT/System/lib:/usr/trimui/lib:$LD_LIBRARY_PATH"

if [ "$1" = "-v" ]; then
    echo -n $UPDATE_VERSION
    exit
fi

RED='\033[1;31m'
GREEN='\033[1;32m'
YELLOW='\033[1;33m'
BLUE='\033[1;34m'
PURPLE='\033[01;35m'
NC='\033[0m' # No Color

GITHUB_REPOSITORY=littepointR/CrossMix-OS
UPDATE_CHANNEL=stable
UPDATE_DEVICE=tsp
updatedir="$SDCARD_ROOT/System/updates"
Local_CrossMixVersion="$(cat "$SDCARD_ROOT/System/usr/trimui/crossmix-version.txt" 2>/dev/null)"
current_date=$(date "+%Y-%m-%d")
timestamp=$(date +'%Y%m%d-%Hh%M')

# All OTA clients use this configuration and the same release selection rules.
# The old "beta" setting is accepted only as an alias for "prerelease".
crossmix_load_settings() {
    local config="$SDCARD_ROOT/System/etc/update.json" saved_channel
    if [ -f "$config" ]; then
        jq -e '(.repository | type == "string" and test("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$"))
            and (.channel == "stable" or .channel == "prerelease") and .device == "tsp"' "$config" >/dev/null || {
            echo "Invalid update configuration: $config" >&2
            return 2
        }
        GITHUB_REPOSITORY=$(jq -r '.repository' "$config")
        UPDATE_CHANNEL=$(jq -r '.channel' "$config")
        UPDATE_DEVICE=$(jq -r '.device' "$config")
    fi
    saved_channel=$(cat "$updatedir/ota_channel.txt" 2>/dev/null)
    case "$saved_channel" in
        stable) UPDATE_CHANNEL=stable ;;
        prerelease|beta) UPDATE_CHANNEL=prerelease ;;
        "") ;;
        *) echo "Invalid OTA channel: $saved_channel" >&2; return 2 ;;
    esac
}

crossmix_fetch_file() {
    local url="$1" destination="$2" ca="$SDCARD_ROOT/System/updates/update_001/ca-certificates.crt"
    set -- --fail --location --silent --show-error --retry 2 --connect-timeout 15 --max-time 3600 -o "$destination" "$url"
    # Official Tina firmware can have curl but no installed CA store. Use the
    # trust bundle shipped in this verified release, without changing /etc or
    # waiting for the legacy update_001 first-boot marker to be reset.
    [ -s "$ca" ] && set -- --cacert "$ca" "$@"
    curl "$@"
}

crossmix_asset_url() {
    jq -er --arg name "$1" '.assets[] | select(.name == $name) | .browser_download_url' "$Release_JSON"
}

crossmix_load_release() {
    Release_JSON="$updatedir/selected_release.json"
    Release_Manifest="$updatedir/release-manifest.json"
    Release_Sums="$updatedir/SHA256SUMS"
    Release_Tag=$(jq -r '.tag_name' "$Release_JSON") || return 2
    Release_Prerelease=$(jq -r '.prerelease' "$Release_JSON")
    Release_Date=$(jq -r '.published_at' "$Release_JSON")
    Release_Version=$(jq -r '.version' "$Release_Manifest")
    Release_FullVersion="$Release_Tag"
    Release_Name=$(jq -r '.archive_name' "$Release_Manifest")
    Release_size=$(jq -r '.archive_size' "$Release_Manifest")
    Release_size_MB=$(((Release_size + 1048575) / 1048576))
}

crossmix_validate_manifest() {
    jq -e --arg device "$UPDATE_DEVICE" --arg tag "$Release_Tag" '
        .version as $version | .schema == 1 and .device == $device
        and (.version | type == "string" and test("^[0-9]+\\.[0-9]+\\.[0-9]+$"))
        and ($tag == ("v" + $version) or ($tag | startswith("v" + $version + "-")))
        and .archive_name == ("CrossMix-OS_v" + .version + ".zip")
        and (.archive_size | type == "number" and . > 0 and floor == .)
        and (.archive_sha256 | type == "string" and test("^[0-9a-f]{64}$"))
        and (.uncompressed_size == null or (.uncompressed_size | type == "number" and . >= 0 and floor == .))
        and (.parts | type == "array" and length > 0 and length <= 999)
        and all(.parts[]; (.size | type == "number" and . > 0 and floor == .)
            and (.sha256 | type == "string" and test("^[0-9a-f]{64}$")))
        and ([.parts[].size] | add) == .archive_size
        and (.archive_name as $archive | .parts as $parts |
            if ($parts | length) == 1 then $parts[0].name == $archive
            else all(range(0; $parts | length); . as $i |
                $parts[$i].name == ($archive + "." + ("000" + (($i + 1) | tostring))[-3:])) end)
    ' "$Release_Manifest" >/dev/null || {
        echo "Invalid release manifest, device, version, or part sequence." >&2
        return 2
    }
    # Every required asset must occur once and belong to this exact repository/tag.
    jq -e --arg repo "$GITHUB_REPOSITORY" --arg tag "$Release_Tag" --slurpfile manifest "$Release_Manifest" '
        .assets as $assets |
        all((["release-manifest.json", "SHA256SUMS"] + [$manifest[0].parts[].name])[];
            . as $name | [$assets[] | select(.name == $name)] as $matches |
            ($matches | length) == 1 and $matches[0].browser_download_url ==
                ("https://github.com/" + $repo + "/releases/download/" + $tag + "/" + $name))
        and all($manifest[0].parts[]; . as $part |
            [$assets[] | select(.name == $part.name)][0].size == $part.size)
    ' "$Release_JSON" >/dev/null || {
        echo "Release assets do not match the manifest or repository." >&2
        return 2
    }
    local name digest listed
    jq -r '.parts[] | [.name, .sha256] | @tsv' "$Release_Manifest" > "$updatedir/.checks.$$"
    printf '%s\t%s\n' "$(jq -r '.archive_name' "$Release_Manifest")" "$(jq -r '.archive_sha256' "$Release_Manifest")" >> "$updatedir/.checks.$$"
    while read -r name digest; do
        listed=$(awk -v name="$name" '{sub(/\r$/, "")} $2 == name {n++; value=$1} END {if(n == 1) print value}' "$Release_Sums")
        if [ "$listed" != "$digest" ]; then
            rm -f "$updatedir/.checks.$$"
            echo "SHA256SUMS is missing or inconsistent for $name." >&2
            return 2
        fi
    done < "$updatedir/.checks.$$"
    rm -f "$updatedir/.checks.$$"
}

# Return 0 for a validated release, 1 for no eligible release, 2 for an error.
crossmix_fetch_release() {
    crossmix_load_settings || return 2
    mkdir -p "$updatedir" || return 2
    local metadata="$updatedir/.metadata.$$" api="$updatedir/.releases.$$" result
    mkdir -p "$metadata" || return 2
    crossmix_fetch_file "https://api.github.com/repos/$GITHUB_REPOSITORY/releases?per_page=100" "$api" || {
        rm -rf "$metadata"; rm -f "$api"; return 2
    }
    if ! jq -e 'type == "array"' "$api" >/dev/null; then
        rm -rf "$metadata"; rm -f "$api"; return 2
    fi
    jq --arg channel "$UPDATE_CHANNEL" '[.[] | select(.draft == false)
        | select($channel == "prerelease" or .prerelease == false)]
        | sort_by(.published_at) | reverse | .[0] // empty' "$api" > "$metadata/selected_release.json"
    rm -f "$api"
    if [ ! -s "$metadata/selected_release.json" ]; then
        rm -rf "$metadata"; return 1
    fi
    Release_JSON="$metadata/selected_release.json"
    Release_Manifest="$metadata/release-manifest.json"
    Release_Sums="$metadata/SHA256SUMS"
    Release_Tag=$(jq -r '.tag_name' "$Release_JSON")
    if ! jq -e '(.tag_name | test("^v[0-9]+\\.[0-9]+\\.[0-9]+(-[A-Za-z0-9.-]+)?$"))
        and (.assets | type == "array") and (.prerelease | type == "boolean")' "$Release_JSON" >/dev/null; then
        rm -rf "$metadata"; return 2
    fi
    # Validate metadata URLs before making requests (not after downloading them).
    if ! jq -e --arg repo "$GITHUB_REPOSITORY" --arg tag "$Release_Tag" '.assets as $assets |
        all(["release-manifest.json", "SHA256SUMS"][]; . as $name |
            [$assets[] | select(.name == $name)] as $matches | ($matches | length) == 1
            and $matches[0].browser_download_url == ("https://github.com/" + $repo + "/releases/download/" + $tag + "/" + $name))' "$Release_JSON" >/dev/null; then
        rm -rf "$metadata"; return 2
    fi
    crossmix_fetch_file "$(crossmix_asset_url release-manifest.json)" "$Release_Manifest" &&
        crossmix_fetch_file "$(crossmix_asset_url SHA256SUMS)" "$Release_Sums" &&
        crossmix_validate_manifest
    result=$?
    if [ "$result" -ne 0 ]; then rm -rf "$metadata"; return 2; fi
    mv "$metadata/selected_release.json" "$metadata/release-manifest.json" "$metadata/SHA256SUMS" "$updatedir/" || return 2
    rmdir "$metadata"
    crossmix_load_release
}

crossmix_version_number() {
    echo "$1" | sed 's/^v//; s/-.*//' | awk -F. '{printf "%d%03d%03d\n", $1, $2, $3}'
}

crossmix_release_is_new() {
    local local_version remote_version installed_tag installed_preview installed_repo
    installed_repo=$(cat "$SDCARD_ROOT/System/usr/trimui/update-repository.txt" 2>/dev/null)
    if [ "$installed_repo" != "$GITHUB_REPOSITORY" ]; then
        echo "First install of $GITHUB_REPOSITORY requires the documented manual migration." >&2
        return 2
    fi
    local_version=$(crossmix_version_number "$Local_CrossMixVersion")
    remote_version=$(crossmix_version_number "$Release_Version")
    [ "$remote_version" -gt "$local_version" ] && return 0
    [ "$remote_version" -lt "$local_version" ] && return 1
    installed_tag=$(jq -r '.tag // empty' "$updatedir/installed_release.json" 2>/dev/null)
    installed_preview=$(jq -r '.prerelease // false' "$updatedir/installed_release.json" 2>/dev/null)
    [ "$installed_tag" = "$Release_Tag" ] && return 1
    # A stable release supersedes the same numeric preview. A stable install is
    # never offered an older/equal preview simply because its tag differs.
    [ "$installed_preview" = "true" ] && [ "$Release_Prerelease" = "false" ] && return 0
    if [ "$installed_preview" = "true" ] && [ "$Release_Prerelease" = "true" ]; then
        local old_seq new_seq
        old_seq=${installed_tag##*.}; new_seq=${Release_Tag##*.}
        case "$old_seq:$new_seq" in *[!0-9:]*|:*) return 1 ;; esac
        [ "$new_seq" -gt "$old_seq" ] && return 0
    fi
    return 1
}

crossmix_verify_archive() {
    local archive="$1" actual size expected listing="$updatedir/.archive-list.$$"
    size=$(stat -c %s "$archive" 2>/dev/null) || return 2
    expected=$(jq -r '.archive_sha256' "$Release_Manifest")
    actual=$(sha256sum "$archive" | awk '{print $1}')
    [ "$size" = "$Release_size" ] && [ "$actual" = "$expected" ] || {
        echo "Archive size or SHA-256 mismatch." >&2; return 2
    }
    "$SDCARD_ROOT/System/bin/7zz" t "$archive" >/dev/null || {
        echo "ZIP integrity check failed." >&2; return 2
    }
    "$SDCARD_ROOT/System/bin/7zz" l -slt "$archive" > "$listing" || { rm -f "$listing"; return 2; }
    if ! awk '
        /^----------/ {entries=1; next}
        entries && /^Path = / {
            path=substr($0, 8)
            if (path ~ /^\// || path ~ /\\/ || path ~ /:/ || path ~ /(^|\/)\.\.(\/|$)/) bad=1
        }
        END {exit bad ? 1 : 0}
    ' "$listing"; then
        rm -f "$listing"
        echo "ZIP contains an unsafe installation path." >&2
        return 2
    fi
    rm -f "$listing"
}

crossmix_install_preflight() {
    crossmix_load_settings || return 2
    local pending="$updatedir/pending_release.json" archive="$1"
    if ! jq -e --arg repo "$GITHUB_REPOSITORY" --arg device "$UPDATE_DEVICE" --arg name "$(basename "$archive")" '
        .schema == 1 and .repository == $repo and .device == $device and .archive_name == $name
        and (.archive_size | type == "number" and . > 0 and floor == .)
        and (.archive_sha256 | type == "string" and test("^[0-9a-f]{64}$"))
        and (.tag | type == "string") and (.prerelease | type == "boolean")
        and (.uncompressed_size == null or (.uncompressed_size | type == "number" and . >= 0 and floor == .))
    ' "$pending" >/dev/null 2>&1; then
        echo "No matching verified pending manifest. Use OTA or the manual migration guide." >&2
        return 2
    fi
    Release_Manifest="$pending"
    Release_size=$(jq -r '.archive_size' "$pending")
    Release_Version=$(jq -r '.version' "$pending")
    Release_Tag=$(jq -r '.tag' "$pending")
    Release_Prerelease=$(jq -r '.prerelease' "$pending")
    crossmix_require_install_space && crossmix_verify_archive "$archive"
}

crossmix_pending_archive() {
    local name
    name=$(jq -er '.archive_name | select(test("^CrossMix-OS_v[0-9]+\\.[0-9]+\\.[0-9]+\\.zip$"))' "$updatedir/pending_release.json") || return 2
    [ -f "$SDCARD_ROOT/$name" ] || return 2
    printf '%s\n' "$SDCARD_ROOT/$name"
}

crossmix_install_space_bytes() {
    local unpacked
    unpacked=$(jq -r '.uncompressed_size // 0' "$Release_Manifest") || return 2
    case "$unpacked" in ""|*[!0-9]*) return 2 ;; esac
    [ "$unpacked" -lt 5368709120 ] && unpacked=5368709120
    echo $((unpacked + 536870912))
}

crossmix_require_free_space() {
    local required="$1" free
    free=$(df -Pk "$SDCARD_ROOT" | awk 'NR == 2 {printf "%.0f", $4 * 1024}')
    case "$free" in ""|*[!0-9]*) echo "Cannot determine free SD card space." >&2; return 2 ;; esac
    if [ "$free" -lt "$required" ]; then
        echo "Insufficient free space: need $required bytes for download/extraction and reserve." >&2
        return 2
    fi
}

crossmix_require_install_space() {
    local required
    required=$(crossmix_install_space_bytes) || return 2
    crossmix_require_free_space "$required"
}

crossmix_download_release() {
    local work="$updatedir/.download.$$" count required name size digest actual url
    Verified_Archive="$updatedir/$Release_Name"
    crossmix_validate_manifest || return 2
    if [ -f "$Verified_Archive" ] && crossmix_verify_archive "$Verified_Archive"; then
        crossmix_require_install_space
        return $?
    fi
    count=$(jq '.parts | length' "$Release_Manifest")
    # The boot installer reserves 5000 MiB after download. Keep that reserve
    # in addition to the ZIP/parts, rather than counting it as download space.
    required=$(crossmix_install_space_bytes) || return 2
    required=$((required + Release_size))
    [ "$count" -gt 1 ] && required=$((required + Release_size))
    crossmix_require_free_space "$required" || return 2
    mkdir -p "$work" || return 2
    jq -r '.parts[] | [.name, .size, .sha256] | @tsv' "$Release_Manifest" > "$work/parts"
    while read -r name size digest; do
        url=$(crossmix_asset_url "$name") || { rm -rf "$work"; return 2; }
        crossmix_fetch_file "$url" "$work/$name" || { rm -rf "$work"; return 2; }
        actual=$(sha256sum "$work/$name" | awk '{print $1}')
        if [ "$(stat -c %s "$work/$name")" != "$size" ] || [ "$actual" != "$digest" ]; then
            echo "Downloaded part failed size/SHA-256 verification: $name" >&2
            rm -rf "$work"; return 2
        fi
    done < "$work/parts"
    if [ "$count" -gt 1 ]; then
        : > "$work/$Release_Name"
        while read -r name size digest; do
            cat "$work/$name" >> "$work/$Release_Name" || { rm -rf "$work"; return 2; }
        done < "$work/parts"
    fi
    crossmix_verify_archive "$work/$Release_Name" || { rm -rf "$work"; return 2; }
    mv "$work/$Release_Name" "$Verified_Archive" || { rm -rf "$work"; return 2; }
    rm -rf "$work"
    echo "Verified update: $Verified_Archive"
}

crossmix_stage_release() {
    # Verify again immediately before installing a script or scheduling a reboot.
    crossmix_require_install_space && crossmix_verify_archive "$Verified_Archive" || return 2
    local installer="$updatedir/.installer.$$"
    mkdir -p "$installer" || return 2
    "$SDCARD_ROOT/System/bin/7zz" e "$Verified_Archive" "System/usr/trimui/scripts/crossmix_update.sh" "-o$installer" -y >/dev/null || {
        rm -rf "$installer"; return 2
    }
    [ -s "$installer/crossmix_update.sh" ] && sh -n "$installer/crossmix_update.sh" || {
        echo "The verified archive lacks a usable installation script." >&2
        rm -rf "$installer"; return 2
    }
    jq --arg repository "$GITHUB_REPOSITORY" --arg tag "$Release_Tag" --argjson prerelease "$Release_Prerelease" \
        '. + {repository: $repository, tag: $tag, prerelease: $prerelease}' "$Release_Manifest" > "$updatedir/pending_release.json" || {
        rm -rf "$installer"; return 2
    }
    mv "$installer/crossmix_update.sh" "$SDCARD_ROOT/System/usr/trimui/scripts/crossmix_update.sh" || return 2
    rmdir "$installer"
    mv "$Verified_Archive" "$SDCARD_ROOT/$Release_Name" || return 2
    sync
}

check_connection() {
    echo -n "Checking internet connection... "
    if wget -q --spider https://github.com >/dev/null; then
        echo -e "${GREEN}OK${NC}"
    else
        echo -e "${RED}FAIL${NC}\nError: https://github.com not reachable. Check your wifi connection."
        echo -ne "${YELLOW}"
        read -n 1 -s -r -p "Press A to exit"
        exit 2
    fi
}

enable_wifi() {
    # Check if the Wi-Fi interface already has an IP
    IP=$(ip route get 1 | awk '/src/ {print $NF; exit}')
    if [ -n "$IP" ]; then
        echo "Wi-Fi is already enabled. IP: $IP"
        return 0
    fi

    echo "Wi-Fi is disabled - trying to enable it..."

    pkill -9 wpa_supplicant 2>/dev/null
    pkill -9 udhcpc 2>/dev/null
    rm -rf /etc/wifi/sockets/wlan0 2>/dev/null

    # Bring up the loopback interface
    if ! ifconfig lo up; then
        echo "Failed to bring up loopback interface (lo)."
        return 1
    fi

    sleep 1

    # Bring up the Wi-Fi interface
    if ! ifconfig wlan0 up; then
        echo "Failed to bring up Wi-Fi interface (wlan0)."
        return 1
    fi

    sleep 1

    # Start wpa_supplicant
    if ! wpa_supplicant -B -D nl80211 -i wlan0 -c /etc/wifi/wpa_supplicant.conf -O /etc/wifi/sockets; then
        echo "Failed to start wpa_supplicant."
        return 1
    fi

    sleep 5

    # Start udhcpc to obtain an IP address
    if
        ! udhcpc -i wlan0 &
        >/dev/null &
    then
        echo "Failed to start udhcpc."
        return 1
    fi

    # Verify if an IP address has been obtained
    IP=$(ip route get 1 | awk '/src/ {print $NF; exit}')
    if [ -n "$IP" ]; then
        echo "Wi-Fi enabled successfully. IP: $IP"
        return 0
    else
        echo "Failed to obtain an IP address."
        return 1
    fi
}
check_filesystem() {
    echo -e "\n${BLUE}================== CHECKDISK ==================${NC}\n"

    force=0
    if [ "$1" = "--force" ]; then
        force=1
    fi

    # Check the filesystem
    last_fsck_date=$(cat /mnt/SDCARD/System/updates/last_fsck.txt 2>/dev/null)

    if [ "$force" -eq 0 ] && [ "$last_fsck_date" = "$current_date" ]; then
        echo -e "The last fsck was performed today ($current_date).\nNo need to rerun."
    else
        echo -ne "\n" \
            "Please wait during FAT file system integrity check.\n" \
            "Issues should be fixed automatically.\n" \
            "The process can be long:\n" \
            "about 2 minutes for 128GB SD card\n\n"

        mount_point=$(mount | grep -m 1 '/mnt/SDCARD' | awk '{print $1}')
        /mnt/SDCARD/System/bin/fsck.fat -a "$mount_point" 2>&1 | awk 'NR > 3'

        echo "$current_date" >/mnt/SDCARD/System/updates/last_fsck.txt

        if ls /mnt/SDCARD/FSCK*.REC 1>/dev/null 2>&1; then
            rec_dir="/mnt/SDCARD/rec_files"
            mkdir -p "$rec_dir"
            mv /mnt/SDCARD/FSCK*.REC "$rec_dir"
            echo "FSCK*.REC files moved to $rec_dir"

            cat >"$rec_dir/_description.txt" <<EOL
The files with the extension .REC are recovery files generated by the fsck.fat tool during a file system integrity check.
These files are created when the tool encounters potential issues with the file system. 
They may contain data that was recovered or repaired. In general, these files can be ignored if no issues are noticed with the system.
However, they may also contain partial or deleted data that may not be fully usable.
You can safely delete them if you're sure the file system is working properly.
EOL
        fi
    fi
}

ReadableSizeValue() {
    local size_bytes=$1
    local result

    if [ -z "$size_bytes" ]; then
        size_bytes=0
    fi

    if [ "$size_bytes" -lt 1024 ]; then
        result="${size_bytes} Bytes"
    elif [ "$size_bytes" -lt $((1024 * 1024)) ]; then
        size_kb=$((size_bytes / 1024))
        result="${size_kb} KB"
    else
        size_mb=$(echo "$size_bytes" | awk '{printf "%.2f", $1 / (1024 * 1024)}')
        result="${size_mb} MB"
    fi

    echo "$result"
}

check_available_space() {
    required_space=$1
    echo -e "\n${BLUE}=== Checking available space on the SD Card ===${NC}\n"
    # Available space in MB
    mount_point=$(mount | grep -m 1 '/mnt/SDCARD' | awk '{print $1}')
    available_space=$(df -m $mount_point | awk 'NR==2{print $4}')
    echo "Required space: $required_space MB"
    # Check available space
    if [ "$available_space" -lt "$required_space" ]; then
        echo -e "${RED}Available space is insufficient on SD card${NC}\n"
        echo "CrossMix-OS update requires $required_space MB of free space."
        return 1
    else
        echo -e "${GREEN}Available space is sufficient on SD card (${available_space}MB)${NC}\n"
        return 0
    fi
}

download_file() {
    local url=""
    local destination_dir="."
    local destination_file=""
    local title=""

    # Parse options
    while [ $# -gt 0 ]; do
        case "$1" in
        -d)
            destination_dir="$2"
            shift 2
            ;;
        -f)
            destination_file="$2"
            shift 2
            ;;
        -t)
            title="$2"
            shift 2
            ;;
        *)
            url="$1"
            shift
            ;;
        esac
    done

    local filename=$(basename "$url")

    # Ensure the URL is provided
    if [ -z "$url" ]; then
        echo "Error: URL is required."
        return 1
    fi

    # Determine the filename if not explicitly set
    if [ -z "$destination_file" ]; then
        destination_file="$destination_dir/$filename"
    fi

    # Create destination directory if it doesn't exist
    mkdir -p "$(dirname "$destination_file")"

    # Use the title if provided, otherwise fallback to the filename
    local display_name="${title:-$filename}"

    # Temporary file name
    local temp_file="${destination_file}_tmp"

    # Download the file
    echo -e "\n${BLUE}==== Downloading: $display_name ====${NC}"
    crossmix_fetch_file "$url" "$temp_file"
    if [ $? -eq 0 ] && [ -f "$temp_file" ]; then
        mv "$temp_file" "$destination_file"
        sync
        echo -e "$display_name: ${GREEN}OK${NC}\n"
        return 0
    else
        # Remove the temporary file if download failed
        [ -f "$temp_file" ] && rm "$temp_file"
        sync
        echo -e "$display_name: ${RED}Failed${NC}\n"
        return 1
    fi
}
