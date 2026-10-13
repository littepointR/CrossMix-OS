"""Run the real POSIX updater against mocked GitHub assets; never access a device.

python _assets/tests/test_updater.py --shell /bin/bash --jq /path/to/jq
On Windows, use Git for Windows bash and a native jq executable.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[2]
REPO = "littepointR/CrossMix-OS"
SHELL = "bash"
JQ = "jq"


def shell_path(path):
    value = str(Path(path).resolve()).replace("\\", "/")
    return "/" + value[0].lower() + value[2:] if len(value) > 1 and value[1] == ":" else value


def sha(data):
    return hashlib.sha256(data).hexdigest()


class UpdaterTest(unittest.TestCase):
    def setUp(self):
        test_tmp = ROOT / "_assets/tests/.tools"
        test_tmp.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="crossmix-updater-", dir=test_tmp)
        self.work = Path(self.temp.name)
        self.sd = self.work / "sd"
        self.bin = self.work / "bin"
        self.assets = self.work / "assets"
        for path in [self.bin, self.assets, self.sd / "System/bin", self.sd / "System/etc", self.sd / "System/usr/trimui"]:
            path.mkdir(parents=True)
        (self.sd / "System/usr/trimui/crossmix-version.txt").write_text("1.3.5\n")
        (self.sd / "System/usr/trimui/update-repository.txt").write_text(REPO + "\n")
        (self.sd / "System/etc/update.json").write_text(json.dumps({"repository": REPO, "channel": "stable", "device": "tsp"}))
        scripts = self.sd / "System/usr/trimui/scripts"
        scripts.mkdir()
        for name in ["update_common.sh", "update_ota_release.sh", "update_notification.sh", "crossmix_update.sh"]:
            shutil.copyfile(ROOT / "System/usr/trimui/scripts" / name, scripts / name)
        self.write_mock("curl", r'''#!/bin/sh
out=""
while [ "$#" -gt 0 ]; do
    case "$1" in -o) out=$2; shift 2;; -H|--retry|--connect-timeout|--max-time) shift 2;; -*) shift;; *) url=$1; shift;; esac
done
printf '%s\n' "$url" >> "$FIXTURE/network.log"
case "$url" in
    https://api.github.com/repos/littepointR/CrossMix-OS/releases\?per_page=100) src="$FIXTURE/releases.json";;
    https://github.com/littepointR/CrossMix-OS/releases/download/*) src="$FIXTURE/assets/${url##*/}";;
    *) exit 22;;
esac
[ -f "$src" ] || exit 22
if [ -n "$out" ]; then cp "$src" "$out"; else cat "$src"; fi
''')
        self.write_mock("df", "#!/bin/sh\nprintf 'Filesystem 1024-blocks Used Available Capacity Mounted\\nmock 30000000 1 %s 1%% /\\n' \"${MOCK_FREE_KB:-20000000}\"\n")
        self.write_mock("ip", "#!/bin/sh\necho '1.0.0.0 dev wlan0 src 192.168.1.10'\n")
        self.write_mock("pkill", "#!/bin/sh\nexit 0\n")
        # Native Windows jq prints CRLF; the handheld's jq prints LF.
        self.write_mock("jq", '#!/bin/sh\nset -o pipefail\n"' + shell_path(JQ) + '" "$@" | tr -d "\\r"\n')
        self.write_mock("7zz", '''#!/bin/sh
case "$1" in
  t) unzip -t "$2" >/dev/null;;
  l) printf '%s\\n' '----------'; unzip -Z -1 "$3" | sed 's/^/Path = /';;
  e)
    archive=$2; entry=$3; shift 3
    for arg in "$@"; do case "$arg" in -o*) out=${arg#-o};; esac; done
    unzip -p "$archive" "$entry" > "$out/${entry##*/}";;
  *) exit 99;;
esac
''', self.sd / "System/bin")

    def tearDown(self):
        self.temp.cleanup()

    def write_mock(self, name, text, where=None):
        path = (where or self.bin) / name
        path.write_text(text, encoding="utf-8", newline="\n")
        path.chmod(0o755)

    def fixture(self, split=False, prerelease=False, version="1.3.6", tag=None):
        archive = "CrossMix-OS_v" + version + ".zip"
        zip_path = self.assets / archive
        with zipfile.ZipFile(zip_path, "w") as z:
            z.writestr("System/usr/trimui/scripts/crossmix_update.sh", "#!/bin/sh\necho installer\n")
            z.writestr("System/usr/trimui/crossmix-version.txt", version + "\n")
        data = zip_path.read_bytes()
        chunks = [data[:len(data)//2], data[len(data)//2:]] if split else [data]
        parts = []
        for i, chunk in enumerate(chunks):
            name = archive + f".{i+1:03d}" if split else archive
            (self.assets / name).write_bytes(chunk)
            parts.append({"name": name, "size": len(chunk), "sha256": sha(chunk)})
        if split:
            zip_path.unlink()
        manifest = {"schema": 1, "device": "tsp", "version": version, "archive_name": archive,
                    "archive_size": len(data), "archive_sha256": sha(data), "uncompressed_size": 100, "parts": parts}
        self.manifest = manifest
        (self.assets / "release-manifest.json").write_text(json.dumps(manifest))
        sums = {p["name"]: p["sha256"] for p in parts}
        sums[archive] = sha(data)
        (self.assets / "SHA256SUMS").write_text("".join(f"{digest}  {name}\n" for name, digest in sums.items()), newline="\n")
        tag = tag or "v" + version
        assets = [{"name": p.name, "size": p.stat().st_size,
                   "browser_download_url": f"https://github.com/{REPO}/releases/download/{tag}/{p.name}"}
                  for p in self.assets.iterdir()]
        release = {"id": 123, "tag_name": tag, "prerelease": prerelease, "draft": False,
                   "published_at": "2026-10-13T00:00:00Z", "body": "Fixture", "assets": assets}
        (self.work / "releases.json").write_text(json.dumps([release]))
        return data, release

    def run_sh(self, body, **extra):
        env = os.environ.copy()
        env.update({"CROSSMIX_SDCARD_ROOT": shell_path(self.sd), "FIXTURE": shell_path(self.work),
                    "PATH": shell_path(self.bin) + ":" + env.get("PATH", ""), **extra})
        script = 'export PATH="' + shell_path(self.bin) + ':$PATH"\n. "' + shell_path(ROOT / "System/usr/trimui/scripts/update_common.sh") + '"\n' + body
        return subprocess.run([SHELL, "-c", script], env=env, capture_output=True, text=True)

    def download(self, **extra):
        return self.run_sh('crossmix_fetch_release || exit $?\ncrossmix_download_release || exit $?\nprintf "VERIFIED=%s\\n" "$Verified_Archive"\n', **extra)

    def test_single_zip_is_verified(self):
        data, _ = self.fixture()
        result = self.download()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.sd / "System/updates/CrossMix-OS_v1.3.6.zip").read_bytes(), data)
        self.assertFalse((self.sd / "CrossMix-OS_v1.3.6.zip").exists())

    def test_split_zip_is_reassembled_exactly(self):
        data, _ = self.fixture(split=True)
        result = self.download()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.sd / "System/updates/CrossMix-OS_v1.3.6.zip").read_bytes(), data)

    def test_corrupt_part_fails_before_staging(self):
        self.fixture(split=True)
        part = self.assets / self.manifest["parts"][0]["name"]
        part.write_bytes(b"x" * part.stat().st_size)
        result = self.download()
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.sd / "System/updates/CrossMix-OS_v1.3.6.zip").exists())
        self.assertFalse((self.sd / "CrossMix-OS_v1.3.6.zip").exists())

    def test_low_space_stops_before_archive_download(self):
        self.fixture(split=True)
        result = self.download(MOCK_FREE_KB="1")
        self.assertNotEqual(result.returncode, 0)
        network = (self.work / "network.log").read_text()
        self.assertNotIn(".zip.001", network)

    def test_installer_reserve_is_kept_in_addition_to_download(self):
        self.fixture()
        result = self.download(MOCK_FREE_KB="5242880")
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(".zip\n", (self.work / "network.log").read_text())

    def test_cached_archive_does_not_bypass_install_space_check(self):
        self.fixture()
        result = self.run_sh('crossmix_fetch_release && crossmix_download_release || exit $?\nexport MOCK_FREE_KB=1\ncrossmix_download_release\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Insufficient free space", result.stderr)

    def test_expanded_manifest_space_is_required_by_install_preflight(self):
        self.fixture()
        result = self.run_sh('crossmix_fetch_release && crossmix_download_release && crossmix_stage_release || exit $?\njq \' .uncompressed_size = 17179869184 \' "$updatedir/pending_release.json" > "$updatedir/pending.tmp" && mv "$updatedir/pending.tmp" "$updatedir/pending_release.json"\nexport MOCK_FREE_KB=6291456\ncrossmix_install_preflight "$SDCARD_ROOT/$Release_Name"\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Insufficient free space", result.stderr)

    def test_stable_excludes_prerelease(self):
        self.fixture(prerelease=True, tag="v1.3.6-preview.1")
        self.assertNotEqual(self.download().returncode, 0)

    def test_prerelease_channel_accepts_preview(self):
        self.fixture(prerelease=True, tag="v1.3.6-preview.1")
        (self.sd / "System/etc/update.json").write_text(json.dumps({"repository": REPO, "channel": "prerelease", "device": "tsp"}))
        result = self.download()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_bad_manifest_device_fails(self):
        self.fixture()
        self.manifest["device"] = "brick"
        (self.assets / "release-manifest.json").write_text(json.dumps(self.manifest))
        self.assertNotEqual(self.download().returncode, 0)

    def test_checksum_manifest_disagreement_stops_before_payload(self):
        self.fixture()
        (self.assets / "SHA256SUMS").write_text("0" * 64 + "  " + self.manifest["archive_name"] + "\n", newline="\n")
        self.assertNotEqual(self.download().returncode, 0)
        self.assertNotIn(".zip\n", (self.work / "network.log").read_text())

    def test_non_fork_download_url_is_rejected_before_download(self):
        _, release = self.fixture()
        release["assets"][0]["browser_download_url"] = "https://example.invalid/third-party.zip"
        (self.work / "releases.json").write_text(json.dumps([release]))
        self.assertNotEqual(self.download().returncode, 0)
        self.assertNotIn("example.invalid", (self.work / "network.log").read_text())

    def test_missing_part_stops_without_installing_files(self):
        self.fixture(split=True)
        (self.assets / self.manifest["parts"][1]["name"]).unlink()
        self.assertNotEqual(self.download().returncode, 0)
        self.assertFalse((self.sd / "System/updates/CrossMix-OS_v1.3.6.zip").exists())

    def test_stage_and_install_preflight_use_verified_manifest(self):
        data, _ = self.fixture(split=True)
        result = self.run_sh('crossmix_fetch_release && crossmix_download_release && crossmix_stage_release && crossmix_install_preflight "$SDCARD_ROOT/$Release_Name"\n')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.sd / "CrossMix-OS_v1.3.6.zip").read_bytes(), data)
        pending = json.loads((self.sd / "System/updates/pending_release.json").read_text())
        self.assertEqual(pending["repository"], REPO)
        self.assertEqual(pending["tag"], "v1.3.6")

    def test_install_preflight_rejects_changed_staged_archive(self):
        self.fixture()
        result = self.run_sh('crossmix_fetch_release && crossmix_download_release && crossmix_stage_release || exit $?\nprintf corrupted >> "$SDCARD_ROOT/$Release_Name"\ncrossmix_install_preflight "$SDCARD_ROOT/$Release_Name"\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SHA-256 mismatch", result.stderr)

    def test_installer_without_pending_manifest_stops_before_device_changes(self):
        data, _ = self.fixture()
        (self.sd / "CrossMix-OS_v1.3.6.zip").write_bytes(data)
        result = self.run_sh('sh "$SDCARD_ROOT/System/usr/trimui/scripts/crossmix_update.sh"\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("No matching verified pending manifest", result.stderr)
        self.assertNotIn("scaling_governor", result.stderr)
        self.assertFalse((self.sd / "_Updates").exists())

    def run_boot_handoff(self, tamper=False, same_version=False, low_space=False):
        self.fixture()
        if same_version:
            (self.sd / "System/usr/trimui/crossmix-version.txt").write_text("1.3.6\n")
            installed = self.sd / "System/updates/installed_release.json"
            installed.parent.mkdir(parents=True)
            installed.write_text(json.dumps({"repository": REPO, "tag": "v1.3.6-preview.1", "prerelease": True}))
        self.write_mock("infoscreen.sh", '#!/bin/sh\necho "${MOCK_BUTTON:-A}"\n', self.sd / "System/usr/trimui/scripts")
        self.write_mock("text_viewer", '#!/bin/sh\nprintf "%s\\n" "$*" >> "$FIXTURE/boot_install_called"\n', self.sd / "System/bin")
        internal = self.work / "internal"
        (internal / "bin").mkdir(parents=True)
        self.write_mock("trimui_inputd", "#!/bin/sh\nexit 0\n", internal / "bin")
        tmp = self.work / "boot-tmp"
        tmp.mkdir()
        boot_source = (ROOT / "System/starts/_FirmwareCheck.sh").read_text(encoding="utf-8")
        boot_section = boot_source.split("################ check if a CrossMix-OS update is available ################", 1)[1]
        boot = self.work / "boot-handoff.sh"
        boot.write_text(boot_section, encoding="utf-8", newline="\n")
        body = 'crossmix_fetch_release && crossmix_download_release && crossmix_stage_release || exit $?\n'
        if tamper:
            body += 'printf changed >> "$SDCARD_ROOT/$Release_Name"\n'
        if low_space:
            body += 'export MOCK_FREE_KB=1\n'
        # A stale earlier ZIP must never be selected instead of pending metadata.
        (self.sd / "CrossMix-OS_v0.0.1.zip").write_text("stale unrelated archive")
        body += 'sh "' + shell_path(boot) + '"\n'
        return self.run_sh(body, CROSSMIX_INTERNAL_ROOT=shell_path(internal), CROSSMIX_TMP_ROOT=shell_path(tmp))

    def test_boot_handoff_accepts_same_numeric_preview_to_stable(self):
        result = self.run_boot_handoff(same_version=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.work / "boot_install_called").exists())

    def test_boot_handoff_rejects_changed_archive_before_extract_or_ui(self):
        result = self.run_boot_handoff(tamper=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SHA-256 mismatch", result.stderr)
        self.assertFalse((self.work / "boot_install_called").exists())
        self.assertFalse(any((self.work / "boot-tmp").iterdir()))

    def test_boot_handoff_rejects_low_space_before_extract(self):
        result = self.run_boot_handoff(low_space=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Insufficient free space", result.stderr)
        self.assertFalse(any((self.work / "boot-tmp").iterdir()))

    def test_actual_interactive_client_download_only(self):
        data, _ = self.fixture(split=True)
        result = self.run_sh('sh "$SDCARD_ROOT/System/usr/trimui/scripts/update_ota_release.sh" --download-only\n')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.sd / "System/updates/CrossMix-OS_v1.3.6.zip").read_bytes(), data)

    def test_actual_boot_checker_flags_only_validated_release(self):
        self.fixture()
        result = self.run_sh('sh "$SDCARD_ROOT/System/usr/trimui/scripts/update_notification.sh" --force\n')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        available = json.loads((self.sd / "System/updates/available_release.json").read_text())
        self.assertEqual(available["repository"], REPO)
        self.assertEqual(available["channel"], "stable")
        self.assertTrue((self.sd / "System/updates/.CrossMixUpdateAvailable").exists())

    def test_packer_output_is_downloadable_by_real_updater(self):
        spec = importlib.util.spec_from_file_location("crossmix_package", ROOT / "_assets/release/package_release.py")
        package = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(package)
        source = self.work / "package-source"
        (source / "System/usr/trimui/scripts").mkdir(parents=True)
        (source / "LICENSE").write_text("fixture GPL notice")
        (source / package.VERSION_PATH).write_text("1.3.6\n")
        (source / "System/usr/trimui/scripts/crossmix_update.sh").write_text("#!/bin/sh\necho fixture\n")
        manifest = package.package_source(source, self.assets, REPO, "a" * 40, "1.3.6", 1024, "v1.3.6", False)
        release_assets = [{"name": path.name, "size": path.stat().st_size,
                           "browser_download_url": f"https://github.com/{REPO}/releases/download/v1.3.6/{path.name}"}
                          for path in self.assets.iterdir()]
        (self.work / "releases.json").write_text(json.dumps([{"id": 123, "tag_name": "v1.3.6", "prerelease": False,
            "draft": False, "published_at": "2026-10-13T00:00:00Z", "assets": release_assets}]))
        result = self.download()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        archive = self.sd / "System/updates" / manifest["archive_name"]
        self.assertEqual(sha(archive.read_bytes()), manifest["archive_sha256"])

    def test_numerical_version_does_not_downgrade(self):
        self.fixture(version="1.3.4")
        result = self.run_sh('crossmix_fetch_release || exit $?\ncrossmix_release_is_new\n')
        self.assertNotEqual(result.returncode, 0)

    def test_preview_can_upgrade_to_same_number_stable(self):
        self.fixture()
        (self.sd / "System/usr/trimui/crossmix-version.txt").write_text("1.3.6\n")
        installed = self.sd / "System/updates/installed_release.json"
        installed.parent.mkdir(parents=True)
        installed.write_text(json.dumps({"repository": REPO, "tag": "v1.3.6-preview.1", "prerelease": True}))
        result = self.run_sh('crossmix_fetch_release || exit $?\ncrossmix_release_is_new\n')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_installed_preview_is_not_offered_again(self):
        self.fixture(prerelease=True, tag="v1.3.6-preview.1")
        (self.sd / "System/usr/trimui/crossmix-version.txt").write_text("1.3.6\n")
        installed = self.sd / "System/updates/installed_release.json"
        installed.parent.mkdir(parents=True)
        installed.write_text(json.dumps({"repository": REPO, "tag": "v1.3.6-preview.1", "prerelease": True}))
        (installed.parent / "ota_channel.txt").write_text("prerelease\n")
        result = self.run_sh('crossmix_fetch_release || exit $?\ncrossmix_release_is_new\n')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)

    def test_draft_release_is_never_selected(self):
        _, release = self.fixture()
        release["draft"] = True
        (self.work / "releases.json").write_text(json.dumps([release]))
        self.assertEqual(self.download().returncode, 1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--shell", default="bash")
    parser.add_argument("--jq", default=shutil.which("jq"))
    args, remaining = parser.parse_known_args()
    if not args.jq:
        parser.error("jq is required; supply --jq")
    SHELL, JQ = args.shell, args.jq
    unittest.main(argv=[__file__, *remaining])
