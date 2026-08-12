# KICKPI K2B MSC / Printer 报告网关

当前开发版本：`v0.22.4`。完整变更和部署注意事项见
[v0.22.4 版本说明](docs/RELEASE_NOTES_v0.22.4.md)。

本项目是 RK3566 报告网关的独立迁移版本，目标硬件为 KICKPI K2B（Allwinner
H618，2GB LPDDR4，16GB eMMC）。原 RK3566 项目不会被本目录的开发和部署改动。

## 当前状态

- 已复制当前有效的 Python 后端、Vue 管理端和生产构建。
- 已把固定 RK3566 UDC 改为单 UDC 自动识别。
- USB Printer 厂商描述符固定为 JVLEI，设备名称和序列号可配置。
- 已在 K2B 实板和 Windows 主机验证 UDC、MSC、Printer、HID 与 HTTPS。
- 已完成 Windows 写入真实 PDF、板端提取转换、队列处理和 Mock HTTP 上传闭环，
  `MacCode`、`MsgId`、`hospitalCode` 及两个 multipart 文件字段均通过校验。
- 已完成 Windows RAW PostScript 到 `/dev/g_printer0`、PRN 保存和 PDF 转换的 Printer
  真机闭环；模式切换后需确认 Windows 打印队列绑定当前 `USB00x` 端口。
- 已增加 MSC/Printer 与 HID Keyboard/Mouse 的复合模式。
- 已修复 K2B V2 Armbian USB0 Host/Peripheral 角色冲突并完成冷启动验收。
- GhostPDL 10.07.1 已在当前 K2B 测试板编译安装，PCL 和 PCL XL 官方样本及
  网关 `PdfConverter` 均已完成转换验证；医疗设备兼容性仍需现场验收。

迁移进度和上板顺序见
[docs/K2B_H618_MIGRATION.md](docs/K2B_H618_MIGRATION.md)。

## 功能

- 标准 HTTPS 443 管理页面切换四种 USB 工作模式，并保留 8443 兼容访问。
- 支持 `msc_hid`、`printer_hid`、`msc`、`printer`。
- HID 复合模式同时提供标准键盘和相对鼠标 Function。
- MSC 模式通过 FAT32 镜像接收报告。
- Printer 模式从 `/dev/g_printer0` 接收打印流。
- 处理 PDF、PostScript、PCL/PCL XL、JPEG、PNG、BMP 和文本。
- SQLite 上传队列、失败重试、日志查询和定期清理。
- 生成最小 `ReportInfo.xml`。
- 正式上传携带 `MacCode`、`MsgId`、`hospitalCode` Header。
- 模拟打印配置支持切换通用、PCL、PostScript 和 RAW 驱动声明，并只读分析最近的 PRN 协议。
- 实体打印机配置通过 CUPS 扫描 USB/网络打印机、选择受控驱动、创建队列、打印测试页，
  并可将新生成的报告 PDF 自动提交到实体打印机。HP LaserJet Pro 400 M401 默认使用
  通用黑白 PCL 6/PCL XL（pxlmono）；HL-1218W 使用 arm64 原生 `brlaser`。
- 模拟U盘配置支持调整容量、卷标、去重、转换成功后自动删除及标志文件保护。
- 报告日志支持直接下载板端留存的 PDF。
- 网络配置页统一显示有线 IP、Wi-Fi 状态和附近网络，并支持无线连接、断开和忘记网络。
- 维护热点使用 `wlan1` 提供 `192.168.0.1/24` 管理网络，可配置 SSID、密码、开机自启和无人连接自动关闭。
- 在线升级直接接入公司平台，开机上报终端并检查一次，使用公司 ZIP、原子切换和自动回滚。
- 支持在板端本地审核导入实体打印驱动，并通过 CUPS 创建队列和打印测试页。

所有模式共用一个 USB Device Controller，同一时刻只绑定一个 Gadget。

## 目标目录

```text
程序：/opt/gadget-msc-printer
配置：/etc/gadget-msc-printer/config.yaml
数据：/var/lib/gadget-msc-printer
管理：https://<board-ip>
```

`gadget.udc_device` 和 `msc.udc_device` 默认是 `auto`。只有一个 UDC 时自动选择；
出现多个 UDC 时必须在配置文件中明确填写目标控制器名称。

## 首次上板

先把本目录传到 K2B 的临时目录，只运行只读预检：

```bash
cd /tmp/kickpi_k2b_report_gateway
sudo bash scripts/k2b_preflight.sh | tee /tmp/k2b_preflight.txt
```

预检必须确认：

- `/sys/class/udc` 中存在 USB Device Controller；
- configfs 可用；
- `CONFIG_USB_CONFIGFS_MASS_STORAGE` 已启用；
- `CONFIG_USB_CONFIGFS_F_PRINTER` 已启用；
- eMMC、网络、Python 和基础命令正常。

首次安装先保持服务关闭：

```bash
sudo ENABLE_SERVICES=0 START_SERVICES=0 bash scripts/install.sh
```

在 K2B 上，安装器默认自动编译并启用 `k2b-usb0-peripheral` 覆盖层。首次安装后如
提示需要重启，应先执行 `sudo reboot`，再进行物理 USB 枚举。覆盖层自动安装可用
`INSTALL_K2B_USB0_OVERLAY=0` 显式关闭，也可用 `=1` 强制启用。

安装脚本会安装以下 systemd 单元；是否立即启动或设置开机自启分别由
`START_SERVICES` 和 `ENABLE_SERVICES` 控制：

```text
gadget-mode.service
gadget-collector.service
gadget-web.service
cups.service
jvlei-updater.service
```

## 本地验证

```powershell
$env:PYTHONPATH='src'
py -3.14 -m unittest discover -s tests -v
py -3.14 -m compileall -q src scripts tests
```

Vue 生产构建必须位于：

```text
portal/portal/dist/index.html
```

板端不安装 Node.js，前端必须在开发电脑构建后随部署包一起传输。

调整 U 盘容量只会更新配置。必须在“模拟U盘配置”页面明确确认“重建U盘”后，
系统才会重新格式化镜像并使新容量生效。重建会清空普通文件，配置的标志文件会从
保护目录恢复。

## 关键风险

H618 芯片具有 USB OTG 不等于当前 Armbian 内核已经启用 USB Printer
configfs function。Printer 能否创建 `/dev/g_printer0` 是本次迁移的首要门槛，
必须实板验证，不能只依据芯片或开发板规格判断。

PCL/PCL XL 转 PDF 依赖 GhostPDL `gpcl6`。当前安装仅获准用于该 K2B 测试板的
内部测试；商业发布前必须重新完成 AGPL、PCL/XL 字体 AFPL 或 Artifex 商业许可
评审。安装和实测记录见
[docs/GHOSTPDL_INTERNAL_TEST_20260803.md](docs/GHOSTPDL_INTERNAL_TEST_20260803.md)。

## 项目结构

```text
src/gadget_msc_printer/   采集、转换、上传、配置和 Web 后端
portal/portal/            Vue 管理端及生产构建
scripts/                  预检、USB gadget、安装和维护脚本
overlays/                 K2B USB0 peripheral 设备树覆盖层
systemd/                  板端服务单元
tests/                    Python 回归测试
docs/                     迁移、架构和产品资料
MIGRATION_SOURCE.md       本迁移副本的来源记录
```
