# T113 MSC / Printer 报告网关设计规格与成本预估

版本：Draft 0.2  
日期：2026-07-16  
基线项目：RK3566 MSC / Printer 报告网关

## 1. 设计目标

本产品用于替代当前 RK3566 报告网关，在更低成本的平台上保留以下能力：

- 通过一个 USB Device 口互斥模拟 USB Mass Storage 或 USB Printer。
- 从 FAT32 虚拟 U 盘提取新增报告。
- 从 `/dev/g_printer0` 接收 PDF、PostScript、PCL/PCL XL 或图片打印流。
- 将可支持的输入统一转换为 PDF。
- 通过有线网络或 WiFi 自动上传 PDF 和 `ReportInfo.xml`。
- 提供 HTTPS 8443 本地管理页面、登录、CSRF 防护、任务查询和失败重试。
- 使用 SQLite 保存上传状态，支持断网重试、重启恢复、内容去重和自动清理。
- 无风扇连续运行，满足医院室内设备长期通电要求。

基础型号必须同时提供 10/100M Ethernet 和双频 WiFi，Ethernet 作为优先链路，WiFi 作为移动部署和断线回退链路。LCD、触摸屏、4G、HDMI 和音频不作为基础型号的必选功能。

## 2. 选型结论

### 2.1 推荐型号

推荐使用 **T113-i + 512MB DDR3 + 8GB eMMC**。

原因：

- T113 系列具备双核 Cortex-A7、USB OTG、USB Host 和 EMAC，接口满足网关需求。
- T113-i 可以外接 DDR2/DDR3，规避 T113-S3 内存容量过小的问题。
- 8GB eMMC 可以容纳系统、512MB MSC 镜像、转换工具、SQLite、日志和临时报告。
- 512MB 是移植现有 Python 服务和单任务 GhostPCL 转换的最低建议容量。

### 2.2 稳妥量产型号

建议首批现场产品使用 **T113-i + 1GB DDR3 + 8GB eMMC**。

1GB 版本主要降低以下风险：

- PCL/PCL XL 或 PostScript 大页面转换时发生 OOM。
- HTTPS、上传线程、SQLite、文件监控和转换程序同时运行时内存不足。
- 后续增加远程升级、诊断打包或更多格式转换后需要重新改板。

### 2.3 不建议直接采用 T113-S3 128MB

T113-S3 的集成内存版本适合轻量 HMI 或单一控制程序，但不适合原样运行当前软件栈。128MB 下同时运行 Python、aiohttp、SQLite、Pillow、Ghostscript/GhostPCL 和 systemd 服务，风险很高。

只有满足以下条件时才考虑 T113-S3：

- 后端改写为 C/C++ 或 Go。
- 根文件系统改为精简 Buildroot/Tina Linux。
- 不在设备本地转换复杂 PCL，或者把转换放到服务器端。
- MSC 镜像和报告缓存容量明显缩小。

因此 T113-S3 属于第二阶段极限降本路线，不作为第一版硬件基线。

### 2.4 与 RK3506 的平台选择更新

若项目尚未冻结 SoC，完整功能版优先评估 **RK3506B/J + 512MB 内存 + 8GB eMMC**。RK3506 的三核 Cortex-A7、两个 USB 2.0 OTG 控制器以及与现有 Rockchip 软件经验的连续性，更适合同时运行 Python 服务、GhostPCL、USB Gadget 和网络上传。T113-i 保留为成本优先备选。

详细比较、WiFi 方案和双平台成本见 [RK3506 与 T113 报告网关选型对比](RK3506_VS_T113_REPORT_GATEWAY.md)。

## 3. 总体架构

```text
                  医疗设备 / Windows 主机
                            |
                    USB 2.0 Device
                            |
                 ESD + VBUS检测 + 防倒灌
                            |
                     T113-i USB0 DRD
                            |
       +--------------------+--------------------+
       |                    |                    |
  512MB/1GB DDR3       8GB eMMC        100M Ethernet + 双频 WiFi
       |                    |                    |
  Python/转换程序      系统与报告缓存       医院报告接口
       |
       +-- MSC configfs function
       +-- Printer configfs function
       +-- HTTPS 管理页面
       +-- SQLite 上传队列

基础：USB Host/SDIO WiFi、RJ45；可选：MicroSD 恢复卡、UART 调试、外部 RTC
```

## 4. 硬件规格

### 4.1 主处理器

