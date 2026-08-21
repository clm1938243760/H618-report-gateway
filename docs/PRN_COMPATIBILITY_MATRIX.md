# PRN兼容矩阵

本文记录`v0.81`研发工作树的离线PRN识别和PDF转换能力。它不代表正式生产版本
版本。A组和B组不再强制要求取得真实PRN；通过完整编码链并逐页检查内容即可验收。
C组只要求准确识别、保留原始PRN并允许下载，不要求转换PDF。

## 状态定义

- **真实PRN验证**：使用Windows或对应Linux驱动产生的完整打印流完成转换和PDF检查。
- **编码链验证**：使用协议对应的开源编码器产生完整打印流并完成反向转换。
- **合成流验证**：协议探测、解码器调用和页面合成已经验证，仍缺对应真机PRN。
- **条件支持**：需要另行安装并完成授权审查的软件。
- **仅识别**：能分类和下载原始PRN，但不能可靠生成PDF。

## A/B/C范围与验收规则

### A组：标准语言和通用文档格式

| 编号 | 格式 | 当前结论 |
| --- | --- | --- |
| A01 | PDF | 支持 |
| A02 | PostScript/EPS | 支持 |
| A03 | PCL5/PCL5e/PCL5c | 支持 |
| A04 | PCL XL/PCL6 | 支持 |
| A05 | HP-GL/HP-GL/2 | 支持 |
| A06 | XPS/OpenXPS | 支持 |
| A07 | PWG Raster | 支持 |
| A08 | CUPS Raster v1/v2/v3 | 支持；异常超大流仍受资源限制 |
| A09 | PCLm | 支持 |
| A10 | Apple URF | 支持 |
| A11 | JPEG/PNG/BMP | 支持 |
| A12 | TIFF | 支持多页 |
| A13 | PCX/DCX | 支持；DCX保留全部页面 |
| A14 | 纯文本 | 支持 |

A组验收要求是格式识别、完整转换链、PDF页数和页面内容检查通过。真实Windows PRN
可作为补充证据，但不是发布前置条件。

### B组：具有可行离线解码路径的打印机语言

| 原编号 | 格式 | 当前结论 |
| --- | --- | --- |
| B01 | ZjStream | 支持 |
| B02 | QPDL/SPL-C | 支持 |
| B03 | HP XQX | 支持 |
| B04 | OKI HIPERC | 支持 |
| B05 | HBPL/HBPL2 | 支持 |
| B06 | Ricoh DDST | 支持 |
| B07 | LAVAFLOW | 支持 |
| B08 | Raster Object/OPL | 支持 |
| B09 | Lexmark SLX | 支持 |
| B10 | Oak OAKT | 支持 |
| B11 | Brother HBP/XL2HB | 支持；当前K2B已部署独立`brdecode` |
| B12 | PCL3/PCL3GUI | 已移至C01 |
| B13 | ESC/P | 条件支持；EscaPy 1.1.0编码链与页面验证通过 |
| B14 | ESC/P2 | 条件支持；`xp410`已验证XP-440、L120、L310和ET-2750，`sr800`已验证R800，必须选择匹配的Profile |
| B15 | ESC/P-R | 支持官方`printer-driver-escpr 1.7.17`的COLOR、MONO和多页RGB路径；六类PPD完整编码链与页面验证通过 |

B组验收要求是固定来源的离线解码器或可维护实现、完整编码链、页面内容检查和资源
限制测试通过；不强制真实PRN实测。

