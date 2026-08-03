# K2B 迁移实测记录（2026-08-03）

## 目标设备

- 地址：`192.168.20.144`
- 主机名：`kickpi-k2b-v2`
- SoC：Allwinner H618
- 系统：Armbian unofficial 25.11 / Ubuntu 24.04
- 内核：`6.12.47-current-sunxi64`
- UDC：`musb-hdrc.4.auto`

## 安装策略

首次安装使用：

```bash
sudo ENABLE_SERVICES=0 START_SERVICES=0 bash scripts/install.sh
```

安装完成后，`gadget-mode.service`、`gadget-collector.service` 和
`gadget-web.service` 先保持 `disabled/inactive`。完成物理枚举和重启验收后，三个
服务已设置为开机自启。

## 已通过项目

### 系统和内核

- K2B 预检：`failures=0`
- ConfigFS、libcomposite、MSC、Printer、HID 内核能力通过
- Python 3.12、AIOHTTP、Pillow、PyYAML 可导入
- Ghostscript 10.02.1 和 `ps2pdf` 已安装
- HTTPS 8443 服务、登录、会话恢复、状态接口和退出接口通过

### 四种 USB 模式

| 模式 | ConfigFS Functions | 板端节点 | 结果 |
| --- | --- | --- | --- |
| `msc` | `mass_storage.0` | 512MB FAT32 镜像 | 通过 |
| `printer` | `printer.usb0` | `/dev/g_printer0` | 通过 |
| `msc_hid` | `mass_storage.0`、`hid.keyboard`、`hid.mouse` | `/dev/hidg0`、`/dev/hidg1` | 通过 |
| `printer_hid` | `printer.usb0`、`hid.keyboard`、`hid.mouse` | `/dev/g_printer0`、`/dev/hidg0`、`/dev/hidg1` | 通过 |

HID Keyboard 报告长度为 8 字节，描述符长度为 63 字节；HID Mouse 报告长度为
4 字节，描述符长度为 52 字节。物理连接 Windows 后，`msc_hid` 已枚举为 512 MiB
Mass Storage、键盘和鼠标；`printer_hid` 已枚举为 USB 打印支持、键盘和鼠标。
两种模式的 UDC 均达到 `configured / high-speed`。

### MSC 实际报告闭环

使用隔离测试配置完成了真实 Windows 主机到板端上传链路，测试结束后已恢复原配置和
SQLite 数据库：

1. Windows 向 512 MiB FAT32 虚拟 U 盘写入 `K2B_E2E_REPORT.pdf`，文件大小为
   `137636` 字节。
2. `gadget-collector` 从镜像提取文件到 `msc_files`，并在约 3 秒内生成同尺寸 PDF。
3. 上传队列向板端本机 Mock HTTP 接口发送 multipart 请求。
4. Mock 接口确认 `Report`、`ReportInfo`、PDF 内容和 XML 设备字段均存在。
5. `MacCode=K2B-E2E-TEST`、随机 `MsgId`、`hospitalCode=tejian01` 三个 Header 均存在。

测试期间曾在连续切换全速、PIO、stall 等底层实验参数后出现 Windows 写进程阻塞。
停止实验并通过 `apply_gadget_mode.sh` 干净重建 configfs gadget 后，写入恢复正常。
MUSB tracepoint 显示 `ep1 OUT` 的 4096 字节请求全部完成并正常 giveback。生产维护时
不得运行时解绑 `musb-sunxi`；如开发实验留下异常枚举状态，应先停止主机 I/O，再重建
configfs gadget 或重启板子。

### Printer 实际报告闭环

使用 Windows 真实打印队列和板端 `gadget-collector` 完成了 Printer 数据通道验证：

1. Windows 当前枚举的 K2B USB Printer 端口为 `USB016`。
2. 原测试队列仍绑定旧端口 `USB015`，表现为任务长期停留在
   `Error, Printing, Retained`，板端收到 `0` 字节。
3. 将同一队列改绑 `USB016` 后，发送 `158` 字节 RAW PostScript；Windows 任务正常
   结束，板端保存为 `.prn`。
4. `gadget-collector` 成功将该 PostScript 转换为 `2445` 字节有效 PDF。
5. `/dev/g_printer0` 的状态在测试前后均为 `0x18`，即已选择、无错误、未缺纸；故障
   原因不是 Printer 状态位，也不是 K2B 内核或采集程序。

