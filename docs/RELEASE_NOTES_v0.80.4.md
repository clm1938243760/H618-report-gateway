# v0.80.4 研发版说明

`v0.80.4`完善Epson ESC/P-R离线转换和打印流结束判定。该版本继续仅用于当前K2B
研发测试，不改变EscaPy和GhostPDL的既有授权范围。

## ESC/P-R即时结束

- 新增ESC/P-R流式命令解析器，按小端长度字段识别`setq/setj/sttp/setn/dsnd/endp/endj`。
- `dsnd`图像载荷按声明长度整段跳过，压缩像素中出现伪`endj`或控制字节不会误切任务。
- 完整页面后的`endj`和官方24字节REMOTE1收尾到齐后立即封包，不再等待现场配置的
  4秒空闲超时。
- `endj`后没有已知收尾时使用200 ms候选确认；未知或损坏变体仍走空闲超时兜底。
- 保留PJL封装流的`EOJ + UEL`路径，裸ESC/P-R与PJL ESC/P-R均可正确结束。

## 官方编码链验证

- 使用Ubuntu Noble ARM64 `printer-driver-escpr 1.7.17`、正式PPD、CUPS wrapper和
  指向板内TCP捕获端口的临时队列生成最终PRN，全程不连接实体打印机。
- L3250 COLOR和MONO单页流均为674,259字节、3,777条RLE光栅，约1.55秒生成A4 PDF，
  峰值内存约80 MB；MONO页面已正确灰度化。
- 双页COLOR流为1,014,998字节、7,408条光栅，约2.63秒生成两页A4 PDF，峰值内存
  约129 MB。两页文字、色块、灰阶、边框和独立页面标记均通过120 dpi渲染检查。
- Artisan 630、Stylus Photo R260、ET-2750、WF-6590、XP-4100和L3250的PPD在相同
  A4/COLOR输入下生成字节一致的流，SHA-256为
  `dad9673fdbca4b29c7b5ea1f7f8f22a5ea624058c177918f45ad641372cccfd0`。

## 网页与约束

- “模拟打印配置”将ESC/P-R列为可用的内置受限解码器，并显示COLOR、MONO、多页和
  EndJob即时封包能力。
- 打印流分析将`escpr_endj`显示为“ESC/P-R EndJob 结束”。
- 当前结论只覆盖`printer-driver-escpr 1.7.17`的已验证RGB命令方言；调色板、JPEG型
  ESC/P-R和未知扩展仍保留原始PRN，不生成猜测性PDF。

## 部署约束

- 升级不覆盖`/etc/gadget-msc-printer`、报告数据、现有CUPS队列或USB描述符。
- 不重新处理历史PRN；新结束判定只作用于升级后收到的打印任务。
- 保留`v0.80.3`作为原子回滚版本。
