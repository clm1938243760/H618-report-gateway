# K2B 板端实测基线

## 设备

- 采集日期：2026-08-03
- 主机名：`kickpi-k2b-v2`
- 管理地址：`192.168.20.144`
- 架构：`aarch64`
- 内核：`6.12.47-current-sunxi64`
- 系统：Armbian unofficial 25.11 / Ubuntu 24.04 Noble
- 内存：约 2 GB，另有约 988 MB zram swap
- 存储：16 GB eMMC，根分区可用空间约 13 GB

本文档不记录 SSH 密码。登录凭据应由现场安全配置管理。

## USB Device Controller

板端只发现一个 UDC：

```text
musb-hdrc.4.auto
```

预检时状态为 `not attached`。项目配置使用 `udc_device: auto`，运行时会自动
解析到该控制器，不需要把 Allwinner 控制器名称硬编码到业务配置中。

## 内核能力

2026-08-03 执行 `scripts/k2b_preflight.sh`，以下能力全部通过：

- `CONFIG_USB_GADGET=y`
- `CONFIG_USB_LIBCOMPOSITE=m`
- `CONFIG_USB_CONFIGFS=m`
- `CONFIG_USB_CONFIGFS_MASS_STORAGE=y`
- `CONFIG_USB_CONFIGFS_F_PRINTER=y`
- `CONFIG_USB_CONFIGFS_F_HID=y`
- `CONFIG_USB_PRINTER=m`
- `libcomposite`、`usb_f_mass_storage`、`usb_f_printer`、`usb_f_hid` 模块可用
- ConfigFS 文件系统可用并已挂载到 `/sys/kernel/config`

预检结论：`failures=0`，没有阻塞 MSC、Printer 或 HID 复合设备迁移的内核问题。

## 用户空间依赖

系统已具备 Python 3.12、OpenSSL、loop/mount、FAT 格式化工具和 systemd。
初始镜像没有安装：

- `gs`
- `ps2pdf`
- `gpcl6` / `pcl6`

`scripts/install.sh` 会通过 Ubuntu 软件源安装 Ghostscript，从而补齐 `gs` 和
`ps2pdf`。GhostPCL 不随基础安装自动构建；需要处理原始 PCL/PCL XL 时，再审核
许可证并执行 `scripts/build_ghostpcl.sh`。

## 网络

- 有线接口：`eth0`，当前地址 `192.168.20.144/24`
- 无线接口：`wlan0`、`wlan1`，预检时均未连接

## 下一阶段顺序

1. 将迁移包暂存到板端 `/tmp`，不启用服务。
2. 分别验证纯 MSC、纯 Printer、MSC+HID 和 Printer+HID。
3. 确认 OTG 口连接方向、电源路径及无 VBUS 倒灌风险。
4. 安装业务依赖并部署到 `/opt/gadget-msc-printer`。
5. 先手动启动三个服务完成端到端验证，再决定是否启用开机自启。
