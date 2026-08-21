# H618 报告网关 v0.80.1（研发版）

## 离线 PRN 转换

- 新增纯HP-GL/2和PCL内嵌HP-GL/2自动识别，复用GhostPCL离线转换。
- 新增XPS/OpenXPS OPC包结构校验和本地转换链路，优先使用Ubuntu Noble ARM64
  `libgxps-utils`提供的`xpstopdf`，`gxps`作为备用；缺少转换器时保留原始PRN并
  在网页明确显示缺失，不生成伪PDF。
- 新增统一的私有栅格打印流探测、受控解码、页面分组和 PDF 合成框架。
- 新增C组私有协议只读识别：Canon UFR/CAPT、Pantum GDI、Sharp SPLC、Ricoh RPCS、
  IBM AFP、Zebra ZPL/EPL/CPCL和Printrex。识别成功后仅保留并允许下载原始PRN，
  不调用猜测性转换器；Sharp SPLC要求同时存在厂商上下文，避免误判Samsung SPL。
- 模拟打印配置新增C01-C11静态能力清单，显示协议、代表机型、识别依据和处理方式；
  未收到现场样本时也能确认设备只会识别、保留并提供PRN下载，不会生成占位PDF。
- C组任务新增`retained`元数据状态，网页显示“仅识别，已保留”，不再误报“转换失败”；
  历史C组任务的旧失败状态由分析API兼容映射，真正的解码异常仍显示转换失败和错误详情。
- 新增 QPDL/SPL-C、XQX、HIPERC、DDST、LAVAFLOW、Raster Object/OPL、SLX和
  Oak Technology OAKT转换；GIPD只做高置信识别和原始PRN保留。
- 保留原有 ZjStream 转换，并支持不同协议各自的 CMYK 颜色平面顺序。
- OAKT支持单色、Y/M/C/K平面和2位灰度子平面重建；根据流内方向字段自动区分
  HP水平镜像模式和Kyocera旋转模式。
- HBPL 改用隔离安装的 OpenPrinting 审核版解码器，支持HBPL v1页面图像和HBPL v2
  平面输出；绝不调用Ubuntu Noble中对有效输入会崩溃的`/usr/bin/hbpldecode`。
- DDST和SLX同样改用固定源码、固定SHA-256的隔离解码器。Ubuntu Noble自带
  `ddstdecode`会对完整Ricoh流段错误，自带`slxdecode`会漏掉彩色流的黄色平面。
- OPL使用带两处审计修复的独立解码器：保留`JBG_EOK`返回码，并在本平面完成后
  跳过记录填充，避免向已释放的JBIG状态继续送入数据。
- 精确区分PCL3/PCL3GUI、ESC/P、ESC/P2、ESC/P-R、ESC/Page和只有EJL外层的
  Epson未知流，避免把PCL3GUI误投GhostPCL或把EJL误报为ESC/P-R。
- 新增EscaPy命令适配层。当前K2B研发板已按AGPL安装EscaPy 1.1.0，可将
  ESC/P、ESC/P2转换为PDF；本研发升级包包含适配代码、离线依赖锁、完整ARM64
  wheelhouse和安装脚本，目标板缺少EscaPy时自动离线安装。
- ESC/P和ESC/P2送入EscaPy前只在临时副本中移除作业末尾的一个换页符；后续字节
  必须仅由空白、`ESC @`、UEL或受限的Epson `REMOTE1/IR/LD/JE`结束块组成。远程
  命令名、长度和载荷必须严格匹配白名单；原始PRN保持不变，多页任务中的正常
  换页和显式空白页仍保留。
- 模拟打印配置新增ESC/P2打印机Profile白名单，允许`auto`、`generic`、`xp410`和`sr800`，
  不接受网页传入配置路径。K2B使用XP-440 Gutenprint完整编码流和`xp410` Profile
  生成内容及颜色对齐的单页PDF，转换约39秒；`generic`对该流会产生颜色通道偏移。
  Stylus Photo R800 Gutenprint编码流配`sr800` Profile也已还原为内容及颜色对齐的
  单页A4 PDF，K2B转换约52.8秒。
