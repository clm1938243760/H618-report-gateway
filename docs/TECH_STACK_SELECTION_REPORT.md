# 报告采集网关系统、语言与技术栈选型报告

版本：1.0  
日期：2026-07-16  
适用项目：USB MSC / USB Printer 医疗报告采集上传网关

## 1. 执行结论

### 1.1 当前项目使用的技术栈

当前已经实现并经过测试的产品基线不是 RK3506，而是：

```text
硬件              KICKPI K11C / Rockchip RK3566
操作系统          Debian 12，arm64，systemd
内核功能          Linux USB Gadget、configfs、UDC、Mass Storage、Printer
系统配置          Bash + configfs + systemd unit
业务后端          Python 3.11（项目声明兼容 Python >= 3.9）
并发模型          asyncio + asyncio.to_thread
Web 后端          aiohttp
管理页面          原生 HTML / CSS / JavaScript，嵌入 Python 模块
配置              YAML / PyYAML
本地数据库        SQLite，WAL 模式
上传              urllib.request + multipart/form-data
XML               xml.etree.ElementTree
图片和文本转 PDF  Pillow
PCL/PCL XL 转 PDF GhostPCL / GhostPDL
PostScript 转 PDF Ghostscript / ps2pdf
服务管理          systemd + journald
测试              unittest + compileall
部署              apt + Python venv + systemd + 安装脚本
```

仓库当前的 28 项单元和集成级测试已在 Windows Python 3.14 环境通过。板端目标为 Python 3.11，具体见 [AI_CONTEXT.md](../AI_CONTEXT.md)。

### 1.2 推荐结论

1. **样机、医院试点和小批交付：继续使用 Debian + Python。** 当前功能已经跑通，重写语言会增加回归风险，短期收益主要是内存和部署，不是业务吞吐。
2. **新做 RK3506 量产硬件：优先评估 Buildroot + 当前 Python 应用。** 先更换系统，不先重写业务。这样能缩小系统、减少后台服务和依赖漂移，同时保留已经验证的业务逻辑。
3. **当 512MB 内存压测不通过，或批量部署要求单文件程序时：把控制面改为 Go。** USB configfs 和 GhostPDL 保持不变，Go 负责 Web、配置、队列、上传和采集编排。
4. **不建议全量改成 C++ 或 Rust。** 两者运行时资源最好，但对当前约 2200 行 Python 业务的开发、测试和维护成本明显更高，PCL 转换速度仍由 GhostPDL 决定。
5. **不建议为本项目采用 Ubuntu、OpenWrt、Android、Docker 或 RTOS。** 它们分别存在镜像偏大、文档转换生态不匹配、USB Gadget 业务不匹配、特权设备访问复杂或缺少 Linux 用户态能力的问题。
6. **当前 Debian 12 已进入 LTS 阶段。** Debian 官方说明 Bookworm 的 LTS 到 2028-06-30。2026 年新立项不应默认继续锁定 Debian 12；如果 RK3506 BSP 能验证 Debian 13，应优先使用 Debian 13，否则要制定 Debian 12 安全补丁和后续迁移计划。
7. **存储不要按 2GB eMMC 设计。** Debian 路线至少 8GB，建议 16GB；Buildroot 路线理论上可装进 2GB，但还要容纳 512MB MSC 镜像、GhostPDL、报告、日志、升级和恢复空间，工程上仍建议 8GB 起步。

## 2. 项目约束决定技术选型

本项目不是普通网页服务器。技术栈必须同时满足以下约束：

- 一个 USB Device Controller 在 MSC 与 Printer 两种功能之间互斥切换。
- 直接操作 `/sys/kernel/config/usb_gadget`、`/sys/class/udc` 和 `/dev/g_printer0`。
- MSC 模式需要解绑 UDC、只读挂载 FAT32 镜像、提取文件并恢复枚举。
- Printer 模式需要接收 PCL、PCL XL、PostScript、PDF、图片或文本打印流。
- 断网期间报告必须保留，重启后继续上传。
- 医院现场需要 HTTPS 管理、身份验证、审计日志和错误详情。
- 设备需要 7 x 24 小时运行，并能承受直接断电、网络波动和 eMMC 空间压力。
- 目标量产硬件为 512MB DDR、8GB 或 16GB eMMC、以太网和 WiFi。

因此选型优先级应为：

```text
USB UDC/BSP 可靠性
  > 报告不丢失和断电恢复
  > PCL 转换峰值内存
  > 系统可维护和可升级
  > 空闲资源占用
  > Web 请求峰值性能
```

Web 页面只有少量管理员访问，HTTP 每秒请求数不是主要性能指标。

## 3. 当前架构审计

### 3.1 服务边界

当前部署由三个 systemd 服务组成：

| 服务 | 实现 | 主要职责 | 故障影响 |
|---|---|---|---|
| `gadget-mode.service` | Bash + configfs | 开机建立 MSC 或 Printer gadget | 失败时 USB 不枚举 |
| `gadget-collector.service` | Python | MSC 提取或 Printer 捕获、PDF 转换 | 失败时停止采集，Web 仍可用 |
| `gadget-web.service` | Python + aiohttp | HTTPS、配置、SQLite、上传和清理 | 失败时不能管理和上传，USB 仍可枚举 |

三个服务拆分是合理的。它把 USB 枚举、数据采集和管理上传分成独立故障域，优于把全部逻辑塞进一个进程。

### 3.2 USB Gadget 层

当前采用 Linux 内核官方的 configfs 接口：

```text
setup_msc_gadget.sh
  -> mass_storage.0
  -> FAT32 backing image
  -> bind fcc00000.usb

setup_hp_printer_gadget.sh
  -> printer.usb0
  -> /dev/g_printer0
  -> bind fcc00000.usb
```

这是正确的技术路线。Linux 内核文档把 configfs 定义为用户态配置 USB Gadget、configuration 和 function 的标准机制。改用 Go、C++ 或 Rust不会改变这个内核依赖，只会改变操作 configfs 的编排代码。

### 3.3 Python 业务层

当前 Python 源码约 2200 行，核心依赖只有三个：

- `aiohttp`：HTTPS 管理端。
- `PyYAML`：配置文件。
- `Pillow`：图片和文本转 PDF。

其余主要能力来自 Python 标准库：`asyncio`、`sqlite3`、`urllib`、`hashlib`、`ElementTree`、`subprocess`、`pathlib` 和 `select`。依赖面并不算大。