`B13/B14`的转换器固定为EscaPy 1.1.0。项目提供Python 3.12 ARM64离线依赖锁、
完整wheelhouse和显式AGPL确认安装脚本；`v0.81`研发包在目标板缺少EscaPy时
自动离线安装，已安装同版本时只刷新Profile和命令链接，不重复创建运行环境。
当前仅在指定K2B测试板按AGPL安装并用于内部测试；量产分发仍需完成AGPL合规方案或取得商业
授权。经典ESC/P的9针和24针完整编码链均已还原为内容正确的单页PDF。ESC/P2已用
Gutenprint的Epson XP-440完整编码流验证：`generic` Profile会产生颜色通道偏移，
EscaPy内置`xp410` Profile可正确对齐文字、图形和颜色，K2B转换约39秒。同一Profile
又用Epson L310的360 dpi和720 dpi完整编码流验证：759,602字节和3,258,963字节的
打印流均严格匹配同一`PM/SN`指纹，分别在36.6秒和129.2秒内生成单页A4 PDF。
120 dpi渲染中，`xp410`将C/M/Y通道顶边对齐；`generic`仍分别错开约80/40/0像素。
Gutenprint对Plain介质执行墨量和网点分色，输出颜色不按屏幕RGB数值做等值比较，但文字、
边框、色块边界、灰阶和通道相对位置均已逐页检查。

Epson L120又以360/720 dpi完成同一测试，转换分别约36.5秒和128.8秒，输出仍是
单页A4且通道顶边保持在同一行。ET-2750使用独立正式PPD生成的360 dpi打印流与
L120输出字节完全一致：均为759,602字节，SHA-256均为
`97333ddead787f3f1809b798b72a9fa0014459da654aa7a896ceacd7d22e6807`。
这证明Gutenprint 5.3.4在两者上使用相同编码链；结论不外推到未验证的其他型号或驱动版本。
另使用
Epson Stylus Photo R800 Gutenprint完整编码流验证`sr800` Profile：999,264字节
打印流还原为单页A4 PDF，文字、边框、C/M/Y/K、R/G/B及灰阶页面检查通过，K2B
转换约52.8秒。R800的`REMOTE1` 结束块包含`IR/LD/JE`，网关只在三个命令的长度和
载荷严格匹配时移除最终退纸换页符，原始PRN不修改。因此B14不能脱离具体型号
Profile宣称通用支持。

ESC/P2 Profile默认为`auto`。它不从文件名或普通ESC/P2命令猜测型号，只匹配本项目
用Gutenprint 5.3.4验证过的完整`REMOTE1 PM/SN`和`REMOTE1 IR/EX/PP`初始化指纹。
前者已覆盖XP-440、L120、L310与ET-2750，其中L120、L310覆盖360/720 dpi；
后者覆盖R800的A4/360 dpi和
Letter/720 dpi编码。未匹配的流不运行可能
错位的通用Profile，而是保留PRN并提示手动选择。每个新任务的元数据记录实际使用的
Profile，网页同时显示自动建议和指纹依据。这不代表Windows Epson驱动或其他Gutenprint
版本会产生相同指纹，未知来源仍需现场验证。
经典ESC/P还通过网关`PdfConverter`完成端到端实板验证，生成页面的文字、图形和页数
均已逐页检查；`k2b_acceptance.sh`会在EscaPy可用时自动运行最小网关转换烟雾测试。

`B15`使用项目内置的受限ESC/P-R解码器，不依赖EscaPy。测试板通过Ubuntu Noble ARM64
`printer-driver-escpr 1.7.17`和Epson L3250 PPD，将A4彩色测试页经真实CUPS队列编码为
1,721,206字节ESC/P-R流；解码器还原3840条`dsnd`光栅行，输出2976x4209、360 DPI
单页PDF。重新渲染后页面尺寸、边距、文字、七个色块、边框和校准线均与源PDF一致，
K2B解码约1.94秒、峰值内存约69 MB。当前明确支持`setq/setj/sttp/dsnd/endp/endj`
命令和全彩RGB的未压缩/逐像素RLE数据；调色板、JPEG型ESC/P-R及其他厂商扩展仍只
识别和保留原始PRN，不能据此宣称所有Epson ESC/P-R型号通用。

`v0.80.4`又通过指向板内TCP捕获端口的临时CUPS队列验证了完整wrapper链，而不是把
CUPS Raster错误地直接交给底层过滤器。L3250 COLOR和MONO单页流均为674,259字节、
包含3,777条RLE `dsnd`光栅，分别约1.55秒生成A4 PDF，峰值内存约80 MB；MONO由官方
驱动先灰度化，ESC/P-R载荷仍是RGB三字节像素。双页COLOR流为1,014,998字节、7,408条
光栅，约2.63秒生成两页A4 PDF，峰值内存约129 MB。文字、色块、灰阶、边框、页码和
第二页标记均逐页渲染检查通过。

