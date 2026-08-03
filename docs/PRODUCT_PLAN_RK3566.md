# RK3566 MSC / Printer 报告采集与上传产品计划

## 1. 目标

在 RK3566 K11C 上提供一套独立、可部署的医疗报告采集网关，包含：

- 模拟 USB Mass Storage（MSC）或 USB Printer。
- 从 MSC 文件或 Printer 打印流生成 PDF 报告。
- 自动上传 PDF 与 `ReportInfo.xml`。
- 提供需要账户登录的本地配置网页。
- 在配置网页中维护 `DeviceCode`、`ExamDoct` 和 `ExamDoctCode`，并自动生成最小 XML。
- 提供报告日志分页、时间/状态筛选、失败重试、手动清理和定时自动清理。
- 保留原网关已验证的上传协议、业务成功判断、去重和失败重试能力。

本项目不包含患者接口、扫码、HID 自动录入、HDMI 视觉识别和 KVM。

## 2. 目标硬件约束

RK3566 当前只有一个可用 USB Device Controller：

```text
fcc00000.usb
```

因此 MSC 和 Printer 采用互斥运行模式，不能让两个独立 gadget 同时绑定同一个 UDC。

推荐模式：

```yaml
gadget:
  mode: msc  # msc 或 printer
  udc_device: fcc00000.usb
```

切换模式时按以下顺序执行：

```text
停止当前采集器
解绑当前 UDC
删除当前 configfs function 和 gadget
创建目标 gadget
绑定 fcc00000.usb
等待 host 枚举完成
启动对应采集器
```

切换失败时保持“未绑定”状态并返回明确错误，不应自动同时创建两个 gadget。

## 3. 总体架构

```text
医疗设备
  |-- 保存到 USB U盘 --> MSC gadget --> FAT 镜像监控 --> 新文件提取 --|
  |                                                               |
  `-- 打印到 USB 打印机 --> Printer gadget --> PRN/PCL 接收 -------|
                                                                  v
                                                            PDF 归一化
                                                                  |
                                                                  v
                                                        报告任务与去重队列
                                                                  |
                                     ReportInfo.xml --------------|
                                                                  v
                                                      医院报告上传接口
```

三个常驻服务：

1. `gadget-mode.service`
   根据配置创建且只创建一种 USB gadget。
2. `gadget-collector.service`
   运行 MSC 监控或 Printer 捕获，并把产物归一化到 PDF 目录。
3. `gadget-web.service`
   提供登录、配置、XML 生成、状态查询、上传队列和手动重试。

## 4. 目录设计

程序目录：

```text
/opt/gadget-msc-printer
```

只读/管理员配置：

```text
/etc/gadget-msc-printer/config.yaml
/etc/gadget-msc-printer/tls.crt
/etc/gadget-msc-printer/tls.key
```

运行数据：

```text
/var/lib/gadget-msc-printer/
  auth/admin.json
  device/ReportInfo.xml
  msc/ums_shared.img
  msc_files/
  print_jobs/
  reports_pdf/
  state/jobs.sqlite3
  state/last_status.json
```

敏感文件权限：

```text
auth/admin.json  0600
tls.key          0600
config.yaml      0640
ReportInfo.xml   0640
```

## 5. 配置网页

推荐访问地址：

```text
https://<board-ip>:8443
```

管理页面固定使用 HTTPS，不提供 HTTP 登录入口。

### 5.1 登录

- 默认管理员用户名：`admin`。
- 安装时生成随机初始密码，不在代码和 YAML 中保存固定默认密码。
- 密码使用 PBKDF2-HMAC-SHA256 + 独立随机盐保存。
- 首次登录必须修改密码。
- 登录成功后使用 HttpOnly、SameSite=Strict 会话 Cookie。
- 修改配置、切换 gadget、测试上传等 POST 请求必须校验 CSRF token。
- 连续登录失败需要短时间限速。

### 5.2 页面功能

- 当前模式：MSC / Printer。
- USB UDC、枚举状态和当前 function。
- `DeviceCode`。
- `ExamDoct`（检查医生姓名）。
- `ExamDoctCode`。
- 上传接口地址。
- 上传超时、重试间隔和最大次数。
- MSC 容量、卷标和报告扩展名。
- Printer 型号标识、打印任务空闲结束时间。
- 最近报告、当前上传状态、失败原因和重试次数。
- 保存配置。
- 测试上传。
- 手动重新上传。
- 切换 USB 模式。

保存 `DeviceCode`、`ExamDoct` 或 `ExamDoctCode` 时立即重新生成 XML。修改上传参数不需要重启 gadget；修改 MSC/Printer 模式时才执行 gadget 切换。

## 6. ReportInfo.xml

XML 只保留接口需要的根标签和三个业务字段，字段顺序固定：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<UploadReportInfo>
  <DeviceCode>DEVICE_CODE</DeviceCode>
  <ExamDoct>DOCTOR_NAME</ExamDoct>
  <ExamDoctCode>DOCTOR_CODE</ExamDoctCode>
</UploadReportInfo>
```

