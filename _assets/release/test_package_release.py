import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import zipfile

import package_release


class ReleasePackagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "source"
        self.output = self.base / "release"
        self.root.mkdir()
        self.write("LICENSE", "integration GPL license")
        self.write(package_release.VERSION_PATH, "1.3.6")
        self.write("System/start.sh", "#!/bin/sh\necho preview\n")
        self.write("BIOS/private.bin", b"private BIOS")
        self.write("BIOS/LICENSE.vendor", "retain vendor notice")
        self.write("Roms/SNES/private.sfc", b"private game")
        self.write("Roms/SNES/.gitkeep", "")
        self.write("Best/Free Games Collection/Roms/GB/game.gb", b"bundled game")
        self.write("Apps/PortMaster/PortMaster/themes/Doom/sound.ogg", b"theme data")
        self.write("Apps/PortMaster/PortMaster/themes/Doom/amazdoomlicense.txt", "noncommercial notice")
        self.write("Apps/PortMaster/PortMaster/themes/Stardew/music.ogg", b"theme data")
        self.write("Apps/PortMaster/PortMaster/themes/Stardew/OstUseLicense.txt", "permission note")
        self.write("Apps/PortMaster/PortMaster/themes/default/theme.json", "{}")
        self.write("Emus/N64/doc/LICENSES", "component license")
        self.write("_assets/private.bin", b"development file")
        self.write(".git/config", "private git state")
        self.write(".github/workflows/build.yml", "development workflow")

    def write(self, relative, content):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if isinstance(content, bytes) else content.encode())

    def package(self, part_size=package_release.PART_SIZE):
        return package_release.package_source(self.root, self.output, "maintainer/independent-fork", "a" * 40, "1.3.6", part_size)

    def test_clean_payload_keeps_notices_and_empty_game_directories(self):
        manifest = self.package()
        with zipfile.ZipFile(self.output / manifest["archive_name"]) as archive:
            names = set(archive.namelist())
            self.assertIn("LICENSE", names)
            self.assertIn("Emus/N64/doc/LICENSES", names)
            self.assertIn("BIOS/LICENSE.vendor", names)
            self.assertIn("Roms/SNES/", names)
            self.assertIn("Apps/PortMaster/PortMaster/themes/Doom/amazdoomlicense.txt", names)
            self.assertIn("Apps/PortMaster/PortMaster/themes/Stardew/OstUseLicense.txt", names)
            self.assertIn("Apps/PortMaster/PortMaster/themes/default/theme.json", names)
            for omitted in ["BIOS/private.bin", "Roms/SNES/private.sfc", "Best/Free Games Collection/Roms/GB/game.gb",
                            "Apps/PortMaster/PortMaster/themes/Doom/sound.ogg", "Apps/PortMaster/PortMaster/themes/Stardew/music.ogg",
                            "_assets/private.bin", ".git/config", ".github/workflows/build.yml", "Roms/SNES/.gitkeep"]:
                self.assertNotIn(omitted, names)
            exclusions = json.loads(archive.read("RELEASE_EXCLUSIONS.json"))
            self.assertIn("BIOS/private.bin", {entry["path"] for entry in exclusions})
            info = json.loads(archive.read("RELEASE_INFO.json"))
            self.assertEqual(info["device"], "tsp")
            self.assertEqual(info["hardware_validation"], "pending")
            installed = json.loads(archive.read("System/updates/installed_release.json"))
            self.assertEqual(installed, {"repository": "maintainer/independent-fork", "tag": "v1.3.6", "prerelease": True})
            self.assertIn(b"maintainer/independent-fork", archive.read("SOURCE_INFORMATION.txt"))
            self.assertEqual(manifest["uncompressed_size"], sum(item.file_size for item in archive.infolist()))

    def test_split_parts_reconstruct_a_valid_zip_and_verify_all_hashes(self):
        self.write("System/data.bin", bytes(range(256)) * 10)
        manifest = self.package(part_size=1024)
        self.assertGreater(len(manifest["parts"]), 1)
        joined = b"".join((self.output / part["name"]).read_bytes() for part in manifest["parts"])
        self.assertEqual(len(joined), manifest["archive_size"])
        self.assertEqual(hashlib.sha256(joined).hexdigest(), manifest["archive_sha256"])
        for index, part in enumerate(manifest["parts"], 1):
            self.assertEqual(part["name"], f"{manifest['archive_name']}.{index:03d}")
            self.assertLessEqual(part["size"], 1024)
            self.assertEqual(package_release.sha256(self.output / part["name"]), part["sha256"])
        reconstructed = self.base / "reconstructed.zip"
        reconstructed.write_bytes(joined)
        with zipfile.ZipFile(reconstructed) as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual(archive.read("System/data.bin"), bytes(range(256)) * 10)
        for row in (self.output / "SHA256SUMS").read_text().splitlines():
            digest, name = row.split("  ", 1)
            path = self.output / name if name != manifest["archive_name"] else reconstructed
            self.assertEqual(package_release.sha256(path), digest)

    def test_missing_license_and_mismatched_versions_stop_packaging(self):
        (self.root / "LICENSE").unlink()
        with self.assertRaisesRegex(ValueError, "license"):
            self.package()
        self.write("LICENSE", "license")
        self.write(package_release.VERSION_PATH, "1.3.5")
        with self.assertRaisesRegex(ValueError, "version"):
            self.package()

    def test_output_inside_source_and_oversized_assets_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "outside"):
            package_release.package_source(self.root, self.root / "release", "owner/repo", "a" * 40, "1.3.6")
        with self.assertRaisesRegex(ValueError, "2 GiB"):
            self.package(part_size=package_release.GITHUB_ASSET_LIMIT)

    def test_nonempty_output_does_not_mix_stale_assets(self):
        self.output.mkdir()
        (self.output / "stale.zip").write_bytes(b"stale")
        with self.assertRaisesRegex(ValueError, "empty"):
            self.package()

    @unittest.skipUnless(shutil.which("git"), "Git is required for the sparse checkout regression")
    def test_sparse_checkout_is_rejected_before_preparation_mutates_files(self):
        sparse = self.base / "sparse"
        sparse.mkdir()
        subprocess.run(["git", "init", "--quiet", str(sparse)], check=True)
        subprocess.run(["git", "config", "core.sparseCheckout", "true"], cwd=sparse, check=True)
        archive = sparse / "RetroArch/.retroarch/cores/test_libretro.7z"
        archive.parent.mkdir(parents=True)
        archive.write_bytes(b"original archived core")
        with self.assertRaisesRegex(ValueError, "sparse checkout"):
            package_release.validate_preparation_source(sparse)
        self.assertEqual(archive.read_bytes(), b"original archived core")


if __name__ == "__main__":
    unittest.main()