Artisan 630、Stylus Photo R260、ET-2750、WF-6590、XP-4100和L3250六份官方PPD在
同一A4/COLOR测试下输出字节完全一致，SHA-256均为
`dad9673fdbca4b29c7b5ea1f7f8f22a5ea624058c177918f45ad641372cccfd0`。
这证明这些型号在当前驱动版本和选项下共用已验证命令方言，但不外推到其他驱动版本、
调色板或JPEG扩展。采集器现在流式解析命令长度，跳过`dsnd`二进制载荷，仅在完整页面
后的`endj`及官方24字节REMOTE1收尾到齐时立即封包；收尾缺失时使用200 ms候选确认，
无法解析的变体继续使用现场空闲超时。真实COLOR、MONO、双页流已在4 KiB、64 KiB、
整块和收尾跨块输入下精确回放，两份任务背靠背也不会合并。

### C组：仅识别和保留PRN

| 编号 | 格式 | 当前识别状态 |
| --- | --- | --- |
| C01 | PCL3/PCL3GUI | 已高置信识别并保留PRN |
| C02 | Canon UFR II/UFR II LT | 已高置信识别明确UFR/UFR II标记 |
| C03 | Canon CAPT | 已高置信识别明确CAPT标记 |
| C04 | Pantum GDI | 已高置信识别明确Pantum/GDI标记 |
| C05 | Sharp SPLC | 已识别显式Sharp/SPLC上下文；单独SPLC仍按歧义处理 |
| C06 | Ricoh RPCS | 已高置信识别明确RPCS/PJL标记 |
| C07 | Granite GIPD | 已高置信识别并保留PRN |
| C08 | IBM AFP | 已高置信识别连续AFP结构化字段 |
| C09 | Epson ESC/Page | 已识别并保留PRN |
| C10 | Zebra ZPL/EPL/CPCL | 已识别ZPL、EPL、CPCL结构命令 |
| C11 | Printrex | 已识别明确Printrex标记，仍需真实样本扩充特征 |

C组不得调用猜测性转换器，也不得生成空白或破损的占位PDF。识别成功后必须在网页
显示协议、置信度和原因，并保留原始PRN供下载。B13-B15已经分别形成条件支持或受限
支持结论，继续保留在B组。

当前C组识别器只在以下证据成立时报告协议：Canon需要UFR/CAPT语言或明确标记，
Pantum需要Pantum与GDI上下文，Sharp需要Sharp厂商上下文与SPLC同时出现，Ricoh需要
RPCS/PJL标记，AFP需要连续的AFP结构化字段，Zebra需要ZPL/EPL/CPCL的作业头和命令
组合，Printrex需要明确厂商标记。单独的`SPLC`仍保留Samsung QPDL/SPL-C兼容路径，
避免把Samsung和Sharp混淆；无法满足证据条件的流继续显示为未知并保留原始PRN。

与当前网关对照

EscapeE栏依据本项目评估时提供的RedTitan能力清单整理，表示对应桌面产品声称能够
读取该格式，不等于已在当前版本、当前样本上完成复核，也不代表能够移植或分发到
ARM64 Linux。网关栏只记录本项目已有证据，二者的证据等级不能互相替代。

