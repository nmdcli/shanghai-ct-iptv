#!/usr/bin/env python3
"""
上海电信 IPTV 频道列表和节目单抓取脚本。

脚本参考 denymz/sh-tel-iptv-spider 的核心流程，用纯 Python 实现，
方便放在 OpenWrt/ImmortalWrt 上通过 cron 定时运行。

运行环境需要能访问上海电信 IPTV 专网；如果脚本所在设备不是 IPTV WAN
出口，需要在上级路由上给它做源 NAT 到 IPTV 接口。
"""

from __future__ import annotations

import argparse
import binascii
import datetime as _dt
import gzip
import hashlib
import html
import json
import random
import re
import socket
import sys
import time
import urllib.parse
import urllib.request
import zlib
from http.cookiejar import Cookie, CookieJar
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from xml.sax.saxutils import escape as xml_escape


# --- 用户可配置项 ----------------------------------------------------------
#
SCRIPT_DIR = Path(__file__).resolve().parent

# IPTV 账号，通常是“数字@etv1”。这是模拟盒子鉴权的必要参数。
DEFAULT_USER_ID = "11111111@xxxx"

# IPTV 盒子的 SN/序列号。抓包里的 SN 要和账号、MAC 对应。
DEFAULT_SN = "222222222222222222222222"

# IPTV 盒子的 MAC 地址。格式保持 XX:XX:XX:XX:XX:XX。
DEFAULT_MAC = "33:33:33:33:33:33"

# 上海电信 IPTV 认证入口。一般不用改，除非抓包发现认证服务器变化。
DEFAULT_AUTH_HOST = "222.68.208.73:7001"

# 输出目录。默认写到本脚本所在目录，适合 /iptv/shctiptv.py 这种部署方式。
DEFAULT_OUTPUT_DIR = str(SCRIPT_DIR)

# 爱快/udpxy 地址，用于生成 shctiptv.m3u 的直播地址。
DEFAULT_UDPXY = "192.168.50.10:4022"

# rtp2httpd 地址，用于生成 shctiptv2.m3u 的直播和 RTSP 回放代理地址。
DEFAULT_RTP2HTTPD_URL = "http://192.168.50.10:5140"

# 写入 M3U 头部的节目单 URL，需要和静态文件服务地址一致。建议本机有http服务，讲脚本生成的shctepg.xml文件放进去http服务的相应目录
DEFAULT_EPG_URL = "http://192.168.50.10/iptv/shctepg.xml"

# FCC地址。这只是其中一个，更多的请见 https://rtp2httpd.com/reference/cn-fcc-collection
DEFAULT_FCC_POSTFIX = "?fcc=124.75.25.211:7777"

# 回放天数，只影响 M3U 的 catchup-days 标记，不改变电信平台实际可回放范围。
DEFAULT_CATCHUP_DAYS = "7"
DEFAULT_DAYS_FORWARD = 3
DEFAULT_IP = ""
DEFAULT_CATEGORIES_TEXT = ""
DEFAULT_URL_MODE = "udp"
DEFAULT_TIMEOUT = 20

# 回放时间占位符。当前默认适配 APTV 风格，本地时间由播放器按 EPG 节目段替换。
DEFAULT_CATCHUP_TEMPLATE = "playseek=${(b)yyyyMMddHHmmss}-${(e)yyyyMMddHHmmss}"

# 是否生成 rtp2httpd 版 shctiptv2.m3u。默认生成；可用 --skip-rtp2httpd-m3u 关闭。
DEFAULT_WRITE_RTP2HTTPD_M3U = True

# 默认输出文件名。可以根据自己的需要变更
M3U_FILENAME = "shctiptv.m3u"
RTP2HTTPD_M3U_FILENAME = "shctiptv_rtp2httpd.m3u"
M3U_RAW_FILENAME = "shctiptv_raw.m3u"
RTP2HTTPD_SIMP_M3U_FILENAME = "shctiptv_rtp2httpd_simp.m3u"
RTP2HTTPD_RAW_M3U_FILENAME = "shctiptv_rtp2httpd_raw.m3u"
EPG_FILENAME = "shctepg.xml"

# 台标 CDN 基础地址，配置文件里的 logo 文件名拼在这后面。上海的台标见这个项目：https://cdn.jsdelivr.net/gh/ihipop/Shanghai-IPTV@master/tv-logo/
DEFAULT_LOGO_BASE_URL = "https://cdn.jsdelivr.net/gh/ihipop/Shanghai-IPTV@master/tv-logo/"
# 台标配置文件名（JSON：{"播放源频道名": "logo文件名"}，没有 logo 的频道值留空）。
# 相对路径时按脚本所在目录解析，可用 --logo-config 指定别处。
LOGO_CONFIG_FILENAME = "shctiptv_logos.json"

AUTH_UA = "webkit;Resolution(PAL,720P,1080P)"
DALVIK_UA = "Dalvik/1.6.0 (Linux; U; Android 4.4.2; HG680 Build/1.5.2)"

# 抓包和参考项目中用到的栏目分类。通常不用改；脚本会自动去重合并频道。
DEFAULT_CATEGORIES: Tuple[Tuple[str, str], ...] = (
    ("000406", ""),
    ("000406", "tvod"),
    ("00040A", ""),
    ("000403", ""),
    ("000404", ""),
    ("000404", "tvod"),
    ("000405", ""),
    ("000408", ""),
    ("000409", ""),
    ("000401", ""),
    ("00040B", ""),
    ("00040B", "tvod"),
)


class IPTVError(RuntimeError):
    pass


# --- 最小 AES-128 ECB 实现 ------------------------------------------------