| 项目 | 规格 |
|---|---|
| SoC | Allwinner T113-i |
| CPU | 双核 Arm Cortex-A7，最高约 1.2GHz，以实际料号和 BSP 为准 |
| 封装 | LFBGA337，13mm x 13mm，0.65mm pitch |
| 工作温度 | 工业级目标 -40℃～85℃；整机首版验证按 0℃～50℃ |
| 看门狗 | 使用片内 watchdog，服务卡死时自动复位 |

### 4.2 内存与存储

| 项目 | 最低配置 | 推荐配置 |
|---|---:|---:|
| DDR3/DDR3L | 512MB | 1GB |
| eMMC | 8GB | 8GB 或 16GB |
| MicroSD | 预留，不必标配 | 用于恢复和工厂烧录 |
| MSC 镜像 | 512MB FAT32 | 可配置 256MB～1GB |

建议分区：

```text
boot / boot-resource       64～128MB
rootfs A                  1.0～1.5GB
rootfs B                  1.0～1.5GB（量产升级可选）
data                      剩余空间，ext4
```

如果暂不做 A/B 升级，可保留单 rootfs，把更多空间留给报告缓存。

### 4.3 网络

- 使用 T113-i EMAC 的 RMII 模式。
- 外接 10/100M Ethernet PHY 和带网络变压器 RJ45。
- 100M 带宽足够上传 PDF，成本和布线风险低于千兆 RGMII。
- RJ45 侧增加 TVS/ESD；屏蔽壳与机壳地按 EMC 方案连接。
- 默认 DHCP，预留静态 IP 配置。
- 标配双频 WiFi 5（802.11ac）1T1R 模组和外置 IPEX/MHF4 天线。
- WiFi 优先采用有正式 Linux 驱动、固件和长期供货承诺的模组，不使用无型号白牌 USB 网卡。
- 网络优先级为 Ethernet > WiFi；网线断开时自动切换 WiFi，网线恢复后自动回到 Ethernet。
- 2.4GHz 单频方案只作为极限降本选项，不作为医院现场基础配置。

### 4.4 USB Device 接口

基础型号提供一个专用 USB 2.0 Device 接口，建议使用 USB-C 母座或 USB-B 母座。

设计要求：

- 连接 T113-i USB0 DRD/OTG 控制器。
- D+/D- 按 90Ω 差分阻抗布线，等长并远离 DDR、DC/DC 电感和时钟。
- 接口处放置低电容 USB2.0 ESD 管。
- 产品由独立 5V 输入供电，USB VBUS 只用于存在检测，不给主板反向供电。
- 禁止把主板 5V 直接接到被控设备 VBUS，避免 VBUS 倒灌。
- 若使用 Type-C Device 口，CC1/CC2 按 UFP/Sink 规范配置 Rd。
- 预留 0Ω、电流限制或 load switch 位置，便于 EVT 阶段修正供电策略。

USB 功能：

```text
MSC 模式      -> configfs mass_storage function
Printer 模式  -> configfs printer function -> /dev/g_printer0
```

同一时刻只绑定一种功能，保持与当前项目一致。

### 4.5 USB Host 接口

建议预留一个 USB Host 控制器。若 WiFi 使用 USB 模组，基础功能依赖该 Host，调试 USB-A 口应通过独立 Hub 端口引出。

用途：

- 维护 U 盘。
- USB 转串口或现场诊断。
- 连接双频 WiFi 模组、扫码枪或维护设备。

Host 5V 必须经过限流负载开关，建议持续 500mA，并具备短路和过流保护。

### 4.6 电源

| 项目 | 规格 |
|---|---|
| 输入 | 5V DC，建议 2A |
| 接口 | 独立 USB-C Power 或 5.5/2.1mm DC；不能与 Gadget 数据口混用供电路径 |
| 保护 | 反接、过压、输入保险丝/自恢复保险丝、TVS |
| 主要电源轨 | 3.3V、1.8V、DDR 电源、CPU/SYS 内核电源；严格遵守 T113-i 上下电时序 |
| 典型功耗目标 | 2.5～4.5W，包含 WiFi 在线待机和正常上传 |
| 峰值预算 | 6～8W，包含 WiFi 发射和 USB Host 负载时按 10W 电源适配器设计 |

生产版建议使用工业级 PMIC 或已由核心板厂家验证的电源方案，不建议在第一版自行简化电源时序。

### 4.7 调试、状态和恢复

- UART0 三针或四针调试座：3.3V TTL、TX、RX、GND。
- Reset 按键。
- FEL/Recovery 按键或测试点。
- 状态灯：Power、Network、USB Mode、Upload/Error。
- 预留硬件 watchdog 测试点。
- 可选外部 RTC；有稳定医院网络时优先使用 NTP。
- 预留 eMMC 烧录和量产测试点。

