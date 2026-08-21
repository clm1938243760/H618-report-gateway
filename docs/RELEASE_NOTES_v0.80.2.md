# v0.80.2 研发版说明

`v0.80.2`在`v0.80.1`离线PRN转换能力上扩展Epson ESC/P2的严格自动匹配证据，
不增加未经验证的通用猜测路径。

## ESC/P2 L310验证

- 使用Ubuntu Noble ARM64的Gutenprint 5.3.4和Epson L310正式PPD，将同一张无业务
  测试页分别编码为360 dpi和720 dpi完整ESC/P2打印流。
- 两份打印流大小分别为759,602字节和3,258,963字节，SHA-256分别为
  `5f0b09b8d2246985d5e59bf7751872ce8ca934302683ff63d433be424849605d`和
  `5c52a48d89fc2c1cc653339f70ccc86961c83400c2e833deef5cd7403f1c4444`。
- 两种分辨率均包含与已验证XP-440相同的完整`REMOTE1 PM/SN`初始化指纹，网关
  严格自动选择EscaPy的`xp410` Profile，不根据文件名或普通ESC/P2命令猜测型号。
- K2B转换耗时分别约36.6秒和129.2秒，均生成单页A4 PDF。720 dpi输出明显增加
  CPU时间和PDF体积，报告采集现场优先建议360 dpi。
- 逐页渲染确认文字、边框、色块边界、灰阶和通道相对位置正确。120 dpi对照中，
  `xp410`将C/M/Y通道顶边对齐，`generic`仍分别错开约80/40/0像素。
- Gutenprint对Plain介质执行墨量和网点分色，PDF中的模拟墨色不按屏幕RGB值做
  等值验收；验收重点是页面内容、几何位置和颜色通道对齐。

## 配置和显示

- `xp410`网页选项更新为“Epson XP-200/205/410、L310系列”，详情明确列出
  XP-440和L310两条已验证编码链。
- 自动识别依据更新为“Gutenprint c8x/c82系列PM/SN初始化指纹”，并在打印流
  详情中显示XP-440和L310验证证据。
- 未匹配完整指纹的ESC/P2仍保留原始PRN，不调用`generic`生成可能错位的PDF。

## 部署约束

- EscaPy 1.1.0、GhostPDL和随包解码器的内部研发授权范围不变，本版本仍不是
  正式量产发布版本。
- 不重新处理历史PRN，不覆盖现场配置、报告数据或CUPS任务。
- 升级后应确认`/health`为`0.80.2`、`gadget-mode`、`gadget-collector`、
  `gadget-web`和`jvlei-updater`均为`active`，USB UDC保持`configured`。