阻塞操作通过 `asyncio.to_thread()` 下沉到线程，包括 SQLite、密码哈希、文件扫描、转换和 systemd 命令；低并发管理页面下不会形成明显瓶颈。

### 3.4 数据持久化

SQLite 已启用：
 
```sql
PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=30000;
```

关键状态使用 `BEGIN IMMEDIATE` 和事务提交。上传状态机为：

```text
pending -> uploading -> uploaded
                    -> retry_wait -> uploading
                                  -> exhausted
```

SQLite 官方建议设备本地、低并发写入场景使用 SQLite。本项目只有少量写入者，不需要 PostgreSQL 或 MariaDB。

### 3.5 原生转换工具

Python 并不直接解释 PCL。实际重负载由外部原生程序承担：

- GhostPCL / GhostPDL：PCL 和 PCL XL。
- Ghostscript：PostScript。
- Pillow：图片和文本。

因此控制层语言从 Python 改为 Go/C++/Rust 后：

- Web、目录扫描、哈希和 JSON/XML 处理会更省资源。
- PCL/PCL XL 的主要 CPU 时间和峰值内存基本不变。
- 大报告能否在 512MB 内存下稳定转换，仍取决于 GhostPDL、页面复杂度、分辨率和并发数。

### 3.6 当前部署方式

当前 [install.sh](../scripts/install.sh) 执行：

```text
apt 安装系统依赖
-> 复制整个源码目录到 /opt/gadget-msc-printer
-> 创建 --system-site-packages venv
-> pip install --no-deps -e
-> 生成自签名证书
-> 屏蔽厂家 usb-gadget.service
-> 安装并启用三个 systemd 服务
```

优点是现场修改快；缺点是：

- `apt` 和在线软件源使安装结果可能随时间变化。
- `--system-site-packages` 让 venv 依赖系统包版本，隔离并不完整。
- editable install 适合开发，不是最佳量产制品。
- 复制整个仓库会带入测试、文档和非运行文件。
- 没有软件包签名、版本回滚和原子系统升级。
- 仓库 `pyproject.toml` 当前标记为 `0.2.0`，而 `AI_CONTEXT.md` 记录板端管理服务为 `0.3.0`，说明版本元数据与部署记录已经发生漂移。

量产前应建立唯一版本来源，由 CI 同时写入软件包名、Web 状态接口、Git tag 和升级清单，禁止人工分别维护多个版本号。

## 4. 当前性能模型

### 4.1 性能瓶颈排序

按当前实现，预计瓶颈从高到低为：

1. GhostPCL/Ghostscript 转换的 CPU 与峰值内存。
2. eMMC 上的打印流、PDF、MSC 镜像和 SQLite 写入。
3. MSC 解绑、挂载、复制、卸载和重新枚举的固定等待。
4. 上传网络质量和医院接口响应时间。
5. Python Web、YAML、XML、哈希和 SQLite 编排开销。

### 4.2 资源占用估算

下表是针对 arm64/armv7 嵌入式 Linux 的**工程估算区间，不是本次板端实测结果**。板子 `192.168.20.51` 当前 SSH 不可达，必须在恢复网络后按第 13 章补测。

| 项目 | 典型区间 | 说明 |
|---|---:|---|
| 精简 Debian 空闲内存 | 80～180MB | 与厂家镜像后台服务差异很大 |
| `gadget-collector` RSS | 25～55MB | Python、Pillow、业务模块 |
| `gadget-web` RSS | 35～75MB | Python、aiohttp、SQLite、HTML 字符串 |
| 两个 Python 服务合计 | 60～130MB | 不含共享页去重后的 PSS 差异 |
| GhostPCL/Ghostscript 单任务峰值 | 80～300MB+ | 与页数、图像、DPI 和 PCL 类型高度相关 |
| Buildroot 基础系统空闲内存 | 20～70MB | 取决于 systemd、网络和 WiFi 服务 |
| Go 控制面进程 | 15～45MB | 单进程、无浏览器引擎、无大型缓存 |
| C++/Rust 控制面进程 | 5～30MB | 取决于 TLS、Web 和数据库库 |

对 512MB DDR 的含义：

- 当前 Debian + Python 在空闲状态大概率可运行。
- 遇到复杂 PCL 时可能接近内存上限。
- Buildroot 通常比重写 Python 更先释放可用内存。
- Go 能进一步节约约 30～80MB，但不能消除 GhostPDL 峰值。
- 必须保持单个转换任务串行，配置 zram 或受控 swap 只能作为缓冲，不能代替内存验证。

2026-07-16 的 RK3566 板端补测表明，两个 Python 服务合计 PSS 仅约 42.7MB，低于上表保守估算；当前整机高内存主要来自 XFCE/Xorg 桌面。详见第 13.6 节。该结果证明 512MB 版本应优先移除桌面并精简系统，而不是直接重写 Python；但它不能代替 512MB RK3506 实板和复杂 PCL 样本测试。

### 4.3 启动、镜像和更新估算

以下为面向本项目功能集的工程规划区间：

| 系统 | 根文件系统/镜像 | 冷启动到服务可用 | 空闲内存 | 说明 |
|---|---:|---:|---:|---|
| Debian minimal | 1.2～3GB | 15～40s | 80～180MB | 开发方便，受厂家镜像影响大 |
| Ubuntu Server | 2～5GB | 20～60s | 150～350MB | 对 512MB 目标偏重 |
| Buildroot | 80～400MB | 4～15s | 20～70MB | 需自行维护完整镜像 |
| Yocto 精简镜像 | 200～900MB | 8～30s | 30～120MB | 可裁剪但构建体系复杂 |
| Alpine | 100～500MB | 5～20s | 30～90MB | musl 和厂家二进制兼容风险 |
| OpenWrt | 30～200MB | 5～20s | 20～80MB | 网络强，文档转换和 BSP 适配弱 |

数值受内核、WiFi、日志、SSH、systemd/BusyBox、驱动和文件系统影响，不能作为验收结果。

## 5. 操作系统详细对比

### 5.1 Debian 12/13

**优势**

- 当前 RK3566 已验证，开发人员熟悉 apt、systemd、Python 和 Debian 工具。
- Ghostscript、Pillow、aiohttp、dosfstools、util-linux 等依赖容易获得。
- 现场 SSH 排查最方便，招聘和维护门槛低。
- systemd 的服务重启、依赖关系和 journald 已在项目中使用。

