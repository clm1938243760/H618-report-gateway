# H618 K2B 当前运行基线（2026-08-18）

## 基线用途

本文档根据 `192.168.20.144` 实板运行状态、本地工作区和板端文件 SHA-256 对照反推，
记录 `v0.22.6` 收版前的现场基线。后续开发应以本文档和 `v0.22.6` 代码共同判断
已实现功能，不能只参考更早的 Git `a5cc4aa` / `v0.22.5`。

板端核心 Python 模块、驱动目录模块、构建脚本、安装脚本和 Vue 产物与收版前工作区
SHA-256 完全一致。这些成果随后整理为本地 `v0.22.6` 版本；本文不代表已经推送远程、
生成公司升级包或完成实体打印验收。

## 板端运行状态

- 板卡：KICKPI K2B V2，Allwinner H618，约 2 GB 内存、16 GB eMMC。
- 系统：Armbian 25.11 rolling / Ubuntu 24.04 Noble ARM64。
- 内核：`6.12.47-current-sunxi64`。
- 当前 release：`/opt/jvlei/releases/gateway/0.22.5-driver-catalog-20260818`。
- 运行链接：`/opt/gadget-msc-printer` 指向上述 release。
- `pyproject.toml` 和 `/health` 仍报告 `0.22.5`，因此目录名中的驱动目录功能尚未形成正式版本号。
- `gadget-mode`、`gadget-collector`、`gadget-web`、`jvlei-updater`、`cups` 均为
  `enabled/active`。
- HTTPS 管理端监听 `443` 和 `8443`；升级代理监听本机 `8765`；CUPS 监听本机 `631`。
- 当前 USB Gadget 模式为 `msc`，不是 Printer 模式。

## 打印流捕获和结束判定

当前代码包含 `v0.22.5` 的完整智能结束判定：

- 协议结束边界优先，空闲超时兜底。
- 支持 PJL、PCL、PJL 封装 PCL XL、PostScript、PDF 的常见结束标志。
- 跟踪 PCL 二进制长度，避免栅格载荷中的伪 UEL 误切。
- 捕获与转换分离，GhostPCL/Ghostscript 转换不会阻塞 `/dev/g_printer0` 读取。
- 活动任务先写 `.prn.part`，完成后 `fsync + os.replace` 发布 `.prn`。
- 每个新任务写入首字节、末字节、边界时间、接收耗时、转换耗时和结束依据。

当前配置中未知或异常打印流空闲兜底为 `4.0` 秒，采集块为 `65536` 字节。

## 当前解析和转换栈

| 输入类型 | 识别与转换工具 | 当前状态 |
| --- | --- | --- |
| PDF | 原文件复制 | 可用 |
| PostScript | Ghostscript / `ps2pdf` 10.02.1 | 可用 |
| PCL / PCL XL | `/usr/local/bin/gpcl6` 10.07.1 | 可用，仅获准当前测试板内部测试 |
| ZjStream / HP ACL 页面流 | `printer-driver-foo2zjs` 的 `/usr/bin/zjsdecode` + Pillow | 可用 |
| HP ACL 固件/初始化流 | `AGIACLDOWNLOAD` 识别后忽略 | 可用，不生成报告 |
| JPEG/PNG/BMP | Pillow | 可用 |
| TXT | Pillow 文本渲染 | 可用 |
| Epson ESC/P-R、Canon UFR/CAPT、Samsung SPL 等 | 只识别和保留原始 PRN | 暂无通用转换器 |

对板端现存 63 份 PRN 使用当前分析器重新识别，结果为：

- PCL：48 份；
- PCL XL：4 份；
- ZjStream：5 份；
- HP ACL 固件/初始化流：6 份；
- 未知：0 份。

原先网页显示的 11 份“未知”已经反推清楚：6 份是 HP LaserJet 1020 ACL 固件/初始化
数据，5 份是带 PJL 作业边界的 ZjStream 页面流。隔离复验中 5 份 ZjStream 均成功生成
单页 PDF，6 份固件流均被正确忽略。

这些旧 PRN 的 `.meta.json` 是 ACL 支持加入前产生的，可能仍显示旧的“转换完成”状态；
当前分析器的协议结论才是现行语义，系统不会自动重写历史任务。

## 实体打印驱动体系

系统现有两条驱动路径。

### 现场上传驱动

`DriverManager` 支持先分析再安装：

- ARM64 或 `all` 架构 DEB；
- PPD、PPD.GZ；
- 包含 PPD 和 ARM64 CUPS Filter 的 ZIP/TAR/TGZ；
- 安装前分析架构、PPD、Filter、依赖和 DEB maintainer scripts；
- 含 root 安装脚本时要求二次确认；
- 安装前备份 CUPS 配置和驱动注册表，可按备份回滚；
- HTTP 不能直接提交 PPD 路径或 Shell 命令。