### 4.8 PCB 与结构

直接使用 T113-i + 外部 DDR 时建议：

- 6 层 PCB，推荐叠层：Signal / GND / Signal / Power / GND / Signal。
- DDR3 必须按参考设计做拓扑、阻抗、等长和时序检查。
- T113-i 为 BGA，SMT 后需要 X-Ray 抽检。
- 目标主板尺寸约 85mm x 60mm；最终根据 RJ45、USB 和外壳开口调整。
- 整机外壳目标约 105mm x 75mm x 28mm。
- 铝散热片或 SoC 导热垫连接外壳，默认不使用风扇。
- RJ45、Gadget USB、电源口布置在同一侧或相邻两侧，避免现场接线交叉。

第一轮样机建议使用成熟 T113-i 核心板加自研载板。直接 BGA 改板应在软件链路和 USB Printer 已验证后再进行。

## 5. 软件规格

### 5.1 系统

- 优先使用全志 Tina Linux/Buildroot BSP，保留 systemd 或提供等价服务管理机制。
- 如果沿用现有 Python 实现，需要构建 Python 3、aiohttp、PyYAML、Pillow、SQLite、Ghostscript 和 GhostPCL。
- 集成 `wpa_supplicant` 或等价无线管理组件，支持 WPA2-PSK/WPA3-SAE、自动重连、信号强度读取和 Ethernet 优先路由。
- WiFi SSID 和密码存入仅 root 可读配置，不写入日志、前端 HTML 或出厂镜像。
- 根文件系统应关闭不需要的桌面、音频、视频和图形服务。
- 系统日志限制大小并按天清理，防止 eMMC 写放大。
- 文件系统异常后应能自动 fsck 或进入只读恢复模式。

### 5.2 内核必须验证的能力

```text
CONFIG_USB_GADGET
CONFIG_USB_LIBCOMPOSITE
CONFIG_USB_CONFIGFS
CONFIG_USB_CONFIGFS_MASS_STORAGE
CONFIG_USB_CONFIGFS_F_PRINTER
CONFIG_USB_PRINTER
CONFIG_CONFIGFS_FS
CONFIG_BLK_DEV_LOOP
CONFIG_VFAT_FS
CONFIG_FAT_FS
CONFIG_EXT4_FS
CONFIG_CFG80211
CONFIG_MAC80211
CONFIG_RFKILL
```

同时必须启用 T113 USB0 DRD/UDC 驱动。具体 Kconfig 名称以采用的全志 BSP 为准。

在硬件原理图冻结前，必须在 T113 开发板上完成以下验证：

1. `/sys/class/udc` 能看到 UDC。
2. configfs MSC 能在 Windows 和目标医疗设备上枚举并写文件。
3. configfs Printer 能生成 `/dev/g_printer0`。
4. Printer 能连续接收完整 PCL/PDF 流。
5. MSC 与 Printer 切换 100 次不残留 UDC 占用。
6. WiFi 上传与 USB Gadget 并行工作，不发生 USB 控制器重置、掉盘或打印中断。
7. 拔插网线时 Ethernet/WiFi 自动切换，待上传任务不丢失且不重复提交。

### 5.3 应用迁移策略

第一阶段保持当前 Python 架构，降低功能回归风险：

```text
gadget-mode      USB 模式构建和切换
gadget-collector MSC/Printer 报告采集和 PDF 转换
gadget-web       HTTPS 配置、上传、SQLite 和自动清理
```

需要修改：

- 将 UDC 名称、USB 描述符和产品名称改成配置项，不再写死 RK3566。
- 替换安装脚本中的 Debian 包管理逻辑。
- 交叉编译 GhostPDL，并测量 Cortex-A7 上的速度和峰值内存。
- 对 eMMC、FAT 镜像和 configfs 路径做 T113 BSP 适配。

第二阶段若需要降到 T113-S3，则把常驻后端改为 Go/C，并重新设计打印格式转换路径。

## 6. 性能与可靠性指标

| 项目 | 目标 |
|---|---|
| 冷启动到网关服务可用 | ≤ 25s |
| HTTPS 页面可访问 | 启动后 ≤ 30s |
| MSC/Printer 模式切换 | ≤ 10s |
| 典型 PDF 入队 | 文件稳定后 ≤ 5s |
| 典型 PDF 上传 | 由医院网络决定，程序无额外 2s 以上固定延迟 |
| PCL 转换 | 以现场样本实测，10 页样本不得 OOM |
| 断电恢复 | SQLite 队列和配置不损坏 |
| 模式切换寿命测试 | 连续 100 次无 UDC 残留 |
| 连续运行 | 7 x 24 小时无服务退出、内存持续增长或 eMMC 爆满 |
| 上电循环 | 100 次自动恢复业务 |
| WiFi 恢复 | AP 重启或信号中断后 60s 内自动重连 |
| 有线/无线切换 | 业务队列不丢失，恢复网络后自动续传 |

