# AI 接手上下文：KICKPI K2B / H618 报告网关

## 项目边界

- 当前目录：`D:\documents\New project\kickpi_k2b_report_gateway`
- 目标板：KICKPI K2B，全志 H618，2GB RAM，16GB eMMC
- 目标系统：Armbian Minimal / Ubuntu Noble
- 原项目：`D:\documents\New project\rk3566_report_gateway`
- 不得修改或回退 RK3566、RK3568、RK3588 仓库。

## 当前进度

1. 独立迁移副本已建立，RK3566、RK3568、RK3588 仓库未被修改。
2. K2B USB0 peripheral 设备树覆盖层已实板验证，UDC 为
   `musb-hdrc.4.auto`，状态为 `configured / high-speed`。
3. `msc`、`printer`、`msc_hid`、`printer_hid` 四种模式均已枚举通过。
4. Windows MSC 真实文件闭环和 Printer RAW PostScript 闭环均已通过。
5. HTTPS、Vue、XML、SQLite 队列、上传 Header 和 Mock 上传闭环已通过。
6. `gadget-mode`、`gadget-collector`、`gadget-web` 已启用开机自启并正常运行。
7. GhostPDL 10.07.1 已按授权仅安装到当前测试板；PCL/PCL XL 直接转换和
   `PdfConverter` 业务转换均通过。
8. 最终验收结果为 `failures=0 warnings=0`。

## 不能跳过的实板检查

- `/sys/class/udc` 的实际名称和数量；
- OTG 口是否工作在 peripheral/device 模式；
- `CONFIG_USB_CONFIGFS_F_PRINTER`；
- `CONFIG_USB_CONFIGFS_MASS_STORAGE`；
- `/dev/g_printer0` 是否能生成；
- 厂家 systemd 服务是否占用 UDC；
- 医疗设备真实 PCL/PCL XL 报告的兼容性和压力；
- 网口、Wi-Fi、eMMC、系统时间和断网缓存。

## 正确推进顺序

1. 修改前先备份 `/etc/gadget-msc-printer/config.yaml` 和状态数据库。
2. 执行 `scripts/k2b_preflight.sh` 与 `scripts/k2b_acceptance.sh` 保存基线。
3. 模式切换后确认 Windows 使用当前枚举的 MSC 或 `USB00x` Printer 端口。
4. 业务测试使用隔离输出目录，结束后恢复配置和 SQLite 状态。
5. GhostPDL 当前授权范围仅限测试板内部测试，量产前重新做许可证评审。

## 主要硬件耦合点

- `scripts/lib/udc.sh`：解析单个 UDC。
- `scripts/apply_gadget_mode.sh`：解绑当前 UDC 并创建目标 gadget。
- `scripts/setup_msc_gadget.sh`：创建 FAT32 Mass Storage function。
- `scripts/setup_hp_printer_gadget.sh`：创建 Printer function。
- `src/gadget_msc_printer/msc_monitor.py`：提取 MSC 文件时解绑和恢复 UDC。
- `src/gadget_msc_printer/config.py`：默认 UDC、USB 描述符和上传设置。

## 本地测试

```powershell
$env:PYTHONPATH='src'
py -3.14 -m unittest discover -s tests -v
py -3.14 -m compileall -q src scripts tests
```

任何部署前先执行 `git status --short`，不要覆盖用户在本目录中的新改动。
