# KICKPI K2B / H618 迁移准备

## 目标

把已经在 RK3566 上验证过的报告采集网关迁移到 KICKPI K2B：

- SoC：Allwinner H618
- 内存与存储：2GB LPDDR4 + 16GB eMMC
- 系统：Armbian Minimal，Ubuntu Noble 用户空间
- USB Device：MSC 或 Printer 二选一
- 管理端：HTTPS 8443
- 业务：报告采集、PDF 转换、队列上传、失败重试、日志与自动清理

原 RK3566 仓库不作修改。本目录是独立迁移副本。

首块实测 K2B 的系统与 USB 能力记录见
[`K2B_BOARD_BASELINE_192.168.20.144.md`](K2B_BOARD_BASELINE_192.168.20.144.md)。

## 已完成的迁移准备

1. 从 RK3566 当前工作树复制了业务源码、测试、Vue 前端和生产构建。
2. UDC 配置从固定的 `fcc00000.usb` 改为 `auto`：
   - 只有一个 UDC 时自动使用；
   - 没有 UDC 时停止；
   - 多个 UDC 时停止并要求显式配置。
3. USB Printer 描述符改为 KICKPI K2B/H618。
4. 增加只读板端检查脚本 `scripts/k2b_preflight.sh`。
5. 上传协议、三个业务 Header、XML、SQLite、PDF 和 Web 行为保持不变。

## 第一次启动后的检查

先不要运行安装脚本，也不要删除厂家服务。把项目目录传到板端临时目录后执行：

```bash
cd /tmp/kickpi_k2b_report_gateway
sudo bash scripts/k2b_preflight.sh | tee /tmp/k2b_preflight.txt
```

必须重点确认：

```text
/sys/class/udc 至少存在一个控制器
CONFIG_USB_GADGET=y/m
CONFIG_USB_LIBCOMPOSITE=y/m
CONFIG_USB_CONFIGFS=y/m
CONFIG_USB_CONFIGFS_MASS_STORAGE=y/m
CONFIG_USB_CONFIGFS_F_PRINTER=y/m
```

其中 `CONFIG_USB_CONFIGFS_F_PRINTER` 是 Printer 模式的硬门槛。只有 USB OTG
接口并不代表内核已经提供 Printer function。

## 分阶段上板

首次迁移先只安装，不启用或启动服务：

```bash
sudo ENABLE_SERVICES=0 START_SERVICES=0 bash scripts/install.sh
```

单项验收后可以手动启动但暂不设置开机自启：

```bash
sudo ENABLE_SERVICES=0 START_SERVICES=1 bash scripts/install.sh
```

只有全部功能验收通过后，才使用默认值完成开机自启配置。

### 阶段 1：系统与接口基线

```bash
cat /etc/os-release
uname -a
ip -br address
lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINTS
lsusb
ls -l /sys/class/udc
```

确认 eMMC、网口、Wi-Fi、USB OTG 物理接口和系统时间均正常。

### 阶段 2：独立 MSC 测试

只运行 `setup_msc_gadget.sh`，确认 Windows/医疗设备能够：

- 枚举 U 盘；
- 写入 2-3MB 报告；
- 安全解绑并读取 FAT32 镜像；
- 重建 gadget 后仍可再次枚举。

### 阶段 3：独立 Printer 测试

只运行 `setup_hp_printer_gadget.sh`，确认：

- configfs 能创建 `printer.usb0`；
- 板端出现 `/dev/g_printer0`；
- Windows 能创建 K2B USB Printer 端口；
- PCL、PCL XL、PostScript 和 PDF 测试流能完整接收。

### 阶段 3.5：复合 HID 测试

管理页面提供四种模式：

- `msc_hid`：MSC + HID Keyboard + HID Mouse
- `printer_hid`：Printer + HID Keyboard + HID Mouse
- `msc`：仅 MSC
- `printer`：仅 Printer

复合模式必须同时出现 `/dev/hidg0` 和 `/dev/hidg1`。键盘报告长度为 8 字节，
鼠标使用 4 字节相对坐标报告。物理主机验收时需要分别确认存储/打印 Function 与
两个 HID Function 均被枚举。

### 阶段 4：业务服务

完成分阶段安装和单项验证后，依次检查：

```text
gadget-mode.service
gadget-collector.service
gadget-web.service
```

最后测试 HTTPS 8443、XML 生成、测试上传、正式上传、失败重试和清理任务。

## 实板待完成项目

- GhostPDL 在该 Armbian 版本上的依赖和转换耗时；
- Windows/医疗设备对四种 USB 模式的物理枚举；
- Wi-Fi 固件、时钟同步和 eMMC 长时间写入稳定性。

其余内核、UDC、MSC、Printer 和基础转换能力已在 `192.168.20.144` 实测通过。

## 回退原则

- 系统验证阶段始终保留可启动 TF 卡。
- 首次 gadget 测试不设开机自启。
- 安装前备份 `/etc` 中网络配置和已有 systemd unit。
- 任一 Printer/MSC 测试失败时，先解绑 UDC，再恢复厂家服务，不直接反复重启。
