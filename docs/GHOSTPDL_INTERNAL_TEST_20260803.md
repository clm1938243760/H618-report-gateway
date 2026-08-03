# GhostPDL 10.07.1 K2B 内部测试记录

## 授权边界

2026-08-03 已获得明确确认：仅在当前 KICKPI K2B 测试板上按 GNU AGPL 安装
GhostPDL 10.07.1，用于内部功能验证。本记录不构成量产、闭源分发或商业发布授权。

GhostPDL 主体许可证为 GNU AGPL。源码内 PCL/XL 字体另带 AFPL 文件；内部功能
测试可继续，但商业分发前必须由公司重新评审 AGPL、AFPL 与 Artifex 商业许可。

## 源码来源与校验

- 版本：GhostPDL `10.07.1`
- Artifex 标签：`ghostpdl-10.07.1`
- 标签提交：`9a39d68ca934f8e9343f46a2803e765122a3b4a9`
- 下载来源：freedesktop-sdk 的 ArtifexSoftware/ghostpdl GitLab 镜像标签归档
- 本次归档：`ghostpdl-10.07.1-gitlab.tar.gz`
- 文件大小：`81953090` 字节
- SHA-256：`d7aa9a1926d936ae0cefec31b3b768071da3516ad7f3dfe298a27f13f24a7d01`
- Artifex 正式发布归档允许哈希：
  `56f6a82907c3a73bba95de1319e029adf16477e34df2dea180d390e71e7c4053`

构建脚本只接受上述两个固定哈希，其他归档会立即终止。GitLab 标签归档没有预生成
`configure`，脚本会先执行 `NOCONFIGURE=1 sh ./autogen.sh`。

## 构建记录

- 测试板：KICKPI K2B V2，Allwinner H618，2GB RAM，16GB eMMC
- 系统：Armbian unofficial 25.11 / Ubuntu 24.04
- 内核：`6.12.47-current-sunxi64`
- 构建命令：

```bash
sudo JOBS=2 /opt/gadget-msc-printer/scripts/build_ghostpcl.sh \
  --accept-agpl /var/tmp/ghostpdl-10.07.1-gitlab.tar.gz
```

- 安装路径：`/usr/local/bin/gpcl6`
- 二进制大小：约 `27 MiB`
- 编译峰值内存：约 `710 MiB`
- 编译 Swap：`0 B`
- 编译期间网关三个 systemd 服务保持 `active`
- `gpcl6 -h` 报告：`Version: 10.07.1`、`Languages: PJL PCL PCLXL`

## 转换验证

样本来自同一 GhostPDL 10.07.1 源码树的 `pcl/examples`，测试输出写入隔离的
`/var/tmp` 目录，没有进入正式报告队列。

| 输入 | 类型 | 直接转换 | 网关 `PdfConverter` | 输出 |
| --- | --- | ---: | ---: | --- |
| `owl.pcl` | PCL | 约 258 ms | 约 258 ms | 93677 字节，1 页 |
| `fonts.pxl` | PCL XL | 约 222 ms | 约 221 ms | 13834 字节，2 页 |

两份输出均满足：

- 文件头为 `%PDF-`；
- Ghostscript `-sDEVICE=nullpage` 完整解析且退出码为 0；
- 在开发电脑用 Poppler 渲染成功；
- PCL 页面包含文字、线条、图形和复杂字体效果；
- PCL XL 页面文字、数字和线条可见，无空白或截断。

## 最终状态

```text
k2b_acceptance.sh --require-host --require-enabled
RESULT failures=0 warnings=0
```

验收时 `gadget-mode`、`gadget-collector`、`gadget-web` 均为
`active/enabled`，UDC 为 `configured`，HTTPS `/health` 返回 `ok=true`。

## 量产前仍需完成

1. 使用现场医疗设备产生的真实 PCL/PCL XL 样本做兼容性回归。
2. 使用 2-3MB、多页和彩色复杂报告测试峰值内存、耗时和连续稳定性。
3. 明确最终交付方式，并完成 AGPL、AFPL 或 Artifex 商业许可评审。
4. 不得把本次“测试板内部使用”确认直接扩展为产品出货许可。