**不足**

- 镜像、内存和 eMMC 占用高于定制嵌入式系统。
- 在线 apt 安装不利于量产可复现。
- 厂家 Debian 镜像可能包含无关桌面、服务和调试组件。
- Debian 用户态版本与 Rockchip 厂商内核/BSP 并不总是同步。
- Debian 12 已进入 LTS，官方支持到 2028-06-30；新产品生命周期可能超过该日期。

**稳定性判断**

Debian 本身成熟，当前风险主要不是发行版崩溃，而是厂家 BSP、UDC 驱动、在线依赖变化和现场非原子升级。固定镜像、锁定包版本并进行 7 天压力测试后，试点稳定性较高。

**适用阶段**

- 研发、样机、试点、小批量。
- 项目时间优先于极致成本和启动速度。

### 5.2 Buildroot

Buildroot 是生成交叉工具链、bootloader、kernel 和 root filesystem 的嵌入式 Linux 构建系统。

**优势**

- 只包含需要的组件，镜像和空闲内存最容易压缩。
- 固定 defconfig、下载源和哈希后，量产镜像高度可复现。
- 可把 Python、aiohttp、Pillow、SQLite、GhostPDL 和本项目作为 Buildroot package 固化。
- rootfs 可以只读，运行数据单独放数据分区，抗误操作能力更好。
- 适合 512MB DDR 和 8GB eMMC。

**不足**

- 目标板上不适合随意 apt 安装和修改。
- 删除或改变底层依赖时常需要重新生成完整镜像；Buildroot 官方手册也说明其不跟踪每个软件包安装的全部文件，删除包不支持增量完成。
- Python C 扩展、GhostPDL、WiFi 固件和 Rockchip BSP 都要纳入交叉编译体系。
- 开发人员需要维护 defconfig、overlay、package recipe 和升级镜像。

**稳定性判断**

固定镜像和只读 rootfs 能降低版本漂移，量产运行稳定性通常优于“现场 apt + pip”。但首次 BSP 集成和升级机制如果做得不好，开发期风险高于 Debian。

**适用阶段**

- RK3506 定型、512MB 内存、1000 台级量产。
- 有能力维护板级 BSP 和整机镜像。

### 5.3 Yocto Project

**优势**

- Layer、recipe、license manifest、SDK、包源和镜像策略适合长期产品线。
- 多硬件、多客户 SKU 和十年生命周期时，比 Buildroot 更容易形成组织化维护体系。
- 适合接入 SBOM、签名、A/B 升级和企业 CI。

**不足**

- 学习、构建时间、磁盘和 CI 资源需求最高。
- 当前只有一个小型产品和约 2200 行业务代码，前期投入偏大。
- 排查 recipe、layer 优先级和 sstate 问题需要专门经验。

**稳定性判断**

体系成熟后，版本治理和可追溯性最佳；团队经验不足时，构建系统本身会成为交付风险。

**适用阶段**

- 多型号产品线、严格软件物料清单、长期 OTA、多人 BSP 团队。
- 当前单产品首版不作为第一选择。

### 5.4 Ubuntu Server / Ubuntu Core

- 软件生态接近 Debian，开发容易。
- 默认服务和镜像更重，对 512MB DDR、8GB eMMC 没有优势。
- Ubuntu Core 的 snap 和只读系统有升级优势，但需引入独立生态和服务管理方式。
- Rockchip 厂家通常先提供自己的 Debian/Buildroot BSP，Ubuntu 用户态不等于更好的 UDC 驱动。

结论：除非模块厂家只对 Ubuntu 提供完整支持，否则不选择。

### 5.5 Alpine Linux

- 体积小，包管理简单。
- 使用 musl libc，厂家预编译工具、GhostPDL 构建脚本和部分 Python wheel 可能需要重新适配。
- Rockchip BSP 社区资料少于 Debian/Buildroot。

结论：节省的空间不足以抵消兼容风险。

### 5.6 OpenWrt

- 网络、WiFi、Web 管理和升级能力强。
- 本项目的核心是 USB Printer、FAT 镜像和 PCL/PDF 转换，不是路由器。
- GhostPDL、Pillow、完整 Python 环境和医疗报告归档会显著增加 OpenWrt 适配成本。

结论：如果产品只做网络串口网关可以考虑；当前完整报告网关不采用。

### 5.7 Android、Windows IoT 和 RTOS

- Android 不适合通过标准 Linux configfs 管理本产品的完整 Gadget/Printer 流程，也会增加系统体积和权限限制。
- Windows IoT 缺少当前 Rockchip BSP、configfs 和 `/dev/g_printer0` 路线。
- FreeRTOS/Zephyr 缺少 GhostPDL、SQLite、完整文件系统、HTTPS 管理和 Linux USB Gadget 生态。

结论：都不满足当前功能边界。

### 5.8 系统综合评分

5 分为最好，评分面向当前报告网关而不是通用评价。

| 指标 | 权重 | Debian | Buildroot | Yocto | Ubuntu | Alpine | OpenWrt |
|---|---:|---:|---:|---:|---:|---:|---:|
| RK35xx BSP/现有经验 | 20% | 5.0 | 4.5 | 3.5 | 3.0 | 2.0 | 2.5 |
| 512MB 资源效率 | 20% | 2.5 | 5.0 | 4.0 | 1.5 | 4.5 | 4.5 |
| PCL/Python 依赖可用性 | 15% | 5.0 | 3.5 | 4.0 | 5.0 | 2.5 | 2.0 |
| 量产可复现 | 15% | 3.0 | 4.5 | 5.0 | 3.0 | 3.5 | 4.0 |
| 现场调试效率 | 10% | 5.0 | 3.0 | 3.0 | 5.0 | 3.5 | 3.5 |
| OTA/回滚能力 | 10% | 3.0 | 4.0 | 5.0 | 4.0 | 3.5 | 4.5 |
| 团队学习成本 | 10% | 5.0 | 3.0 | 1.5 | 4.5 | 3.0 | 2.5 |
| **加权总分** | **100%** | **4.00** | **4.18** | **3.80** | **3.13** | **3.13** | **3.20** |

结论不是立即抛弃 Debian，而是：**Debian 最适合当前交付，Buildroot 最适合 RK3506 量产定型。**

## 6. 语言详细对比

### 6.1 Python（当前方案）