SBOX = [
    0x63, 0x7C, 0x77, 0x7B, 0xF2, 0x6B, 0x6F, 0xC5, 0x30, 0x01, 0x67, 0x2B, 0xFE, 0xD7, 0xAB, 0x76,
    0xCA, 0x82, 0xC9, 0x7D, 0xFA, 0x59, 0x47, 0xF0, 0xAD, 0xD4, 0xA2, 0xAF, 0x9C, 0xA4, 0x72, 0xC0,
    0xB7, 0xFD, 0x93, 0x26, 0x36, 0x3F, 0xF7, 0xCC, 0x34, 0xA5, 0xE5, 0xF1, 0x71, 0xD8, 0x31, 0x15,
    0x04, 0xC7, 0x23, 0xC3, 0x18, 0x96, 0x05, 0x9A, 0x07, 0x12, 0x80, 0xE2, 0xEB, 0x27, 0xB2, 0x75,
    0x09, 0x83, 0x2C, 0x1A, 0x1B, 0x6E, 0x5A, 0xA0, 0x52, 0x3B, 0xD6, 0xB3, 0x29, 0xE3, 0x2F, 0x84,
    0x53, 0xD1, 0x00, 0xED, 0x20, 0xFC, 0xB1, 0x5B, 0x6A, 0xCB, 0xBE, 0x39, 0x4A, 0x4C, 0x58, 0xCF,
    0xD0, 0xEF, 0xAA, 0xFB, 0x43, 0x4D, 0x33, 0x85, 0x45, 0xF9, 0x02, 0x7F, 0x50, 0x3C, 0x9F, 0xA8,
    0x51, 0xA3, 0x40, 0x8F, 0x92, 0x9D, 0x38, 0xF5, 0xBC, 0xB6, 0xDA, 0x21, 0x10, 0xFF, 0xF3, 0xD2,
    0xCD, 0x0C, 0x13, 0xEC, 0x5F, 0x97, 0x44, 0x17, 0xC4, 0xA7, 0x7E, 0x3D, 0x64, 0x5D, 0x19, 0x73,
    0x60, 0x81, 0x4F, 0xDC, 0x22, 0x2A, 0x90, 0x88, 0x46, 0xEE, 0xB8, 0x14, 0xDE, 0x5E, 0x0B, 0xDB,
    0xE0, 0x32, 0x3A, 0x0A, 0x49, 0x06, 0x24, 0x5C, 0xC2, 0xD3, 0xAC, 0x62, 0x91, 0x95, 0xE4, 0x79,
    0xE7, 0xC8, 0x37, 0x6D, 0x8D, 0xD5, 0x4E, 0xA9, 0x6C, 0x56, 0xF4, 0xEA, 0x65, 0x7A, 0xAE, 0x08,
    0xBA, 0x78, 0x25, 0x2E, 0x1C, 0xA6, 0xB4, 0xC6, 0xE8, 0xDD, 0x74, 0x1F, 0x4B, 0xBD, 0x8B, 0x8A,
    0x70, 0x3E, 0xB5, 0x66, 0x48, 0x03, 0xF6, 0x0E, 0x61, 0x35, 0x57, 0xB9, 0x86, 0xC1, 0x1D, 0x9E,
    0xE1, 0xF8, 0x98, 0x11, 0x69, 0xD9, 0x8E, 0x94, 0x9B, 0x1E, 0x87, 0xE9, 0xCE, 0x55, 0x28, 0xDF,
    0x8C, 0xA1, 0x89, 0x0D, 0xBF, 0xE6, 0x42, 0x68, 0x41, 0x99, 0x2D, 0x0F, 0xB0, 0x54, 0xBB, 0x16,
]
RCON = [0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36]


def _xtime(a: int) -> int:
    return (((a << 1) ^ 0x1B) & 0xFF) if (a & 0x80) else (a << 1)


def _mix_single_column(a: List[int]) -> None:
    t = a[0] ^ a[1] ^ a[2] ^ a[3]
    u = a[0]
    a[0] ^= t ^ _xtime(a[0] ^ a[1])
    a[1] ^= t ^ _xtime(a[1] ^ a[2])
    a[2] ^= t ^ _xtime(a[2] ^ a[3])
    a[3] ^= t ^ _xtime(a[3] ^ u)


def _bytes2matrix(text: bytes) -> List[List[int]]:
    return [list(text[i:i + 4]) for i in range(0, len(text), 4)]


def _matrix2bytes(matrix: List[List[int]]) -> bytes:
    return bytes(sum(matrix, []))


def _xor_bytes(a: Iterable[int], b: Iterable[int]) -> bytes:
    return bytes(i ^ j for i, j in zip(a, b))


def _sub_word(word: List[int]) -> List[int]:
    return [SBOX[b] for b in word]


def _rot_word(word: List[int]) -> List[int]:
    return word[1:] + word[:1]


def _expand_key(master_key: bytes) -> List[List[List[int]]]:
    key_columns = _bytes2matrix(master_key)
    iteration_size = len(master_key) // 4
    i = 1
    while len(key_columns) < 44:
        word = list(key_columns[-1])
        if len(key_columns) % iteration_size == 0:
            word = _sub_word(_rot_word(word))
            word[0] ^= RCON[i]
            i += 1
        word = list(_xor_bytes(word, key_columns[-iteration_size]))
        key_columns.append(word)
    return [key_columns[4 * i:4 * (i + 1)] for i in range(11)]


def _add_round_key(s: List[List[int]], k: List[List[int]]) -> None:
    for i in range(4):
        for j in range(4):
            s[i][j] ^= k[i][j]


def _sub_bytes(s: List[List[int]]) -> None:
    for i in range(4):
        for j in range(4):
            s[i][j] = SBOX[s[i][j]]


def _shift_rows(s: List[List[int]]) -> None:
    s[0][1], s[1][1], s[2][1], s[3][1] = s[1][1], s[2][1], s[3][1], s[0][1]
    s[0][2], s[1][2], s[2][2], s[3][2] = s[2][2], s[3][2], s[0][2], s[1][2]
    s[0][3], s[1][3], s[2][3], s[3][3] = s[3][3], s[0][3], s[1][3], s[2][3]


def _mix_columns(s: List[List[int]]) -> None:
    for i in range(4):
        _mix_single_column(s[i])


def _encrypt_block(plaintext: bytes, round_keys: List[List[List[int]]]) -> bytes:
    state = _bytes2matrix(plaintext)
    _add_round_key(state, round_keys[0])
    for i in range(1, 10):
        _sub_bytes(state)
        _shift_rows(state)
        _mix_columns(state)
        _add_round_key(state, round_keys[i])
    _sub_bytes(state)
    _shift_rows(state)
    _add_round_key(state, round_keys[-1])
    return _matrix2bytes(state)


def aes_128_ecb_pkcs7_encrypt(data: bytes, key: bytes) -> bytes:
    pad = 16 - (len(data) % 16)
    data = data + bytes([pad]) * pad
    round_keys = _expand_key(key)
    out = bytearray()
    for i in range(0, len(data), 16):
        out.extend(_encrypt_block(data[i:i + 16], round_keys))
    return bytes(out)


# --- HTTP and parsing helpers ---------------------------------------------


def now() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg: str) -> None:
    print(f"[{now()}] {msg}", flush=True)


def decode_body(resp: urllib.response.addinfourl, body: bytes) -> bytes:
    encoding = resp.headers.get("Content-Encoding", "").lower()
    if "gzip" in encoding:
        return gzip.decompress(body)
    if "deflate" in encoding:
        try:
            return zlib.decompress(body)
        except zlib.error:
            return zlib.decompress(body, -zlib.MAX_WBITS)
    return body


