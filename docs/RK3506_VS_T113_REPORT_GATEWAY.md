# RK3506 与 T113 报告网关选型对比

版本：Draft 0.1  
日期：2026-07-16  
目标产品：USB MSC / USB Printer 报告采集上传网关

## 1. 结论

在保留当前完整软件功能的前提下，推荐顺序如下：

1. **首选：RK3506B/J + 512MB LPDDR3L + 8GB eMMC + 100M Ethernet + 双频 WiFi。**
2. **成本备选：T113-i + 512MB DDR3 + 8GB eMMC + 100M Ethernet + 双频 WiFi。**
3. 大页 PCL/PCL XL、PostScript 较多时，两种平台都优先升级到 1GB 内存。
4. 不采用 RK3506G2 128MB 或 T113-S3 128MB 直接承载当前 Python、SQLite、Pillow 和 GhostPCL 软件栈。

RK3506 的优势不是单纯多一个 CPU 核，而是三核 Cortex-A7、两个 USB 2.0 OTG 控制器，以及与现有 RK3566 项目的 Rockchip BSP/configfs 经验更接近。它能降低 USB Gadget、Python 服务和打印转换并行时的调度压力，也能减少软件迁移的不确定性。

T113-i 的主要优势是成熟低成本核心板较多、直接 SoC BOM 潜力较好。若 T113 开发板能先通过 Printer configfs、真实医疗设备枚举和 GhostPCL 压力测试，仍可作为成本优先路线。

## 2. 业务负载

平台必须同时支持：

- 一个 USB Device 口在 MSC 与 Printer 两种 configfs function 之间切换。
- MSC FAT32 镜像文件提取和稳定性判断。
- `/dev/g_printer0` 接收打印流。
- PDF、PostScript、PCL/PCL XL 和图片识别、转换与归档。
- Python 3、aiohttp、SQLite、Pillow、Ghostscript/GhostPCL 常驻或按任务运行。
- HTTPS 8443 管理页面、任务日志、失败重试、自动清理。
- Ethernet 与 WiFi 自动切换，断网期间任务持久化。
- 无风扇 7 x 24 小时运行。

这类负载对内存、USB UDC 驱动和 BSP 稳定性的要求，高于普通采集盒或轻量 HMI。

## 3. 核心规格对比

| 项目 | Rockchip RK3506B/J | Allwinner T113-i | 对本项目的影响 |
|---|---|---|---|
| CPU | 3 x Cortex-A7；B 最高约 1.5GHz，J 最高约 1.2GHz；另有 Cortex-M0 | 2 x Cortex-A7，最高约 1.2GHz | RK3506 更适合转换、Web、上传并行；实际差异须用 PCL 样本验证 |
| 推荐内存 | 512MB LPDDR3L，1GB 更稳 | 512MB DDR3，1GB 更稳 | 两者最低都按 512MB，不使用 128MB 版本承载完整功能 |
| 存储 | 8GB eMMC，建议保留恢复分区 | 8GB eMMC，建议保留恢复分区 | 基本等价 |
| USB | 2 x USB 2.0 OTG | 1 x USB 2.0 DRD + 1 x USB 2.0 Host | RK3506 更容易把 Gadget 与 WiFi/维护 Host 分开 |
| Ethernet | 2 x RMII 10/100M | EMAC，可按设计选择 100M/1000M | 本项目 100M 已足够；RK3506 双网口不是刚需 |
| WiFi | 无片内 WiFi，需外接 | 无片内 WiFi，需外接 | 两者都要增加模组、天线、驱动和认证验证 |
| 系统路线 | Linux 6.1、Buildroot/Ubuntu 厂商方案较常见 | Tina Linux/Buildroot 厂商方案较常见 | 现有 RK3566 经验使 RK3506 迁移成本更低 |
| PCB/量产 | 可选成熟核心板；直接 SoC 方案需按厂商参考设计 | 可选成熟核心板；T113-i 为 LFBGA337 | 首版均建议核心板 + 载板验证 |
| 显示/多媒体 | 非本项目重点 | 显示接口资源更丰富 | 对无屏报告网关没有决定性价值 |
| 供货与温度 | B/J 及工业核心板需按供应商确认 | T113-i 工业路线成熟 | 必须取得量产料号、温度、生命周期书面承诺 |

注：芯片参数只用于初选，不能代替 BSP 实机验证。两家官方资料都不能证明目标医疗设备一定能枚举 USB Printer，Printer configfs 必须作为立项门槛实测。

## 4. 加权评估

按本项目权重做工程评分，10 分为满分：