## 7. 安全与合规边界

- Web 端只开放 HTTPS 8443，不开放未认证配置接口。
- 保留首次密码修改、PBKDF2 哈希、Secure/HttpOnly Cookie、CSRF 和登录限速。
- 固件升级包需要签名校验，量产版关闭默认调试账户。
- UART 调试口在外壳内，正式交付时不对外暴露。
- 医院网络要求可加入固定服务器白名单和出站端口限制。
- WiFi 配置必须支持 WPA2-PSK，推荐支持 WPA3-SAE；禁止出厂固化医院 SSID、密码或开放调试热点。
- 若产品被纳入医疗器械电气安全边界，需要由合规工程师确认 USB 隔离、漏电流、电源适配器和 IEC 60601 相关要求。
- 医疗级 USB 隔离和医疗级电源不包含在基础 BOM 中；如要求，预计增加 100～250 元/台，并需要重新做信号兼容验证。
- GhostPDL 为 AGPL/商业双许可，封闭式商业产品应确认 Artifex 授权，许可费用不包含在本成本表中。

## 8. 成本预估

### 8.1 估算口径

- 币种：人民币。
- 日期：2026-07-16。
- 未含税、运费、渠道加价、GhostPDL 商业许可、认证和售后备件。
- 百台价格按国内小批量 PCBA 估算；千台价格按稳定供应链和一次性下单估算。
- T113-i、DDR 和 eMMC 必须在立项后向两家以上供应商重新询价。

参考样品价格：MYIR 公布的 T113-i 512MB DDR3 + 8GB eMMC 核心板样品价为 27.80 美元，1GB + 8GB 为 35.80 美元。该价格只能作为样机路线参考，不代表量产报价。

### 8.2 直接 SoC 自研板 BOM

推荐配置：T113-i + 512MB DDR3 + 8GB eMMC + 100M Ethernet + 双频 WiFi。

| 项目 | 100 台单价 | 1000 台单价 | 说明 |
|---|---:|---:|---|
| T113-i | 38～55 | 30～45 | 以正式代理报价为准 |
| 512MB DDR3/DDR3L | 14～22 | 10～16 | 1GB 版本另加约 15～35 |
| 8GB eMMC | 22～32 | 17～25 | 工规或高耐久料价格更高 |
| PMIC、DC/DC、LDO 与保护 | 15～25 | 10～18 | 含输入保护，不含适配器 |
| Ethernet PHY、晶振、RJ45 | 16～26 | 12～20 | 100M RMII |
| USB 连接器、ESD、限流开关 | 12～20 | 8～14 | 一个 Device，一个可选 Host |
| 双频 WiFi 模组、天线及射频辅料 | 31～52 | 20～37 | WiFi 5 1T1R，含 IPEX 天线 |
| WiFi 供电、ESD、Hub/外围及测试增量 | 13～28 | 8～18 | 无需 Hub 时可减少约 5～10 元 |
| 时钟、RTC、按键、LED、阻容 | 16～26 | 10～18 | 含调试和测试点器件 |
| 6 层 PCB | 30～45 | 12～20 | 约 85mm x 60mm |
| SMT、BGA、X-Ray 和 PCBA 测试 | 35～55 | 18～30 | 与工厂良率和测试覆盖相关 |
| **PCBA 小计** | **242～386** | **155～261** | 目标值约 295 / 200 |
| 塑胶外壳 | 25～45 | 10～20 | 千台价不含模具摊销 |
| 5V/2A 电源和 USB 线 | 20～30 | 15～22 | 普通安规电源 |
| 整机装配、老化、包装 | 24～40 | 13～24 | 含基础功能测试 |
| **整机硬件成本** | **311～501** | **193～327** | 建议目标 375 / 250 |

建议项目预算按以下目标控制：

- 100 台试产：**约 375 元/台**，合理区间 310～500 元。
- 1000 台量产：**约 250 元/台**，合理区间 195～325 元。
- 1GB DDR 版本：在上述基础上增加约 15～35 元/台。
- 16GB eMMC：增加约 8～20 元/台。

### 8.3 核心板 + 载板路线

