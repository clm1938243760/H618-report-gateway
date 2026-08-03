# WinCE U盘模板目录

这个目录用于存放 WinCE 医疗设备需要的 U盘初始化文件。

医院现场测试发现，有些 WinCE 医疗软件不接受空 U盘。
即使 U盘的文件系统和设备枚举都正常，软件也可能不提示保存成功。

原因通常是业务软件会检查 U盘里是否已有固定目录或标记文件，例如：

```text
KX/
USER/
DUMP/
```

其中：

- `KX/` 可能存放设备或厂商识别标记。
- `USER/` 通常用于保存新检查数据。
- `DUMP/` 可能用于保存设备原始数据或历史数据。

本目录只放“干净模板”，不要提交真实患者数据。

如果需要把医院原 U盘内容写入模拟 U盘镜像，可以执行：

```bash
sudo ./scripts/seed_msc_image.sh /var/lib/gadget-msc-printer/msc/ums_shared.img /path/to/hospital_template
```

建议模板只保留必要目录和标记文件，不要保留历史患者报告。
