# KICKPI K2B 报告网关架构

## 平台基线

- 板卡：KICKPI K2B
- SoC：Allwinner H618
- 系统：Armbian / Ubuntu 24.04 aarch64
- USB Device Controller：运行时从 `/sys/class/udc` 自动选择
- 当前实板 UDC：`musb-hdrc.4.auto`
- 管理端：标准 HTTPS 443，兼容 8443，Vue 3 + aiohttp

项目不在业务代码中写死 UDC 名称。只有一个 UDC 时自动选择；如果目标系统暴露
多个 UDC，必须在 `config.yaml` 中明确指定 `gadget.udc_device`。

## 服务边界

```text
gadget-mode.service
  -> 读取 gadget.mode
  -> 清理本项目已有 gadget
  -> 创建并绑定选定的 configfs gadget

gadget-collector.service
  -> MSC 模式：MscMonitor -> PdfConverter
  -> Printer 模式：PrintCapture -> PdfConverter

gadget-web.service
  -> HTTPS 登录、配置和模式切换
  -> ReportInfo.xml
  -> ReportJobStore (SQLite)
  -> ReportUploadWorker
  -> MaintenanceManager
  -> PhysicalPrintWorker -> CUPS -> 实体打印机
```

三个服务共享 `/etc/gadget-msc-printer/config.yaml`。配置和 XML 均通过临时文件、
`fsync` 和原子替换写入，避免掉电或进程中断留下半文件。

## USB 工作模式

K2B 当前使用一个 UDC，因此四种模式互斥：

| 配置值 | USB Functions | 页面名称 |
| --- | --- | --- |
| `msc_hid` | Mass Storage + HID Keyboard + HID Mouse | U盘 + HID |
| `printer_hid` | Printer + HID Keyboard + HID Mouse | 打印 + HID |
| `msc` | Mass Storage | 仅U盘 |
| `printer` | Printer | 仅打印 |

`apply_gadget_mode.sh` 的切换顺序为：

```text
停止采集服务
  -> 从 UDC 解绑旧 gadget
  -> 只清理本项目的 gmp_msc / gmp_printer
  -> 创建新 functions 和 configuration links
  -> 绑定自动解析出的 UDC
  -> 启动对应采集服务
```

Web 模式切换失败时会恢复旧配置并尝试重建旧模式。

HID 键盘使用标准 8 字节 Boot Keyboard report；鼠标使用 4 字节相对坐标 report。
HID 设备节点通常为 `/dev/hidg0` 和 `/dev/hidg1`，但主机侧功能枚举不依赖 Linux
设备节点编号。

## MSC 报告链路

```text
医疗设备写入 FAT32 镜像
  -> 监控镜像 mtime
  -> 等待 stable + quiet
  -> 解绑 UDC 和 backing file
  -> loop 挂载（普通采集只读，自动删除/标志恢复时读写）
  -> 按路径、大小和 SHA-256 去重
  -> 复制到 msc_files
  -> 校验副本并转换为 PDF
  -> 可选删除已成功处理的源文件
  -> 检查并恢复受保护的标志文件
  -> 卸载并恢复 MSC gadget
  -> reports_pdf
  -> SQLite 上传队列
```

默认镜像为 512 MB、MBR + FAT32，数据目录位于
`/var/lib/gadget-msc-printer`。容量变更不会隐式格式化镜像，必须通过网页显式确认后
调用 `scripts/rebuild_msc_image.sh` 重建。`msc.protected_files` 中的相对路径不会作为
报告采集；首次发现时备份到 `msc.protected_seed_dir`，后续缺失时按配置自动恢复。

## Printer 报告链路

```text
医疗设备枚举 K2B USB Printer
  -> /dev/g_printer0
  -> 连续 idle_complete_seconds 无数据后结束任务
  -> print_jobs/*.prn
  -> 识别 PDF / PCL / PostScript / 图片 / 文本
  -> 转换为 PDF
  -> SQLite 上传队列
```

- PDF：校验后直接归档。
- PostScript：使用 Ghostscript / `ps2pdf`。
- JPEG、PNG、BMP：使用 Pillow。
- 文本：生成 PDF。
- PCL/PCL XL：需要 GhostPDL `gpcl6` 或 `pcl6`。

无法识别或转换时保留原始打印流并记录失败，不生成占位 PDF，防止上传错误报告。
GhostPDL 使用 AGPL/商业双许可，量产前必须完成许可证评审。

## 实体打印链路

```text
reports_pdf 新生成 PDF
  -> PhysicalPrintWorker 稳定性检查和 SQLite 状态记录
  -> CUPS 打印队列
  -> brlaser / IPP Everywhere / 通用 PCL 或 PostScript 驱动
  -> USB Host 或网络实体打印机
```

网页“实体打印机配置”调用 CUPS 标准命令扫描设备、列出已安装驱动、创建队列、设置
默认队列、打印测试页及暂停/恢复/删除队列。网页只能从内置白名单中选择驱动配置，
不能上传驱动或执行任意命令。HP LaserJet Pro 400 M401 使用 Foomatic 的通用黑白
PCL 6/PCL XL `pxlmono` PPD；Brother HL-1218W 使用 Ubuntu arm64 仓库中的
`printer-driver-brlaser`，映射为 Brother HL-1200 series。

