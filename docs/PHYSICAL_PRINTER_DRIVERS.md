# 实体打印驱动目录与按需安装

## 适用范围

本功能仅面向 KICKPI K2B 当前使用的 Ubuntu Noble 24.04 ARM64 / Armbian。
不能把 Debian Trixie、amd64、i386 或 Windows 驱动混入板端。现代 USB 打印机优先使用
`ipp-usb` 和 IPP Everywhere；原生支持 PCL 5/6 或 PostScript 的打印机优先使用通用驱动。

系统支持三层型号目录：

1. 可选的应用内置版本化 Noble ARM64 全型号目录。
2. 板端当前 `lpinfo -m` 返回的已安装 CUPS 型号。
3. 已验签 `.jvdrv` 离线包携带的目录。

相同稳定 `model_id` 会合并，板端已安装型号优先。网页只能提交 `model_id`，后端重新
解析白名单软件包和 CUPS 模型，不接受网页传入包名、PPD 路径或 Shell 命令。

`v0.22.6` 提供目录生成工具、在线软件源目录和离线包框架，但不附带生成后的完整
`driver-catalog-noble-arm64.json` 或 `.jvdrv` 驱动库。

## 网页流程

在“实体打印机配置”页面执行：

1. 扫描 USB 或网络打印机。
2. 查看自动推荐，或按厂商和型号搜索目录。
3. 查看来源、协议、验证等级、候选版本、依赖、下载量和磁盘占用。
4. 确认后启动后台安装任务。
5. 安装完成后选择具体型号，保存并创建 CUPS 队列。
6. 打印测试页，确认实体纸张内容后点击“内容正常”或“内容异常”。

只有人工确认正常的型号会显示“已实机验证”。CUPS 任务进入完成状态不能自动提升验证等级。

“实体打印驱动”页面用于刷新 Noble 软件源、查看安装任务详情、导入完整离线驱动库，
以及保留原有的 DEB、PPD 和 ARM64 Filter 现场驱动上传流程。

## 在线安装

受控白名单定义在 `src/gadget_msc_printer/driver_catalog.py` 的 `PACKAGE_CATALOG`。
实际安装等价于：

```text
apt-get -o DPkg::Lock::Timeout=120 install -y --no-install-recommends -- <白名单软件包>
```

APT 索引超过 24 小时才会在生成安装计划时自动刷新，也可以在高级驱动页面手动刷新。
系统会等待 APT/DPKG 锁最多 120 秒，不会终止系统中的升级进程。安装完成后重启 CUPS、
重建目录并验证目标模型存在；删除打印队列不会卸载驱动或共享依赖。

运行数据保存在：

```text
/var/lib/gadget-msc-printer/driver-catalog/catalog.sqlite3
/var/lib/gadget-msc-printer/driver-catalog/staging/
/var/lib/gadget-msc-printer/driver-catalog/offline/
```

## 生成版本化目录

目录必须在干净的 Ubuntu Noble 24.04 ARM64 构建环境中生成。先安装
`PACKAGE_CATALOG` 中的全部包，再执行：

```bash
sudo apt-get update
sudo apt-get install -y --no-install-recommends <全部白名单打印驱动包>
python3 scripts/build_driver_catalog.py \
  --output assets/driver-catalog-noble-arm64.json
```

脚本会核对系统版本、架构和软件包安装状态，并同时生成
`assets/driver-catalog-noble-arm64.build.json`。正式目录不应使用
`--allow-missing-packages`，该参数只供开发排查。

## 生成完整离线包

发布电脑只需生成一次 Ed25519 密钥。私钥必须离线保存，绝不能复制到板子或 Git：

```bash
python3 scripts/generate_driver_pack_keys.py \
  --private-key /secure/jvlei-driver-pack-private.pem \
  --public-key assets/driver-pack-public.pem
```

密钥生成脚本依赖发布电脑上的 Python `cryptography`。板端验签使用 OpenSSL，不需要安装
`cryptography`。安装脚本检测到 `assets/driver-pack-public.pem` 后，只会把公钥复制到：

```text
/etc/gadget-msc-printer/driver-pack-public.pem
```

当前随应用发布的公钥文件 SHA-256 指纹为：

```text
c8f52c7bea842d0241c9bef3ba7240771d02f9299b2860ffaf92e081fe6b9bbb
```

在同一个 Noble ARM64 构建环境生成离线包：

```bash
python3 scripts/build_driver_offline_pack.py \
  --catalog assets/driver-catalog-noble-arm64.json \
  --version 2026.08.1 \
  --private-key /secure/jvlei-driver-pack-private.pem \
  --output outputs/jvlei-printer-drivers-noble-arm64-2026.08.1.jvdrv
```

构建器计算全部白名单包的依赖闭包，下载 ARM64/`all` DEB，生成只读本地 APT 索引，
写入 SHA-256 清单并对外层包签名。导入时强制校验签名、产品名、Ubuntu 24.04、ARM64、
安全路径、软件包架构和授权依赖。导入只注册本地源，不会一次安装所有 DEB。

## API

```text
GET  /api/driver-catalog
POST /api/driver-catalog/refresh
POST /api/driver-packages/plan
POST /api/driver-packages/install
GET  /api/driver-jobs/{id}
POST /api/driver-offline/analyze
POST /api/driver-offline/install
POST /api/driver-validation
```

所有接口都使用现有 HTTPS 会话和 CSRF 校验。安装接口只接收稳定 `model_id`。

## 验收型号

- Brother HL-1218W：优先 `printer-driver-brlaser`，完成测试页后人工确认。
- HP LaserJet Pro 400 M401：优先通用 PCL 6/PCL XL，使用设备实际支持的 PCL 驱动。
- IPP 打印机：优先 IPP Everywhere，不安装型号驱动。
- 无目录匹配的私有型号：继续使用“实体打印驱动”页面导入经过审核的 ARM64 厂商驱动。
