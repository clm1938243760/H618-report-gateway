# H618 Report Gateway v0.1 版本说明

发布日期：2026-08-04

## 版本定位

`v0.1` 是面向 KICKPI K2B（Allwinner H618、2GB LPDDR4、16GB eMMC）的首个可部署版本。
它将医疗设备产生的 U 盘报告或 USB 打印数据采集到板端，转换为 PDF，生成配套 XML，
并通过 HTTP 接口自动上传。项目同时保留标准 HID 键盘和鼠标复合设备能力，供后续设备
自动录入扩展使用。

## 核心功能

- 支持 `MSC + HID`、`Printer + HID`、纯 `MSC`、纯 `Printer` 四种 USB Gadget 模式。
- 单 UDC 自动识别和安全绑定；模式切换时避免多个 Gadget 抢占同一控制器。
- MSC FAT32 镜像采集，支持容量、卷标、重复文件去重、成功后自动删除和标志文件保护。
- USB Printer 打印流采集，支持 PDF、PostScript、PCL、PCL XL、JPEG、PNG、BMP 和文本转换。
- 只读 PRN 协议分析，显示识别依据、PJL 命令、转换路径、SHA-256、HEX/ASCII 文件头，
  并允许从管理端下载原始 PRN 文件。
- 生成无 XML 命名空间的最小 `ReportInfo.xml`，包含设备编码、检查医生和检查医生编码。
- SQLite 上传队列、失败重试、状态筛选、错误详情、PDF 下载和定期清理。
- 上传请求携带 `MacCode`、`MsgId`、`hospitalCode` Header，并保持既有 multipart 协议。
- Vue 3 + Element Plus HTTPS 管理端，标准端口 `443`，兼容端口 `8443`。
- 管理端支持配置、报告日志、存储清理、模拟打印、模拟 U 盘和网络管理。
- 有线网络显示网卡、IP、MAC、默认网关和链路状态。
- Wi-Fi 支持扫描、连接、断开、忘记网络和开机自动连接。
- 双无线网卡场景下支持 `wlan1` 维护热点，默认地址 `192.168.0.1/24`，可配置开机自启和
  无客户端自动关闭。

## 实板验证

- KICKPI K2B Armbian / Linux 6.1 环境完成安装和冷启动验证。
- USB Device Controller `musb-hdrc.4.auto` 可正常创建 MSC、Printer 和 HID Functions。
- Windows 主机已验证 U 盘写入、USB Printer 枚举、RAW PostScript 采集和 HID 枚举。
- 已验证 PDF 采集、XML 生成、队列处理、三个业务 Header 和 Mock HTTP 上传闭环。
- GhostPDL 10.07.1 已在当前测试板按 GNU AGPL 用于内部测试，PCL/PCL XL 官方样本可转换。
- 本版本发布前通过 `60` 项 Python 单元测试、`compileall` 和 Vue 生产构建。

## 部署信息

```text
程序目录：/opt/gadget-msc-printer
配置文件：/etc/gadget-msc-printer/config.yaml
数据目录：/var/lib/gadget-msc-printer
管理页面：https://<board-ip>
兼容入口：https://<board-ip>:8443
```

安装命令：

```bash
sudo ENABLE_SERVICES=1 START_SERVICES=1 bash scripts/install.sh
```

部署前建议先运行：

```bash
sudo bash scripts/k2b_preflight.sh
sudo bash scripts/k2b_acceptance.sh
```

## 配置与安全注意事项

- `config.example.yaml` 中的网页账号和热点密码仅为初始示例。正式部署必须在板端
  `/etc/gadget-msc-printer/config.yaml` 中修改，并保持文件权限为 `0640`。
- 管理端使用自签名 TLS 证书；生产环境应替换为受控证书或通过可信管理网络访问。
- Wi-Fi 密码、热点密码和网页密码不会通过状态 API 返回。
- USB VID/PID 当前使用 Linux Gadget 测试值；产品量产销售前应申请或获得合法授权。

## 已知限制

- 同一块 K2B 只有一个可用 USB Device Controller，因此四种 Gadget 模式互斥，不能同时
  独立绑定 MSC 和 Printer。
- Printer 转换能力取决于上游驱动实际产生的数据语言；厂商私有 GDI、UFR II、CAPT、
  ESC/P-R、SPL 等流不能保证转换为 PDF。
- GhostPDL 当前只获准在测试板内部验证。商业发布前必须重新完成 AGPL、字体授权或
  Artifex 商业许可评审。
- 调整 MSC 容量后必须在网页中明确执行“重建U盘”，该操作会重新格式化镜像。
- 维护热点设置了无人连接关闭时间时会按配置自动关闭；设为 `0` 才表示始终保持开启。

## 升级与回退

升级前备份以下目录：

```text
/etc/gadget-msc-printer
/var/lib/gadget-msc-printer
/opt/gadget-msc-printer
```

安装脚本会幂等补充缺失配置，不覆盖已有设备编码、上传地址和清理策略。出现异常时，
恢复上述目录并重启 `gadget-mode.service`、`gadget-collector.service` 和
`gadget-web.service` 即可回退。