板端已有两个现场导入 PPD：

- HP LaserJet Pro 400 M401：通用 PCL 6/PCL XL `pxlmono`；
- Brother HL-5590DN：通用 PCL 6/PCL XL `pxlmono`。

### 全型号驱动目录

`DriverCatalogManager` 提供：

- 稳定 `model_id` 搜索、厂商/型号匹配和设备推荐；
- 软件包白名单，不接受网页传入任意包名；
- APT 安装计划、后台安装任务、安装后刷新 CUPS 型号；
- 人工测试页验证，CUPS 提交成功不会自动标记“实机验证”；
- 签名 `.jvdrv` Noble ARM64 离线驱动库导入；
- 离线包只注册只读本地 APT 源，不一次安装全部驱动。

板端目录数据库：

```text
/var/lib/gadget-msc-printer/driver-catalog/catalog.sqlite3
```

当前目录包含 `12439` 个型号记录，其中 `11963` 个型号对应已安装 CUPS 驱动，`476`
个型号的软件包可从当前软件源获得但尚未安装。当前没有离线驱动包、安装任务或人工验证
记录。

已安装的主要打印驱动包：

- `printer-driver-brlaser 6-3build2`；
- `printer-driver-foo2zjs 20200505dfsg0-2ubuntu6`；
- `printer-driver-hpcups 3.23.12+dfsg0-0ubuntu5.1`；
- `printer-driver-pxljr 1.4+repack0-6build2`；
- `foomatic-db-compressed-ppds 20230202-1`；
- `ipp-usb 0.9.24-0ubuntu3.3`。

离线驱动包公钥已安装，板端与 release 内公钥 SHA-256 均为：

```text
c8f52c7bea842d0241c9bef3ba7240771d02f9299b2860ffaf92e081fe6b9bbb
```

当前 release 没有 `assets/driver-catalog-noble-arm64.json`，板端目录主要由软件包种子和
当前 `lpinfo -m` 结果生成。正式发布前仍需在干净 Noble ARM64 构建环境生成版本化目录。

## 当前 CUPS 和实体打印机状态

- CUPS 版本：`2.4.7`。
- 当前队列：`Physical_Printer`。
- 当前设备 URI 配置为 HP LaserJet 400 M401dn USB。
- 当前模型为 `Generic PCL 6/PCL XL Printer Foomatic/pxlmono`。
- 页面大小 A4，分辨率配置为 600 dpi，自动转发已开启，轮询间隔 0.5 秒。
- 实体打印机目前不在 `lsusb` 中，CUPS 状态为“等待打印机可用”。
- CUPS 当前有 94 个未完成任务；物理打印数据库记录 116 个已提交、2 个失败耗尽和 2 个
  基线任务。

“submitted”只表示任务已经交给 CUPS，不表示纸张已经打印完成。实体打印机断开时 CUPS
会保留任务，因此在处理积压队列前不能用当前队列测量实时转发延迟，也不能直接清理队列，
必须先确认这些现场任务是否仍需打印。

## 网页功能

当前网页已经包含：

- 实体打印机扫描、驱动推荐、型号目录搜索和队列配置；
- 软件源驱动安装计划和后台安装任务；
- 签名 `.jvdrv` 离线驱动包分析与导入；
- DEB、PPD、压缩包现场上传、兼容性分析、安装和回滚；
- 打印流协议、结束依据、接收耗时、转换耗时、PRN 下载；
- 打印流分析列表每 5 秒自动刷新，浏览器标签重新可见时立即刷新。

## 后续开发约束

1. 开始修改前先检查本地 `git status`，以 `v0.22.6` 之后的提交作为开发基线。
2. 不得用 `a5cc4aa`、`v0.22.5` 或远程旧 `main` 覆盖当前工作区或实板 release。
3. 不覆盖 `/etc/gadget-msc-printer/config.yaml` 和 `/var/lib/gadget-msc-printer`。
4. 驱动目录代码正式发布前需生成 Noble ARM64 版本化目录并完成离线包测试。
5. GhostPDL 10.07.1 当前授权仅限该测试板内部验证，量产分发前必须重新评审许可。
6. 实体打印时延测试前先处理“打印机未连接 + 94 个待打印任务”的现场状态。
7. 将当前未提交成果整理为正式版本时，必须重新运行 Python 全量测试、Vue 构建、实板
   健康检查、驱动搜索/安装和 ACL/ZjStream 真实样本回归。

## 当前验证结果

- 本地 `compileall` 通过；
- 本地 Python 测试 `139` 项通过、`3` 项按平台条件跳过；
- 板端 5 份真实 ZjStream 均成功生成 1 页 PDF；
- 板端 6 份 HP ACL 固件流均未生成 PDF；
- 板端核心部署文件与本地工作区 SHA-256 一致。
