# CrossMix-OS · Smart Pro maintenance fork

An independently maintained fork of [cizia64/CrossMix-OS](https://github.com/cizia64/CrossMix-OS), focused on fixes and reliable releases for **TrimUI Smart Pro (TSP / TG5040)**.

本分支从上游 `main` 的 `206d612fdef83972ed54a17de955125d0c0b3528` 开始，先维护 Smart Pro 的现有软件功能。首个维护版本为 **1.3.6**。它仍使用 TrimUI 官方底层固件和界面；当前发布流程只生成供审核和实机验证的草稿预发布版。

**支持范围：Smart Pro。Brick 和其他型号暂不支持。** 主分支包含未发布的维护工作，不能直接当作已验证的 SD 卡发行包使用。

## 下载与安装

- 本分支的 [Releases](https://github.com/littepointR/CrossMix-OS/releases) 和 [Actions](https://github.com/littepointR/CrossMix-OS/actions) 是自己的发布渠道。
- [安装和迁移说明](docs/installation.md)：首次迁入本分支使用手动安装，建议备用 SD 卡。
- [Smart Pro 实机验收清单](docs/device-validation.md)：预发布转正式版前需要完成的检查。
- [维护与发布说明](docs/maintenance.md)：版本、更新协议和本地检查。
- [变更记录](CHANGELOG.md)。

包内更新配置位于 `System/etc/update.json`。稳定渠道只接受本 fork 的正式 Release；测试渠道可以接受本 fork 的预发布版。草稿 Release 不会出现在公开 OTA 中。首次迁移前的原版更新器仍指向上游，必须通过手动安装迁入本分支。

## 首个维护版本

1. 将更新仓库、渠道和发布元数据独立到本 fork，使用包内更新器，停止从远程主分支执行 bootstrap 和 hotfix。
2. 校验发布清单、下载分卷和重组 ZIP 的 SHA256，下载与验证成功后才进入安装阶段。
3. 使用不依赖固定仓库目录的 GitHub Actions 打包流程，保留许可证和来源说明，支持超过单资产限额的分卷。
4. 修复最低固件版本与附带固件版本不同导致的检查失败，保留原最低版本要求，并限制固件准备流程只用于 Smart Pro。

这些是代码与自动化检查的范围，实机启动、休眠、模拟器、升级和恢复仍需要设备验收。发行包不附带需要用户自行提供的 BIOS/游戏数据，也不包含许可范围受限或未确认的 Doom/Stardew PortMaster 主题资源。已有 SD 卡中的 BIOS、ROM、存档和设置应在迁移前备份。

## 来源与许可

感谢原作者 **Cizia**，以及 **Schmurtzm、Kloptops、PortMaster、libretro** 和上游贡献者。保留完整上游 Git 历史；原版介绍与署名可在 [基线 README](https://github.com/cizia64/CrossMix-OS/blob/206d612fdef83972ed54a17de955125d0c0b3528/README.md) 查看。[原版 Wiki](https://github.com/cizia64/CrossMix-OS/wiki) 可作为既有功能参考，它不代表本分支的发布或支持渠道。

CrossMix 代码根许可证为 [GPLv3](LICENSE)。第三方程序、素材、固件和游戏具有各自许可条件，根许可证不覆盖一切。发布工具记录包中排除的资源和来源信息；完整第三方对应源码核对仍是后续维护事项。TrimUI 的 [固件仓库](https://github.com/trimui/firmware_smartpro) 和 [SDK 仓库](https://github.com/trimui/toolchain_sdk_smartpro) 是底层兼容性参考。

问题与修复请提交到 [本 fork 的 Issues](https://github.com/littepointR/CrossMix-OS/issues) 或 Pull Requests。