def decode_text(body: bytes, content_type: str = "") -> str:
    if "gbk" in content_type.lower() or "gb2312" in content_type.lower():
        return body.decode("gbk", errors="replace")
    return body.decode("utf-8", errors="replace")


def resolve_url(base: str, maybe_url: str) -> str:
    return urllib.parse.urljoin(base, html.unescape(maybe_url))


def html_unescape(s: str) -> str:
    return html.unescape(s or "")


def parse_attrs(tag: str) -> Dict[str, str]:
    attrs: Dict[str, str] = {}
    for m in re.finditer(r'([A-Za-z_:][-A-Za-z0-9_:.]*)\s*=\s*("([^"]*)"|\'([^\']*)\'|([^\s>]+))', tag):
        attrs[m.group(1).lower()] = html_unescape(m.group(3) or m.group(4) or m.group(5) or "")
    return attrs


def parse_forms(text: str) -> List[Dict[str, object]]:
    forms: List[Dict[str, object]] = []
    for m in re.finditer(r"(?is)<form\b([^>]*)>(.*?)</form>", text):
        attrs = parse_attrs(m.group(1))
        inputs: Dict[str, str] = {}
        for im in re.finditer(r"(?is)<input\b([^>]*)>", m.group(2)):
            ia = parse_attrs(im.group(1))
            name = ia.get("name") or ia.get("id")
            if name:
                inputs[name] = ia.get("value", "")
        forms.append({"attrs": attrs, "inputs": inputs})
    return forms


def pick_form(text: str, form_id: Optional[str] = None) -> Dict[str, object]:
    forms = parse_forms(text)
    if not forms:
        raise IPTVError("no form found in HTML response")
    if form_id:
        for form in forms:
            attrs = form["attrs"]  # type: ignore[index]
            if attrs.get("id") == form_id or attrs.get("name") == form_id:
                return form
    return forms[0]


def js_var(text: str, name: str) -> str:
    m = re.search(rf"\bvar\s+{re.escape(name)}\s*=\s*(['\"])(.*?)\1", text, re.S)
    if not m:
        return ""
    return m.group(2)


def extract_top_location(text: str) -> str:
    m = re.search(r"top\.document\.location\s*=\s*(['\"])(.*?)\1", text, re.S)
    return html_unescape(m.group(2)) if m else ""


def extract_js_set_config(text: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for m in re.finditer(r"jsSetConfig\(\s*(['\"])(.*?)\1\s*,\s*(['\"])(.*?)\3", text, re.S):
        out[m.group(2)] = m.group(4)
    return out


def extract_channel_array(text: str) -> List[Dict[str, str]]:
    m = re.search(r"var\s+channelArray\s*=\s*\[(.*?)\]\s*;", text, re.S)
    if not m:
        return []
    raw = m.group(1)
    items = re.findall(r"'([^']*)'", raw)
    channels: List[Dict[str, str]] = []
    for item in items:
        data: Dict[str, str] = {}
        for k, v in re.findall(r'([A-Za-z0-9_]+)="(.*?)"', item):
            data[k] = html_unescape(v)
        if data:
            channels.append(data)
    return channels


def compact_name(name: str) -> str:
    n = name.strip()
    upper = n.upper()
    for suffix in ("HD", "4K"):
        if upper.endswith(suffix) and not upper.endswith("-4K"):
            n = n[: -len(suffix)].strip()
            break
    n = n.replace("(高清)", "").replace("（高清）", "").strip()
    return n or name


def fixed_tz8(ts_ms: int) -> str:
    tz = _dt.timezone(_dt.timedelta(hours=8))
    dt = _dt.datetime.fromtimestamp(ts_ms / 1000, tz)
    return dt.strftime("%Y%m%d%H%M%S +0800")


def display_time(ts_ms: int) -> str:
    tz = _dt.timezone(_dt.timedelta(hours=8))
    return _dt.datetime.fromtimestamp(ts_ms / 1000, tz).strftime("%m-%d %H:%M")


def as_int(value: object, default: int = 0) -> int:
    try:
        return int(str(value))
    except Exception:
        return default


def local_ip_for(host: str) -> str:
    target = host.split(":", 1)[0]
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((target, 7001))
        return s.getsockname()[0]
    finally:
        s.close()


def ip_for_auth(ip: str) -> str:
    return ",".join(f"{int(part):03d}" for part in ip.split("."))


def make_authenticator(encrytoken: str, user_id: str, sn: str, ip: str, mac: str) -> str:
    payload = {
        "Randon": f"{random.randint(0, 99999999):08d}",
        "EncryToken": encrytoken,
        "UserID": user_id,
        "SN": sn,
        "IP": ip_for_auth(ip),
        "MAC": mac,
        "MagicCode": "CTC",
        "UpdateTime": "20230301175307",
    }
    plain = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    key = hashlib.md5(b"123456").digest()
    return binascii.hexlify(aes_128_ecb_pkcs7_encrypt(plain, key)).decode("ascii")


def make_cookie(name: str, value: str, domain: str, path: str = "/") -> Cookie:
    return Cookie(
        version=0,
        name=name,
        value=value,
        port=None,
        port_specified=False,
        domain=domain.split(":", 1)[0],
        domain_specified=False,
        domain_initial_dot=False,
        path=path,
        path_specified=True,
        secure=False,
        expires=None,
        discard=True,
        comment=None,
        comment_url=None,
        rest={},
        rfc2109=False,
    )


class HTTP:
    def __init__(self, timeout: int = 20):
        self.cookiejar = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookiejar))
        self.timeout = timeout

    def request(
        self,
        method: str,
        url: str,
        data: Optional[Dict[str, str]] = None,
        referer: str = "",
        ua: str = AUTH_UA,
    ) -> Tuple[str, bytes, urllib.response.addinfourl]:
        headers = {
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,en-US;q=0.8",
            "Accept-Charset": "UTF-8",
            "X-Requested-With": "com.android.smart.terminal.ctsh.iptv",
        }
        if referer:
            headers["Referer"] = referer
        body = None
        if data is not None:
            body = urllib.parse.urlencode(data).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        req = urllib.request.Request(url, data=body, headers=headers, method=method.upper())
        try:
            resp = self.opener.open(req, timeout=self.timeout)
            raw = resp.read()
            body_bytes = decode_body(resp, raw)
            text = decode_text(body_bytes, resp.headers.get("Content-Type", ""))
            return text, body_bytes, resp
        except Exception as exc:
            raise IPTVError(f"{method.upper()} {url} failed: {exc}") from exc

    def get(self, url: str, **kw) -> Tuple[str, bytes, urllib.response.addinfourl]:
        return self.request("GET", url, None, **kw)

    def post(self, url: str, data: Dict[str, str], **kw) -> Tuple[str, bytes, urllib.response.addinfourl]:
        return self.request("POST", url, data, **kw)

    def set_cookie(self, name: str, value: str, host_url: str) -> None:
        parsed = urllib.parse.urlparse(host_url)
        self.cookiejar.set_cookie(make_cookie(name, value, parsed.netloc or parsed.path))