自动打印默认关闭。首次启动 `PhysicalPrintWorker` 时，系统把已有 PDF 记为历史基线，
不会突然补打旧报告；之后新 PDF 使用独立 SQLite 状态机提交到 CUPS，失败按配置重试，
且不影响原有报告上传任务。

网页“模拟打印配置”只开放驱动声明、打印机名称、序列号、任务结束等待时间和最小
任务大小。USB VID/PID 使用固定 Gadget 测试值，厂商固定为 `JVLEI`，这些字段不会由
查询 API 返回，也不能通过网页修改。驱动类型只改变 USB Printer 的 IEEE 1284 Device
ID 命令声明：`universal`、`pcl`、`postscript` 或 `raw`；它不会把一种打印语言转换成
另一种。Printer 模式运行期间保存会影响枚举的字段时，服务会事务式重新枚举 gadget，
失败则回滚旧配置。只读 PRN 分析器根据文件头和协议特征报告可能的 PCL、PCL XL、
PostScript、PDF 或私有打印流，不修改原始任务。

## XML 和上传

管理页面保存以下字段：

```text
DeviceCode
ExamDoct
ExamDoctCode
```

生成的 `ReportInfo.xml` 不包含 XML namespace，字段顺序固定。任务入队时保存 XML
完整快照，之后修改配置不会影响已经入队的历史报告。

上传采用 `multipart/form-data`：

```text
Report      = PDF
ReportInfo  = 入队时的 XML 快照
```

每次正式请求同时携带：

```text
MacCode      = DeviceCode
MsgId        = 本次请求的唯一标识
hospitalCode = upload.hospital_code
```

状态机为：

```text
pending -> uploading -> uploaded
                    `-> retry_wait -> uploading
                                   `-> exhausted
```

SQLite 记录 PDF/XML 哈希、来源、HTTP 状态、响应摘要、完整错误、尝试次数和下次重试
时间。网页中的“重复文件去重”会同步设置 `upload.deduplicate` 与
`msc.deduplicate`：开启时跳过已提取或已入队的相同内容，关闭时允许同一文件
重复提取、转换和上传，供现场测试使用。SHA-256 完整性校验不受该开关影响。

报告下载接口 `GET /api/reports/{job_id}/download` 只允许访问配置的 PDF 输出目录，
要求有效登录会话，并以附件方式返回队列中仍然存在的 PDF；路径越界或文件已清理时
返回 404。

## Web 与安全

- 主监听端口为标准 HTTPS 443，同时保留 HTTPS 8443 兼容访问。
- 用户名、密码和会话时长保存在 `config.yaml`，配置权限为 `0640`。
- 登录比较使用常量时间比较。
- 会话 Cookie 使用 Secure、HttpOnly 和 SameSite=Strict。
- 所有写操作校验 CSRF token。
- 登录失败有限流保护。
- 配置查询接口不返回密码。
- 打印配置、U盘配置和重建操作均要求登录；所有写操作继续校验 CSRF token。

Vue 开发服务器默认代理到 `https://192.168.20.144:8443`，可通过
`VITE_API_PROXY_TARGET` 覆盖。生产环境由 aiohttp 直接提供预构建的 `dist`，板端
不安装 Node.js。

## 网络与维护热点

管理端通过 `/api/network` 汇总有线、Wi-Fi 客户端和维护热点状态。有线 IP 从 `ip -j`
结构化输出读取；`/api/wifi/*` 和 `/api/hotspot/*` 调用独立的 `WifiManager`，由
NetworkManager 的 `nmcli` 完成无线开关、扫描、连接和 AP 管理。命令以参数数组执行，
不经过 Shell；Wi-Fi 和热点密码不会通过状态 API 返回，也不会写入应用日志。

Wi-Fi 配置默认设置 `ipv4.route-metric=600` 和 `ipv6.route-metric=600`。现有有线网络
metric 为 100 时优先走有线，拔掉网线后 NetworkManager 自动使用已保存且允许自动
连接的 Wi-Fi。网页服务监听 `0.0.0.0:443` 和兼容端口 `8443`，因此可分别通过有线 IP 或 Wi-Fi IP
访问同一管理端。

维护热点固定使用 `wlan1` 和 `192.168.0.1/24`，连接配置名为 `gmp-hotspot`。
NetworkManager 的 shared IPv4 模式负责 DHCP 和地址分配，运行环境因此需要
`dnsmasq-base` 与 `iptables`。`gadget-web` 每 15 秒通过 `iw station dump` 统计热点客户
端；当客户端数量为零且达到 `hotspot.idle_timeout_minutes` 时关闭热点。`0` 表示禁用
自动关闭，手动关闭不清除开机自启设置。

## 目录与故障恢复

```text
/opt/gadget-msc-printer                 程序
/etc/gadget-msc-printer/config.yaml     配置
/etc/gadget-msc-printer/tls.*           自签名证书
/var/lib/gadget-msc-printer             报告、镜像、SQLite 和状态
```

- 断网：任务进入 `retry_wait`，PDF 和 XML 快照保留。
- 重启：SQLite 恢复未完成任务，遗留 `uploading` 回退为可重试状态。
- XML 无效：停止新任务入队，已存在的完整任务仍可继续。
- 转换失败：保留原始文件，不上传伪报告。
- UDC 未连接主机：gadget 可建立，但 `/sys/class/udc/<name>/state` 显示
  `not attached`；这不是服务故障。
- 模式切换失败：恢复旧配置并尝试重建旧 gadget。
