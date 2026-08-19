# H618 报告网关 v0.22.6

## 打印流兼容

- 识别 HP `AGIACLDOWNLOAD` 固件和初始化流，避免将其误当作患者报告生成 PDF。
- 支持识别和转换 ZjStream 页面流，使用 `zjsdecode` 解码后生成 PDF。
- 打印流分析页面显示 ACL/ZjStream 协议、结束依据、接收耗时和转换结果。
- 保留 v0.22.5 的协议边界优先、空闲超时兜底和异步转换机制。

## 实体打印驱动

- 新增 Ubuntu Noble ARM64 打印机型号目录，可搜索厂商和型号并推荐已安装驱动。
- 驱动安装限定为后端白名单软件包，通过后台 APT 任务安装并刷新 CUPS 型号。
- 实体打印机配置支持型号选择、安装计划、测试页和人工实机验证。
- 支持签名 `.jvdrv` 离线驱动库的分析和导入，并保留 DEB、PPD 及 ARM64 Filter 现场导入。
- 本版本只交付离线驱动框架和验签公钥，不附带完整 Noble ARM64 离线驱动库。

## 部署说明

- 目标平台：`linux-arm64`，系统基线为 Ubuntu Noble 24.04 / Armbian ARM64。
- 新增 ZjStream 转换依赖 `printer-driver-foo2zjs` 提供的 `zjsdecode`。
- 不覆盖 `/etc/gadget-msc-printer` 和 `/var/lib/gadget-msc-printer`。
- 不清理或重新提交现有 CUPS 任务，不重新处理已有 PRN。
- GhostPDL 10.07.1 仍仅限当前 K2B 测试板内部测试，量产分发前需重新评审许可。
