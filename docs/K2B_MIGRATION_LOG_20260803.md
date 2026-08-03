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
`gadget-web.service` 均保持 `disabled/inactive`。后续测试均为手动启动，尚未设置
开机自启。

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
4 字节，描述符长度为 52 字节。测试时未连接 USB 主机，所以 UDC 状态为
`not attached`，这不等同于物理主机枚举通过。

### 报告转换

板端隔离测试目录：`/tmp/k2b-pipeline-test-20260803`。

- PDF 复制：通过
- PNG 转 PDF：通过
- TXT 转 PDF：通过
- PostScript 转 PDF：通过
- PCL/PCL XL：等待 GhostPCL

### 前端

- Vue 生产构建通过
- 真实浏览器以 `1920x1080` 登录板端 HTTPS 页面
- 四种模式按钮全部显示
- 页面未发现重叠、裁切或无法滚动的问题

## 仍需完成

1. 接入物理 USB 主机，逐项确认四种模式在 Windows/医疗设备上的枚举。
2. 在 HID 复合模式发送键盘和鼠标测试报告。
3. 录入正式设备编码、检查医生、检查医生编码和上传服务地址。
4. 安装 GhostPCL 后验证 PCL 与 PCL XL 转换。
5. 使用真实报告完成上传 Header、失败重试和去重测试。
6. 全部通过后启用三个 systemd 服务并重启验收。