适合 1～100 台样机和现场试用。

| 项目 | 预计成本/台 |
|---|---:|
| T113-i 512MB + 8GB 核心板 | 约 200～240 |
| 自研载板 PCBA | 70～120 |
| 双频 WiFi 模组、天线与测试 | 44～80 |
| 外壳、电源、线材 | 55～90 |
| 装配与测试 | 20～35 |
| **整机合计** | **389～565** |

核心板路线单价更高，但能减少 DDR、BGA、电源时序和 BSP 风险，首轮样机优先采用。

### 8.4 T113-S3 极限降本路线

若完成 Go/C 重写并取消复杂本地 PCL 转换，1000 台量级的目标整机成本可尝试压到 **110～170 元/台**。

该数字必须在软件重构和内存压力测试后重新核算。不能把它当作当前功能完整迁移的承诺成本。

### 8.5 一次性开发费用

| 项目 | 预计费用 |
|---|---:|
| T113-i 核心板载板、结构和样机 | 2～5 万 |
| 直接 T113-i BGA 主板硬件、DDR/电源审查和 2～3 轮打样 | 8～18 万 |
| BSP、USB Gadget、应用和 GhostPCL 迁移验证 | 6～15 万 |
| WiFi 驱动、射频、漫游与共存验证 | 1～4 万 |
| 注塑模具 | 3～8 万 |
| EMC、安规和兼容性测试 | 2～8 万 |
| **完整自研量产路线合计** | **20～53 万** |

以上是外包或折算人力后的工程估算。内部已有软件和硬件团队时，实际现金支出可以明显降低。

## 9. 开发阶段

### 阶段 A：T113 开发板可行性验证

1. 选择 T113-i 512MB/1GB + 8GB 开发板。
2. 编译并验证 configfs MSC 和 Printer。
3. 验证 `/dev/g_printer0`、FAT 镜像解绑挂载和 UDC 重建。
4. 移植当前 Python 项目。
5. 使用真实医疗设备测试 MSC、Printer、上传和 XML。
6. 记录空闲内存、转换峰值、CPU、温度和单页/多页耗时。

阶段 A 通过前，不冻结自研板原理图。

### 阶段 B：核心板载板 EVT

- 完成接口、电源、防倒灌、ESD 和结构验证。
- 连续运行 7 天。
- 做 100 次模式切换和 100 次上电循环。
- 在至少两台 Windows 和一台目标医疗设备上验证 USB 枚举。

### 阶段 C：直接 SoC DVT

- 迁移到 6 层 T113-i 自研板。
- 做 DDR 压力、eMMC、网络、USB Eye/兼容性、ESD 和温升测试。
- 完成工装、烧录、序列号和老化流程。

### 阶段 D：PVT/量产

- 小批 50～100 台。
- 跟踪 PCBA 良率、BGA 空洞、DDR 错误、USB 枚举失败和上传失败率。
- 根据实际采购报价更新 BOM 和销售成本。

## 10. 决策建议

1. **现在不要直接画 T113-S3 128MB 板。** 先用 T113-i 512MB 或 1GB 开发板验证完整软件。
2. **第一批现场机使用核心板 + 载板。** 单价多约 100～150 元，但能显著降低首版失败风险。
3. **现场流程稳定后再做 T113-i 直接 SoC 板。** 1000 台目标整机成本约 210 元。
4. **只有在服务器端可接管 PCL 转换时，才启动 T113-S3 极限降本。**
5. 原理图冻结前，把 USB Printer configfs、VBUS 防倒灌和真实医疗设备枚举列为三个一票否决项。
6. WiFi 作为基础配置，但不能取代 RJ45；原理图冻结前必须完成 WiFi 与 USB Gadget 并行压力测试。

## 11. 参考资料

- Allwinner T113 官方产品页：<https://www.allwinnertech.com/index.php?a=index&c=product&id=106&solveid=43>
- Allwinner T113-i Datasheet V1.4：<https://bbs.aw-ol.com/assets/uploads/files/1678720117073-eb74fed1-28d3-4451-b1e6-c9be3af193af-t113-i_datasheet_v1.4.pdf>
- MYIR T113-i 核心板与样品价格：<https://en.myir.cn/T113/76.html>
- 飞凌 T113-i 开发板参考：<https://buy.forlinx.com/h-pd-148.html>
- Rockchip RK3506 官方产品页：<https://www.rock-chips.com/a/en/products/RK35_Series/2025/1208/2126.html>
- MYIR RK3506 核心板：<https://www.myir.cn/product/som/rk3506/myc-yr3506.html>
