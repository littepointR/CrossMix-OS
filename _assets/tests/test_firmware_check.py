#!/usr/bin/env python3
"""Exercise the real startup checker with virtual device paths and fake firmware.

No firmware is downloaded, extracted by 7-Zip, or flashed. These host tests prove
selection and failure handling; they do not establish device compatibility.
"""

import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
CHECKER = ROOT / "System/starts/_FirmwareCheck.sh"
IMAGE = "trimui_tg5040.awimg"


def find_shell():
    configured = os.environ.get("CROSSMIX_TEST_SHELL")
    if configured:
        return configured
    if os.name != "nt":
        return shutil.which("sh")
    git = shutil.which("git")
    if git:
        candidate = Path(git).resolve().parent.parent / "bin/bash.exe"
        if candidate.exists():
            return str(candidate)
    raise RuntimeError("Set CROSSMIX_TEST_SHELL to a POSIX shell (Git Bash on Windows).")


def posix_path(path):
    result = Path(path).resolve().as_posix()
    if os.name == "nt":
        result = "/" + result[0].lower() + result[2:]
    return result


class FirmwareCheckTests(unittest.TestCase):
    def run_checker(self, *, device="tsp", archives=None, bundled="1.1.1\n20251128\n",
                    existing_crc=None, extracted_crc="1234ABCD", listing_crc="1234ABCD",
                    listing_failure=False, crc_failure=False, extraction_failure=False,
                    current_revision="20240413", listing_size="1024", listing_image=IMAGE):
        with tempfile.TemporaryDirectory(prefix="crossmix-fw-") as temp:
            fixture = Path(temp)
            sd = fixture / "sd"
            log = fixture / "calls.log"
            replacements = {
                "/mnt/SDCARD": posix_path(sd),
                "/etc": posix_path(fixture / "etc"),
                "/tmp": posix_path(fixture / "tmp"),
                "/usr": posix_path(fixture / "internal/usr"),
                "/bin": posix_path(fixture / "internal/bin"),
                "/swapfile": posix_path(fixture / "internal/swapfile"),
            }

            def write(relative, text):
                path = fixture / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8", newline="\n")
                path.chmod(0o755)

            write("etc/trimui_device.txt", device + "\n")
            write("etc/openwrt_release", "DISTRIB_DESCRIPTION='Trimui.0." + current_revision + ".0'\n")
            write("etc/version", "1.0.4\n")
            write("sd/System/etc/last_device.txt", device + "\n")
            write("sd/System/usr/trimui/crossmix-version.txt", "1.3.6\n")
            write("sd/System/usr/trimui/scripts/common_functions.sh", "check_filesystem() { :; }\ncheck_available_space() { return 0; }\n")
            write("sd/trimui/firmwares/MinFwVersion.txt", "1.1.0\r\n20250505\r\n")
            if bundled is not None:
                write("sd/trimui/firmwares/BundledFwVersion.txt", bundled)
            if archives is None:
                archives = ["firmware_tsp_v1.1.1_20251128.7z.001", "firmware_tsp_v1.1.1_20251128.7z.002"]
            for archive in archives:
                write("sd/trimui/firmwares/" + archive, "fake split archive\n")
            if existing_crc is not None:
                write("sd/" + IMAGE, existing_crc + "\n")
            write("sd/System/bin/7zz", """#!/bin/sh
printf '7zz %s\n' "$*" >> "$FIXTURE_LOG"
archive=$2
[ -f "$archive" ] && [ -f "${archive%.001}.002" ] || exit 2
if [ "$1" = l ]; then
    printf 'Path = %s\nType = Split\n\nPath = %s\nSize = %s\nCRC = %s\n' "$archive" "$LISTING_IMAGE" "$LISTING_SIZE" "$LISTING_CRC"
    [ "$LISTING_FAILURE" = 0 ] || exit 2
elif [ "$1" = x ]; then
    [ "$EXTRACTION_FAILURE" = 0 ] || exit 2
    printf '%s\n' "$FIXTURE_EXTRACTED_CRC" > "$FIXTURE_SD/trimui_tg5040.awimg"
else
    exit 2
fi
""")
            write("sd/System/usr/trimui/scripts/busybox", "#!/bin/sh\nprintf 'busyboxcrc %s\\n' \"$*\" >> \"$FIXTURE_LOG\"\nprintf '11111111\n'\n")
            write("sd/System/usr/trimui/scripts/infoscreen2.sh", "#!/bin/sh\nprintf 'screen %s\\n' \"$*\" >> \"$FIXTURE_LOG\"\nexit 0\n")
            write("sd/System/usr/trimui/scripts/cpufreq.sh", "#!/bin/sh\nprintf 'cpufreq\\n' >> \"$FIXTURE_LOG\"\n")
            write("sd/Apps/SystemTools/Menu/TOOLS/FW Settings Save-Load.sh", "#!/bin/sh\nprintf 'backup\\n' >> \"$FIXTURE_LOG\"\nprintf 'fixture-backup\\n'\n")
            for name in ["sleep", "pkill", "sync", "swapoff", "ln", "cp", "rm", "rsync", "poweroff"]:
                write("stubs/" + name, "#!/bin/sh\nprintf '%s %s\\n' \"" + name + "\" \"$*\" >> \"$FIXTURE_LOG\"\n")
            write("stubs/pgrep", "#!/bin/sh\nexit 0\n")
            write("stubs/crc32", """#!/bin/sh
cat "$1"
[ "$CRC_FAILURE" = 0 ] || exit 1
""")
            source = CHECKER.read_text(encoding="utf-8")
            pattern = r"(?<![A-Za-z0-9_])(?:" + "|".join(re.escape(p) for p in replacements) + r')(?=/|["\s:])'
            source = re.sub(pattern, lambda match: replacements[match.group()], source)
            source = '#!/bin/sh\nPATH="' + posix_path(fixture / "stubs") + ':$PATH"\n' + source
            write("checker.sh", source)
            env = dict(os.environ, FIXTURE_LOG=posix_path(log), FIXTURE_SD=posix_path(sd), LISTING_CRC=listing_crc,
                       LISTING_FAILURE=str(int(listing_failure)), LISTING_SIZE=listing_size, LISTING_IMAGE=listing_image,
                       CRC_FAILURE=str(int(crc_failure)), EXTRACTION_FAILURE=str(int(extraction_failure)),
                       FIXTURE_EXTRACTED_CRC=extracted_crc)
            process = subprocess.run([find_shell(), posix_path(fixture / "checker.sh")], env=env,
                                     capture_output=True, text=True, encoding="utf-8", timeout=10)
            calls = log.read_text(encoding="utf-8") if log.exists() else ""
            return process, calls

    def assert_not_prepared(self, calls):
        self.assertNotIn("7zz x ", calls)
        self.assertNotIn("backup\n", calls)
        self.assertNotIn("rsync ", calls)
        self.assertNotIn("busyboxcrc ", calls)
        self.assertNotIn("Ready for update!", calls)

    def test_current_tree_uses_bundled_firmware_when_minimum_archive_is_absent(self):
        process, calls = self.run_checker()
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertIn("7zz x ", calls)
        self.assertIn("firmware_tsp_v1.1.1_20251128.7z.001", calls)
        self.assertIn("Ready for update!", calls)

    def test_exact_minimum_archive_is_preferred(self):
        process, calls = self.run_checker(archives=["firmware_tsp_v1.1.0_20250505.7z.001", "firmware_tsp_v1.1.0_20250505.7z.002", "firmware_tsp_v1.1.1_20251128.7z.001", "firmware_tsp_v1.1.1_20251128.7z.002"])
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertIn("firmware_tsp_v1.1.0_20250505.7z.001", calls)
        self.assertNotIn("firmware_tsp_v1.1.1_20251128.7z.001", calls)

    def test_missing_archive_or_split_volume_cannot_prepare_update(self):
        for archives in [[], ["firmware_tsp_v1.1.1_20251128.7z.001"]]:
            with self.subTest(archives=archives):
                process, calls = self.run_checker(archives=archives)
                self.assertNotEqual(process.returncode, 0)
                self.assert_not_prepared(calls)

    def test_incompatible_or_invalid_bundled_metadata_is_rejected(self):
        for bundled in [None, "1.1.1\n20240413\n", "1.0.4\n20261128\n", "1.1.1\nnot-a-revision\n", "../1.1.1\n20251128\n"]:
            with self.subTest(bundled=bundled):
                archives = None
                if bundled and "/" not in bundled:
                    version, revision = bundled.splitlines()
                    name = f"firmware_tsp_v{version}_{revision}.7z"
                    archives = [name + ".001", name + ".002"]
                process, calls = self.run_checker(bundled=bundled, archives=archives)
                self.assertNotEqual(process.returncode, 0)
                self.assert_not_prepared(calls)

    def test_brick_and_unknown_device_are_rejected_before_preparation(self):
        for device in ["brick", "smartpro_s", "unknown"]:
            with self.subTest(device=device):
                process, calls = self.run_checker(device=device)
                self.assertNotEqual(process.returncode, 0)
                self.assert_not_prepared(calls)
                self.assertNotIn("7zz l ", calls)

    def test_matching_existing_image_skips_extraction(self):
        process, calls = self.run_checker(existing_crc="1234abcd")
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertNotIn("7zz x ", calls)
        self.assertIn("Ready for update!", calls)

    def test_mismatching_existing_image_is_replaced_and_verified(self):
        process, calls = self.run_checker(existing_crc="DEADBEEF")
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertIn("7zz x ", calls)
        self.assertIn("Ready for update!", calls)

    def test_bad_extracted_crc_never_prepares_update(self):
        process, calls = self.run_checker(extracted_crc="DEADBEEF")
        self.assertNotEqual(process.returncode, 0)
        self.assertNotIn("backup\n", calls)
        self.assertNotIn("Ready for update!", calls)

    def test_failed_crc_utility_never_prepares_update(self):
        process, calls = self.run_checker(crc_failure=True)
        self.assertNotEqual(process.returncode, 0)
        self.assertNotIn("backup\n", calls)
        self.assertNotIn("Ready for update!", calls)

    def test_invalid_archive_listing_is_rejected_before_extraction(self):
        for options in [{"listing_failure": True}, {"listing_crc": ""}, {"listing_crc": "NOTACRC!"}, {"listing_size": ""}, {"listing_size": "0"}, {"listing_image": "trimui_tg3040.awimg"}]:
            with self.subTest(options=options):
                process, calls = self.run_checker(**options)
                self.assertNotEqual(process.returncode, 0)
                self.assert_not_prepared(calls)

    def test_extraction_failure_never_prepares_update(self):
        process, calls = self.run_checker(extraction_failure=True)
        self.assertNotEqual(process.returncode, 0)
        self.assertNotIn("backup\n", calls)
        self.assertNotIn("Ready for update!", calls)

    def test_sufficient_current_firmware_does_not_extract_or_backup(self):
        process, calls = self.run_checker(current_revision="20251128")
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assert_not_prepared(calls)

    def test_invalid_current_revision_fails_before_preparation(self):
        for revision in ["", "invalid", "20251128'", "2025:2026"]:
            with self.subTest(revision=revision):
                process, calls = self.run_checker(current_revision=revision)
                self.assertNotEqual(process.returncode, 0)
                self.assert_not_prepared(calls)


if __name__ == "__main__":
    unittest.main()
