# AI 接手上下文：KICKPI K2B / H618 报告网关

## 项目边界

- 当前目录：`D:\documents\New project\kickpi_k2b_report_gateway`
- 目标板：KICKPI K2B，全志 H618，2GB RAM，16GB eMMC
- 目标系统：Armbian Minimal / Ubuntu Noble
- 原项目：`D:\documents\New project\rk3566_report_gateway`
- 不得修改或回退 RK3566、RK3568、RK3588 仓库。

## 当前进度

1. 已按 RK3566 当前工作树建立独立副本，保留最新未提交业务与 Vue 功能。
2. UDC 默认配置改为 `auto`，单 UDC 自动选择，多 UDC 明确拒绝猜测。
3. USB Printer 描述符已经改为 KICKPI K2B/H618。
4. `scripts/k2b_preflight.sh` 是只读板端能力检查脚本。
5. 本地 Python 基线为 31 项测试通过；增加 UDC 测试后需要重新验证。
6. 尚未在 K2B 上运行安装、创建 gadget 或启用 systemd 服务。

## 不能跳过的实板检查

- `/sys/class/udc` 的实际名称和数量；
- OTG 口是否工作在 peripheral/device 模式；
- `CONFIG_USB_CONFIGFS_F_PRINTER`；
- `CONFIG_USB_CONFIGFS_MASS_STORAGE`；
- `/dev/g_printer0` 是否能生成；
- 厂家 systemd 服务是否占用 UDC；
- GhostPDL 构建与转换速度；
- 网口、Wi-Fi、eMMC、系统时间和断网缓存。

## 正确推进顺序

1. 先从 TF 卡启动 Armbian并确认系统稳定。
2. 运行 `sudo bash scripts/k2b_preflight.sh`，保存完整输出。
3. 单独测试 MSC，不设置开机自启。
4. 单独测试 Printer，不设置开机自启。
5. 两种模式都通过后再运行 `scripts/install.sh`。
6. 验证 HTTPS 8443、XML、上传 Header、测试上传与正式上传。
7. 最后才安装到 eMMC并启用开机自启。

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
