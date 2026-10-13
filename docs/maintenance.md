# 维护与发布

当前只维护 Smart Pro。`upstream` 指向原仓库，`origin` 指向本 fork。引入上游提交应先检查兼容性，避免同步覆盖独立更新地址。

安装版本在 `System/usr/trimui/crossmix-version.txt`。基线文件仍标记 1.3.0，虽然主分支已有后续未发布改进。本 fork 选择 1.3.6 作为维护版本；当前预览标签为 `v1.3.6-preview.2`，后续正式标签可用 `v1.3.6`。标签的数字版本和包内版本应一致。更新仓库与渠道在 `System/etc/update.json`。

## 检查与打包

```sh
python -m unittest discover -s _assets/release -p 'test_*.py' -v
python _assets/tests/test_firmware_check.py
python _assets/tests/test_updater.py
git diff --check
```

固件和 OTA 测试需要 POSIX shell；Windows 可用 Git for Windows 自带的 Bash。OTA 测试还需要 jq；Windows 可通过 `test_updater.py --shell "D:/Program Files/Git/bin/bash.exe" --jq "路径/jq.exe"` 指定工具。fixture 使用临时路径和假设备工具，不刷写固件。

`Release Smoke` 运行轻量检查；`CrossMix-OS Release` 用完整检出打包。手动运行生成 Actions 产物；版本标签创建草稿预发布版。详细构建与资产协议见 [_assets/release/README.md](../_assets/release/README.md)。

`release-manifest.json` 记录设备、版本、完整 ZIP 大小及哈希，有序分卷名称、大小和哈希。下载校验必须在安装前完成，不能先执行远程主分支脚本。

草稿不进入公开 API 或 OTA。完成自动化检查、包内容审核和 [实机验收](device-validation.md) 后，维护者再公开预发布版或正式版。正式发布前应核对随包二进制对应源码和许可范围；打包成功不能替代这些检查。

## 来源参考

- [CrossMix 上游](https://github.com/cizia64/CrossMix-OS)
- [TrimUI 官方组织](https://github.com/trimui/)
- [Smart Pro 固件](https://github.com/trimui/firmware_smartpro)
- [Smart Pro SDK](https://github.com/trimui/toolchain_sdk_smartpro)

记录引入内容的来源提交、二进制版本、构建方法和许可。厂商提供二进制不等同于提供完整可重建源码；无法核实的项目应明确记录。
