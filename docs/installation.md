# Smart Pro 安装和迁移

适用于 TrimUI Smart Pro / TG5040。Brick 和其他型号不在当前支持范围内。首次维护版用于实机验证，先完整备份当前 SD 卡，建议使用备用 SD 卡。

## 发行包与校验

下载本 fork 的 Release 或 Actions 构建产物。需要构建后的发行包，GitHub 自动生成的 Source code ZIP 不等同于可安装发行包。草稿 Release 仅维护者可见，转正式版前需要完成 [验收清单](device-validation.md)。

若提供单个 `CrossMix-OS_v1.3.6.zip`，使用 `SHA256SUMS` 校验后解压。若提供 `.zip.001`、`.zip.002` 等分卷，下载所有连续分卷并逐个校验；这些是按字节切分的一个 ZIP，必须按编号顺序重组后解压。

Windows PowerShell 重组示例，文件名按实际版本调整：

```powershell
$parts = @(Get-ChildItem -File 'CrossMix-OS_v1.3.6.zip.*' | Sort-Object Name)
if ($parts.Count -eq 0) { throw '没有找到分卷' }
for ($i = 0; $i -lt $parts.Count; $i++) {
    if ($parts[$i].Name -ne ('CrossMix-OS_v1.3.6.zip.{0:d3}' -f ($i + 1))) { throw '分卷不连续' }
}
$outputPath = Join-Path (Get-Location) 'CrossMix-OS_v1.3.6.zip'
if (Test-Path -LiteralPath $outputPath) { throw '输出文件已存在' }
$outputStream = [IO.File]::OpenWrite($outputPath)
try {
    foreach ($part in $parts) {
        $inputStream = [IO.File]::OpenRead($part.FullName)
        try { $inputStream.CopyTo($outputStream) } finally { $inputStream.Dispose() }
    }
} finally { $outputStream.Dispose() }
Get-FileHash -LiteralPath $outputPath -Algorithm SHA256
```

将完整 ZIP 的 SHA256 与 `release-manifest.json` 的 `archive_sha256` 比较，并按清单核对每个分卷的大小和 SHA256。不一致时停止安装。保留足够空间供分卷、重组 ZIP 和解压结果同时存在。

## 首次安装和手动迁移

1. 备份原卡的 BIOS、ROM、普通存档、即时存档、RetroArch 配置和个人设置。保留原卡不动，是最直接的恢复方式。
2. 准备 FAT32 备用 SD 卡，将发行包解压到根目录，确认根目录直接包含 `Apps`、`Emus`、`System`、`trimui` 等目录。
3. 从备份复制自己持有的 BIOS、ROM 和存档。不要覆盖整份新 `System` 或更新配置，以免恢复成上游更新渠道。
4. 正常退出游戏并关闭 Smart Pro，再换入备用卡。连接电源，完成首次启动和验收。
5. 检查 `System/usr/trimui/crossmix-version.txt` 和 `System/etc/update.json`，确认版本与仓库属于本 fork。

从原版首次迁入必须手动安装，原版 OTA 不会自动切换到本 fork。备份可供迁移参考，不应整体覆盖新版 System。

## 迁入后的 OTA

配置支持 `stable` 或 `prerelease` 渠道。稳定渠道忽略草稿和预发布版；测试渠道允许本 fork 的预发布版。没有可用 Release 时应正常提示暂无更新，不回到原作者仓库下载脚本。

OTA 应用中的渠道选择保存在 `System/updates/ota_channel.txt`，优先于配置文件的默认渠道；开机更新检查使用同一选择。

更新器先检查元数据、下载并校验发行包，再进入安装阶段。更新前仍需备份、连接电源和检查空间。fixture 没有证明安装阶段断电后可完整回滚；发生异常时优先换回保留的原卡。

固件版本与发行版版本是不同概念。本分支保留最低固件要求，附带更高版本不意味着每次启动都要升级。固件准备流程仍需实机验收，不要用于 Brick。