| PRN内部格式 | EscapeE能力清单 | H618网关当前状态 | 代表驱动或打印机 | 结论 |
| --- | --- | --- | --- | --- |
| PCL5/PCL5e/PCL5c | 支持 | 真实PRN验证 | HP LaserJet通用PCL5、旧款Brother PCL | 两者都可，现场优先使用标准PCL |
| PCL XL/PCL6 | 支持 | 真实PRN验证 | HP M401、Brother HL-5590DN | 两者都可，优先级最高 |
| HP-GL/HP-GL/2 | 支持 | K2B编码链验证 | HP DesignJet、工程绘图仪 | 两者都可；网关仍需更多真实绘图PRN |
| PostScript/EPS | 支持 | 真实PRN验证 | HP PS、Brother BR-Script、Adobe PS | 两者都可 |
| PDF直传 | 支持 | 真实文件验证 | Direct PDF、部分IPP打印路径 | 两者都可，网关无损保留原始PDF |
| JPEG/PNG/BMP/TIFF/PCX/DCX | 支持 | 文件及多页K2B验证 | 图像型RAW任务、扫描和传真输出 | 两者都可；网关限制页数和解码像素 |
| 普通文本 | 支持 | 文件验证 | Generic/Text Only | 两者都可 |
| XPS/OpenXPS | 本次资料未确认 | 规范包验证 | Microsoft XPS/V4打印路径 | 网关可离线转换，EscapeE需按版本复核 |
| PWG/CUPS Raster | 本次资料未确认 | K2B编码链验证 | IPP Everywhere、Linux CUPS | 网关可离线转换 |
| PCLm/Apple URF | 本次资料未确认 | K2B编码链验证 | Mopria、AirPrint、移动打印 | 网关可离线转换 |
| ESC/P | 支持 | K2B条件支持，9针/24针编码链验证 | Epson FX-80/FX-890、LQ系列点阵机 | 研发包离线安装EscaPy；量产需完成授权方案 |
| ESC/P2 | 支持 | K2B按型号Profile条件支持 | Epson XP-200/205/410、L120、L310、ET-2750、Stylus Photo R800同类喷墨机 | XP-440、L120、L310和ET-2750配`xp410`，R800配`sr800`的Gutenprint编码链验证通过 |
| ESC/P-R | 提供方称支持，需按版本实测 | K2B官方编码链验证 | Epson L3250、Artisan 630、R260、ET-2750、WF-6590、XP-4100 | 网关内置COLOR/MONO/多页RGB解码器；其他变体保留PRN |
| IBM AFP | 支持 | 高置信识别并保留PRN | IBM InfoPrint、大型机AFP任务 | 网关尚不能转换，需继续取得真实样本 |
| Printrex | 支持 | 识别明确厂商标记并保留PRN | Printrex医疗热敏打印机 | 网关尚不能转换，必须取得真实PRN扩充特征 |
| ZjStream | 支持 | 真实PRN验证 | HP 1000/1018/1020/P1102、KM 2430DL | 两者都可 |
| QPDL/SPL-C | 本次资料未确认 | K2B完整编码链验证 | Samsung CLP-300/315/325、Xerox 6110 | 网关可用，仍需Windows真实PRN扩充证据 |
| HP XQX | 本次资料未确认 | K2B完整编码链验证 | HP M1005、P1005/P1006/P1505 | 网关可用 |
| OKI HIPERC | 本次资料未确认 | K2B完整编码链验证 | OKI C310/C3200/C3300/C5100 | 网关可用 |
| HBPL/HBPL2 | 本次资料未确认 | K2B完整编码链验证 | Dell 1355/C1765、Epson CX17/M1400 | 网关可用 |
| Ricoh DDST | 本次资料未确认 | K2B完整编码链验证 | Ricoh SP112 | 网关可用 |
| LAVAFLOW/OPL | 本次资料未确认 | K2B完整编码链验证 | KM 1600W/1690MF/2480MF | 网关可用 |
| Lexmark SLX | 本次资料未确认 | K2B完整编码链验证 | Lexmark C500n | 网关可用 |
| Oak OAKT | 本次资料未确认 | K2B完整编码链验证 | HP LaserJet 1500、Kyocera KM-1635 | 网关可用 |
| Brother HBP/XL2HB | 本次资料未确认 | K2B完整编码链验证 | Brother HL-1110/1200/1218W、DCP-1510 | 网关可用 |
| Granite GIPD | 本次资料未确认 | 仅识别并保留PRN | Lexmark X500、Dell 1125MFP | 两边都缺少本项目可证明的可靠转换结果 |
| PCL3/PCL3GUI | 本次资料未确认 | K2B编码链否定，保持仅识别 | HP DeskJet 2130/2330等主机型喷墨机 | DeskJet 2130的完整hpcups流经GhostPCL会生成破损页面，不能作为转换能力；EscapeE仍需单独实测 |
| Canon UFR II/CAPT | 未确认 | 仅识别 | Canon MF3010、LBP2900/3000 | 当前两边都不能作为已验证方案 |
| Pantum GDI/Sharp SPLC/Ricoh RPCS | 未确认 | 明确标记可识别并保留PRN | 奔图P2200/M6500、Sharp低端机、Ricoh Aficio | 网关不转换；仍需真实PRN扩充特征 |