生成规则：

- 使用 XML API 构建，不拼接字符串。
- 自动处理 `&`、`<`、`>` 等特殊字符。
- 两个字段去除首尾空白后不能为空。
- 建议限制为 1-128 个字符。
- 先写临时文件、`fsync`，再原子替换正式文件。
- 保存后立即重新解析验证；验证失败不覆盖旧 XML。
- 上传任务创建时保存 XML 内容摘要，便于审计报告使用了哪一版配置。

XML 根节点不保留旧文件中的 `xmlns:xsi` 和 `xmlns:xsd` 声明。

## 7. 报告采集

### 7.1 MSC 模式

复用现有流程：

```text
host 写入 FAT32 镜像
检测镜像 mtime 变化
等待 stable_seconds + quiet_seconds
短暂解绑 UDC 和 backing file
只读挂载镜像
提取新增文件并计算 SHA-256
卸载镜像并恢复 backing file
重新绑定 UDC
把可转换文件写入 reports_pdf
```

需要保持 WinCE 兼容参数：MBR、FAT32、removable、SanDisk 类 USB 标识，并支持预置现场要求的目录模板。

### 7.2 Printer 模式

复用现有流程：

```text
host 识别 HP LaserJet Pro 400 M401
/dev/g_printer0 接收打印流
连续空闲达到 idle_complete_seconds 后结束任务
保存原始 PRN
识别 PDF / PCL / PostScript / 图片
使用 GhostPCL、Ghostscript 或 Pillow 转换为 PDF
写入 reports_pdf
```

原始文件始终保留，转换失败时记录失败原因，不生成伪造的正式医疗报告。

## 8. 自动上传

接口沿用旧网关协议：

```text
POST <configured-endpoint>
Content-Type: multipart/form-data

Report      = PDF 文件，application/pdf
ReportInfo  = ReportInfo.xml，application/xml
```

默认接口可沿用：

```text
http://192.168.112.139:9061/api/client/uploadOriginalReport
```

业务成功判断继续兼容：

- HTTP 2xx 且非 JSON 响应：成功。
- `success=true`：成功。
- `code=SUCCESS`：成功。
- `data.code=100` 或 `SUCCESS`：成功。
- HTTP 非 2xx、`success=false`、`FAIL/FAILED/ERROR`：失败。
- `data.code=201/202/203/204/205`：失败。

### 8.1 任务状态

使用 SQLite 保存任务，状态为：

```text
pending -> uploading -> uploaded
                    `-> retry_wait -> uploading
                                   `-> exhausted
```

每个任务至少保存：

- PDF 路径、文件名、大小、SHA-256。
- XML 路径、XML SHA-256、DeviceCode、ExamDoctCode。
- 来源：MSC 或 Printer。
- 创建时间、最后尝试时间、下次重试时间。
- 尝试次数、HTTP 状态、响应摘要、错误信息。

PDF SHA-256 作为报告去重键；修改设备配置不会把目录中的历史 PDF 使用新 XML 再次提交。任务仍保存 XML SHA-256，用于审计当次上传使用的配置版本。

旧上传实现存在一次失败后直接跳过的状态问题；本项目必须让 `retry_wait` 任务按配置重新进入 `uploading`，直到成功或达到最大次数。

### 8.2 文件稳定与并发

- PDF 生成完成并原子改名后才能入队。
- 同一时间只上传一个任务，避免现场弱网络拥塞。
- 断网不会删除报告。
- 服务重启后恢复 `pending/retry_wait/uploading` 任务；遗留的 `uploading` 回退为 `retry_wait`。
- 成功上传后保留本地 PDF，后续可增加按天数清理策略。

## 9. 配置结构

