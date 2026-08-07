# 在线升级与驱动发布

本模块用于更新 H618 报告网关的应用、Vue 管理页面、Python 依赖和经过审核的
Linux 打印机驱动。它不升级内核、U-Boot、设备树或完整系统镜像。

## 设计边界

```text
Windows 升级中心 -- HTTPS / Cloudflare Tunnel --> 板端主动签到代理
                                                |
                                                +-- 已签名 .jvpkg 下载与校验
                                                +-- 原子切换 /opt/gadget-msc-printer
                                                +-- 127.0.0.1:8765 本机 API
管理浏览器 -- HTTPS 443 / 8443 --> 板端配置页面 -- 代理本机 API
```

- 板端主动向中心签到；中心不直接连接设备，不提供远程 Shell、任意命令或在线文件编辑。
- 浏览器只访问原有 HTTPS 管理页面。更新代理固定监听 `127.0.0.1:8765`，不能从局域网访问。
- 程序版本位于 `/opt/jvlei/releases/gateway/<version>/`，
  `/opt/gadget-msc-printer` 是当前版本的符号链接。
- 现场配置和报告数据永远保留在 `/etc/gadget-msc-printer/`、
  `/var/lib/gadget-msc-printer/`，发布包不得覆盖这些目录。
- 当前版本只保留运行版本和一个可回滚版本。

## 版本包与签名

升级包扩展名为 `.jvpkg`，其中只有三个顶层文件：

```text
manifest.json
payload.tar.gz
signature.bin
```

`manifest.json` 使用确定性 JSON，包含产品、版本、兼容来源版本、目标架构、Git
提交、迁移级别、SHA-256、包大小、发布说明和服务重启要求。板端先校验外层文件清单、
JSON、大小、哈希与 Ed25519 签名，再安全解压；绝对路径、`..`、链接、设备文件、FIFO
和异常大的包都会拒绝。

应用更新只接受 `package_type: application`。中心下发的打印驱动使用
`package_type: printer_driver`，且必须为已签名包；含 DEB root 安装脚本的驱动会被拒绝，
只能在板端“实体打印驱动”页面进行本地二次确认。

## 首次搭建升级中心

在 Windows 开发电脑的项目根目录执行。私钥只能保留在发布电脑，不要提交 Git、不要
复制到板子。

```powershell
py -3.14 scripts/generate_update_keys.py `
  --private-key .\update_center_data\keys\update-private.pem `
  --public-key .\update_center_data\keys\update-public.pem

py -3.14 scripts/generate_center_tls.py `
  --cert .\update_center_data\tls.crt `
  --key .\update_center_data\tls.key `
  --common-name update.jvlei.com

Copy-Item .\update_center\config.example.yaml .\update_center\config.yaml
```

编辑 `update_center/config.yaml`：

- 修改 `username`、至少 12 位的 `password`；
- 将 `public_key_file` 指向 `update-public.pem`；
- 将 `tls_cert`、`tls_key` 指向上面生成的 TLS 文件；
- 生产环境保持 `allow_unsigned_packages: false`。

启动中心：

```powershell
.\update_center\run.ps1
```

管理端为 `https://<电脑IP>:9443`。它只适合可信局域网使用；默认设备 API 仅监听
`127.0.0.1:9444`。

若使用 Cloudflare Named Tunnel，将公开域名只映射到设备 API：

```yaml
tunnel: <tunnel-id>
credentials-file: C:\secure\cloudflared\<tunnel-id>.json
ingress:
  - hostname: update.jvlei.com
    service: http://127.0.0.1:9444
  - service: http_status:404
```

不要把 `9443` 管理端通过该 Tunnel 暴露到公网。

## 板端启用

安装 `v0.21` 后，升级代理服务名为 `jvlei-updater.service`。安装公钥并编辑配置：

```bash
sudo install -D -m 0644 /tmp/update-public.pem /etc/jvlei-updater/update-public.pem
sudoedit /etc/jvlei-updater/config.yaml
sudo systemctl daemon-reload
sudo systemctl enable --now jvlei-updater.service
sudo systemctl status jvlei-updater.service --no-pager
```

至少确认以下字段：

```yaml
center_url: "https://update.jvlei.com"
allow_unsigned_packages: false
install_policy: "local_confirm"
```

在板端 HTTPS 页面进入“软件升级”，用升级中心生成的一次性配对码完成配对。配对后会
保存独立 `agent_id` 与令牌；令牌文件为 `/etc/jvlei-updater/device.token`，权限 `0600`。

默认每 60 秒签到一次，失败采用指数退避，最长间隔 30 分钟。`local_confirm` 是默认
策略：中心可以下发和下载，安装必须由本机页面确认。只有板端管理员可以改为
`remote_allowed`。

## 发布应用更新

前端先在开发电脑构建：

```powershell
pnpm --dir portal\portal build
py -3.14 scripts/build_jvpkg.py `
  --version 0.21.0 `
  --compatible-from 0.20.0 `
  --output .\output\h618-report-gateway-0.21.0.jvpkg `
  --private-key .\update_center_data\keys\update-private.pem `
  --notes "v0.21 在线升级与打印驱动管理"
```

在升级中心上传并校验该包，选择一个设备或设备分组下发“下载”或“安装”。板端下载后会
再次验证签名；应用安装时先等待正在上传的报告（最多 90 秒），随后切换符号链接、重启
网页和采集服务，并访问本机 `/health` 确认版本。失败时恢复旧链接和旧服务。

## 发布中心审核驱动

支持 ARM64/all 的 DEB、PPD/PPD.GZ、以及含 PPD 和 ARM64 Filter 的 ZIP、TAR、TGZ、
TAR.GZ。生成中心驱动包：

```powershell
py -3.14 scripts/build_driver_jvpkg.py `
  --source .\drivers\approved-model.ppd `
  --version 2026.08.06 `
  --output .\output\approved-model.jvpkg `
  --private-key .\update_center_data\keys\update-private.pem `
  --notes "已审核的现场打印机驱动"
```

中心下发后，板端按同一签名和兼容性校验流程处理。现场来源不明的原始驱动不要通过中心
远程安装，应从板端“实体打印驱动”页面上传；该页面会显示厂商、型号、架构、PPD、CUPS
Filter、依赖、DEB 安装脚本和风险，再由登录用户确认。

## 回滚与故障排查

- 管理页面“软件升级”可回滚应用到上一版本。
- 驱动页面的回滚只恢复 CUPS 队列和已审核驱动注册表；它不会盲目卸载未知 DEB。
- `sudo systemctl status jvlei-updater.service gadget-web.service gadget-collector.service --no-pager`
  用于查看服务状态。
- `sudo journalctl -u jvlei-updater.service -n 150 --no-pager` 用于查看下载、签名或健康检查失败。
- 中心离线、DNS 或 Tunnel 故障不会中断报告采集和上传；代理只记录错误并延迟重试。