**优势**

- 当前功能和测试已存在，修改速度最快。
- 文件、XML、SQLite、HTTP、哈希和 subprocess 编排代码简洁。
- 异常堆栈和现场调试友好。
- 对低并发 Web 和 I/O 编排，性能已经足够。

**不足**

- 两个解释器进程有明显空闲内存成本。
- 动态类型错误主要依赖测试发现。
- 依赖解释器、Python 包和 C 扩展版本。
- CPU 密集型纯 Python 循环受 GIL 和解释执行影响。

**对当前项目的实际影响**

当前 CPU 重负载在 GhostPDL 子进程，不在 Python 循环。保持单任务转换时，Python 不会成为首先需要解决的瓶颈。

### 6.2 Go

**优势**

- 编译为单一 ARM/ARM64 可执行文件，部署和回滚简单。
- goroutine、HTTP、TLS、JSON、文件和并发队列生态成熟。
- 静态类型能在编译期发现一部分错误。
- 通常比两个 Python 服务节省数十 MB 内存。
- 官方工具链直接支持 `linux/arm` 和 `linux/arm64` 交叉编译。

**不足**

- 当前业务需要完整重写和回归。
- SQLite 驱动需要选择 cgo 或纯 Go 实现；cgo 会增加交叉编译和动态库问题。
- Pillow 的功能要换图像/PDF库或继续调用外部工具。
- XML、multipart 成功判断、SQLite 迁移和现有边界条件都需要重新验证。

**适用判断**

如果 512MB 版本的实测峰值只差 30～80MB，Go 是最现实的语言优化路线。建议只重写控制面，继续调用 GhostPDL/Ghostscript。

### 6.3 C++

**优势**

- 运行时和启动开销低。
- 对 configfs、设备节点、epoll 和内存控制最直接。
- 可精确限制缓冲区和线程。

**不足**

- Web、TLS、SQLite、YAML、XML、multipart、认证和错误处理需要组合多个库。
- 内存安全、生命周期、异常和跨线程资源管理风险高。
- ARM 交叉编译和第三方 ABI 管理复杂。
- 对当前 I/O 编排业务，性能优势不能抵消开发成本。

**适用判断**

只适合极小的特权 Gadget helper、设备节点读取器或确有性能证据的热点，不建议全量重写。

### 6.4 Rust

**优势**

- 接近 C++ 的性能和体积，同时提供所有权和类型安全。
- Tokio、Axum、Serde、SQLx/rusqlite 能覆盖当前控制面。
- 适合长期维护的高可靠系统组件。

**不足**

- 学习和首次开发成本高。
- ARM 交叉编译、OpenSSL、SQLite 和 C 库链接仍需要工具链治理。
- 编译时间和泛型错误排查成本高于 Go。
- 现有团队和代码都以 Python 为主。

**适用判断**

适合未来安全边界明确的系统守护进程，但不是当前项目最经济的重写方案。

### 6.5 Node.js / TypeScript

**优势**

- Web 页面、API 和实时状态开发效率高。
- TypeScript 提供较好的应用层类型检查。

**不足**

- V8 基础内存通常高于 Go、C++ 和 Rust，在 512MB 设备上没有明显优势。
- configfs、设备节点、PCL 转换仍需 shell/native 子进程。
- npm 依赖树和量产离线部署复杂度高于当前三个 Python 依赖。

结论：不采用。

### 6.6 Shell

Shell 很适合一次性的 configfs 建立和系统安装，不适合 SQLite 状态机、Web 安全、multipart 上传和复杂错误恢复。当前“Shell 做系统配置、Python 做业务”的边界是合理的。

### 6.7 性能与开发量对比

以下把当前 Python 控制面作为 1.0 基线，均为工程估算；PCL 转换仍使用同一 GhostPDL。

| 指标 | Python | Go | C++ | Rust | Node.js |
|---|---:|---:|---:|---:|---:|
| 控制面空闲内存 | 1.00 | 0.35～0.65 | 0.20～0.45 | 0.20～0.45 | 0.80～1.50 |
| 文件/HTTP/哈希吞吐 | 1.00 | 1.1～1.8 | 1.2～2.0 | 1.2～2.0 | 0.9～1.5 |
| 纯语言 CPU 计算 | 1.00 | 2～5 | 3～10 | 3～10 | 1.5～4 |
| 端到端 PCL 转 PDF | 1.00 | 0.95～1.10 | 0.95～1.10 | 0.95～1.10 | 0.95～1.10 |
| 首次重写工作量 | 1.00 | 1.8～2.8 | 3～5 | 3～5 | 1.5～2.5 |
| 现场热修复效率 | 5/5 | 3/5 | 2/5 | 2/5 | 4/5 |
| 单文件部署能力 | 较弱 | 强 | 强 | 强 | 较弱 |

关键结论：**语言对控制面有明显差异，对整条 PCL 转换链路的差异很小。**

### 6.8 语言综合评分

| 指标 | 权重 | Python | Go | C++ | Rust | Node.js |
|---|---:|---:|---:|---:|---:|---:|
| 现有代码与验证 | 25% | 5.0 | 1.5 | 1.0 | 1.0 | 1.0 |
| 512MB 资源效率 | 20% | 2.5 | 4.3 | 5.0 | 5.0 | 2.0 |
| 部署简单度 | 15% | 3.0 | 5.0 | 4.0 | 4.0 | 2.5 |
| 开发维护效率 | 15% | 5.0 | 4.0 | 2.5 | 2.5 | 4.0 |
| 运行安全和类型 | 10% | 2.5 | 4.0 | 2.5 | 5.0 | 3.5 |
| Linux 设备编排 | 10% | 4.5 | 4.5 | 5.0 | 4.5 | 3.0 |
| 团队迁移风险 | 5% | 5.0 | 3.5 | 2.0 | 2.0 | 3.0 |
| **加权总分** | **100%** | **4.03** | **3.65** | **3.13** | **3.38** | **2.63** |

当前阶段 Python 得分最高；如果去掉“现有代码与验证”这一项，Go 会成为量产控制面的首选。

## 7. Web 技术栈对比

