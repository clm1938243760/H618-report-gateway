# KICKPI K2B MSC / Printer 报告网关

本项目是 RK3566 报告网关的独立迁移版本，目标硬件为 KICKPI K2B（Allwinner
H618，2GB LPDDR4，16GB eMMC）。原 RK3566 项目不会被本目录的开发和部署改动。

## 当前状态

- 已复制当前有效的 Python 后端、Vue 管理端和生产构建。
- 已把固定 RK3566 UDC 改为单 UDC 自动识别。
- 已把 USB Printer 描述符改为 KICKPI K2B。
- 已在 K2B 实板验证 UDC、MSC、Printer、HTTPS 和常用报告转换。
- 已增加 MSC/Printer 与 HID Keyboard/Mouse 的复合模式。
- GhostPCL 和物理 USB 主机枚举仍需完成最终验收。

迁移进度和上板顺序见
[docs/K2B_H618_MIGRATION.md](docs/K2B_H618_MIGRATION.md)。

## 功能

- HTTPS 8443 管理页面切换四种 USB 工作模式。
- 支持 `msc_hid`、`printer_hid`、`msc`、`printer`。
- HID 复合模式同时提供标准键盘和相对鼠标 Function。
- MSC 模式通过 FAT32 镜像接收报告。
- Printer 模式从 `/dev/g_printer0` 接收打印流。
- 处理 PDF、PostScript、PCL/PCL XL、JPEG、PNG、BMP 和文本。
- SQLite 上传队列、失败重试、日志查询和定期清理。
- 生成最小 `ReportInfo.xml`。
- 正式上传携带 `MacCode`、`MsgId`、`hospitalCode` Header。

所有模式共用一个 USB Device Controller，同一时刻只绑定一个 Gadget。

## 目标目录

```text
程序：/opt/gadget-msc-printer
配置：/etc/gadget-msc-printer/config.yaml
数据：/var/lib/gadget-msc-printer
管理：https://<board-ip>:8443
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

安装脚本会安装以下 systemd 单元；是否立即启动或设置开机自启分别由
`START_SERVICES` 和 `ENABLE_SERVICES` 控制：

```text
gadget-mode.service
gadget-collector.service
gadget-web.service
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

## 关键风险

H618 芯片具有 USB OTG 不等于当前 Armbian 内核已经启用 USB Printer
configfs function。Printer 能否创建 `/dev/g_printer0` 是本次迁移的首要门槛，
必须实板验证，不能只依据芯片或开发板规格判断。

PCL/PCL XL 转 PDF 还依赖 GhostPDL `gpcl6`。商业发布前需要确认 AGPL 或
Artifex 商业许可。

## 项目结构

```text
src/gadget_msc_printer/   采集、转换、上传、配置和 Web 后端
portal/portal/            Vue 管理端及生产构建
scripts/                  预检、USB gadget、安装和维护脚本
systemd/                  板端服务单元
tests/                    Python 回归测试
docs/                     迁移、架构和产品资料
MIGRATION_SOURCE.md       本迁移副本的来源记录
```
