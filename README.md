# 上海电信 IPTV 抓取脚本

感谢本项目fork的原作者[pcg兄台的成果](https://github.com/pcg562240/pcg-iptv)。同时感谢[ihipop兄台的Shanghai-IPTV项目](https://github.com/ihipop/Shanghai-IPTV)提供的各频道logo。

本人仅仅是在MUSE的协助下，在pcg兄台成果的基础上进行了改进。在pcg兄台版本的基础上，在输出的m3u文件里增加了每个频道的logo和FCC信息。此外也多增加了3个不同版本的m3u文件，供不同的需求。本人的改动仅仅是对上海电信的脚本。广东的脚本本人不了解当地情况，无法修改。

此脚本用于抓取上海电信 IPTV 的频道列表、XMLTV 节目表和回放地址，并生成可给 APTV、TiviMate、Kodi、udpxy、rtp2httpd 等工具使用的 M3U/XMLTV 文件。
上海电信IPTV要求要有IPTV盒子账号、SN、MAC地址
回放格式有些播放器可能不兼容，可以试试经过rtp2httpd代理的。

脚本是单文件 Python 实现，只依赖 Python 标准库，适合放在 OpenWrt/ImmortalWrt 或内网服务器上定时运行。

shctiptv_logos.json文件是用来配置每个频道logo的。需要和主脚本shctiptv_capture.py放在同一目录下。Logo均取自ihipop兄台项目的[logo地址](https://cdn.jsdelivr.net/gh/ihipop/Shanghai-IPTV@master/tv-logo/)，但不是所有的频道都有Logo文件。对于缺失logo文件的，在配置文件中留空。如果有其他logo来源的话也可以自行更改脚本里的logo来源配置。

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
# shctiptv_capture.py 命令行参数说明

所有参数都有默认值，直接运行 `python3 shctiptv_capture.py` 即可按默认配置工作。

> ⚠️ 安全提醒：`--user-id` / `--sn` / `--mac` 的真实值不要 push 到公开仓库。

## 认证

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--user-id` | 脚本内预设 | IPTV 账号（`数字@etv1` 形式） |
| `--sn` | 脚本内预设 | IPTV 盒子的 SN / 序列号 |
| `--mac` | 脚本内预设 | IPTV 盒子的 MAC 地址 |
| `--auth-host` | 脚本内预设 | 上海电信 IPTV 认证服务器 |
| `--ip` | 留空 | 本机在 IPTV 专网侧使用的地址；留空时自动探测 |
| `--timeout` | `20` | HTTP 请求超时时间（秒） |

## 输出

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--output-dir` | 脚本所在目录 | 输出目录 |
| `--epg-url` | `http://192.168.50.10/iptv/shctepg.xml` | 写入 M3U `x-tvg-url` 的节目单访问地址 |
| `--m3u-raw` | `shctiptv_raw.m3u` | 裸组播地址版 m3u 的文件名 |
| `--m3u-rtp2httpd-raw` | `shctiptv_rtp2httpd_raw.m3u` | rtp2httpd 裸地址版 m3u 的文件名 |
| `--m3u-rtp2httpd-simp` | `shctiptv_rtp2httpd_simp.m3u` | rtp2httpd 简版 m3u 的文件名（无回放信息） |
| `--write-rtp2httpd-m3u` / `--skip-rtp2httpd-m3u` | 默认生成 | 是否生成 rtp2httpd 版 m3u（二选一，互斥） |

## 节目单 / 回放

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--days-back` | `7` | 抓取过去多少天的节目单 |
| `--days-forward` | `3` | 抓取未来多少天的节目单 |
| `--catchup-days` | `7` | 写入 M3U 的 `catchup-days` 标记 |
| `--catchup-template` | `playseek=${(b)yyyyMMddHHmmss}-${(e)yyyyMMddHHmmss}` | 追加到 TimeShiftURL 的回放 playseek 模板 |
| `--skip-epg` | 不跳过 | 只生成频道列表，不抓取节目单（调试用） |

## 频道来源

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--categories` | 脚本内置 12 组分类 | EPG 频道栏目列表，逗号分隔，可写 `cate:type` 形式，例如 `000406,000404:tvod` |
| `--extra-channel-config` | `shctiptv_extra_channel.json` | 额外频道映射配置（JSON：`组播ip:port -> 频道名`），用于收录授权表有但 EPG 分类里没有的频道；相对路径按脚本所在目录解析 |

## 直播地址格式

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--url-mode` | `udp` | 未使用 udpxy 时的直播地址格式：`udp` / `rtp` / `original` 三选一 |
| `--udpxy` | `192.168.1.202:4022` | udpxy 地址，用于 `shctiptv.m3u` |
| `--rtp2httpd-url` | `http://192.168.1.202:5140` | rtp2httpd 地址 |
| `--fcc-postfix` | `?fcc=124.75.25.211:7777` | 拼到 rtp2httpd 版 m3u 播放地址后的 FCC 后缀（频道自带 FCC 时优先用自带的） |

## 台标

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--logo-config` | `shctiptv_logos.json` | 台标配置文件（JSON：频道名 -> logo 文件名）；相对路径按脚本所在目录解析 |
| `--logo-base-url` | `https://cdn.jsdelivr.net/gh/ihipop/Shanghai-IPTV@master/tv-logo/` | 台标 CDN 基础地址 |

## 示例

```bash
# 默认运行
python3 shctiptv_capture.py

# 多抓几天节目单
python3 shctiptv_capture.py --days-back 3 --days-forward 7

# 只生成频道列表，不抓节目单（调试用）
python3 shctiptv_capture.py --skip-epg

# 指定额外频道映射文件
python3 shctiptv_capture.py --extra-channel-config my_extra.json

# 输出到指定目录
python3 shctiptv_capture.py --output-dir /tmp/iptv_test
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
git add README.md .gitignore shctiptv_capture.py shctiptv_logos.json shctiptv_extra_channel.json
git commit -m "Initial IPTV capture script"
git branch -M main
git remote add origin https://github.com/<your-name>/<repo-name>.git
git push -u origin main
```