| 方案 | 性能 | 内存 | 开发 | 部署 | 本项目判断 |
|---|---|---|---|---|---|
| aiohttp（当前） | 足够 | 中 | 已完成 | 需 Python 环境 | 保留 |
| FastAPI + Uvicorn | 足够 | 中偏高 | 数据模型/API 文档更强 | 依赖更多 | 当前 API 很小，无必要迁移 |
| Flask + Gunicorn | 同步模型简单 | 多 worker 时偏高 | 容易 | 需进程管理 | 不优于 aiohttp |
| Go `net/http` | 高 | 低 | 中 | 单文件 | Go 重写时首选标准库或轻框架 |
| Rust Axum/Actix | 高 | 低 | 较高 | 单文件 | 仅随 Rust 路线选择 |
| C++ Drogon/Crow | 高 | 最低 | 高 | 动态库/静态链接 | 不建议为小管理端引入 |

管理页面当前使用原生 HTML/CSS/JavaScript，避免了 React/Vue 构建链和运行时依赖。页面只有配置、日志和状态，不需要 SPA 框架。建议继续使用原生前端，但将 35KB 的内嵌页面逐步拆成独立静态资源，便于缓存、审查和 UI 维护。

## 8. 数据与配置技术对比

### 8.1 SQLite 与替代方案

| 方案 | 断电一致性 | 查询分页 | 资源占用 | 部署 | 结论 |
|---|---|---|---|---|---|
| SQLite WAL（当前） | 高，需正确同步 | 强 | 低 | 单文件 | 最合适 |
| JSON/YAML 状态文件 | 原子替换可保证单文件 | 弱 | 低 | 简单 | 不适合状态机和分页 |
| LMDB | 高 | 键值查询强 | 很低 | 需新库 | 没有 SQL，迁移收益小 |
| PostgreSQL/MariaDB | 高 | 很强 | 高 | 需数据库服务 | 对单设备过度设计 |
| 远程数据库 | 依赖网络 | 强 | 板端低 | 运维复杂 | 断网场景不允许 |

当前 SQLite 方案应保留。后续应补充的验证不是换数据库，而是：

- 直接断电后的 `PRAGMA integrity_check`。
- WAL、主库和 eMMC 同步策略。
- 数据库增长上限和 checkpoint。
- 100 次重启后的 `uploading -> retry_wait` 恢复。

### 8.2 YAML 与替代方案

- YAML 对现场人工查看和修改友好，当前字段量较小，可以保留。
- JSON 语法严格但注释能力弱，收益有限。
- TOML 更适合静态应用配置，但迁移无业务价值。
- SQLite 配置表适合多用户和审计，当前单管理员不需要。

关键是所有配置写入继续使用临时文件、`fsync` 和原子替换。

## 9. USB Gadget 实现方式对比

| 方式 | 特点 | 稳定性 | 适用判断 |
|---|---|---|---|
| configfs + Bash（当前） | 内核标准接口、可观察、易排查 | 已验证 | 保留 |
| configfs + Go/C++/Rust helper | 类型化、可做锁和状态机 | 高，但需重测 | 量产安全加固可采用 |
| libusbgx | C API 封装 configfs | 减少脚本，但增加库 | 当前收益不大 |
| 旧式 `g_mass_storage` 等模块 | 参数固定、组合能力弱 | 旧方案 | 不采用 |
| FunctionFS | 适合自定义用户态 USB function | 灵活但复杂 | MSC/Printer 已有内核 function，不需要 |

建议长期把特权操作收敛为一个很小的 root helper：

```text
Web 服务（非 root）
  -> Unix socket / D-Bus
  -> gadget-helper（root，只允许 msc/printer/status）
  -> configfs
```

这项改造的价值是安全边界和并发锁，不是速度。

## 10. 稳定性差异

### 10.1 当前 Python + Debian

优势：

- 三服务隔离，systemd `Restart=always` 能恢复进程异常。
- SQLite 持久化队列可恢复上传。
- 原始文件保留，转换失败不生成伪 PDF。
- 已有模式切换回滚、未来 FAT 时间戳、去重开关等回归测试。

主要风险：

- root Web 服务可调用 systemctl 和 gadget 脚本，权限面偏大。
- 在线 apt 和 system-site-packages 可能导致依赖漂移。
- Python 异常可被 systemd 拉起，但进行中的文件任务要继续验证幂等性。
- Debian 12 生命周期短于医疗设备预期生命周期。
- 自签名证书和内存会话不适合更严格的集中运维要求。

### 10.2 Buildroot + Python

- 业务稳定性与当前 Python 接近。
- 固定只读镜像减少现场变更和依赖漂移。
- 更少后台进程，OOM 风险更低。
- 但整机镜像构建、WiFi 固件、证书和升级都由项目团队负责，错误镜像影响面更大。

### 10.3 Debian/Buildroot + Go

- 单一控制面二进制减少解释器和包版本问题。
- 静态类型降低部分运行时错误。
- Go runtime 有 GC，极端内存限制仍需设定 `GOMEMLIMIT` 和做压力测试。
- 重写会引入新的状态机、multipart、XML 和模式切换回归风险。

### 10.4 C++/Rust

- C++ 资源可控，但内存安全和并发错误可能比 Python 异常更难复现。
- Rust 能降低内存安全风险，但不能自动保证业务状态机、掉电一致性和 USB 时序正确。
- 两者都需要更完善的交叉编译、sanitizer、静态分析和硬件在环测试。

### 10.5 稳定性不是由语言单独决定

本项目稳定性排序更受以下因素影响：

```text
UDC 驱动和 host 兼容性
> 文件写入与断电一致性
> 状态机幂等性
> eMMC 寿命和空间管理
> PCL 转换内存上限
> 服务监管和回滚
> 语言运行时
```

## 11. 部署方式详细对比

### 11.1 当前安装脚本

**开发速度：最高。量产一致性：一般。**

每块板执行 apt、复制源码、创建 venv、安装服务。适合研发和少量设备，不适合无网络工厂和大规模版本审计。

### 11.2 Python wheel + 离线 wheelhouse

改进方式：

```text
构建 versioned wheel
-> 下载并固定 arm/arm64 依赖 wheel 或系统包
-> 保存 SHA-256 清单
-> 离线创建 venv
-> pip install --no-index --require-hashes
-> 原子切换 /opt/gadget-msc-printer/current 软链接
```

优点是继续使用 Python，部署可复现；缺点是 Pillow/aiohttp 的架构 wheel 和系统库仍要管理。

### 11.3 Debian `.deb` 软件包

**当前路线最推荐的近期改进。**