| 维度 | 权重 | RK3506B/J | T113-i | 说明 |
|---|---:|---:|---:|---|
| USB Gadget/Host 架构 | 25% | 9.0 | 8.0 | RK3506 两路 OTG 的资源安排更灵活 |
| 现有软件迁移 | 25% | 9.0 | 6.5 | 当前项目已有 Rockchip Debian/configfs 经验 |
| CPU 与 GhostPCL 余量 | 15% | 8.5 | 7.0 | RK3506 多一个 A7 核；仍需实测峰值内存 |
| 硬件成本 | 15% | 7.5 | 9.0 | T113 直接 SoC 路线有更强成本潜力 |
| WiFi 实现 | 10% | 8.0 | 8.0 | 都依赖外部模组，差异取决于板级资源 |
| 供货/BSP 生命周期 | 10% | 8.0 | 8.0 | 以最终模块厂书面承诺为准 |
| **加权总分** | **100%** | **85.0** | **76.3** | RK3506 更适合完整功能首版 |

该评分用于方案排序，不是器件认证结果。若 T113 的 Printer configfs 和 PCL 性能已提前验证通过，其软件迁移分可以上调。

## 5. WiFi 基础规格

### 5.1 功能要求

- 标配 WiFi 5 双频 2.4GHz/5GHz、1T1R。
- 至少支持 WPA2-PSK，推荐支持 WPA3-SAE。
- 使用 IPEX/MHF4 外置天线；金属外壳时天线安装在塑胶透波区。
- Ethernet 为第一优先级，WiFi 为第二优先级；切换期间上传队列不得丢失。
- 支持 DHCP、静态 IP、自动重连、信号强度显示和网络连通性检测。
- WiFi 密码仅保存在 root 可读配置中，Web 页面回显时必须脱敏。
- 工厂和医院部署都不得长期开放无密码 AP。

医院现场 2.4GHz 往往较拥挤，因此双频不是为了提高 PDF 上传峰值速度，而是提高可用信道数量和连接稳定性。

### 5.2 RK3506 推荐连接方式

推荐使用 **USB 2.0 双频 WiFi 模组**，接 RK3506 的第二路 USB OTG/Host：

```text
USB OTG0 -> USB Gadget -> 医疗设备/Windows 主机
USB OTG1 -> Host/Hub -> 双频 WiFi 模组 + 可选维护 USB-A
```

原因：

- Gadget 与 WiFi 不共用同一 UDC，WiFi 重连不应触发 MSC/Printer 重新枚举。
- 很多 RK3506 核心板会把 SDMMC 资源用于 eMMC，不能先假设还有空闲 SDIO。
- USB WiFi 驱动和固件更容易在开发板阶段替换、抓日志和做兼容性比较。

若自研直接 SoC 板确认有独立空闲 SDIO，并拿到有长期驱动支持的 SDIO WiFi 模组，也可以改用 SDIO。原理图冻结前必须检查 pinmux、电压、时钟、上电时序和中断脚。

### 5.3 T113-i 推荐连接方式

- SDIO 空闲时优先使用 SDIO WiFi，减少 USB Host 占用。
- SDIO 被 eMMC、MicroSD 或其他外设占用时，使用独立 USB Host WiFi。
- 无论采用哪种方式，都保留 USB Gadget 专用 DRD 控制器，不让 WiFi 与 Gadget 在同一控制器角色之间切换。

### 5.4 硬件细节

- WiFi 3.3V 电源按模组峰值电流留至少 30% 余量，并加独立去耦和可控电源使能。
- 天线馈线远离 DDR、DC/DC 电感、USB 差分线和金属屏蔽罩边缘。
- PCB 预留天线净空，外置天线连接器附近禁止铺铜，以模组厂参考设计为准。
- USB WiFi 路径增加低电容 ESD；内置模组不必放可插拔 USB 连接器。
- 量产镜像固定驱动、固件和模组料号，禁止同一 SKU 随机混用不同芯片网卡。

## 6. 推荐硬件基线

### 6.1 首选 RK3506 版本

| 项目 | 基线 |
|---|---|
| SoC | RK3506J 或 RK3506B |
| 内存 | 512MB LPDDR3L；大 PCL 场景 1GB |
| 存储 | 8GB eMMC；高缓存需求 16GB |
| Gadget | 独立 USB 2.0 OTG，MSC/Printer 互斥切换 |
| 网络 | 100M Ethernet + 双频 WiFi 5 |
| WiFi | USB 2.0 模组，IPEX/MHF4 外置天线 |
| 电源 | 5V/2A，WiFi 峰值和 USB Host 同时负载不得掉压 |
| 系统 | 首版沿用 Python 架构；量产评估 Buildroot 或精简 Debian |

RK3506J 更偏工业温度和稳定供货路线；RK3506B 性能更高。最终选择应以核心板温度等级、生命周期、价格和 BSP 支持协议为准，而不是只按主频决定。

### 6.2 T113 备选版本