选型时不能只看打印机型号：同一型号若同时提供PCL6、PostScript和私有GDI驱动，
电脑实际选择的驱动决定PRN语言。现场应优先PCL6，其次PostScript，最后才评估私有流。

## 标准语言和文档格式

| PRN内部格式 | 当前转换路径 | 验证等级 | 代表驱动或型号 |
| --- | --- | --- | --- |
| PDF | 原文件校验和复制 | 真实文件验证 | Direct PDF、虚拟PDF打印 |
| PostScript/EPS | Ghostscript/ps2pdf | 真实PRN验证 | HP PS、Brother BR-Script |
| PCL5/5e/5c | GhostPCL | 真实PRN验证 | HP LaserJet、通用PCL5 |
| PCL XL/PCL6 | GhostPCL | 真实PRN验证 | HP M401、Brother HL-5590DN |
| HP-GL/2 | GhostPCL | 编码链验证 | HP DesignJet、工程绘图驱动 |
| XPS/OpenXPS | xpstopdf，gxps备用 | 规范包验证 | Microsoft XPS/V4打印路径 |
| PWG Raster | CUPS pwgtopdf | K2B编码链验证 | IPP Everywhere、Linux免驱打印路径 |
| CUPS Raster v1/v2/v3 | CUPS pwgtopdf | K2B编码链验证 | Linux/CUPS中间打印流 |
| PCLm | 直接保留PDF内容 | K2B编码链验证 | Mopria及部分移动/免驱打印路径 |
| Apple URF | CUPS pwgtopdf | K2B编码链验证 | AirPrint、macOS/iOS Raster路径 |
| JPEG/PNG/BMP | Pillow | 文件验证 | 图像型RAW任务 |
| TIFF | Pillow，保留全部帧 | K2B两页验证 | 扫描、传真和医学图像任务 |
| PCX | Pillow | 文件验证 | 旧式图像打印任务 |
| DCX | Pillow，保留全部PCX页 | K2B两页验证 | 多页传真/PCX归档任务 |
| 纯文本 | Pillow文本渲染 | 文件验证 | Generic/Text Only |
| ESC/P | 研发包离线安装的EscaPy 1.1.0 | K2B 9针/24针编码链与页面验证 | Epson FX/LQ点阵打印机 |
| ESC/P2 | 研发包离线安装的EscaPy 1.1.0 + 型号Profile | K2B XP-440、L120、L310、ET-2750/`xp410`和R800/`sr800` Gutenprint编码链验证 | Epson XP-200/205/410、L120、L310、ET-2750、Stylus Photo R800同类喷墨机 |
| PCL3/PCL3GUI | 无 | K2B hpcups编码链否定，仅识别 | HP DeskJet 2130/2330等 |
| ESC/P-R | 内置受限解码器 | K2B六类PPD的CUPS完整编码链与页面验证 | Epson `printer-driver-escpr 1.7.17`同命令方言的COLOR/MONO/多页RGB任务 |
| ESC/Page | 无 | 仅识别 | Epson AcuLaser部分型号 |
| IBM AFP | 无 | 结构化字段识别并保留PRN | IBM大型机和InfoPrint任务 |

## 已接入私有栅格语言