- 把源码、systemd unit、脚本和配置样例打成版本化 `.deb`。
- 依赖由 dpkg 记录，升级和卸载可审计。
- 工厂建立离线 apt 仓库，禁止每台设备直接访问公网。
- 数据目录和配置不随软件包升级删除。

仍需额外解决 GhostPDL 构建/许可和整机系统回滚。

### 11.4 Go/C++/Rust 单二进制

```text
CI 交叉编译
-> 签名和 SHA-256
-> 上传到备用目录
-> systemd stop
-> 原子替换软链接
-> systemd start + health check
-> 失败回滚
```

部署最简单，但仍需要 Bash/configfs、GhostPDL、证书和系统库，不能真正只有一个文件。

### 11.5 Buildroot/Yocto 整机镜像

- 应用、kernel、DTS、WiFi firmware、GhostPDL、证书策略和 systemd/init 配置一起构建。
- 量产烧录同一个签名镜像，可追溯性最好。
- 应采用 A/B rootfs 或 recovery 分区，而不是覆盖正在运行的系统。
- SWUpdate 支持 eMMC、网络、本地介质和双副本方案，可作为 Buildroot/Yocto 的升级框架候选。

### 11.6 容器

不推荐 Docker/Podman 作为当前板端主部署方式：

- 需要特权访问 configfs、UDC、loop、mount 和 `/dev/g_printer0`。
- 镜像层、容器运行时和日志增加 eMMC/内存占用。
- GhostPDL 和硬件设备权限仍需宿主机配置。
- 容器不能替代 BSP、kernel 和 Gadget 驱动升级。

容器可以用于 CI 和 x86 模拟测试，不用于 512MB 产品运行时。

### 11.7 部署综合对比

| 方式 | 首次开发 | 单台安装 | 批量一致性 | 回滚 | 现场调试 | 推荐阶段 |
|---|---|---|---|---|---|---|
| 当前脚本 + venv | 最快 | 5～20 分钟 | 一般 | 手工 | 最方便 | 研发/样机 |
| wheel + 离线依赖 | 较低 | 1～5 分钟 | 较高 | 应用级 | 方便 | 试点/小批 |
| Debian `.deb` | 中 | 1～3 分钟 | 高 | 应用级 | 方便 | 近期量产 |
| Go 单二进制 | 重写成本高 | 秒级 | 高 | 应用级 | 中 | 控制面重写后 |
| Buildroot A/B 镜像 | 高 | 烧录/OTA | 很高 | 系统级 | 较难 | RK3506 量产 |
| Yocto A/B 镜像 | 最高 | 烧录/OTA | 最高 | 系统级 | 较难 | 多产品线 |

## 12. 推荐的分阶段路线

### 阶段 A：当前 RK3566 继续交付

保持：

```text
Debian + systemd + Bash/configfs + Python + aiohttp + SQLite + GhostPDL
```

优先改进：

1. 把当前版本打成 `.deb` 或离线 wheel，停止量产设备在线 apt/pip。
2. 固定 Debian 镜像、Python 和依赖版本，生成 SHA-256 和软件物料清单。
3. 将 Web 服务降权，增加独立的 root gadget helper。
4. 配置 systemd 资源上限、文件权限和日志配额。
5. 正式部署把 `upload.deduplicate` 恢复为 `true`。
6. 确认 GhostPDL 的 AGPL 合规或采购商业许可。Artifex 官方采用 AGPL/商业双许可，闭源分发不能忽略该项。

### 阶段 B：RK3506 样板迁移

1. 首先用厂家 Debian/Buildroot 验证 UDC、Printer、MSC 和 WiFi，不先重写语言。
2. 在同一批 PCL 样本上记录 Python 版本的峰值 RSS 和转换时间。
3. 512MB 压测通过：保留 Python，优先完成硬件和系统定型。
4. 只差数十 MB 内存或要求单文件部署：启动 Go 控制面原型。
5. 复杂 PCL 仍 OOM：升级 1GB DDR、降低转换分辨率或限制文档复杂度；改 Go 不能根治。

### 阶段 C：量产系统

推荐组合：

```text
RK3506B/J
+ 512MB DDR（复杂 PCL 选 1GB）
+ 8GB eMMC 最低，16GB 推荐
+ Buildroot
+ systemd 或受控 BusyBox init
+ 当前 Python 业务，或经 A/B 数据证明后的 Go 控制面
+ SQLite WAL
+ GhostPDL/Ghostscript 原生工具
+ SWUpdate A/B 或 recovery 升级
```

### 阶段 D：是否重写 Go 的门槛

只有同时满足以下任一条件才立项：

- 512MB 版本在系统精简后仍因控制面内存无法通过压力测试。
- Python 服务空闲 PSS 超过整机内存预算的 20%。
- 量产部署明确要求单二进制和无 Python 运行时。
- 业务规模扩大，当前 Python 状态机维护成本显著上升。
- 有至少 6～10 周开发、双实现对照和真实医疗设备回归时间。

## 13. 必须执行的板端性能验证

### 13.1 基础信息

```bash
uname -a
cat /etc/os-release
python3 --version
free -h
df -hT
systemd-analyze
systemd-analyze blame | head -30
```

### 13.2 服务内存

```bash
systemctl show gadget-collector gadget-web \
  -p MainPID -p MemoryCurrent -p CPUUsageNSec

ps -eo pid,ppid,comm,rss,vsz,%cpu --sort=-rss | head -30

for service in gadget-collector gadget-web; do
  pid="$(systemctl show -p MainPID --value "$service")"
  echo "=== $service pid=$pid ==="
  grep -E 'VmRSS|VmHWM|VmSwap|Threads' "/proc/$pid/status"
  grep -E 'Pss:|Private_' "/proc/$pid/smaps_rollup"
done
```

### 13.3 转换峰值

使用同一批真实 PCL、PCL XL、PostScript、PDF、图片样本：

```bash
/usr/bin/time -v gpcl6 -dNOPAUSE -dBATCH -sDEVICE=pdfwrite \
  -sOutputFile=/tmp/out.pdf /path/to/sample.prn
```

记录：

- 1、10、50 页转换耗时。
- Maximum resident set size。
- CPU 利用率。
- 输出 PDF 大小和页面正确性。
- 512MB 条件下是否触发 OOM killer。

### 13.4 业务验收指标

