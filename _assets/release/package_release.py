#!/usr/bin/env python3
"""Build the Smart Pro preview payload and a checksum-addressed release manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import zipfile

UPSTREAM_COMMIT = "206d612fdef83972ed54a17de955125d0c0b3528"
PART_SIZE = 1900 * 1024 * 1024
GITHUB_ASSET_LIMIT = 2 * 1024 * 1024 * 1024
CHUNK_SIZE = 1024 * 1024
OMITTED_ROOTS = {".git", ".github", "_assets"}
OMITTED_THEMES = {
    "Apps/PortMaster/PortMaster/themes/Doom",
    "Apps/PortMaster/PortMaster/themes/Stardew",
}
VERSION_PATH = "System/usr/trimui/crossmix-version.txt"


def is_notice(path: Path) -> bool:
    name = path.name.lower()
    return name.endswith((".md", ".txt")) or name.startswith(
        ("license", "copying", "copyright", "readme", "notice", "authors")
    )


def exclusion(path: Path) -> str | None:
    relative = path.as_posix()
    if relative == "System/updates/installed_release.json":
        return "installed release metadata is generated for this build"
    if path.parts[0] in OMITTED_ROOTS:
        return "repository and development files"
    if path.name == ".gitkeep":
        return "Git placeholder; its parent directory is retained"
    if any(relative == theme or relative.startswith(theme + "/") for theme in OMITTED_THEMES):
        return None if is_notice(path) else "theme assets with restricted or unconfirmed redistribution scope"
    if path.parts[0] in {"BIOS", "Roms"} or relative.startswith("Best/Free Games Collection/Roms/"):
        return None if is_notice(path) else "user-supplied BIOS and game payloads"
    return None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_archive_tool(args: list[str], root: Path) -> None:
    result = subprocess.run(
        args, cwd=root, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", check=False,
    )
    if result.returncode:
        raise RuntimeError(f"Archive preparation failed: {args[0]} (exit {result.returncode}): {result.stderr[-1200:]}")


def prepare_cores(root: Path) -> None:
    tool = shutil.which("7zz") or shutil.which("7z")
    if not tool:
        raise RuntimeError("7-Zip (7zz or 7z) is required to prepare the payload")
    cores = root / "RetroArch/.retroarch/cores"
    if not cores.is_dir():
        raise ValueError("RetroArch cores are missing; release builds require a full checkout")
    for archive in sorted(cores.glob("*.7z")):
        run_archive_tool([tool, "x", "-y", str(archive), f"-o{cores}"], root)
        archive.unlink()
    config = root / "RetroArch/retroarch.cfg"
    if not config.is_file():
        raise ValueError("RetroArch configuration is missing")
    default = root / "RetroArch/default_config.7z"
    default.unlink(missing_ok=True)
    run_archive_tool(
        [tool, "a", "-y", "RetroArch/default_config.7z", "RetroArch/retroarch.cfg", "RetroArch/.retroarch/config/*"],
        root,
    )


def validate_preparation_source(root: Path) -> None:
    if (root / ".git").exists():
        sparse = subprocess.run(["git", "config", "--bool", "core.sparseCheckout"], cwd=root,
                                capture_output=True, text=True, check=False)
        if sparse.returncode not in (0, 1):
            raise ValueError("Cannot inspect checkout completeness")
        if sparse.stdout.strip() == "true":
            raise ValueError("Release preparation requires a full checkout; sparse checkout is enabled")
        tracked = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, check=True)
        missing = [name for name in tracked.stdout.decode("utf-8").split("\0") if name and not (root / name).is_file()]
        if missing:
            raise ValueError("Release checkout has missing tracked files: " + ", ".join(missing[:5]))
    required = [VERSION_PATH, "LICENSE", "System/bin/7zz", "trimui/app/preload.sh", "trimui/app/trimui_inputd"]
    missing = [name for name in required if not (root / name).is_file()]
    if missing:
        raise ValueError("Release input is incomplete: " + ", ".join(missing))


def inventory(root: Path) -> tuple[list[Path], list[str], list[dict[str, str]]]:
    files: list[Path] = []
    directories: list[str] = []
    omitted: list[dict[str, str]] = []
    for base, dirs, names in os.walk(root, followlinks=False):
        base_path = Path(base)
        if base_path == root:
            dirs[:] = sorted(name for name in dirs if name not in OMITTED_ROOTS)
        else:
            dirs.sort()
            directories.append(base_path.relative_to(root).as_posix() + "/")
        for name in sorted(names):
            absolute = base_path / name
            relative = absolute.relative_to(root)
            if absolute.is_symlink():
                raise ValueError(f"Unexpected symbolic link in release input: {relative}")
            reason = exclusion(relative)
            if reason:
                omitted.append({"path": relative.as_posix(), "reason": reason})
            else:
                files.append(relative)
    return sorted(files), sorted(set(directories + ["BIOS/", "Roms/"])), omitted


def add_text(archive: zipfile.ZipFile, name: str, content: str) -> None:
    item = zipfile.ZipInfo(name, date_time=(2026, 10, 13, 0, 0, 0))
    item.compress_type = zipfile.ZIP_DEFLATED
    item.external_attr = 0o100644 << 16
    archive.writestr(item, content.encode("utf-8"), compresslevel=9)


def split_archive(archive: Path, part_size: int) -> list[Path]:
    if not 0 < part_size < GITHUB_ASSET_LIMIT:
        raise ValueError("Every release asset must be smaller than 2 GiB")
    if archive.stat().st_size <= part_size:
        return [archive]
    parts: list[Path] = []
    with archive.open("rb") as source:
        index = 1
        while source.tell() < archive.stat().st_size:
            part = archive.with_name(f"{archive.name}.{index:03d}")
            with part.open("wb") as target:
                remaining = part_size
                while remaining:
                    chunk = source.read(min(CHUNK_SIZE, remaining))
                    if not chunk:
                        break
                    target.write(chunk)
                    remaining -= len(chunk)
            parts.append(part)
            index += 1
    archive.unlink()
    return parts


def package_source(
    root: Path, output: Path, repository: str, commit: str,
    version: str, part_size: int = PART_SIZE, tag: str | None = None, prerelease: bool = True,
) -> dict:
    root, output = root.resolve(), output.resolve()
    if output == root or root in output.parents:
        raise ValueError("Output must be outside the source tree")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Expected an owner/repository identity")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Expected the full source commit SHA")
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("Expected a numeric x.y.z maintenance version")
    if (root / VERSION_PATH).read_text(encoding="utf-8").strip() != version:
        raise ValueError("Release version must match the installed version file")
    if not (root / "LICENSE").is_file():
        raise ValueError("The integration license must be retained in every payload")
    if not 0 < part_size < GITHUB_ASSET_LIMIT:
        raise ValueError("Every release asset must be smaller than 2 GiB")
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("Output directory must be empty to prevent stale release assets")
    files, directories, omitted = inventory(root)
    identity = {
        "schema": 1, "device": "tsp", "version": version,
        "repository": repository, "commit": commit, "tag": tag or f"v{version}",
        "prerelease": prerelease,
        "upstream_baseline": UPSTREAM_COMMIT,
        "hardware_validation": "pending", "component_source_audit": "pending",
    }
    source_url = f"https://github.com/{repository}/tree/{commit}"
    source_text = (
        f"Smart Pro maintenance preview {version}\n"
        f"Integration source: {source_url}\n"
        f"Integration source archive: https://github.com/{repository}/archive/{commit}.tar.gz\n"
        f"Upstream baseline: https://github.com/cizia64/CrossMix-OS/tree/{UPSTREAM_COMMIT}\n\n"
        "The root LICENSE applies to the integration project. Third-party files retain their own licenses.\n"
        "The integration repository does not claim to contain corresponding source for every bundled binary.\n"
        "Component source inventory and device validation are pending; this build remains a draft preview.\n"
        "Existing component LICENSE, COPYING, copyright and README files are retained.\n"
        "User BIOS/game payloads and restricted or unconfirmed theme assets are omitted from this archive.\n"
        "See RELEASE_EXCLUSIONS.json for the exact omitted file list.\n"
    )
    archive_path = output / f"CrossMix-OS_v{version}.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9, allowZip64=True) as archive:
        for directory in directories:
            archive.writestr(directory, b"")
        for relative in files:
            archive.write(root / relative, relative.as_posix())
        add_text(archive, "SOURCE_INFORMATION.txt", source_text)
        add_text(archive, "RELEASE_INFO.json", json.dumps(identity, indent=2) + "\n")
        add_text(archive, "System/updates/installed_release.json", json.dumps(
            {key: identity[key] for key in ("repository", "tag", "prerelease")}, indent=2) + "\n")
        add_text(archive, "RELEASE_EXCLUSIONS.json", json.dumps(omitted, indent=2, ensure_ascii=False) + "\n")
        add_text(archive, "BIOS/INSTALL_USER_BIOS.txt", "Copy your own required BIOS files into this directory. Existing BIOS files are preserved by the maintenance updater.\n")
        uncompressed_size = sum(item.file_size for item in archive.infolist())
    archive_size = archive_path.stat().st_size
    archive_hash = sha256(archive_path)
    parts = split_archive(archive_path, part_size)
    manifest = dict(identity, archive_name=archive_path.name, archive_size=archive_size,
                    uncompressed_size=uncompressed_size, archive_sha256=archive_hash,
                    parts=[{"name": path.name, "size": path.stat().st_size, "sha256": sha256(path)} for path in parts])
    manifest_path = output / "release-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    notes = (
        f"# Smart Pro maintenance preview v{version}\n\n"
        "This draft targets TrimUI Smart Pro only. Hardware acceptance and the component source inventory remain pending.\n\n"
        f"Integration source: [{commit}]({source_url}). Root and nested license notices are retained in the package.\n\n"
        "BIOS and bundled game payloads are omitted; supply your own. Restricted or unconfirmed Doom/Stardew theme assets are omitted; their license/readme notices remain. See the payload exclusion manifest.\n\n"
        "Verify SHA256SUMS before using the assets. If the archive is split, download every numbered .zip.001/.002 part, verify each hash, and concatenate them in numeric order into the archive_name listed in release-manifest.json. The fork OTA performs this verification and reassembly.\n\n"
        "The manifest includes hashes for both individual parts and the complete ZIP. This build does not claim full third-party corresponding-source compliance or verified firmware compatibility.\n"
    )
    notes_path = output / "RELEASE_NOTES.md"
    notes_path.write_text(notes, encoding="utf-8", newline="\n")
    checksum_files = parts + [manifest_path, notes_path]
    checksum_text = "".join(f"{sha256(path)}  {path.name}\n" for path in checksum_files)
    if len(parts) > 1:
        checksum_text += f"{archive_hash}  {archive_path.name}\n"
    (output / "SHA256SUMS").write_text(
        checksum_text,
        encoding="ascii", newline="\n",
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--tag", default="")
    parser.add_argument("--part-size-mib", type=int, default=1900)
    parser.add_argument("--prerelease", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--prepare", action="store_true")
    args = parser.parse_args()
    version = (args.source / VERSION_PATH).read_text(encoding="utf-8").strip()
    if args.tag.startswith("v") and not re.fullmatch(r"v" + re.escape(version) + r"(?:-[A-Za-z0-9.-]+)?", args.tag):
        raise ValueError("Tag must match the installed maintenance version")
    if args.prepare:
        validate_preparation_source(args.source.resolve())
        prepare_cores(args.source.resolve())
    manifest = package_source(args.source, args.output, args.repository, args.commit, version,
                              args.part_size_mib * 1024 * 1024, args.tag if args.tag.startswith("v") else None,
                              args.prerelease)
    print(json.dumps({"version": version, "device": manifest["device"], "archive_size": manifest["archive_size"],
                      "assets": [part["name"] for part in manifest["parts"]]}))


if __name__ == "__main__":
    main()
