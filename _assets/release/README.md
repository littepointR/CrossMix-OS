# Smart Pro preview packaging

The release workflow builds the installed version from `System/usr/trimui/crossmix-version.txt`, packages a full checkout, and creates only draft prereleases on `v*` tags. Manual runs produce reviewable Actions artifacts without creating a Release. Repository paths and source links derive from the current GitHub repository and commit. Both firmware/updater regressions and packaging tests gate the build. `--prepare` rejects sparse or missing tracked inputs before unpacking cores; use a fresh full checkout because preparation replaces archived cores with their extracted runtime files.

Run the small packaging checks without downloading emulator binaries:

```sh
python -m unittest discover -s _assets/release -p 'test_*.py' -v
```

To build a full preview on Linux with 7-Zip installed, use an output directory outside the checkout:

```sh
python _assets/release/package_release.py --source "$PWD" --output /tmp/crossmix-release --repository owner/repository --commit "$(git rev-parse HEAD)" --tag v1.3.6 --prerelease --prepare
```

The payload retains the root LICENSE, README and nested component notices. It excludes development directories, BIOS/game payloads, and restricted or unconfirmed Doom/Stardew PortMaster theme assets. Source files stay in Git history; package exclusions are recorded in `RELEASE_EXCLUSIONS.json`. Existing BIOS and ROM files must be preserved by the updater. This policy does not establish permission or complete corresponding-source coverage for every remaining binary; those inventories and Smart Pro hardware acceptance remain pending.

The ZIP includes `System/updates/installed_release.json` with its repository, tag and prerelease status, so a manual preview install can later move to a stable release with the same numeric version. Preview is explicit (`--prerelease`, also the default); a future accepted stable build can use `--no-prerelease`. OTA replaces installed metadata with the verified GitHub API status after installation.

Asset protocol: `release-manifest.json` schema 1, `device: "tsp"`, `version`, `archive_name`, `archive_size`, `uncompressed_size`, `archive_sha256`, and ordered `parts` with `name`, `size`, `sha256`. A small archive is `CrossMix-OS_vX.Y.Z.zip`; an archive larger than 1900 MiB is byte-split into `.zip.001`, `.zip.002`, and so on. Concatenating verified parts in order reproduces the ZIP and its archive hash. SHA256SUMS covers every numbered archive part, the reconstructed ZIP, the release manifest, and release notes. Before reassembly, use `sha256sum --check --ignore-missing SHA256SUMS` to verify the available parts; after reassembly, verify the full ZIP too. OTA installation must reserve space for both downloaded parts and the reconstructed ZIP as well as the normal update workspace.