建议最终配置：

```yaml
runtime:
  data_dir: /var/lib/gadget-msc-printer
  log_level: INFO

gadget:
  mode: msc
  udc_device: fcc00000.usb

web:
  enabled: true
  host: 0.0.0.0
  port: 8443
  tls: true

device:
  device_code: ""
  exam_doct: ""
  exam_doct_code: ""
  report_info_path: /var/lib/gadget-msc-printer/device/ReportInfo.xml

upload:
  enabled: true
  endpoint: http://192.168.112.139:9061/api/client/uploadOriginalReport
  timeout_seconds: 30
  retry_interval_seconds: 60
  max_attempts: 3

msc:
  enabled: true
  image_path: /var/lib/gadget-msc-printer/msc/ums_shared.img
  image_size_mb: 512
  stable_seconds: 2
  quiet_seconds: 2

printer:
  enabled: true
  device: /dev/g_printer0
  idle_complete_seconds: 20
  min_job_bytes: 128

pdf:
  enabled: true
  output_dir: /var/lib/gadget-msc-printer/reports_pdf
```

`msc.enabled` 和 `printer.enabled` 表示模块可用，不决定当前枚举模式；当前模式只由 `gadget.mode` 决定。

## 10. API 计划

无需登录：

```text
GET /health
```

需要登录：

```text
POST /api/login
POST /api/logout
GET  /api/status
GET  /api/config
PUT  /api/config
POST /api/password
POST /api/gadget/switch
GET  /api/reports
POST /api/reports/{id}/retry
POST /api/upload/test
GET  /api/logs/recent
```

健康状态至少包含：服务版本、当前模式、UDC 状态、采集器状态、XML 是否有效、待上传数量、最近上传结果和磁盘剩余空间。

## 11. 实施阶段

### 阶段 A：RK3566 单 UDC 适配

- 把 gadget 脚本默认 UDC 改为 `fcc00000.usb`。
- 增加统一清理和互斥切换逻辑。
- 替换当前同时依赖两个 gadget 服务的 systemd 关系。
- 分别验证 Windows/WinCE 的 MSC 和 Printer 枚举。

### 阶段 B：报告队列与上传

- 移植 multipart 上传和业务响应判断。
- 新增 SQLite 任务状态机、自动重试和去重。
- 将 MSC/Printer 的 PDF 输出统一接入队列。
- 增加断网、重启和重复文件测试。

### 阶段 C：配置与 XML

- 新增 XML 生成器和配置验证。
- 新增登录、密码修改和会话管理。
- 新增配置网页与 API。
- 保存模式时调用 gadget 切换器。

### 阶段 D：部署和验收

- 安装到 `/opt/gadget-msc-printer`。
- 配置三个 systemd 服务开机自启。
- 完成 MSC、Printer、上传、断网重试、重启恢复和配置安全测试。
- 生成现场部署说明与故障诊断命令。

## 12. 验收标准

1. 任意时刻只有一个 gadget 绑定 `fcc00000.usb`。
2. 网页可在登录后切换 MSC/Printer，未登录不能读写配置。
3. 保存 `DeviceCode`、`ExamDoct`、`ExamDoctCode` 后 XML 内容、顺序正确且可解析。
4. MSC 保存新报告后自动生成或复制 PDF，并恢复 U盘枚举。
5. Printer 打印 PCL/PS/PDF 后生成有效 PDF。
6. 每个新 PDF 自动上传 `Report + ReportInfo`。
7. 后端明确失败或断网时自动重试，不丢文件、不误报成功。
8. 服务或板子重启后未完成任务继续处理，已上传任务不重复上传。
9. 磁盘满、XML 无效、UDC 冲突和转换失败都有可见错误状态。
10. 自动化测试覆盖 XML、认证、配置、模式互斥、上传响应判断、重试和去重。
11. 报告日志支持时间和成功/失败筛选、分页与失败任务重试。
12. 自动清理只删除超过保留期的已上传报告，并按配置清理 systemd journal。

## 13. 已确认的产品决策

以下产品决策已经确认：

1. MSC/Printer 允许在配置网页中切换。
2. 配置网页固定使用 HTTPS 8443。
3. XML 根节点不保留旧 `xmlns:xsi`、`xmlns:xsd` 声明。
4. 上传成功后默认不连接实体打印机打印；本项目只负责采集、转换和上传。