class IPTVClient:
    def __init__(self, user_id: str, sn: str, mac: str, auth_host: str, ip: str, timeout: int):
        self.user_id = user_id
        self.sn = sn
        self.mac = mac.upper()
        self.auth_host = auth_host
        self.ip = ip
        self.http = HTTP(timeout)
        self.dynamic_auth_ip = ""
        self.user_token = ""
        self.epg_group = ""
        self.epg_domain = ""
        self.epg_host_url = ""
        self.bims_token = ""
        self.bims_token_exp = ""

    def login(self) -> List[Dict[str, str]]:
        log(f"auth step 1 via {self.auth_host}, local IPTV IP {self.ip}")
        params = {
            "UserID": self.user_id,
            "Action": "Login",
            "SN": self.sn,
            "Type": "iptv4k",
            "Mode": "MENU.SMG-4K",
            "FCCSupport": "1",
        }
        url = f"http://{self.auth_host}/iptv3a/4kLogAuth.do?{urllib.parse.urlencode(params)}"
        text, _, _ = self.http.get(url)
        form = pick_form(text)
        attrs = form["attrs"]  # type: ignore[index]
        inputs = dict(form["inputs"])  # type: ignore[arg-type]
        self.dynamic_auth_ip = inputs.get("DynamicAuthIP", "")
        action = resolve_url(url, attrs.get("action", ""))

        log(f"auth step 2 dynamic host {urllib.parse.urlparse(action).netloc}")
        text, _, _ = self.http.post(action, inputs, referer=url)
        init_form = pick_form(text, "initform")
        init_attrs = init_form["attrs"]  # type: ignore[index]
        init_inputs = dict(init_form["inputs"])  # type: ignore[arg-type]
        encrytoken = js_var(text, "encrytoken")
        if not encrytoken:
            raise IPTVError("missing encrytoken in auth response")
        init_inputs["authenticator"] = make_authenticator(encrytoken, self.user_id, self.sn, self.ip, self.mac)
        ott_url = resolve_url(action, init_attrs.get("action", "/iptv3a/ottauth"))

        log("auth step 3 ottauth and channelArray")
        text, _, _ = self.http.post(ott_url, init_inputs, referer=action)
        self.user_token = js_var(text, "usertoken")
        self.epg_group = js_var(text, "epggroup") or "1060"
        epg_match = re.search(r"EPGDomain=([^\"']+)", text)
        self.epg_domain = epg_match.group(1).replace("\\/", "/") if epg_match else ""
        channels = extract_channel_array(text)
        if not self.user_token or not self.epg_domain:
            raise IPTVError("missing usertoken or EPGDomain after ottauth")
        log(f"got usertoken, epg_domain={self.epg_domain}, channelArray={len(channels)}")

        self._epg_login(ott_url)
        return channels

    def _epg_login(self, referer: str) -> None:
        log("EPG index login")
        data = {
            "UserID": self.user_id,
            "Action": "Login",
            "UserToken": self.user_token,
            "UserGroupNMB": "8888",
            "EPGGroupNMB": self.epg_group,
            "stbid": "0",
            "Mode": "MENU.SMG",
            "EPGProviderDomain": "",
            "DynamicAuthIP": self.dynamic_auth_ip,
        }
        text, _, _ = self.http.post(self.epg_domain, data, referer=referer)
        balanced = extract_top_location(text)
        if not balanced:
            raise IPTVError("missing balanced EPG URL")
        balanced = resolve_url(self.epg_domain, balanced)

        log(f"EPG load-balanced URL {balanced}")
        text, _, _ = self.http.get(balanced, referer=self.epg_domain)
        form = pick_form(text)
        attrs = form["attrs"]  # type: ignore[index]
        inputs = dict(form["inputs"])  # type: ignore[arg-type]
        inputs.setdefault("UserToken", self.user_token)
        inputs.setdefault("UserID", self.user_id)
        inputs.setdefault("STBID", "0")
        inputs.setdefault("stbinfo", "")
        inputs.setdefault("prmid", "")
        inputs.setdefault("stbtype", "")
        inputs.setdefault("drmsupplier", "")

        parsed_balanced = urllib.parse.urlparse(balanced)
        qs = urllib.parse.parse_qs(parsed_balanced.query)
        inputs.setdefault("easip", (qs.get("easip") or [""])[0])
        inputs.setdefault("networkid", (qs.get("networkid") or ["1"])[0])
        auth_url = resolve_url(balanced, attrs.get("action", "funcportalauth.jsp"))

        log("EPG portal auth")
        text, _, _ = self.http.post(auth_url, inputs, referer=balanced)
        info = extract_js_set_config(text)
        session_id = info.get("SessionID")
        framecode = info.get("framecode")
        ipport = info.get("IpPort")
        if not (session_id and framecode and ipport):
            raise IPTVError(f"missing EPG session fields: {info}")
        self.epg_host_url = f"http://{ipport}/iptvepg/{framecode}"
        self.http.set_cookie("JSESSIONID", session_id, self.epg_host_url)
        log(f"EPG session ready {self.epg_host_url}")

        try:
            self.http.get(f"{self.epg_host_url}/portal.jsp", referer=auth_url)
        except IPTVError:
            pass
        self._bims_auth()

    def _bims_auth(self) -> None:
        url = f"{self.epg_host_url}/service/auth/AuthByAjax.jsp?action=auth"
        log("BIMS auth")
        try:
            text, _, _ = self.http.get(url, referer=f"{self.epg_host_url}/function/auth/bimsPortalAuth.html?jumpUrl=epgEntry.jsp")
            data = json.loads(text.strip())
        except Exception as exc:
            log(f"BIMS auth skipped: {exc}")
            return
        self.bims_token = data.get("bimsUserToken", "")
        self.bims_token_exp = data.get("bimsTokenExp", "")
        if self.bims_token:
            self.http.set_cookie("bims_user_token", self.bims_token, self.epg_host_url)
            self.http.set_cookie("BimsAuthenticationFlag", "SUCCESS", self.epg_host_url)
        if self.bims_token_exp:
            self.http.set_cookie("bims_token_exp", self.bims_token_exp, self.epg_host_url)
        self.http.set_cookie("PRE_ADVERTISEMENT_FLAG", "1", self.epg_host_url)

    def post_ajax(self, data: Dict[str, str], referer: str = "") -> Dict[str, object]:
        url = f"{self.epg_host_url}/function/ajax/epg7getChannelByAjax.jsp"
        text, _, _ = self.http.post(url, data, referer=referer or f"{self.epg_host_url}/portal.jsp")
        stripped = text.strip()
        try:
            return json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise IPTVError(f"bad ajax JSON for {data}: {stripped[:200]}") from exc

    def fetch_channel_infos(self, categories: Iterable[Tuple[str, str]]) -> List[Dict[str, object]]:
        by_mix: Dict[str, Dict[str, object]] = {}
        for cate, ctype in categories:
            payload = {"action": "getChannelList", "cateID": cate}
            if ctype:
                payload["type"] = ctype
            else:
                payload["type"] = ""
            try:
                resp = self.post_ajax(payload)
            except IPTVError as exc:
                log(f"category {cate}/{ctype or '-'} failed: {exc}")
                continue
            data = resp.get("data") or []
            if not isinstance(data, list):
                data = []
            added = 0
            for ch in data:
                if not isinstance(ch, dict):
                    continue
                mix = str(ch.get("mixNo") or "")
                if not mix:
                    continue
                ch["commName"] = compact_name(str(ch.get("name") or ""))
                old = by_mix.get(mix)
                if old is None or _prefer_channel_info(ch, old):
                    by_mix[mix] = ch
                    added += 1
            log(f"category {cate}/{ctype or '-'} returned {len(data)} channels, merged {added}")
            time.sleep(0.2)
        channels = sorted(by_mix.values(), key=lambda x: int(str(x.get("mixNo") or "999999")) if str(x.get("mixNo") or "").isdigit() else 999999)
        return channels

    def fetch_programs(self, channels: Iterable[Dict[str, object]], days_back: int, days_forward: int) -> Dict[str, List[Dict[str, object]]]:
        now_ms = int(time.time() * 1000)
        start_ms = now_ms - days_back * 86400 * 1000
        end_ms = now_ms + days_forward * 86400 * 1000
        out: Dict[str, List[Dict[str, object]]] = {}
        for idx, ch in enumerate(channels, 1):
            mix = str(ch.get("mixNo") or "")
            code = str(ch.get("code") or "")
            chid = str(ch.get("ID") or "")
            name = str(ch.get("commName") or ch.get("name") or mix)
            if not (mix and code and chid):
                continue
            payload = {
                "action": "getChannelProg",
                "code": code,
                "channelID": chid,
                "endTime": str(end_ms),
                "startTime": str(start_ms),
                "offset": "0",
                "limit": "2000",
            }
            try:
                resp = self.post_ajax(payload)
                data = resp.get("data") or []
                if not isinstance(data, list):
                    data = []
                out[mix] = [p for p in data if isinstance(p, dict)]
                log(f"EPG {idx}: {name} {len(out[mix])} programmes")
            except IPTVError as exc:
                log(f"EPG {idx}: {name} failed: {exc}")
            time.sleep(0.35)
        return out

    def fetch_tvod_play_urls(
        self,
        channels: Iterable[Dict[str, object]],
        programs: Dict[str, List[Dict[str, object]]],
        replay_hours: int,
    ) -> Dict[str, List[Dict[str, object]]]:
        now_ms = int(time.time() * 1000)
        min_ms = 0 if replay_hours <= 0 else now_ms - replay_hours * 3600 * 1000
        out: Dict[str, List[Dict[str, object]]] = {}
        total = 0
        resolved = 0
        for idx, ch in enumerate(channels, 1):
            mix = str(ch.get("mixNo") or "")
            chid = str(ch.get("ID") or "")
            name = str(ch.get("commName") or ch.get("name") or mix)
            if not (mix and chid):
                continue
            rows: List[Dict[str, object]] = []
            candidates = 0
            for prog in programs.get(mix, []):
                start_ms = as_int(prog.get("startTime"))
                end_ms = as_int(prog.get("endTime"))
                playbill_id = str(prog.get("ID") or "")
                if not (start_ms and end_ms and playbill_id):
                    continue
                if start_ms >= now_ms or end_ms <= min_ms:
                    continue
                candidates += 1
                total += 1
                payload = {
                    "action": "getTvodPlayUrl",
                    "channelID": chid,
                    "playbillID": playbill_id,
                    "startTime": str(start_ms // 1000),
                    "endTime": str(end_ms // 1000),
                }
                referer = (
                    f"{self.epg_host_url}/IPM/modules/channel/play_pro.html?"
                    f"mixNo={urllib.parse.quote(mix)}&channelID={urllib.parse.quote(chid)}&"
                    f"proid={urllib.parse.quote(playbill_id)}&startTime={start_ms}&cate1=000405"
                )
                try:
                    resp = self.post_ajax(payload, referer=referer)
                except IPTVError as exc:
                    log(f"Replay {idx}: {name} {playbill_id} failed: {exc}")
                    time.sleep(0.2)
                    continue
                data = resp.get("data") or {}
                play_url = ""
                if isinstance(data, dict):
                    play_url = html_unescape(str(data.get("playURL") or ""))
                if play_url:
                    row = dict(prog)
                    row["playURL"] = play_url
                    rows.append(row)
                    resolved += 1
                time.sleep(0.2)
            if rows:
                out[mix] = rows
            if candidates:
                log(f"Replay {idx}: {name} {len(rows)}/{candidates} play URLs")
        log(f"Replay resolved {resolved}/{total} play URLs")
        return out


def _prefer_channel_info(new: Dict[str, object], old: Dict[str, object]) -> bool:
    new_name = str(new.get("name") or "").upper()
    old_name = str(old.get("name") or "").upper()
    if "4K" in new_name and "4K" not in old_name:
        return True
    if "HD" in new_name and "HD" not in old_name:
        return True
    if str(old.get("isCharge") or "0") == "1" and str(new.get("isCharge") or "0") == "0":
        return True
    return False


def merge_channels(
    auth_channels: List[Dict[str, str]],
    infos: List[Dict[str, object]],
) -> List[Dict[str, object]]:
    by_mix_auth = {str(ch.get("UserChannelID") or ""): ch for ch in auth_channels}
    merged: List[Dict[str, object]] = []
    for info in infos:
        mix = str(info.get("mixNo") or "")
        auth = by_mix_auth.get(mix, {})
        row: Dict[str, object] = {}
        row.update(auth)
        row.update(info)
        row["mixNo"] = mix
        row["name"] = str(info.get("name") or auth.get("UserChannelID") or mix)
        row["commName"] = str(info.get("commName") or compact_name(str(row["name"])))
        row["ChannelURL"] = auth.get("ChannelURL", "")
        row["TimeShiftURL"] = auth.get("TimeShiftURL", "")
        merged.append(row)
    return merged


def stream_url(raw_url: str, url_mode: str, udpxy: str) -> str:
    if not raw_url:
        return ""
    parsed = urllib.parse.urlparse(raw_url)
    host = parsed.netloc or parsed.path
    if udpxy:
        return f"http://{udpxy.rstrip('/')}/udp/{host}"
    if url_mode == "original":
        return raw_url
    if url_mode == "rtp":
        return f"rtp://@{host}"
    return f"udp://@{host}"


def raw_timeshift_catchup_url(timeshift_url: str, catchup_template: str) -> str:
    if not timeshift_url or timeshift_url.lower() == "null":
        return ""
    parsed = urllib.parse.urlparse(timeshift_url)
    if parsed.scheme.lower() != "rtsp" or not parsed.hostname:
        return ""
    seek = catchup_template.strip()
    if not seek:
        return ""
    query = f"{parsed.query}&{seek}" if parsed.query else seek
    return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", query, ""))


def parse_multicast_endpoint(raw_url: str) -> str:
    """从原始组播地址里解析出 'ip:port' 部分，失败返回空字符串。

    供各 m3u 生成函数共用，避免对拼好的 URL 做字符串替换。
    """
    if not raw_url:
        return ""
    parsed = urllib.parse.urlparse(raw_url)
    endpoint = (parsed.netloc or parsed.path).strip().lstrip("@")
    if not endpoint or endpoint.lower() == "null":
        return ""
    return endpoint


def rtp2httpd_live_url(raw_url: str, base_url: str, fcc_postfix: str = "") -> str:
    endpoint = parse_multicast_endpoint(raw_url)
    if not endpoint:
        return ""
    return f"{base_url.rstrip('/')}/rtp/{endpoint}{fcc_postfix}"


def rtp_raw_live_url(raw_url: str, fcc_postfix: str = "") -> str:
    """裸组播播放地址：rtp://ip:port，可选拼接 FCC 后缀。"""
    endpoint = parse_multicast_endpoint(raw_url)
    if not endpoint:
        return ""
    return f"rtp://{endpoint}{fcc_postfix}"


def load_logo_map(path: Path) -> Dict[str, str]:
    """加载台标配置（JSON：播放源频道名 -> logo 文件名）。失败返回空表。"""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as exc:
        log(f"logo 配置加载失败（{path}），将跳过台标：{exc}")
        return {}
    if not isinstance(data, dict):
        log(f"logo 配置格式错误（{path}），将跳过台标")
        return {}
    return {str(k): str(v or "") for k, v in data.items()}


def logo_url_for(name: str, logo_map: Dict[str, str], base_url: str) -> str:
    """按播放源频道名查台标，返回完整 URL；没有则返回空字符串。"""
    filename = logo_map.get(name, "")
    if not filename:
        return ""
    return f"{base_url.rstrip('/')}/{filename}"


def extinf_attrs(
    tvg_id: str,
    tvg_name: str,
    group: str,
    logo_url: str,
    catchup_days: str,
    catchup_url: str = "",
) -> List[str]:
    """拼 EXTINF 的属性部分。没有台标 / 没有回放地址时对应属性直接省略。"""
    attrs = [
        f'tvg-id="{tvg_id}"',
        f'tvg-name="{tvg_name}"',
        f'group-title="{group}"',
    ]
    if logo_url:
        attrs.append(f'tvg-logo="{logo_url}"')
    if catchup_url:
        attrs.extend([
            'catchup="default"',
            f'catchup-days="{catchup_days}"',
            f'catchup-source="{catchup_url}"',
        ])
    return attrs


def rtp2httpd_rtsp_catchup_url(timeshift_url: str, base_url: str, catchup_template: str) -> str:
    if not timeshift_url or timeshift_url.lower() == "null":
        return ""
    parsed = urllib.parse.urlparse(timeshift_url)
    if parsed.scheme.lower() != "rtsp" or not parsed.hostname:
        return ""
    netloc = parsed.netloc
    if parsed.port is None and "@" not in netloc:
        netloc = f"{parsed.hostname}:554"
    seek = catchup_template.strip()
    if not seek:
        return ""
    query = f"{parsed.query}&{seek}" if parsed.query else seek
    return f"{base_url.rstrip('/')}/rtsp/{netloc}{parsed.path}?{query}"


# 上海频道关键词（使用播放源返回的频道名）。命中任一关键词，
# 或名字里含有“上海”/“东方”的频道，全部归入“上海”组。
# 注：游戏风云/法治天地/金色学堂名字里不含上海、东方，故显式列出。
SHANGHAI_KEYWORDS = (
    "新闻综合",
    "东方卫视",
    "生活时尚",
    "都市剧场",
    "都市频道",
    "东方影视",
    "体育频道",
    "第一财经",
    "东方财经",
    "上海教育",
    "游戏风云",
    "法治天地",
    "金色学堂",
)


def is_shanghai_channel(name: str) -> bool:
    if any(keyword in name for keyword in SHANGHAI_KEYWORDS):
        return True
    return "上海" in name or "东方" in name


def group_for(name: str) -> str:
    if is_shanghai_channel(name):
        return "上海"
    if "CCTV" in name.upper() or "央视" in name:
        return "央视"
    if "卫视" in name:
        return "卫视"
    if "购物" in name:
        return "购物"
    if "4K" in name.upper():
        return "4K"
    if "HD" in name.upper() or "高清" in name:
        return "高清"
    return "其他"


def write_m3u(
    path: Path,
    channels: List[Dict[str, object]],
    url_mode: str,
    udpxy: str,
    epg_url: str,
    catchup_days: str,
    catchup_template: str,
    logo_map: Dict[str, str],
    logo_base_url: str,
) -> None:
    lines = [f'#EXTM3U x-tvg-url="{epg_url}"' if epg_url else "#EXTM3U"]
    service_counts: Dict[Tuple[str, str], int] = {}
    for ch in channels:
        name = str(ch.get("commName") or ch.get("name") or ch.get("mixNo") or "")
        mix = str(ch.get("mixNo") or "")
        raw_url = str(ch.get("ChannelURL") or "")
        url = stream_url(raw_url, url_mode, udpxy)
        if not url:
            continue
        group = group_for(str(ch.get("name") or name))
        key = (group, name)
        service_counts[key] = service_counts.get(key, 0) + 1
        catchup_url = raw_timeshift_catchup_url(str(ch.get("TimeShiftURL") or ""), catchup_template)
        logo_url = logo_url_for(name, logo_map, logo_base_url)
        attrs = extinf_attrs(mix, name, group, logo_url, catchup_days, catchup_url)
        lines.append(f'#EXTINF:-1 {" ".join(attrs)},{name}')
        lines.append(url)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_rtp2httpd_m3u(
    path: Path,
    channels: List[Dict[str, object]],
    epg_url: str,
    base_url: str,
    catchup_days: str,
    catchup_template: str,
    fcc_postfix: str,
    logo_map: Dict[str, str],
    logo_base_url: str,
    include_catchup: bool = True,
) -> None:
    """rtp2httpd 版 m3u。

    include_catchup=False 时去掉全部回放信息（simp 版），
    其余（FCC 后缀、台标、分组）与完整版一致，可长期使用。
    """
    lines = [f'#EXTM3U x-tvg-url="{epg_url}"' if epg_url else "#EXTM3U"]
    for ch in channels:
        name = str(ch.get("commName") or ch.get("name") or ch.get("mixNo") or "")
        mix = str(ch.get("mixNo") or "")
        url = rtp2httpd_live_url(str(ch.get("ChannelURL") or ""), base_url, fcc_postfix)
        if not url:
            continue
        group = group_for(str(ch.get("name") or name))
        catchup_url = ""
        if include_catchup:
            catchup_url = rtp2httpd_rtsp_catchup_url(
                str(ch.get("TimeShiftURL") or ""),
                base_url,
                catchup_template,
            )
        logo_url = logo_url_for(name, logo_map, logo_base_url)
        attrs = extinf_attrs(mix, name, group, logo_url, catchup_days, catchup_url)
        lines.append(f'#EXTINF:-1 {" ".join(attrs)},{name}')
        lines.append(url)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_m3u_raw(
    path: Path,
    channels: List[Dict[str, object]],
    epg_url: str,
    logo_map: Dict[str, str],
    logo_base_url: str,
) -> None:
    """裸组播地址版 m3u：rtp://ip:port 直连，不带回放信息。"""
    lines = [f'#EXTM3U x-tvg-url="{epg_url}"' if epg_url else "#EXTM3U"]
    for ch in channels:
        name = str(ch.get("commName") or ch.get("name") or ch.get("mixNo") or "")
        mix = str(ch.get("mixNo") or "")
        url = rtp_raw_live_url(str(ch.get("ChannelURL") or ""))
        if not url:
            continue
        group = group_for(str(ch.get("name") or name))
        logo_url = logo_url_for(name, logo_map, logo_base_url)
        attrs = extinf_attrs(mix, name, group, logo_url, "")
        lines.append(f'#EXTINF:-1 {" ".join(attrs)},{name}')
        lines.append(url)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_rtp2httpd_m3u_raw(
    path: Path,
    channels: List[Dict[str, object]],
    epg_url: str,
    fcc_postfix: str,
    catchup_days: str,
    catchup_template: str,
    logo_map: Dict[str, str],
    logo_base_url: str,
) -> None:
    """rtp2httpd 的裸地址版：rtp://ip:port 直连 + FCC 后缀，回放用 rtsp 直连地址。"""
    lines = [f'#EXTM3U x-tvg-url="{epg_url}"' if epg_url else "#EXTM3U"]
    for ch in channels:
        name = str(ch.get("commName") or ch.get("name") or ch.get("mixNo") or "")
        mix = str(ch.get("mixNo") or "")
        url = rtp_raw_live_url(str(ch.get("ChannelURL") or ""), fcc_postfix)
        if not url:
            continue
        group = group_for(str(ch.get("name") or name))
        catchup_url = raw_timeshift_catchup_url(str(ch.get("TimeShiftURL") or ""), catchup_template)
        logo_url = logo_url_for(name, logo_map, logo_base_url)
        attrs = extinf_attrs(mix, name, group, logo_url, catchup_days, catchup_url)
        lines.append(f'#EXTINF:-1 {" ".join(attrs)},{name}')
        lines.append(url)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_xmltv(path: Path, channels: List[Dict[str, object]], programs: Dict[str, List[Dict[str, object]]]) -> None:
    out = ['<?xml version="1.0" encoding="UTF-8"?>']
    gen = f"sh-tel-iptv-openwrt {now()}"
    out.append(f'<tv generator-info-name="{xml_escape(gen)}" source-info-name="Shanghai Telecom IPTV">')
    for ch in channels:
        mix = str(ch.get("mixNo") or "")
        name = str(ch.get("commName") or ch.get("name") or mix)
        if mix:
            out.append(f'  <channel id="{xml_escape(mix)}">')
            out.append(f'    <display-name lang="zh">{xml_escape(name)}</display-name>')
            out.append("  </channel>")
    for ch in channels:
        mix = str(ch.get("mixNo") or "")
        for p in programs.get(mix, []):
            try:
                start = fixed_tz8(int(p.get("startTime") or 0))
                stop = fixed_tz8(int(p.get("endTime") or 0))
            except Exception:
                continue
            title = str(p.get("name") or "")
            out.append(f'  <programme start="{start}" stop="{stop}" channel="{xml_escape(mix)}">')
            out.append(f'    <title lang="zh">{xml_escape(title)}</title>')
            out.append('    <desc lang="zh"></desc>')
            out.append("  </programme>")
    out.append("</tv>")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def parse_categories(value: str) -> List[Tuple[str, str]]:
    if not value:
        return list(DEFAULT_CATEGORIES)
    out: List[Tuple[str, str]] = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            cate, ctype = part.split(":", 1)
            out.append((cate.strip(), ctype.strip()))
        else:
            out.append((part, ""))
    return out


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="抓取上海电信 IPTV 频道列表和 XMLTV 节目单。")
    p.add_argument("--user-id", default=DEFAULT_USER_ID, help="IPTV 账号，通常是数字@etv1。")
    p.add_argument("--sn", default=DEFAULT_SN, help="IPTV 盒子的 SN/序列号。")
    p.add_argument("--mac", default=DEFAULT_MAC, help="IPTV 盒子的 MAC 地址。")
    p.add_argument(
        "--ip",
        default=DEFAULT_IP,
        help="本机在 IPTV 专网侧使用的地址；留空时自动探测。",
    )
    p.add_argument("--auth-host", default=DEFAULT_AUTH_HOST, help="上海电信 IPTV 认证服务器。")
    p.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="输出目录，默认是脚本所在目录。")
    p.add_argument(
        "--days-back",
        type=int,
        default=int(DEFAULT_CATCHUP_DAYS),
        help="抓取过去多少天的节目单。",
    )
    p.add_argument(
        "--days-forward",
        type=int,
        default=DEFAULT_DAYS_FORWARD,
        help="抓取未来多少天的节目单。",
    )
    p.add_argument(
        "--categories",
        default=DEFAULT_CATEGORIES_TEXT,
        help="频道栏目列表，逗号分隔，可写 cate:type，例如 000406,000404:tvod。",
    )
    p.add_argument(
        "--url-mode",
        choices=("udp", "rtp", "original"),
        default=DEFAULT_URL_MODE,
        help="未使用 udpxy 时的直播地址格式。",
    )
    p.add_argument("--udpxy", default=DEFAULT_UDPXY, help="爱快/udpxy 地址，用于 shctiptv.m3u。")
    p.add_argument("--rtp2httpd-url", default=DEFAULT_RTP2HTTPD_URL, help="rtp2httpd 地址，用于 shctiptv2.m3u。")
    p.add_argument("--fcc-postfix", default=DEFAULT_FCC_POSTFIX, help="拼到 rtp2httpd 版 m3u 播放地址后的 FCC 后缀。")
    p.add_argument("--m3u-raw", default=M3U_RAW_FILENAME, help="裸组播地址版 m3u 的文件名。")
    p.add_argument("--m3u-rtp2httpd-raw", default=RTP2HTTPD_RAW_M3U_FILENAME, help="rtp2httpd 裸地址版 m3u 的文件名。")
    p.add_argument("--m3u-rtp2httpd-simp", default=RTP2HTTPD_SIMP_M3U_FILENAME, help="rtp2httpd 简版 m3u 的文件名（无回放信息）。")
    p.add_argument("--logo-config", default=LOGO_CONFIG_FILENAME, help="台标配置文件（JSON），相对路径按脚本所在目录解析。")
    p.add_argument("--logo-base-url", default=DEFAULT_LOGO_BASE_URL, help="台标 CDN 基础地址。")
    p.add_argument("--catchup-days", default=DEFAULT_CATCHUP_DAYS, help="写入 M3U 的 catchup-days 标记。")
    p.add_argument("--catchup-template", default=DEFAULT_CATCHUP_TEMPLATE, help="追加到 TimeShiftURL 的回放 playseek 模板。")
    p.add_argument("--epg-url", default=DEFAULT_EPG_URL, help="写入 M3U x-tvg-url 的节目单公网/内网访问地址。")
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="HTTP 请求超时时间。")
    p.add_argument("--skip-epg", action="store_true", help="只生成频道列表，不抓取节目单。")
    rtp2httpd = p.add_mutually_exclusive_group()
    rtp2httpd.add_argument(
        "--write-rtp2httpd-m3u",
        dest="write_rtp2httpd_m3u",
        action="store_true",
        default=DEFAULT_WRITE_RTP2HTTPD_M3U,
        help="生成 rtp2httpd 版 shctiptv2.m3u。",
    )
    rtp2httpd.add_argument(
        "--skip-rtp2httpd-m3u",
        dest="write_rtp2httpd_m3u",
        action="store_false",
        help="不生成 rtp2httpd 版 shctiptv2.m3u。",
    )
    return p