- ESC/P2 Profile新增默认的`auto`严格自动匹配。它仅识别已在A4/360 dpi和
  Letter/720 dpi编码中复核的XP-410 `PM/SN`与R800 `IR/EX/PP` Gutenprint初始化指纹；
  未匹配时保留原始PRN并提示手动选择，不用`generic`猜测转换。任务元数据新增
  `escp2_profile_used`，网页分别显示实际Profile、自动建议和识别依据。
- 新增受限的内置ESC/P-R解码器，支持Epson官方`printer-driver-escpr`生成的全彩RGB
  `setq/setj/sttp/dsnd/endp/endj`流，以及未压缩和逐像素RLE光栅。解析过程限制源文件、
  命令长度、页数、页面像素、光栅数和解压体积，损坏或不支持的变体继续保留原始PRN。
- 已在K2B使用Epson L3250 PPD完成真实CUPS编码链验证：1.72 MB ESC/P-R流还原为A4、
  360 DPI单页PDF，页面边距、文字、RGB/CMYK色块和校准线均通过渲染检查；板端解码
  约1.94秒，峰值内存约69 MB。该结论不覆盖调色板、JPEG型ESC/P-R或未知扩展。
- 新增Brother HBP/XL2HB识别和离线转换，使用`brlaser`上游自带的`brdecode`
  还原单色PBM页面后合成为PDF。K2B已用HL-1200和DCP-1510配置生成的真实
  `rastertobrlaser`输出完成闭环验证。
- JPEG、PNG、BMP、TIFF、PCX和DCX图像型PRN现在会显示准确协议，不再误报为
  未知二进制流；多页TIFF和DCX会完整保留全部页面，并限制页数和解码像素总量。
- 新增PWG Raster、PCLm和Apple URF的精确识别。PWG Raster和Apple URF通过
  板端固定的CUPS `pwgtopdf`离线转换，PCLm直接保留其PDF内容。
- 新增CUPS Raster v1/v2/v3正反字节序同步字识别，并复用`pwgtopdf`离线转换。
- 私有栅格PDF不再固定使用600×600 dpi。新增QPDL、XQX、HIPERC、HBPL2、
  LAVAFLOW、OPL、SLX和OAKT的协议内分辨率解析，并在网页详细分析中显示实际横纵DPI。
- 对超过600 dpi的1-bit解码页面先保持物理尺寸降采样，再合成PDF；合法的
  1200×1200 QPDL不再因像素阈值失败，也不会膨胀为高峰值RGB页面。
- 打印边界探测不再对探测窗口的每个字节重复复制和扫描完整缓冲区；未知/私有流的
  普通数据段及PCL声明长度的`V/W`二进制载荷改为安全批量处理，控制标志、跨USB读取
  标志和同块多任务仍走精确状态机。K2B上两项256 KB大流回归由14.530秒降至0.036秒。
- 修复PJL头之后的中间UEL候选未在私有载荷到来时取消的问题，避免慢速USB间隙下
  提前切分任务。新增只读PRN边界回放脚本；K2B现存13份真实任务均保持单一正确边界，
  两份324–355 KB PCL由13.7–14.8秒降至0.85–0.86秒，16 KB ZjStream降至41–59 ms。

## 安全与诊断

- 私有解码器固定为板端白名单命令，不接受网页传入程序或参数。
- 限制解码时间、页数、单页像素和临时栅格总量，拒绝重复平面及尺寸不一致的输出。
- 解码器缺失、退出异常或页面无效时不生成 PDF，保留原始 PRN并记录完整失败原因。
- 模拟打印页面显示全部离线私有协议解析器的可用、缺失或禁用状态。

## 实板验证

- K2B现有`gpcl6`已对纯HP-GL/2绘图流完成网关端到端转换，生成PDF渲染后包含
  非白像素，不是空白页。
- K2B安装Ubuntu Noble ARM64官方`libgxps-utils 0.3.2-4build3`后，XPS和
  OpenXPS最小规范包均由网关识别并通过`xpstopdf`生成有效非空PDF。
- K2B使用CUPS过滤器生成的PWG Raster和Apple URF均已通过`pwgtopdf`生成有效
  单页PDF；PCLm编码流可由PDF工具和Ghostscript读取并由网关无损保留。