| 项目 | 建议门槛 |
|---|---|
| 开机到 Web 健康 | Debian <= 40s；Buildroot <= 15s |
| 空闲可用内存 | 512MB 版本 >= 180MB |
| 空闲 swap 使用 | 0 |
| 10 页现场 PCL | 无 OOM，结果页面完整 |
| 模式切换 | 100 次无 EBUSY、无残留 gadget |
| USB 插拔 | 500 次无服务永久退出 |
| 断电恢复 | 100 次后 SQLite 完整，任务不丢失 |
| 网络恢复 | AP/网线恢复后任务自动继续上传 |
| 存储压力 | eMMC 90% 使用率时拒绝新任务并告警，不破坏数据库 |
| 稳定运行 | 7 x 24 小时无持续内存增长 |

### 13.5 A/B 比较方法

系统或语言比较必须使用：

- 同一块板或同规格板。
- 同一内核和 DTS。
- 同一 GhostPDL 版本、参数和输入文件。
- 同一 WiFi/有线网络。
- 同一 eMMC 文件系统和剩余空间。
- 至少 30 次重复测试，记录中位数、P95 和最大值。

否则不能把差异归因于 Debian/Buildroot 或 Python/Go。

### 13.6 2026-07-16 RK3566 板端补测结果

#### 13.6.1 测试环境

本次通过 SSH 直接读取运行中的现场测试板，未停止业务服务，未修改正式配置，未触发报告重传。测试生成的文件均位于 `/tmp` 或专用临时路径，完成后删除。

| 项目 | 实测值 |
|---|---|
| 板卡/CPU | RK3566，4 x Cortex-A55，408MHz～1.8GHz |
| 内核 | Linux 6.1.141，aarch64 |
| 系统 | Debian GNU/Linux 12 Bookworm |
| 物理内存 | 1.9GiB，无 swap |
| eMMC | 14.7GB 标称分区容量，根分区 14GB |
| Python | 3.11.2 |
| GhostPCL | 10.07.1，PJL/PCL/PCLXL |
| 当前 Gadget | Printer，`fcc00000.usb` 为 `configured` |
| 服务 | `gadget-mode`、`gadget-collector`、`gadget-web` 均 enabled/active |
| 健康接口 | `{"ok": true, "service": "gadget-web", "version": "0.3.0"}` |

板端 `pyproject.toml` 仍为 `0.2.0`，健康接口为 `0.3.0`，版本元数据不一致；该问题验证了第 3.6 节所述部署版本漂移风险。

#### 13.6.2 启动与磁盘

| 指标 | 实测值 |
|---|---:|
| 内核启动 | 1.589s |
| 用户态启动 | 8.675s |
| 总启动时间 | 10.264s |
| `gadget-collector` 开始 | 开机后 6.504s |
| `gadget-web` 开始 | 开机后 6.663s |
| graphical target | 开机后 8.554s |
| 根分区使用 | 4.1GB / 14GB，31% |
| 项目 `/opt` 占用 | 26MB |
| Python venv | 25MB |
| 运行数据目录 | 5.9MB |
| `/var/log` | 53MB |

结论：当前应用本身很小，4.1GB 主要来自完整 Debian 和桌面环境。8GB eMMC 可以运行但升级和缓存余量有限，16GB 更适合正式产品。

#### 13.6.3 内存与空闲 CPU

| 项目 | RSS | PSS | 30 秒空闲 CPU |
|---|---:|---:|---:|
| `gadget-collector` | 27.0MB | 16.9MB | 单核占比 0.188% |
| `gadget-web` | 34.4MB | 25.8MB | 单核占比 1.199% |
| 两个业务服务合计 | 61.4MB | 42.7MB | 约 1.387% 单核 |

30 秒 CPU 百分比以一个 CPU 核为 100%；RK3566 有四核，因此两个服务合计只占整机总 CPU 容量约 0.35%。`gadget-web` 的主要空闲活动来自每 5 秒扫描上传目录和任务队列。

整机进程 PSS：

| 进程组 | PSS |
|---|---:|
| 全部进程 | 525.7MB |
| 普通桌面用户会话 | 315.8MB |
| LightDM/Xorg | 80.3MB |
| 桌面相关合计 | 396.1MB |
| 扣除桌面后的其他进程估算 | 129.6MB |

结论：当前 2GB 板运行非常充裕。若迁移到 512MB，必须关闭 XFCE、Xorg、LightDM、蓝牙托盘、Tracker、音频面板等无关组件。以当前样本看，Python 服务不是首要内存瓶颈。

#### 13.6.4 GhostPCL 真实样本

使用正式代码相同参数：

```text
gpcl6 -dNOPAUSE -dBATCH -sDEVICE=pdfwrite -sPAPERSIZE=a4
```

对 1,258,464 字节真实 PRN 连续转换 30 次：

| 指标 | 实测值 |
|---|---:|
| 最小耗时 | 0.485s |
| 中位数 | 0.520s |
| 平均值 | 0.520s |
| P95 | 0.547s |
| 最大值 | 0.548s |
| 峰值 RSS 中位数 | 45,132KB |
| 峰值 RSS 最大值 | 45,248KB |
| 输出 | 137,630 字节，PDF 1.7，1 页 |

三份现有打印样本各执行一次：

| 输入 | 页数 | 转换耗时 | 峰值 RSS | 输出大小 | 警告 |
|---:|---:|---:|---:|---:|---|
| 29,029B | 24 页 | 0.572s | 28,224KB | 43,323B | 无 |
| 1,258,464B | 1 页 | 0.544s | 45,136KB | 137,630B | RasterOP 204 |
| 1,258,464B | 1 页 | 0.519s | 45,264KB | 137,630B | RasterOP 204 |

两份大样本均返回：

```text
Unsupported use of RasterOP 204 detected. Output may not be correct.
```

这不是性能错误，进程返回码为 0 且生成了 PDF；但必须将 PDF 与原始打印页面逐项视觉比对，确认 RasterOP 混合效果、文字和图形没有丢失。当前样本峰值约 45MB，不代表复杂彩色、多页或高 DPI PCL 的上限。

#### 13.6.5 Printer 端到端延迟

三份历史任务从接收首批打印数据到 PDF 文件生成：

```text
20.748s
20.864s
20.856s
```

当前配置 `printer.idle_complete_seconds=20`，而转换本身约 0.52s，因此约 97% 的等待来自打印任务空闲结束判定，不是 RK3566 性能不足。

