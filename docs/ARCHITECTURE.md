# KICKPI K2B 报告网关架构

## 平台基线

- 板卡：KICKPI K2B
- SoC：Allwinner H618
- 系统：Armbian / Ubuntu 24.04 aarch64
- USB Device Controller：运行时从 `/sys/class/udc` 自动选择
- 当前实板 UDC：`musb-hdrc.4.auto`
- 管理端：HTTPS 8443，Vue 3 + aiohttp

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
  -> loop 只读挂载
  -> 按路径、大小和 SHA-256 去重
  -> 复制到 msc_files
  -> 卸载并恢复 MSC gadget
  -> PdfConverter
  -> reports_pdf
  -> SQLite 上传队列
```

默认镜像为 512 MB、MBR + FAT32，数据目录位于
`/var/lib/gadget-msc-printer`。

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
时间。是否按 PDF SHA-256 去重由 `upload.deduplicate` 控制。

## Web 与安全

- 只监听 HTTPS 8443。
- 用户名、密码和会话时长保存在 `config.yaml`，配置权限为 `0640`。
- 登录比较使用常量时间比较。
- 会话 Cookie 使用 Secure、HttpOnly 和 SameSite=Strict。
- 所有写操作校验 CSRF token。
- 登录失败有限流保护。
- 配置查询接口不返回密码。

Vue 开发服务器默认代理到 `https://192.168.20.144:8443`，可通过
`VITE_API_PROXY_TARGET` 覆盖。生产环境由 aiohttp 直接提供预构建的 `dist`，板端
不安装 Node.js。

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