- K2B已通过网关`PdfConverter`完成完整ESC/P调用链验证：Ghostscript `epson`设备
  生成包含标题、版本号和矩形边框的打印流，网关识别后调用EscaPy生成单页A4 PDF；
  Ghostscript结构检查和150 DPI逐页渲染均通过，无额外空白页。验收脚本现在会执行
  一个不写入业务目录的ESC/P网关转换烟雾测试。
- K2B生成的CUPS Raster v3反字节序样本（`3SaR`）也已完成单页PDF闭环验证。
- 使用板端 `foo2zjs` 编码器生成无业务数据的合成打印流进行隔离验证。
- QPDL、XQX和HIPERC使用对应CUPS PPD、`foomatic-rip`及正式编码器完成完整
  编码链验证；八种横纵分辨率组合均生成单页非空PDF。
- DDST、HBPL2、LAVAFLOW、OPL、SLX和OAKT均使用正式PPD、`foomatic-rip`和
  对应`foo2*`编码器完成K2B完整编码链；彩色协议额外逐页检查CMYK组合、方向和比例。
- OAKT分别使用HP Color LaserJet 1500和Kyocera KM-1635 PPD验证水平镜像和
  90°旋转两种模式；LAVAFLOW/OPL彩色测试使用无ICM校正路径验证原始颜色平面。
- GIPD源码审计确认，Noble的`gipddecode`对真实`GDIJ/GDIP/GDIB`分支只输出结构，
  不会通过`-d`导出页面；上游也没有反向编码器或对应PPD。当前明确禁用伪转换路径，
  保留原始PRN，等待Dell 1125 MFP或Lexmark X500真实样本和专用解码器。
- K2B使用Noble官方hpcups 3.23.12和HP DeskJet 2130 PPD完成PCL3GUI完整编码链
  验证。GhostPCL 10.07.1虽然返回成功并生成单页A4 PDF，但逐页渲染后只有破碎黑块
  和横向拖影；同源基准页完整。进一步将Mode 10蓝色差分符号扩展从上游的
  `0xffffffd0`修正为`0xffffffc0`并隔离重编译，输出仍然破损，因此问题不止这一处。
  PCL3/PCL3GUI从候选B12降为C01，只识别并保留PRN，不以退出码、文件大小或页数
  作为兼容证据，也不把研究用Python原型接入正式服务。
- 板端原有 48 份 PCL、4 份 PCL XL 和5份 ZjStream仍全部可生成有效 PDF；
  6份HP ACL固件/初始化流继续正确忽略。

## 部署说明

- 目标平台为Ubuntu Noble 24.04 / Armbian ARM64。
- 新装板由`install.sh`安装`libgxps-utils`；公司应用升级包本身不会联网安装系统
  软件包，已有板升级前必须确认`xpstopdf`或`gxps`状态为可用。
- 私有协议解析器主要由`printer-driver-foo2zjs`提供，安装脚本已包含该依赖。
- HBPL、DDST、OPL和SLX审核版解码器的完整对应源码、来源、修改说明和GPL许可证
  分别保存在`third_party/foo2zjs-*`目录，并附ARM64二进制和可重复构建脚本；商业
  分发前仍需法律审核。
- Brother解码器的固定来源、完整源码和ARM64二进制保存在
  `third_party/brlaser-brdecode`，作为独立GPL命令运行；商业分发前同样需要法律审核。
- 本版本不重新处理历史 PRN，不覆盖现场配置、报告数据或CUPS任务。
- GhostPDL 10.07.1仍仅限当前K2B测试板内部测试，量产分发前需重新评审许可。
- EscaPy采用AGPL或商业授权；当前仅获准在指定K2B测试板安装并用于内部研发测试。
  `v0.80.1`研发包包含集成代码、锁定依赖和离线安装脚本，量产分发前仍需重新评审许可。
- 新增EscaPy 1.1.0的Python 3.12 ARM64离线依赖锁、完整wheelhouse和
  `install_escapy.sh`。研发升级包在目标板缺少EscaPy时自动执行离线安装；脚本要求
  显式传入`--accept-agpl`、验证全部wheel的SHA-256并使用`--no-index`安装；本次研发
  升级包包含该脚本、锁文件和全部wheel。脚本同时从独立安装中生成`generic`、`xp410`和`sr800`
  三套只读Profile配置，不把AGPL文件复制进应用源码。
