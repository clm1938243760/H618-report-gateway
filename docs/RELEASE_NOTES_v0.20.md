# H618 Report Gateway v0.20 版本说明

发布日期：2026-08-06

## 版本定位

`v0.20` 是 KICKPI K2B 报告采集网关完成现场功能扩展后的稳定基线。版本覆盖 USB
报告采集、格式转换、自动上传、网络管理和实体打印转发，后续在线升级功能将以本版本
为基础独立开发。

## 核心功能

- 支持 `MSC + HID`、`Printer + HID`、纯 `MSC`、纯 `Printer` 四种 USB Gadget 模式。
- MSC 模式支持容量、卷标、哈希去重、成功后删除和标志文件保护。
- Printer 模式接收原始打印流，并支持 PDF、PostScript、PCL、PCL XL、JPEG、PNG、
  BMP 和文本转换。
- 报告转换完成后生成最小 `ReportInfo.xml`，通过 SQLite 队列自动上传并记录完整日志。
- 上传请求携带 `MacCode`、`MsgId`、`hospitalCode` Header，并保持现有 multipart 协议。
- 打印流分析显示协议、PJL 声明、判断依据、转换方式、SHA-256 和文件头，并支持下载
  原始 PRN。
- 通过 CUPS 扫描 USB/网络实体打印机、选择受控驱动、创建队列、打印测试页，并可将
  新生成的报告自动提交到实体打印机。
- 内置通用 PostScript、PCL 5、PCL 6/PCL XL、HP M401 和 Brother brlaser 配置。
- 网络页面统一管理有线 DHCP/静态地址、Wi-Fi 扫描连接以及 `wlan1` 维护热点。
- 维护热点默认使用 `192.168.0.1/24`，支持开机自启和无人连接自动关闭。
- Vue 3 管理端已适配桌面和手机浏览器，支持报告下载、失败详情、重试及存储清理。
- 实体打印轮询缩短至 0.5 秒，历史 PDF 优先查数据库，减少重复哈希计算。
- 修正网页报告接收时间显示和网络配置状态读取。

## 实板验证

- KICKPI K2B（Allwinner H618、2GB LPDDR4、16GB eMMC）完成冷启动和持续运行验证。
- Windows 主机已验证 MSC 写入、USB Printer、HID、HTTPS 和四种 Gadget 模式切换。
- PCL/PCL XL/PostScript 转 PDF、XML 生成、业务 Header 和 Mock HTTP 上传完成闭环。
- HP LaserJet Pro 400 M401 使用通用黑白 PCL 6/PCL XL 队列完成配置验证。
- Brother HL-1218W 使用 ARM64 `brlaser` 驱动完成配置路径验证。
- 发布前通过 `69` 项 Python 单元测试、`compileall` 和 Vue 生产构建。

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

## 安全与授权

- 网页账号、Wi-Fi 密码和热点密码必须在现场配置中修改，配置文件权限保持 `0640`。
- USB VID/PID 仍为 Linux Gadget 测试值，量产销售前必须获得合法授权。
- GhostPDL 10.07.1 仅获准在当前测试板按 GNU AGPL 用于内部测试；商业发布前必须完成
  AGPL、字体授权或 Artifex 商业许可评审。
- 厂商私有 GDI、UFR II、CAPT、ESC/P-R、SPL 等打印流不保证能够转换为 PDF。

## 升级与回退

升级前备份：

```text
/etc/gadget-msc-printer
/var/lib/gadget-msc-printer
/opt/gadget-msc-printer
```

安装脚本只补充缺失配置，不覆盖现场设备编码、上传地址、网络和清理策略。异常时恢复
上述目录并重启 `gadget-mode.service`、`gadget-collector.service`、`gadget-web.service`
和 `cups.service`。