可将空闲时间试验性降到 3～5 秒以显著改善体验，但必须使用真实设备连续打印多页，确认设备不会在页间停顿超过该值；否则会把一个打印任务错误拆成多个 PDF。更稳的长期方案是同时识别 PJL/UEL 作业结束标志，以 3～5 秒为空闲兜底。

#### 13.6.6 Web、SQLite 与上传

| 项目 | 实测值 |
|---|---:|
| 20 次全新本机 TLS 连接中位数 | 38.3ms |
| 全新 TLS 连接平均值 | 38.3ms |
| 复用 HTTPS 连接 100 次中位数 | 8.75ms |
| 复用连接 P95 | 9.83ms |
| SQLite integrity check | `ok` |
| SQLite journal mode | `wal` |
| 历史任务 | uploaded 4，exhausted 4 |
| 已成功 MSC 上传总处理 | 4.67～5.85s |

4 个 `exhausted` 任务均收到了 HTTP 200，但后端返回患者/申请单匹配失败，属于业务数据拒绝，不是网络或板端崩溃。当前测试配置仍为：

```yaml
upload:
  deduplicate: false
```

正式上线前必须恢复为 `true`。

#### 13.6.7 eMMC 顺序 I/O

使用 128MiB 临时文件和 direct I/O，完成后已删除：

| 指标 | 实测值 |
|---|---:|
| 顺序写入 | 52.6MB/s |
| 顺序读取 | 163MB/s |

该速度足够当前打印流、PDF 和 SQLite 负载。该测试只反映短时顺序吞吐，不代表 4K 随机写、掉电一致性、寿命或长期写放大。

#### 13.6.8 补测后的选型修正

1. 当前 Python 控制面约 43MB PSS，暂时没有重写 Go 的性能依据。
2. 512MB RK3506 首版应采用无桌面 Debian 或 Buildroot；完整 XFCE Debian 不适合。
3. 当前样本 GhostPCL 峰值约 45MB，512MB 有希望通过，但仍缺复杂现场样本压力测试。
4. 最大可感知延迟来自 20 秒 Printer 空闲阈值，优先优化作业边界检测，不是更换 CPU 或语言。
5. Web、SQLite 和 eMMC 吞吐均有充足余量。
6. 当前必须处理版本号不一致、测试去重仍关闭和 RasterOP 输出正确性三个上线问题。

## 14. 风险清单

| 风险 | 影响 | 优先措施 |
|---|---|---|
| RK3506 UDC/Printer BSP 未验证 | 产品不可用 | 立项前真实设备枚举测试 |
| 512MB 下 GhostPDL OOM | 报告丢失或服务重启 | 真实 PCL 峰值压测，必要时 1GB |
| Debian 12 生命周期 | 安全维护中断 | Debian 13 验证或 Buildroot 长期分支 |
| GhostPDL 许可证 | 商业发布法律风险 | AGPL 合规评审或商业授权 |
| 在线 apt/pip 漂移 | 批次不一致 | 离线仓库、哈希、镜像冻结 |
| 单 UDC 模式切换失败 | MSC/Printer 均不可用 | 锁、回滚、100 次切换测试 |
| eMMC 填满/磨损 | 数据库损坏、服务异常 | 16GB、配额、清理、健康监控 |
| Web 服务 root 权限过大 | 安全风险 | root helper + 最小权限服务 |
| 自签名证书 | 浏览器警告和信任管理 | 工厂证书注入或医院 CA |
| 全量语言重写 | 长期回归和延期 | 先测量，再局部迁移 |

## 15. 最终选型表

| 产品阶段 | 系统 | 语言 | Web | 数据库 | Gadget | 部署 |
|---|---|---|---|---|---|---|
| 当前 RK3566 研发/试点 | Debian 12 | Python | aiohttp + 原生前端 | SQLite WAL | configfs + Bash | 当前脚本，尽快改 `.deb` |
| RK3506 样板 | 厂家 Debian/Buildroot | Python | aiohttp | SQLite WAL | configfs + Bash | 离线 wheel/镜像 |
| RK3506 量产首版 | Buildroot | Python | aiohttp | SQLite WAL | configfs + root helper | A/B 整机镜像 |
| 内存优化版 | Buildroot | Go 控制面 + 原生转换器 | `net/http` | SQLite WAL | configfs + helper | 单二进制 + A/B 镜像 |
| 多产品长期平台 | Yocto | Go/Rust 或 Python | 按产品选择 | SQLite | configfs helper | Layer/recipe + A/B OTA |

一句话结论：

> 当前项目继续使用 Python 是风险最低的正确选择；RK3506 量产首先从 Debian 切到 Buildroot，只有实测证明控制面内存或部署成为瓶颈时，再把 Python 控制面迁移到 Go。USB configfs、SQLite 和 GhostPDL 不需要因为换语言而重做。

## 16. 证据与参考资料

### 16.1 当前仓库

- [项目依赖与 Python 版本](../pyproject.toml)
- [系统架构](ARCHITECTURE.md)
- [RK3566 产品计划](PRODUCT_PLAN_RK3566.md)
- [RK3506 与 T113 对比](RK3506_VS_T113_REPORT_GATEWAY.md)
- [安装脚本](../scripts/install.sh)
- [MSC Gadget 脚本](../scripts/setup_msc_gadget.sh)
- [Printer Gadget 脚本](../scripts/setup_hp_printer_gadget.sh)
- [systemd 服务](../systemd/)
- [Python 业务源码](../src/gadget_msc_printer/)
- [回归测试](../tests/)

### 16.2 官方资料

- Linux Kernel，USB gadget configured through configfs：<https://docs.kernel.org/usb/gadget_configfs.html>
- Debian 12 Bookworm 生命周期：<https://www.debian.org/releases/bookworm/>
- Buildroot User Manual：<https://buildroot.org/downloads/manual/manual.html>
- Yocto Project Documentation：<https://docs.yoctoproject.org/>
- Python `venv`：<https://docs.python.org/3.11/library/venv.html>
- Go 支持的 GOOS/GOARCH：<https://go.dev/doc/install/source>
- Rust Cargo cross target：<https://doc.rust-lang.org/cargo/commands/cargo-build.html>
- SQLite 适用场景：<https://www.sqlite.org/whentouse.html>
- SWUpdate：<https://sbabic.github.io/swupdate/swupdate.html>
- Artifex Licensing：<https://artifex.com/licensing>