| 项目 | 基线 |
|---|---|
| SoC | T113-i，不采用 T113-S3 128MB 完整功能版 |
| 内存 | 512MB DDR3；大 PCL 场景 1GB |
| 存储 | 8GB eMMC |
| Gadget | USB0 DRD 专用 |
| 网络 | 100M Ethernet + 双频 WiFi 5 |
| WiFi | SDIO 优先，资源冲突时使用 USB Host 模组 |
| 系统 | Tina Linux/Buildroot，第一阶段保留 Python 应用 |

## 7. 成本预估

以下为 2026-07-16 工程估算，未含税、运费、认证、模具、GhostPDL 商业授权和售后备件，不等于供应商正式报价。

### 7.1 WiFi 增量

| WiFi 项目 | 100 台 | 1000 台 |
|---|---:|---:|
| 双频模组 | 25～40 元 | 18～30 元 |
| 天线、同轴线、连接器 | 6～12 元 | 4～8 元 |
| Hub/供电/ESD/阻容 | 8～18 元 | 4～10 元 |
| 装配与射频功能测试 | 5～10 元 | 2～7 元 |
| **合计增量** | **44～80 元** | **28～55 元** |

不需要 USB Hub 时，每台可减少约 5～10 元，但不能因此取消维护和量产测试接口。

### 7.2 双平台整机目标

| 平台 | 100 台试产 | 1000 台量产 | 建议控制目标 |
|---|---:|---:|---:|
| RK3506B/J + 512MB + 8GB + Ethernet + WiFi | 330～480 元 | 205～310 元 | 390 / 255 元 |
| T113-i + 512MB + 8GB + Ethernet + WiFi | 310～500 元 | 195～325 元 | 375 / 250 元 |

两者硬件成本差距不足以单独决定平台。只要 RK3506 能减少一次 BSP/USB Gadget 返工，项目总成本就可能低于器件 BOM 更便宜的 T113。

## 8. 一票否决验证

在选定核心板或冻结原理图前，两种平台必须完成相同测试：

1. `/sys/class/udc` 稳定出现目标 UDC。
2. configfs Printer 生成 `/dev/g_printer0`，目标医疗设备能枚举并连续打印。
3. configfs MSC 能被目标设备写入，拔插和模式切换后无文件系统损坏。
4. MSC/Printer 连续切换 100 次，不残留 UDC 占用。
5. WiFi 连续上传时切换 USB 模式，不掉网、不重置 Gadget。
6. 网线拔插、AP 重启和弱信号恢复时，SQLite 上传队列不丢失。
7. 512MB 版本转换 10 页现场 PCL/PCL XL 样本，无 OOM、无 watchdog 复位。
8. 连续运行 7 天，日志、缓存和临时文件不会填满 eMMC。
9. 100 次断电上电后自动恢复到正确 USB 模式和网络状态。
10. WiFi 天线装入最终外壳后测试 RSSI、吞吐、重连和 EMC。

任一平台未通过第 2、3、5 或 7 项，不进入自研主板阶段。

## 9. 开发建议

1. 先购入 RK3506 512MB/8GB 和 T113-i 512MB/8GB 开发板各一套。
2. 使用同一批 PCL/PDF 样本和同一台医疗设备做 A/B 测试。
3. 记录冷启动、空闲内存、PCL 耗时、峰值 RSS、CPU、温度、WiFi RSSI 和 USB 失败次数。
4. 首轮推荐 RK3506 核心板 + 载板，确认软件和射频后再评估直接 SoC 降本。
5. 只有当 T113-i 的总成本优势达到约 30 元/台，且全部一票否决测试通过时，才值得为它承担单独 BSP 迁移成本。

## 10. 参考资料

- Rockchip RK3506 官方产品页：<https://www.rock-chips.com/a/en/products/RK35_Series/2025/1208/2126.html>
- Rockchip RK3506G2 Datasheet：<https://opensource.rock-chips.com/images/5/51/Rockchip_RK3506G2_Datasheet_V1.3-20250811.pdf>
- MYIR RK3506 核心板：<https://www.myir.cn/product/som/rk3506/myc-yr3506.html>
- Tronlong RK3506 核心板：<https://www.tronlong.com/productinfo171.html>
- Tronlong RK3506 开发板：<https://www.tronlong.com/productinfo170.html>
- Allwinner T113 官方产品页：<https://www.allwinnertech.com/index.php?a=index&c=product&id=106&solveid=43>
- Allwinner T113-i Datasheet V1.4：<https://bbs.aw-ol.com/assets/uploads/files/1678720117073-eb74fed1-28d3-4451-b1e6-c9be3af193af-t113-i_datasheet_v1.4.pdf>
- MYIR T113-i 核心板与样品价格：<https://en.myir.cn/T113/76.html>