def validate_args(args: argparse.Namespace) -> None:
    required = [
        ("DEFAULT_USER_ID 或 --user-id", args.user_id),
        ("DEFAULT_SN 或 --sn", args.sn),
        ("DEFAULT_MAC 或 --mac", args.mac),
    ]
    missing = [name for name, value in required if not str(value).strip()]
    if missing:
        raise IPTVError(
            "缺少上海电信配置："
            + ", ".join(missing)
            + "。请在脚本顶部“用户可配置项”区域填写，或运行时传入命令行参数。"
        )


def main() -> int:
    args = build_arg_parser().parse_args()
    validate_args(args)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    ip = args.ip.strip()
    if not ip:
        ip = local_ip_for(args.auth_host)

    client = IPTVClient(args.user_id, args.sn, args.mac, args.auth_host, ip, args.timeout)
    auth_channels = client.login()
    channel_infos = client.fetch_channel_infos(parse_categories(args.categories))
    merged = merge_channels(auth_channels, channel_infos)
    if not merged:
        raise IPTVError("no channels fetched")

    programs: Dict[str, List[Dict[str, object]]] = {}
    if not args.skip_epg:
        programs = client.fetch_programs(merged, max(args.days_back, 0), max(args.days_forward, 0))

    logo_config_path = Path(args.logo_config)
    if not logo_config_path.is_absolute():
        logo_config_path = SCRIPT_DIR / logo_config_path
    logo_map = load_logo_map(logo_config_path)
    if logo_map:
        log(f"logo 配置已加载：{len(logo_map)} 个频道")

    m3u_path = output_dir / M3U_FILENAME
    rtp2httpd_m3u_path = output_dir / RTP2HTTPD_M3U_FILENAME
    m3u_raw_path = output_dir / args.m3u_raw
    rtp2httpd_raw_m3u_path = output_dir / args.m3u_rtp2httpd_raw
    rtp2httpd_simp_m3u_path = output_dir / args.m3u_rtp2httpd_simp
    epg_path = output_dir / EPG_FILENAME
    write_m3u(
        m3u_path,
        merged,
        args.url_mode,
        args.udpxy,
        args.epg_url,
        args.catchup_days,
        args.catchup_template,
        logo_map,
        args.logo_base_url,
    )
    write_m3u_raw(
        m3u_raw_path,
        merged,
        args.epg_url,
        logo_map,
        args.logo_base_url,
    )
    if args.write_rtp2httpd_m3u:
        write_rtp2httpd_m3u(
            rtp2httpd_m3u_path,
            merged,
            args.epg_url,
            args.rtp2httpd_url,
            args.catchup_days,
            args.catchup_template,
            args.fcc_postfix,
            logo_map,
            args.logo_base_url,
        )
        write_rtp2httpd_m3u_raw(
            rtp2httpd_raw_m3u_path,
            merged,
            args.epg_url,
            args.fcc_postfix,
            args.catchup_days,
            args.catchup_template,
            logo_map,
            args.logo_base_url,
        )
        write_rtp2httpd_m3u(
            rtp2httpd_simp_m3u_path,
            merged,
            args.epg_url,
            args.rtp2httpd_url,
            args.catchup_days,
            args.catchup_template,
            args.fcc_postfix,
            logo_map,
            args.logo_base_url,
            include_catchup=False,
        )

    write_xmltv(epg_path, merged, programs)

    log(f"done: {len(merged)} channels -> {m3u_path}")
    log(f"done: {len(merged)} raw channels -> {m3u_raw_path}")
    if args.write_rtp2httpd_m3u:
        log(f"done: {len(merged)} rtp2httpd channels -> {rtp2httpd_m3u_path}")
        log(f"done: {len(merged)} rtp2httpd raw channels -> {rtp2httpd_raw_m3u_path}")
        log(f"done: {len(merged)} rtp2httpd simp channels -> {rtp2httpd_simp_m3u_path}")
    else:
        log("skip: rtp2httpd M3U disabled")
    log(f"done: {sum(len(v) for v in programs.values())} programmes -> {epg_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
