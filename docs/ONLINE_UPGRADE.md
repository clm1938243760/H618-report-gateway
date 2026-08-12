# 公司在线升级

H618 报告网关从 `v0.22.0` 起直接接入公司升级平台，不再使用本地 Windows 升级中心、
配对码、代理令牌或 `.jvpkg`。升级范围仅包括网关应用、Vue 管理页面和 Python 代码，
不升级内核、U-Boot、设备树或完整 Armbian 镜像。

## 工作流程

```text
板子开机
  -> POST /api/auto-update/report-terminal-info
  -> POST /api/auto-update/check
  -> 使用 check 返回的临时 downloadUrl 下载 ZIP
  -> POST /api/auto-update/report 上报下载、安装结果
  -> 健康检查失败时自动回滚
  -> POST /api/auto-update/rollback-report 上报回滚结果
```

- 固定 `appCode=linux`、`platform=linux-arm64`。
- 当前 IP 和 MAC 根据到公司服务器的实际路由动态获取。
- `hospitalCode` 读取 `/etc/gadget-msc-printer/config.yaml` 中的
  `upload.hospital_code`；其他未配置的可选字段不发送。
- 开机只检查一次，失败不周期重试。恢复网络后可在 HTTPS 管理页手动检查。
- `autoUpgrade=true` 时自动下载和安装；`false` 时只展示更新，等待网页操作。
- 第一版仅使用 `/check` 返回的临时链接。链接下载失败时重新调用 `/check` 刷新一次，
  不调用当前需要 JWT 的 `/api/auto-update/package/{packageId}`。

默认公司服务地址：

```text
http://192.168.112.229:28080
```

## 公司 ZIP 规范

上传到公司版本管理的文件扩展名为 `.zip`，顶层必须且只能包含：

```text
manifest.json
payload.tar.gz
```

`manifest.json` 关键字段：

```json
{
  "schemaVersion": 1,
  "packageType": "application",
  "appCode": "linux",
  "product": "h618-report-gateway",
  "version": "v0.22.0",
  "platform": "linux-arm64",
  "architecture": "arm64",
  "compatibleFrom": ["v0.21.3"],
  "payload": {
    "path": "payload.tar.gz",
    "format": "tar.gz",
    "size": 0,
    "sha256": "64位十六进制SHA-256",
    "fileCount": 0
  },
  "install": {
    "mode": "atomic_release",
    "requiresGadgetRestart": false,
    "requiresCupsRestart": false,
    "healthUrl": "https://127.0.0.1:8443/health"
  }
}
```

板端强制检查公司响应中的包大小、ZIP CRC、固定顶层文件、payload 大小和 SHA-256、
tar 内部文件数量、总展开体积与安全路径。绝对路径、`..`、重复路径、软硬链接、FIFO、
设备文件、错误平台和不兼容版本全部拒绝。当前测试阶段 ZIP 没有数字签名，生产签名应在
后续版本增加。

## 构建升级包

先构建 Vue，再从项目根目录生成公司 ZIP：

```powershell
pnpm --dir portal\portal build
py -3.14 scripts\build_company_update_zip.py `
  --version 0.22.0 `
  --compatible-from 0.21.3 `
  --output .\output\h618-report-gateway-v0.22.0-linux-arm64.zip `
  --notes "v0.22.0 接入公司在线升级接口"
```

脚本会同时生成 `.zip.sha256`，并调用板端相同的校验器进行自检。公司版本列表填写：

```text
应用编码：linux
版本号：v0.22.0
运行平台：linux-arm64
安装包：h618-report-gateway-v0.22.0-linux-arm64.zip
```

升级策略中可按医院、院区、科室、IP 或 MAC 选择终端。板端当前只上报已配置的
`hospitalCode`，以及实际联网 IP/MAC；若策略使用医院维度，需保证业务配置中的医院编码
与平台一致。

## 安装和回滚

应用版本位于：

```text
/opt/jvlei/releases/gateway/<version>/
/opt/gadget-msc-printer -> 当前版本
```

安装前最多等待 90 秒让正在上传的报告完成，并将 `/etc/gadget-msc-printer` 备份到
`/var/lib/jvlei-updater/backups`。报告、SQLite 和打印流数据始终保留在
`/var/lib/gadget-msc-printer`，不会被升级包覆盖。

安装默认只重启 `gadget-collector.service` 和 `gadget-web.service`。只有 Manifest 明确要求时
才重启 CUPS 或 USB Gadget。安装后验证两个业务服务和 `/health` 版本；失败立即恢复旧软链接。
仅保留当前版和一个可回滚版。

网页点击安装或回滚后，代理先返回“任务已启动”，再在后台停服务和切换版本。页面短暂离线
属于正常现象，恢复后会每 3 秒读取最新状态。

## 首次 SSH 引导

从旧版本第一次切换到公司升级代理时，需要通过 SSH 部署一次新代理和配置：

```bash
cd /tmp/gateway
sudo bash scripts/bootstrap_company_updater.sh
```

脚本先将现有更新配置、状态和服务启用状态备份到
`/var/backups/jvlei-updater-company-bootstrap/<UTC时间>/`，然后只切换更新代理。
当前应用仍保持原版本；后续应用和更新代理都随公司 ZIP 更新。

## 排查命令

```bash
sudo systemctl status jvlei-updater.service gadget-web.service gadget-collector.service --no-pager
sudo journalctl -u jvlei-updater.service -n 200 --no-pager
curl -sS http://127.0.0.1:8765/status
curl -ksS https://127.0.0.1:8443/health
```

公司状态上报失败不会回滚已经健康运行的新版本。未成功上报的结果会写入本地队列，并在
下次开机检查或网页操作前补发。