Windows 在 USB Gadget 模式、Function 组合或枚举实例变化后，可能分配新的
`USB00x` 虚拟打印端口。出现“Windows 接受任务但板端没有数据”时，应先确认打印队列
绑定的端口与当前 `USBPRINT` 设备一致，再排查板端。当前默认
`printer.idle_complete_seconds=20`，因此小任务从首字节到封包约等待 20 秒；这是继承
的任务边界策略，不是 H618 转换性能不足。

### USB-C OTG 角色修复

原始 K2B V2 DTB 同时启用了共用 PHY0 的 MUSB peripheral、EHCI0 和 OHCI0。启动时
PHY 被设为 Host，表现为 `USB=1` 与 `USB-HOST=1` 同时成立，ConfigFS 创建成功但
UDC 始终为 `not attached`。

本仓库新增：

- `overlays/k2b-usb0-peripheral.dts`
- `scripts/k2b_usb0_peripheral_overlay.sh`

安装命令：

```bash
sudo /opt/gadget-msc-printer/scripts/k2b_usb0_peripheral_overlay.sh install
sudo reboot
```

覆盖层只禁用 USB-C 对应的 EHCI0/OHCI0，保留 MUSB peripheral；USB1、USB2、USB3
Host 不变。安装前会把 `armbianEnv.txt` 和当前 DTB 备份到
`/boot/k2b-usb0-peripheral-backups/<时间戳>/`。本次备份为
`/boot/k2b-usb0-peripheral-backups/20260803_055324`。

撤销命令：

```bash
sudo /opt/gadget-msc-printer/scripts/k2b_usb0_peripheral_overlay.sh remove
sudo reboot
```

不要在该 6.12.47 内核上运行时解绑 `musb-sunxi`。实测会在
`devm_usb_phy_release()` 触发空指针内核异常，应通过启动阶段设备树配置角色。

### 报告转换

板端隔离测试目录：`/tmp/k2b-pipeline-test-20260803`。

- PDF 复制：通过
- PNG 转 PDF：通过
- TXT 转 PDF：通过
- PostScript 转 PDF：通过
- PCL：GhostPDL 官方 `owl.pcl` 样本通过，板端直接转换约 `258 ms`
- PCL XL：GhostPDL 官方 `fonts.pxl` 样本通过，板端直接转换约 `222 ms`
- 网关 `PdfConverter`：上述 PCL/PCL XL 样本均通过，生成文件头为 `%PDF-`，并由
  Ghostscript `nullpage` 完整解析

GhostPDL 版本为 `10.07.1`，安装路径为 `/usr/local/bin/gpcl6`。本次仅获准用于
当前 K2B 测试板内部测试，源码来源、哈希和许可证边界见
[`GHOSTPDL_INTERNAL_TEST_20260803.md`](GHOSTPDL_INTERNAL_TEST_20260803.md)。

### 前端

- Vue 生产构建通过
- 真实浏览器以 `1920x1080` 登录板端 HTTPS 页面
- 四种模式按钮全部显示
- 页面未发现重叠、裁切或无法滚动的问题

### 冷启动和最终验收

- 执行 `sudo reboot` 后，SSH 在约 13 秒恢复。
- 启动约 23 秒时，`gadget-mode`、`gadget-collector`、`gadget-web` 均为
  `active/enabled`。
- USB 角色为 `USB=1`、`USB-HOST=0`，UDC 为 `configured / high-speed`。
- Windows 自动恢复 USB 打印支持、HID Keyboard 和 HID Mouse。
- `https://192.168.20.144:8443/health` 返回 `ok=true`。
- `k2b_acceptance.sh --require-host --require-enabled` 结果为
  `failures=0 warnings=0`。

## 仍需完成

1. 在 HID 复合模式发送业务级键盘和鼠标测试报告。
2. 使用最终生产参数复核设备编码、检查医生、检查医生编码和上传服务地址。
3. 接入正式医院上传接口，继续验证失败重试和去重策略。
4. 使用医疗设备现场产生的 PCL/PCL XL 报告做兼容性与压力测试。

最终执行：

```bash
sudo /opt/gadget-msc-printer/scripts/k2b_acceptance.sh \
  --require-host --require-enabled
```

结果为 `failures=0 warnings=0`。
