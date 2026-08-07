# H618 报告网关 v0.21.1 测试更新

本版本用于验证 Windows 升级中心到 K2B 的签名下载、现场确认安装、健康检查和自动回滚闭环。

## 修复

- 修复 Windows 事件循环不支持 `add_signal_handler` 时升级中心启动后立即退出的问题。
- 升级中心启动脚本会自动查找 Git for Windows 附带的 OpenSSL，以便校验签名发布包。
- 在线安装不再调用 pip 或联网下载构建依赖，直接复用系统 Python 依赖并写入版本内相对 `.pth`。
- 应用健康检查通过后同步切换独立升级代理版本；失败包不会覆盖当前升级代理。
- 下载记录保留中心任务 ID，现场确认后的安装成功或失败都能回报到原中心任务和审计日志。

## 升级边界

- 不覆盖 `/etc/gadget-msc-printer/` 和 `/var/lib/gadget-msc-printer/`。
- 不重新绑定 USB Gadget，不重启 CUPS。
- 安装策略保持 `local_confirm`，必须由板端管理员确认安装。