| PRN内部格式 | 当前转换路径 | 验证等级 | 代表型号 |
| --- | --- | --- | --- |
| ZjStream | zjsdecode + Pillow | 真实PRN验证 | HP 1000/1018/1020/P1102、KM 2430DL |
| QPDL/SPL-C | qpdldecode + Pillow | K2B完整编码链验证 | Samsung CLP-300/315/325、Xerox 6110 |
| HP XQX | xqxdecode + Pillow | K2B完整编码链验证 | HP M1005、P1005/P1006/P1505 |
| OKI HIPERC | hipercdecode + Pillow | K2B完整编码链验证 | OKI C310/C3200/C3300/C5100 |
| HBPL/HBPL2 | 审核版hbpldecode + Pillow | K2B完整编码链验证 | Dell 1355/C1765、Epson CX17/M1400 |
| Ricoh DDST | 审核版ddstdecode + Pillow | K2B完整编码链验证 | Ricoh SP112等 |
| LAVAFLOW | lavadecode + Pillow | K2B完整编码链验证 | KM 1600W/1690MF/2530DL、Xerox 6115MFP |
| Raster Object/OPL | 修正版opldecode + Pillow | K2B完整编码链验证 | Konica Minolta 2480MF |
| Lexmark SLX | 审核版slxdecode + Pillow | K2B完整编码链验证 | Lexmark C500n |
| Oak OAKT | oakdecode + Pillow | K2B完整编码链验证 | HP LaserJet 1500、Kyocera KM-1635/2035 |
| Brother HBP/XL2HB | 审核版brdecode + Pillow | K2B完整编码链验证 | Brother HL-1110/1200/1218W、DCP-1510 |

## 尚无可靠离线转换器

| PRN内部格式 | 当前行为 | 代表型号 | 建议 |
| --- | --- | --- | --- |
| Canon UFR II/UFR II LT | 仅识别 | Canon MF3010、LBP212dw、imageRUNNER | 型号支持时改用PCL6或PS驱动 |
| Canon CAPT | 仅识别 | Canon LBP2900/3000 | 收集真实PRN并评估CAPT解码器 |
| Pantum GDI | 明确Pantum/GDI标记时识别并保留PRN | Pantum P2200/P2500、M6500 | 优先收集官方Windows驱动PRN |
| Sharp SPLC | Sharp厂商上下文与SPLC同时出现时识别并保留PRN | 部分低端Sharp打印机 | 单独SPLC仍按歧义处理，不得与Samsung SPL-C混淆 |
| Ricoh RPCS | 明确RPCS/PJL标记时识别并保留PRN | 部分Ricoh Aficio/SP | 型号支持时改用PCL/PS |
| Granite GIPD | 高置信识别并保留PRN；系统工具只分析结构 | Lexmark X500、Dell 1125MFP | 取得真实PRN并开发可导出页面的专用解码器 |
| IBM AFP | 连续结构化字段识别并保留PRN | IBM InfoPrint和大型机AFP任务 | 收集真实AFP任务后扩充结构校验 |
| Zebra ZPL/EPL/CPCL | 作业头和命令组合识别并保留PRN | Zebra GK/ZD和标签打印机 | 报告场景低优先级 |
| Printrex | 明确厂商标记时识别并保留PRN | Printrex医疗热敏打印机 | 必须先取得真实PRN和协议资料 |

## 现场判断规则

1. 兼容性由电脑实际安装的驱动决定，不由打印机外壳型号单独决定。
2. 同一型号存在PCL6、PostScript和私有驱动时，优先选择PCL6，其次PostScript。
3. 新协议必须保存原始PRN，并校验PDF页数、方向、文字、图像、灰度和多页顺序。
4. 只有合成流的协议不能标记为“实机验证”；需要对应Windows驱动或实体设备样本。
5. 未知协议转换失败时不得生成占位PDF，必须保留PRN和完整错误信息。

## K2B现代打印流闭环验证（2026-08-20）

测试页不含业务或患者数据，由板端Pillow生成PDF，再通过Ubuntu Noble的CUPS
过滤器链分别编码。所有转换都从`v0.80.4`研发工作树的`PdfConverter`隔离运行，
没有替换正式程序或重启服务。

