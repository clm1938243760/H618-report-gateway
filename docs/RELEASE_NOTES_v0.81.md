# H618 报告网关 v0.81（研发版）

`v0.81`汇总`v0.22.4`之后的打印流识别、离线转换、智能结束判定和实体打印驱动能力，
应用内部版本为`0.81.0`。该版本继续用于K2B研发验证，不改变GhostPDL和EscaPy仅限
当前测试板内部使用的授权范围。

## PRN离线转换矩阵

- A01-A14覆盖PDF、PostScript/EPS、PCL5、PCL XL/PCL6、HP-GL/2、XPS、PWG/CUPS
  Raster、PCLm、Apple URF、常见图像、多页TIFF/DCX和纯文本。
- B01-B11覆盖ZjStream、QPDL/SPL-C、XQX、HIPERC、HBPL、DDST、LAVAFLOW、OPL、
  SLX、OAKT和Brother HBP/XL2HB；所有外部解码器只能通过固定白名单调用。
- B12的PCL3/PCL3GUI完整HPLIP编码链已证明现有GhostPCL会生成严重破损页面，因此
  正式移至C01，只识别和保留PRN，不以返回码或页数冒充转换成功。
- B13/B14通过EscaPy 1.1.0处理ESC/P和按型号Profile匹配的ESC/P2；B15使用项目内置
  受限解码器处理官方`printer-driver-escpr 1.7.17`的RGB未压缩/RLE ESC/P-R。
- C01-C11对PCL3GUI、Canon UFR/CAPT、Pantum GDI、Sharp SPLC、Ricoh RPCS、GIPD、
  IBM AFP、ESC/Page、ZPL/EPL/CPCL和Printrex执行高置信识别、原始PRN保留和下载。

完整协议限制、代表型号和证据等级见`docs/PRN_COMPATIBILITY_MATRIX.md`以及
`docs/H618_PRN完整适配对应表_v0.81.xlsx`。

## 转换与资源保护

- 私有栅格转换会解析协议内实际DPI和方向，高分辨率1-bit页面先按物理尺寸降采样，
  避免在H618上产生数百MB的RGB峰值。
- 页面数、单页像素、总像素、临时输出和转换时间均有限制；失败时删除不完整PDF并保留
  原始PRN和完整错误。
- TIFF和DCX保留多页顺序，PCLm和原始PDF保持字节内容，未知协议不会生成空白占位PDF。
- `third_party/`包含ARM64离线wheelhouse、固定来源说明、许可文本、解码器源码和对应
  小型ARM64构建，部署不依赖现场联网下载。

## ESC/P、ESC/P2与ESC/P-R

- EscaPy 1.1.0离线环境、SHA-256锁定依赖、安装脚本和K2B烟雾测试已纳入研发包。
- ESC/P支持9针和24针编码链；安全预处理只移除作业末尾、复位命令前的终端换页符，
  不修改原始PRN。
- ESC/P2默认使用严格自动匹配：`xp410`覆盖已验证的XP-440、L120、L310和ET-2750
  Gutenprint指纹，`sr800`覆盖Stylus Photo R800；未知指纹保留PRN。
- ESC/P-R已验证L3250的COLOR、MONO和双页任务，以及Artisan 630、R260、ET-2750、
  WF-6590和XP-4100相同命令方言；调色板、JPEG型和未知扩展仍只保留。

## 打印流智能结束

- 采集器使用协议结束标志优先、空闲超时兜底，不再只依赖固定静默等待。
- 支持PJL EOJ/UEL、PCL终端UEL、PostScript Ctrl-D/`%%EOF`、PDF `%%EOF`和
  ESC/P-R结构化`endj`。
- 声明长度的PCL和ESC/P-R二进制载荷整段跳过，载荷内伪控制字不会误切任务。
- 捕获线程与单工作线程转换队列解耦，转换期间仍持续读取`/dev/g_printer0`。
- 每个任务记录接收耗时、结束依据、转换耗时和转换状态，服务重启后补转完整任务。

## 网页、驱动与部署

- “模拟打印配置”显示标准转换器、私有解码器、C组识别能力、结束依据、接收/转换耗时
  以及原始PRN下载。
- 实体打印驱动支持Noble ARM64型号目录、受控APT安装和签名离线驱动包；网页不能传入
  任意命令。
- 配置迁移只补充缺失字段，不覆盖现场USB、网络、上传、热点、打印机或清理配置。
- 公司升级ZIP继续使用大小、ZIP CRC、payload SHA-256和安全路径检查，并通过独立
  release目录与软链接原子切换。

## 验证结果

- Python完整测试：共执行260项，257项通过，3项按环境条件跳过。
- Python `compileall`、Vue生产构建和`git diff --check`通过。
- K2B实板`k2b_acceptance.sh --require-host --require-enabled`结果为
  `failures=0 warnings=0`。
- `gadget-mode`、`gadget-collector`、`gadget-web`、`cups`和`jvlei-updater`均为
  `active/enabled`，USB UDC保持`configured`。

## 授权边界

- GhostPDL 10.07.1和EscaPy 1.1.0仅按已确认授权用于当前K2B测试板内部研发。
- 本次Git发布保留相应安装脚本、锁定依赖和来源说明；量产或对外交付前仍需完成AGPL
  合规方案或取得可接受的商业授权。
