# Changelog

## 1.3.6 — Smart Pro maintenance preview

Base: upstream `main` at `206d612fdef83972ed54a17de955125d0c0b3528`. Its installed-version file still said 1.3.0 despite containing later unpublished improvements. This fork selects 1.3.6 as its independent maintenance version; it is not an upstream release.

- Move update configuration and release discovery to `littepointR/CrossMix-OS`, with stable and preview channels.
- Use the packaged updater instead of executing bootstrap/hotfix scripts fetched from a mutable remote branch.
- Validate Smart Pro release manifests, archive parts and complete ZIP checksums before installation.
- Make packaging independent of repository name and runner directory. Keep license notices and source references, support large archives with numbered parts, and create draft prereleases for review.
- Exclude BIOS/game payloads and restricted or unconfirmed Doom/Stardew PortMaster theme assets from new packages. Keep source history and record exclusions.
- Fix firmware archive selection when the minimum supported version differs from the bundled version, validate the expected TG5040 image, and correct the firmware backup existence test.
- Add packaging, updater and firmware fixture tests that run without a physical device.

Hardware acceptance is pending. No firmware was flashed during development. Packaging checks do not establish full third-party corresponding-source coverage.