| 格式 | 编码流特征 | 输入大小 | 网关输出 | 渲染检查 | 输入SHA-256 |
| --- | --- | ---: | --- | --- | --- |
| PWG Raster | `RaS2PwgRaster` | 24,136 B | 1页PDF，115,036 B | 612×792，263,991个非白像素 | `0ba78da244d23aebc6f175b52ecd2a87a77a42db9b589c1795d865f023260088` |
| PCLm | `%PDF-1.3`、`%PCLm 1.0` | 271,178 B | 字节原样保留，1页PDF | 输入与输出SHA-256一致 | `de32c0d841702cedf8815bce1cecc20319cc39a9f1232466f8ffb6474e4de499` |
| Apple URF | `UNIRAST` | 22,380 B | 1页PDF，115,034 B | 612×792，263,991个非白像素 | `e29cd02491dfb042b0f27121c9dc9edc234593e7afb1f999c77dfe356717a21a` |
| CUPS Raster v3 | 反字节序`3SaR` | 86,401,800 B | 1页PDF，101,152 B | 576×720，226,010个非白像素 | `2b5df8101e9e7eed51f5e8519b2fbc98bacba37ca1aec300a38d2c0afc8c2f84` |

验证后四个业务服务均为`active`，USB UDC保持`configured`。测试数据仅写入`/tmp`。

## K2B私有栅格编码链验证（2026-08-20）

同一张无业务测试页先转为PostScript，再使用CUPS驱动数据库导出的正式PPD和
`foomatic-rip`生成完整PRN。网关从协议流读取实际DPI，调用系统白名单解码器，
最后合成为PDF。

| 协议 | 编码驱动/代表型号 | PRN大小 | 输入SHA-256 | 验证结果 |
| --- | --- | ---: | --- | --- |
| QPDL/SPL-C | `foo2qpdl` / Samsung CLP-300 | 224,144 B | `1105a300a95ba554b765d475f5c1bbe39970f02595e09785b2b189b905eb829f` | 1页非空PDF；600×600、1200×600、1200×1200全部通过 |
| HP XQX | `foo2xqx` / HP LaserJet P1005 | 67,798 B | `61367aa9b7051826826726dbfc2c1d4a621ff3689e55b06beda9cccaf19c2fe1` | 1页非空PDF；600×600、1200×600全部通过 |
| OKI HIPERC | `foo2hiperc` / OKI C3200 | 3,994,854 B | `011ad092e7824562a144258907120ad70d94e4d60ff2622127d8e1a33ecd1ade` | 1页非空PDF；300×300、600×600、600×1200全部通过 |
| Ricoh DDST | `foo2ddst` / Ricoh SP 112 | 78,272 B | `09a4484c44ca93ddbf3fe20106df2b221aba1f2ae84cffe77b7c3856ddf0462c` | 单色1页；600×600；标准A4；审核版解码器通过 |
| HBPL2 | `foo2hbpl2` / Dell 1355 | 135,598 B | `1fd23e4cdaeabf4bce0b46aa297af61e49d73072599bc163840b78db53e96bec` | 单色1页；按2-bit横向打包解析为1200×600 |
| HBPL2彩色 | `foo2hbpl2` / Dell 1355 | 355,273 B | `78e516bd248a2937b843c1918235ef3584b61fc4076acd1401d3ea558466f076` | 四平面颜色、方向和比例正确 |
| LAVAFLOW | `foo2lava` / KM magicolor 1600W | 135,525 B | `7ec65041ba32db6872cd27a90beb3b43faa8178c990b1b317063e8e8614c43d0` | 单色1页；从二进制页头解析1200×600 |
| LAVAFLOW彩色 | `foo2lava` / KM magicolor 1600W | 355,347 B | `86b4ac870ccd749d8db46f5c971e279d757e109401ae8527810736c0bc0d8a22` | C/M/Y/K颜色和方向正确；测试未使用专有ICM |
| Raster Object/OPL | `foo2lava -z1` / KM magicolor 2480 MF | 135,604 B | `273e98e175281be2c53357d3b376e485d4d5c0efbe4570f23a36eec07cee443e` | 单色1页；文本头解析1200×600 |
| OPL彩色 | `foo2lava -z1` / KM magicolor 2480 MF | 355,810 B | `a12af49f53f31416cf979d50ef022d7d10b10f8c08d9f8203f01dd0bad97ca75` | 四平面颜色正确；修正版解码器不再段错误 |
| Lexmark SLX | `foo2slx` / Lexmark C500 | 127,508 B | `85f923f0dd699c40374de12ee0ff4bb61662ab748fd2d33b4d2baaa79f984ddc` | 单色1页；二进制页面项解析1200×600 |
| Lexmark SLX彩色 | `foo2slx` / Lexmark C500 | 102,444 B | `6e2f20f8c71830fe228199beeec3f093a36578938c70b59bb38bebf33de430d2` | 审核版解码器保留四个平面，黄色及RGB组合正确 |
| OAKT HP单色 | `foo2oak -z0` / HP Color LaserJet 1500 | 85,296 B | `d3c3d92e50fe9155e11d6a302f414e2ddd7979b342e5834726cda0610c7542bc` | 600×600；按流内方向标志解除水平镜像 |
| OAKT HP彩色 | `foo2oak -z0` / HP Color LaserJet 1500 | 75,664 B | `00cdfd25fe626e86f5e02f0c3087abc2d8bbd631198991e15605ec863cedab54` | Y/M/C/K平面顺序、方向和RGB组合正确 |
| OAKT Kyocera | `foo2oak -z1` / Kyocera KM-1635 | 72,016 B | `3bdae66bcd5f5425185a26b9b2a68f7aef837c7f7cf546bca99a51a635a730c9` | 600×600；按流内方向标志逆时针旋转90° |

