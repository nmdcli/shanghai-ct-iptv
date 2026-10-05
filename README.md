# 上海电信 IPTV 抓取脚本

感谢本项目fork的原作者[pcg兄台的成果](https://github.com/pcg562240/pcg-iptv)。同时感谢[ihipop兄台的Shanghai-IPTV项目](https://github.com/ihipop/Shanghai-IPTV)提供的各频道logo。

本人仅仅是在MUSE的协助下，在pcg兄台成果的基础上进行了改进。在pcg兄台版本的基础上，在输出的m3u文件里增加了每个频道的logo和FCC信息。此外也多增加了3个不同版本的m3u文件，供不同的需求。本人的改动仅仅是对上海电信的脚本。广东的脚本本人不了解当地情况，无法修改。

此脚本用于抓取上海电信 IPTV 的频道列表、XMLTV 节目表和回放地址，并生成可给 APTV、TiviMate、Kodi、udpxy、rtp2httpd 等工具使用的 M3U/XMLTV 文件。
上海电信IPTV要求要有IPTV盒子账号、SN、MAC地址
回放格式有些播放器可能不兼容，可以试试经过rtp2httpd代理的。

脚本是单文件 Python 实现，只依赖 Python 标准库，适合放在 OpenWrt/ImmortalWrt 或内网服务器上定时运行。

## 脚本和输出

| 地区/运营商 | 脚本 | 主要输出 |
| --- | --- | --- |
| 上海电信 IPTV | `shctiptv_capture.py` | `shctiptv_raw.m3u`、`shctiptv.m3u`、`shctiptv_rtp2httpd_raw`、`shctiptv_rtp2httpd.m3u`、`shctiptv_rtp2httpd_simp`、`shctepg.xml` |

分别对应原始的RTSP/组播链接，以及标准的UDPXY协议，和rtp2httpd。几个文件的说明如下。以下的文件名仅为默认文件名，均可以根据自己的需要修改。

shctiptv_raw.m3u：抓到的原始组播地址。\
shctiptv.m3u：标准的UDPXY的播放地址。UDPXY转发服务的地址由用户的配置决定。\
shctiptv_rtp2httpd_raw：原始组播地址，加上了原始的时移/回看信息和FCC信息。\
shctiptv_rtp2httpd.m3u：跟raw的区别是加上了rtp2httpd的转发服务器地址。UDPXY转发服务的地址由用户的配置决定。\
shctiptv_rtp2httpd_simp：跟上一个文件的区别是不包括时移/回放的信息。因为时移/回放的信息是有时效性的，并且仅限于获取地址的设备使用。对于其他设备或者不支持时移/回放的播放器应该使用这个版本。


## 使用方法

1. 确认运行设备能访问对应运营商 IPTV 专网。
2. 打开对应脚本，在顶部“用户配置”或“用户可配置项”区域填写自己的账号、MAC、SN、代理地址等配置。
3. 运行脚本：

```bash
python3 shctiptv_capture.py
```

## 配置位置

### 上海电信

编辑 `shctiptv_capture.py` 顶部配置：

```python
DEFAULT_USER_ID = "11111111@xxxx"
DEFAULT_SN = "222222222222222222222222"
DEFAULT_MAC = "33:33:33:33:33:33"
DEFAULT_AUTH_HOST = "222.68.208.73:7001"
DEFAULT_UDPXY = "192.168.50.10:4022"
DEFAULT_RTP2HTTPD_URL = "http://192.168.50.10:5140"
DEFAULT_EPG_URL = "http://192.168.50.10/iptv/shctepg.xml"
```

上海脚本保留命令行参数，例如：

```bash
python3 shctiptv_capture.py --user-id '你的账号@etv1' --sn '你的SN' --mac '你的MAC'
```

## 定时任务示例

```cron
30 4 * * * cd /opt/iptv && /usr/bin/python3 shctiptv_capture.py >/tmp/shctiptv.log 2>&1
```
## 参考项目
1、https://github.com/yujincheng08/rust-iptv-proxy \
2、https://github.com/melody0709/cmcc_iptv_auto_py \
3、https://github.com/denymz/sh-tel-iptv-spider \
4、https://github.com/pcg562240/pcg-iptv


## 发布到 GitHub

发布公开仓库前，保持脚本里的账号、MAC、SN、Token 等字段为空或占位值，不要提交本地生成的 M3U、XML、缓存和抓包导出文件。

```bash
git add README.md .gitignore shctiptv_capture.py
git commit -m "Initial IPTV spider scripts"
git branch -M main
git remote add origin https://github.com/<your-name>/<repo-name>.git
git push -u origin main
```