原实现固定按600×600 dpi写PDF，会把1200×600的QPDL、XQX、HBPL2、LAVAFLOW、
OPL和SLX页面横向放大约一倍。现在分别解析QPDL页头、XQX页面属性、HIPERC PJL、
HBPL打包位数、LAVAFLOW二进制页头、OPL文本页头及SLX页面项。超过600 dpi的1-bit
解码页面会先按物理尺寸降采样到最高600 dpi，再转RGB/PDF，避免1200×1200页面
产生约390 MB的RGB峰值；源图、输出图仍分别受1.5亿和7500万像素限制。

OAKT还根据纸张参数中的方向标志区分HP水平镜像模式和Kyocera旋转模式，并使用
协议实际的Y/M/C/K平面顺序。以上单色和彩色PDF均已逐页渲染检查，不以解码器返回
码或“文件非空”代替方向、颜色和内容验收。

GIPD源码审计确认，Ubuntu Noble的`gipddecode`在真实`GDIJ/GDIP/GDIB`分支只输出
记录结构并跳过压缩块，`-d`不会导出页面；上游包也没有反向GIPD编码器或Lexmark
X500/Dell 1125 PPD。因此网关明确禁用这条伪转换路径，只保留协议识别、原始PRN和
诊断信息，不能以mock生成PBM的框架测试作为转换证据。

## K2B PCL3GUI否定性验证（2026-08-20）

本次使用Ubuntu Noble官方`printer-driver-hpcups 3.23.12+dfsg0-0ubuntu5.1`和
`hplip-data 3.23.12+dfsg0-0ubuntu5.1`，从
`drv:///hpcups.drv/hp-deskjet_2130_series.ppd`取得HP DeskJet 2130配置。
CUPS测试页先生成127,353,336字节的CUPS Raster，再由官方`hpcups`过滤器编码为
174,089字节的完整PCL3GUI打印流。输入SHA-256为
`2f487d7f734a2b867537446358a5681a650bab572ec1eec60a868fc51367d924`。

GhostPCL 10.07.1对该流返回成功，并生成208,520字节、单页A4 PDF，SHA-256为
`33a1e528aa0de4f743816872b525605a24f0e4785e012c63d66e81d1b39ca832`；但PDF渲染后
只有破碎黑块、横向拖影和大量空白，文字、色块及灰阶均不可读。同源正常基准PDF为
32,156字节，SHA-256为
`3457ecb210394f754e22ab1bc142a640a21b2cbf220f2811ff66494bf2ef94a9`，渲染后的文字、
颜色、灰阶和版面均完整。

因此“转换命令返回成功、PDF可打开、页数正确”不能证明PCL3GUI兼容。当前网关继续
仅识别PCL3/PCL3GUI并保留原始PRN，不调用GhostPCL。该结论证明这条DeskJet 2130
编码链不能使用现有GhostPCL可靠转换，不外推为所有PCL3变体均不可转换；其他驱动流
和EscapeE仍需用各自真实输出单独验证。
