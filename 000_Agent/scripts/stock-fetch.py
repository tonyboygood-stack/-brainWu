#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
個股資料蒐集器
==============

把一檔股票所有「不需要登入、不需要驗證碼」的公開資料一次抓齊，
整理成一份 markdown 資料表，供後續分析使用。

用法：
  python stock-fetch.py 1786
  python stock-fetch.py 1786 --days 30      # 三大法人抓 30 個交易日
  python stock-fetch.py 1786 --no-cache     # 強制重新下載

產出：
  600_Projects/投資/個股/_data/<代號>.md

需要人工處理的來源（本腳本不涵蓋，見 資料蒐集SOP.md）：
  - 證交所買賣日報表（分點進出）→ 有圖形驗證碼
  - MOPS 法說會 → 查詢參數為加密字串，無法組出
  - Goodinfo、M平方 → 擋自動請求
  - CMoney 籌碼K線（集中度／買賣家數差／外資成本線）→ 需註冊登入
"""

import argparse
import csv
import io
import json
import ssl
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

VAULT = Path(r"C:\Users\user\Documents\GitHub\-")
OUT_DIR = VAULT / "600_Projects" / "投資" / "個股" / "_data"
CACHE_DIR = Path(r"C:\Users\user\.config\stock-data\cache")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

# TDCC 集保持股分級：級距 12 以上為 400 張（40 萬股）以上，15 為 1000 張以上
TDCC_BIG = {"12", "13", "14", "15"}
TDCC_HUGE = {"15"}
TDCC_LABEL = {
    "12": "400~600張", "13": "600~800張", "14": "800~1000張",
    "15": ">1000張", "17": "合計",
}


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def fetch(url, cache_key=None, use_cache=True, timeout=90):
    """抓網頁，可選擇性快取（大檔案如集保 CSV 一天只需抓一次）。"""
    if cache_key and use_cache:
        cf = CACHE_DIR / f"{datetime.now():%Y%m%d}_{cache_key}"
        if cf.exists() and cf.stat().st_size > 0:
            return cf.read_bytes()
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    data = urllib.request.urlopen(req, timeout=timeout, context=CTX).read()
    if cache_key:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (CACHE_DIR / f"{datetime.now():%Y%m%d}_{cache_key}").write_bytes(data)
    return data


def fetch_json(url, **kw):
    return json.loads(fetch(url, **kw).decode("utf-8", "replace"))


# ---------------------------------------------------------------- 市場別

# 上市走證交所，上櫃走櫃買中心。兩邊的端點與欄位名稱都不一樣。
TWSE_API = {
    "基本資料": "https://openapi.twse.com.tw/v1/opendata/t187ap03_L",
    "月營收": "https://openapi.twse.com.tw/v1/opendata/t187ap05_L",
    "綜合損益": "https://openapi.twse.com.tw/v1/opendata/t187ap06_L_ci",
    "資產負債": "https://openapi.twse.com.tw/v1/opendata/t187ap07_L_ci",
    "營益分析": "https://openapi.twse.com.tw/v1/opendata/t187ap17_L",
}
TPEX_API = {
    "基本資料": "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O",
    "月營收": "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap05_O",
    "綜合損益": "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap06_O_ci",
    "資產負債": "https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap07_O_ci",
    # 櫃買沒有對應的營益分析端點
}
# 上櫃的資料表混用中英文欄位名當作代號欄
CODE_FIELDS = ("公司代號", "SecuritiesCompanyCode", "證券代號")


def row_code(r):
    for f in CODE_FIELDS:
        if f in r:
            return str(r[f]).strip()
    return ""


def detect_market(code, use_cache=True):
    """判斷是上市還是上櫃。回傳 'sii' 或 'otc'，查不到回 None。"""
    try:
        rows = fetch_json(TWSE_API["基本資料"],
                          cache_key="openapi_t187ap03_L.json", use_cache=use_cache)
        if any(row_code(r) == code for r in rows):
            return "sii"
    except Exception:  # noqa: BLE001
        pass
    try:
        rows = fetch_json(TPEX_API["基本資料"],
                          cache_key="tpex_t187ap03_O.json", use_cache=use_cache)
        if any(row_code(r) == code for r in rows):
            return "otc"
    except Exception:  # noqa: BLE001
        pass
    return None


def get_openapi(code, market, use_cache=True):
    """公司基本資料、月營收、財報。全市場檔案，抓下來過濾。"""
    table = TWSE_API if market == "sii" else TPEX_API
    prefix = "openapi" if market == "sii" else "tpex"
    out = {}
    for name, url in table.items():
        try:
            rows = fetch_json(url, cache_key=f"{prefix}_{name}.json", use_cache=use_cache)
            hit = [r for r in rows if row_code(r) == code]
            out[name] = hit[0] if hit else None
            log(f"  {name}: {'✓' if hit else '無資料'}")
        except Exception as e:  # noqa: BLE001
            out[name] = None
            log(f"  {name}: ✗ {e}")
    return out


# ---------------------------------------------------------------- 股利與 EPS

def get_dividends(code):
    """歷年 EPS 與現金股利。

    來源是神秘金字塔的個股頁面——資料嵌在 Highcharts 的設定裡，
    一次就能拿到十幾年的序列，上市上櫃通吃，比逐年查證交所有效率。

    宏爺特別重視「歷年股息是否持續增加」，那是他不怕套牢的底氣，
    所以這份資料的權重很高。
    """
    import re
    url = f"https://norway.twsthr.info/StockHolders.aspx?stock={code}"
    try:
        html = fetch(url, timeout=60).decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        log(f"  股利歷史: ✗ {e}")
        return []

    def series(name):
        m = re.search(r"data:\s*\[([^\]]*)\][^}]*?name:\s*'" + name + r"'", html)
        if not m:
            return []
        return [float(x) for x in re.findall(r"-?\d+\.?\d*", m.group(1))]

    # 頁面上有兩張 Highcharts：股權分散圖的 categories 是 '2021-09' 這種年月，
    # 股利圖才是四位數年份。所以要掃過所有 categories，挑年份那一組。
    years = []
    for block in re.findall(r"categories:\s*\[([^\]]*)\]", html):
        cand = re.findall(r"'(\d{4})'", block)
        if len(cand) >= 5:
            years = cand
            break
    eps = series("EPS\\(元\\)")
    cash = series("現金股利\\(元\\)")
    stock_div = series("盈餘配股\\(元\\)")
    if not years or not eps:
        log("  股利歷史: 找不到資料（網站結構可能已改版）")
        return []

    out = []
    for i, y in enumerate(years):
        out.append({
            "year": y,
            "eps": eps[i] if i < len(eps) else None,
            "cash": cash[i] if i < len(cash) else None,
            "stock": stock_div[i] if i < len(stock_div) else None,
        })
    log(f"  股利歷史: {len(out)} 個年度")
    return out


# ---------------------------------------------------------------- 股價

def get_daily(code, market, months=14, use_cache=True):
    """個股日成交，逐月抓。上市走證交所，上櫃走櫃買中心。

    兩邊的欄位順序不同：
      證交所 STOCK_DAY  → [日期, 成交股數, 成交金額, 開, 高, 低, 收, 漲跌, 筆數]
      櫃買 tradingStock → [日期, 成交張數, 成交仟元, 開, 高, 低, 收, 漲跌, 筆數]
    另外櫃買的量單位是「張」，這裡統一換算成股。
    """
    rows = []
    d = datetime.now().replace(day=1)
    for _ in range(months):
        try:
            if market == "sii":
                ds = f"{d:%Y%m01}"
                j = fetch_json(
                    f"https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY"
                    f"?date={ds}&stockNo={code}&response=json",
                    cache_key=f"day_{code}_{ds}.json", use_cache=use_cache, timeout=40,
                )
                data = j.get("data", []) if j.get("stat") == "OK" else []
                vol_mult = 1
            else:
                ds = f"{d:%Y/%m/01}"
                j = fetch_json(
                    f"https://www.tpex.org.tw/www/zh-tw/afterTrading/tradingStock"
                    f"?code={code}&date={ds}&id=&response=json",
                    cache_key=f"day_{code}_{d:%Y%m}.json", use_cache=use_cache, timeout=40,
                )
                tables = j.get("tables") or [{}]
                data = tables[0].get("data", [])
                vol_mult = 1000                 # 張 → 股

            for r in data:
                try:
                    rows.append({
                        "date": r[0].strip(),
                        "open": float(str(r[3]).replace(",", "")),
                        "high": float(str(r[4]).replace(",", "")),
                        "low": float(str(r[5]).replace(",", "")),
                        "close": float(str(r[6]).replace(",", "")),
                        "volume": int(float(str(r[1]).replace(",", "")) * vol_mult),
                    })
                except (ValueError, IndexError):
                    pass
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.4)                      # 對官方站點客氣一點
        d = (d - timedelta(days=1)).replace(day=1)
    rows.sort(key=lambda x: x["date"])
    log(f"  日成交: {len(rows)} 筆")
    return rows


def get_institutional(code, days=20, use_cache=True):
    """三大法人買賣超。T86 是全市場單日檔，需逐日抓。"""
    out = []
    d = datetime.now()
    tries = 0
    while len(out) < days and tries < days * 2:
        tries += 1
        ds = f"{d:%Y%m%d}"
        d -= timedelta(days=1)
        if datetime.strptime(ds, "%Y%m%d").weekday() >= 5:
            continue
        try:
            j = fetch_json(
                f"https://www.twse.com.tw/rwd/zh/fund/T86"
                f"?date={ds}&selectType=ALL&response=json",
                cache_key=f"t86_{ds}.json", use_cache=use_cache, timeout=40,
            )
            if j.get("stat") != "OK":
                continue
            f = j["fields"]
            row = next((x for x in j["data"] if x[0].strip() == code), None)
            if not row:
                continue
            o = dict(zip(f, row))

            def num(*keys):
                for k in keys:
                    if k in o:
                        return int(o[k].replace(",", ""))
                return 0

            out.append({
                "date": ds,
                "foreign": num("外陸資買賣超股數(不含外資自營商)", "外資買賣超股數"),
                "trust": num("投信買賣超股數"),
                "dealer": num("自營商買賣超股數"),
                "total": num("三大法人買賣超股數"),
            })
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.4)
    out.sort(key=lambda x: x["date"])
    log(f"  三大法人: {len(out)} 個交易日")
    return out


# ---------------------------------------------------------------- 集保

def get_tdcc(code, use_cache=True):
    """集保股權分散表（官方 Open Data，全市場單週快照，約 2.3MB）。"""
    try:
        raw = fetch(
            "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5",
            cache_key="tdcc_1-5.csv", use_cache=use_cache, timeout=120,
        )
        rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig", "replace"))))
        hit = [r for r in rows if r["證券代號"].strip() == code]
        log(f"  集保分散表: {len(hit)} 個級距")
        return hit
    except Exception as e:  # noqa: BLE001
        log(f"  集保分散表: ✗ {e}")
        return []


# ---------------------------------------------------------------- 法說會

def get_conferences(code, market="sii"):
    """歷年法人說明會清單。

    公開資訊觀測站新版會把這個查詢轉導到舊系統，網址帶加密參數，
    看起來像是沒辦法自動化。但**舊版的查詢表單可以直接 POST**，
    繞過整個新版前端即可拿到完整歷年清單。

    簡報檔名是有規律的：<代號><西元年月日><M中文|E英文>001.pdf
    """
    url = "https://mopsov.twse.com.tw/mops/web/ajax_t100sb02_1"
    body = urllib.parse.urlencode({
        "step": "0", "firstin": "true", "TYPEK": market, "co_id": code,
    }).encode()
    req = urllib.request.Request(url, data=body, headers={
        "User-Agent": UA,
        "Content-Type": "application/x-www-form-urlencoded",
        "Referer": "https://mopsov.twse.com.tw/mops/web/t100sb02_1",
    })
    html = None
    for attempt in range(3):                 # 舊版 MOPS 偶爾很慢，重試幾次
        try:
            html = urllib.request.urlopen(req, timeout=90, context=CTX).read().decode("utf-8", "replace")
            break
        except Exception as e:  # noqa: BLE001
            if attempt == 2:
                log(f"  法說會: ✗ {e}")
                return []
            time.sleep(2)
    if html is None:
        return []

    import re
    seen, out = set(), []
    for fn in sorted(set(re.findall(rf"({code}\d{{8}}M\d{{3}}\.pdf)", html))):
        ymd = fn[len(code):len(code) + 8]
        if ymd in seen:
            continue
        seen.add(ymd)
        out.append({
            "date": f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:8]}",
            "pdf_zh": fn,
            "pdf_en": fn.replace("M", "E", 1) if "M" in fn else "",
        })
    out.sort(key=lambda x: x["date"], reverse=True)
    # 影音連結（法說會若有錄影，可用 yt-transcribe.py 轉逐字稿）
    videos = sorted(set(re.findall(r"https://www\.youtube\.com/watch\?v=[\w\-]+", html)))
    log(f"  法說會: {len(out)} 場" + (f"，{len(videos)} 個影音連結" if videos else ""))
    return {"list": out, "videos": videos}


def download_conference_pdf(filename, dest_dir):
    """下載法說會簡報 PDF。"""
    body = urllib.parse.urlencode({
        "step": "9", "filePath": "/home/html/nas/STR/",
        "fileName": filename, "functionName": "t100sb02_1",
    }).encode()
    req = urllib.request.Request(
        "https://mopsov.twse.com.tw/server-java/FileDownLoad", data=body,
        headers={"User-Agent": UA, "Content-Type": "application/x-www-form-urlencoded"},
    )
    data = urllib.request.urlopen(req, timeout=90, context=CTX).read()
    if not data.startswith(b"%PDF"):
        raise RuntimeError("回傳的不是 PDF，可能是錯誤頁")
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / filename
    out.write_bytes(data)
    return out


# ---------------------------------------------------------------- CMoney 籌碼

def get_cmoney(code, days=60):
    """CMoney 主力買賣超與買賣家數差。

    不需要登入——實測匿名與登入結果完全相同。但 API 要一把 cmkey，
    那把金鑰是短效的（幾分鐘就換），而且不會出現在 JS 檔裡，只嵌在
    籌碼K線頁面的 HTML 中，一頁約 21 把、每個 action 各一把。

    所以流程是：載入頁面 → 抽出所有候選金鑰 → 逐一試到通為止。
    頁面載入時設下的 session cookie 也是必要的，故共用同一個 opener。
    """
    import http.cookiejar
    import re

    page = f"https://www.cmoney.tw/finance/{code}/stockmainkline"
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=CTX),
        urllib.request.HTTPCookieProcessor(cj),
    )
    op.addheaders = [("User-Agent", UA), ("Accept-Language", "zh-TW,zh;q=0.9")]

    def api(action, key):
        u = (f"https://www.cmoney.tw/finance/ashx/MainPage.ashx?action={action}"
             f"&stockId={code}&days={days}&cmkey={urllib.parse.quote(key, safe='')}")
        req = urllib.request.Request(u, headers={"Referer": page})
        return op.open(req, timeout=30).read().decode("utf-8", "replace")

    try:
        html = op.open(page, timeout=45).read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        log(f"  CMoney: ✗ 頁面載入失敗 {e}")
        return {}

    keys = []
    for m in re.findall(r"cmkey\s*[=:]\s*[\"']([^\"']+)", html):
        if m not in keys:
            keys.append(m)
    if not keys:
        log("  CMoney: ✗ 頁面中找不到金鑰（網站結構可能已改版）")
        return {}

    good = None
    for k in keys:
        try:
            if api("tradersum", k).startswith("["):
                good = k
                break
        except Exception:  # noqa: BLE001
            continue
    if not good:
        log(f"  CMoney: ✗ {len(keys)} 把金鑰全部失敗")
        return {}

    out = {}
    for action, label in [("tradersum", "買賣家數差"), ("mainforceoverbuy", "主力買賣超")]:
        try:
            body = api(action, good)
            out[action] = json.loads(body) if body.startswith("[") else []
            log(f"  CMoney {label}: {len(out[action])} 筆")
        except Exception as e:  # noqa: BLE001
            out[action] = []
            log(f"  CMoney {label}: ✗ {e}")
    return out


# ---------------------------------------------------------------- 計算

def get_margin(code, days=20, use_cache=True):
    """融資融券餘額。

    第 67 期把融資當**散戶熱度**指標：長期打底後融資緩步增加相對健康；
    但在高檔融資持續暴增、跟著指數噴出，是非常危險的訊號。
    """
    out = []
    d = datetime.now()
    tries = 0
    while len(out) < days and tries < days * 2:
        tries += 1
        ds = f"{d:%Y%m%d}"
        d -= timedelta(days=1)
        if datetime.strptime(ds, "%Y%m%d").weekday() >= 5:
            continue
        try:
            j = fetch_json(
                f"https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN"
                f"?date={ds}&selectType=STOCK&response=json",
                cache_key=f"margin_{ds}.json", use_cache=use_cache, timeout=40,
            )
            if j.get("stat") != "OK":
                continue
            for t in j.get("tables", []):
                f = t.get("fields", [])
                if not f or "代號" not in str(f[0]):
                    continue
                row = next((r for r in t.get("data", []) if r[0].strip() == code), None)
                if row:
                    # 欄位：代號 名稱 融資買進 賣出 現金償還 前日餘額 今日餘額 …
                    out.append({
                        "date": ds,
                        "balance": int(str(row[6]).replace(",", "")),
                        "prev": int(str(row[5]).replace(",", "")),
                    })
                break
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.4)
    out.sort(key=lambda x: x["date"])
    log(f"  融資餘額: {len(out)} 個交易日")
    return out


def monthly_kd(monthly, n=9):
    """月 KD。

    第 67 期：日 KD 雜訊太多他不參考，但**月 KD 相對具參考價值**，
    特別留意超過 80 或低於 20。
    """
    if len(monthly) < n:
        return None
    k = d = 50.0
    series = []
    for i in range(n - 1, len(monthly)):
        window = monthly[i - n + 1: i + 1]
        hi = max(x["high"] for x in window)
        lo = min(x["low"] for x in window)
        c = monthly[i]["close"]
        rsv = 50.0 if hi == lo else (c - lo) / (hi - lo) * 100
        k = k * 2 / 3 + rsv / 3
        d = d * 2 / 3 + k / 3
        series.append({"key": monthly[i]["key"], "k": k, "d": d})
    return series


def concentration(cmoney, daily, windows=(20, 60)):
    """籌碼集中度（🔴 自行計算）。

    宏爺的公式是 (前15大買超張數 − 前15大賣超張數) ÷ 區間總成交量。
    CMoney 的「主力買賣超」正是那個分子，成交量則來自交易所，
    所以這個指標其實可以自己算出來，不必依賴付費工具。

    判準（第 70 期）：60 日 > 5%（強者 10%）、120 日 > 3%；
    **負值代表主力正在倒貨**。
    """
    fb = (cmoney or {}).get("mainforceoverbuy") or []
    if not fb or not daily:
        return {}
    vol_by_date = {}
    for r in daily:
        dt = roc_date(r["date"])
        if dt:
            vol_by_date[f"{dt:%Y%m%d}"] = r["volume"] / 1000    # 股 → 張
    out = {}
    for w in windows:
        recent = fb[-w:]
        if len(recent) < w:
            continue
        net = sum(x.get("OverBuy", 0) for x in recent)
        vol = sum(vol_by_date.get(x["Date"], 0) for x in recent)
        if vol > 0:
            out[w] = {"net_lots": net, "volume_lots": vol, "pct": net / vol * 100}
    return out


def roc_date(s):
    """民國 115/09/07 → datetime。兩個交易所都用這個格式。"""
    try:
        y, m, d = s.strip().split("/")
        return datetime(int(y) + 1911, int(m), int(d))
    except (ValueError, AttributeError):
        return None


def aggregate(daily, period):
    """日線聚合成週線或月線 OHLCV。

    宏爺的週期分工：月K看戰略、週K看戰術、日K看戰技。
    月K 的形態要花好幾年才走得出來，所以資料抓得夠久才有意義。
    """
    buckets = {}
    order = []
    for r in daily:
        dt = roc_date(r["date"])
        if not dt:
            continue
        if period == "W":
            iso = dt.isocalendar()
            key = f"{iso[0]}-W{iso[1]:02d}"
        else:
            key = f"{dt.year}-{dt.month:02d}"
        if key not in buckets:
            buckets[key] = {"key": key, "open": r["open"], "high": r["high"],
                            "low": r["low"], "close": r["close"],
                            "volume": r["volume"], "n": 1}
            order.append(key)
        else:
            b = buckets[key]
            b["high"] = max(b["high"], r["high"])
            b["low"] = min(b["low"], r["low"])
            b["close"] = r["close"]          # 期間最後一個交易日
            b["volume"] += r["volume"]
            b["n"] += 1
    return [buckets[k] for k in order]


def sma(series, n):
    """簡單移動平均，資料不足回 None。"""
    if len(series) < n:
        return None
    return sum(series[-n:]) / n


def bias(price, ma):
    return None if not ma else (price - ma) / ma * 100


def technicals(daily):
    """算出宏爺框架實際會用到的均線與位階。

    - 日線：月線 20MA、季線 60MA、半年線 120MA、年線 240MA
    - 週線：20 週均線（他判斷大盤多空、放空條件的關鍵門檻）
    - 月線：6MA、12MA、60MA（第 67 期的月K三工具之一）
    """
    if not daily:
        return {}
    weekly = aggregate(daily, "W")
    monthly = aggregate(daily, "M")
    dc = [r["close"] for r in daily]
    wc = [r["close"] for r in weekly]
    mc = [r["close"] for r in monthly]
    last = dc[-1]

    out = {
        "last": last,
        "weekly": weekly,
        "monthly": monthly,
        "ma": {
            "日線 月線(20MA)": sma(dc, 20),
            "日線 季線(60MA)": sma(dc, 60),
            "日線 半年線(120MA)": sma(dc, 120),
            "日線 年線(240MA)": sma(dc, 240),
            "週線 20週均線": sma(wc, 20),
            "月線 6MA(半年)": sma(mc, 6),
            "月線 12MA(一年)": sma(mc, 12),
            "月線 60MA(五年)": sma(mc, 60),
        },
    }
    out["bias"] = {k: bias(last, v) for k, v in out["ma"].items()}

    # 位階：52 週與全期間的高低區間位置
    span52 = [r for r in daily[-250:]]
    if span52:
        hi = max(r["high"] for r in span52)
        lo = min(r["low"] for r in span52)
        out["52w"] = {
            "high": hi, "low": lo,
            "pct": (last - lo) / (hi - lo) * 100 if hi > lo else None,
        }
    hi_all = max(r["high"] for r in daily)
    lo_all = min(r["low"] for r in daily)
    out["all"] = {
        "high": hi_all, "low": lo_all,
        "pct": (last - lo_all) / (hi_all - lo_all) * 100 if hi_all > lo_all else None,
        "months": len(monthly),
    }
    return out


def summarize_tdcc(rows):
    if not rows:
        return None
    by = {r["持股分級"].strip(): r for r in rows}
    total = by.get("17")
    if not total:
        return None

    def agg(levels):
        ppl = sum(int(by[l]["人數"]) for l in levels if l in by)
        sh = sum(int(by[l]["股數"]) for l in levels if l in by)
        pct = sum(float(by[l]["占集保庫存數比例%"]) for l in levels if l in by)
        return ppl, sh, pct

    b_ppl, b_sh, b_pct = agg(TDCC_BIG)
    h_ppl, h_sh, h_pct = agg(TDCC_HUGE)
    tot_ppl = int(total["人數"])
    tot_sh = int(total["股數"])
    return {
        "date": total["資料日期"],
        "total_holders": tot_ppl,
        "total_shares": tot_sh,
        "avg_lots": tot_sh / 1000 / tot_ppl if tot_ppl else 0,
        "big_ppl": b_ppl, "big_lots": b_sh / 1000, "big_pct": b_pct,
        "huge_ppl": h_ppl, "huge_lots": h_sh / 1000, "huge_pct": h_pct,
        "levels": rows,
    }


# ---------------------------------------------------------------- 輸出

def build_report(code, api, daily, inst, tdcc, cmoney=None, conf=None,
                 divs=None, market="sii", margin=None):
    base = api.get("基本資料") or {}
    name = base.get("公司簡稱", code)
    now = datetime.now()
    L = []

    L += [
        "---",
        f"title: {code} {name} 原始資料",
        "type: 個股資料表",
        f'stock_id: "{code}"',
        f"generated: {now:%Y-%m-%d %H:%M}",
        "generator: 000_Agent/scripts/stock-fetch.py",
        "tags:",
        "  - 投資",
        "  - 個股資料",
        "---",
        "",
        f"# {code} {name}｜原始資料表",
        "",
        "> [!note] 自動產生",
        "> 由 `stock-fetch.py` 抓取公開資料組成。**不要手動編輯**，重跑即可更新。",
        "> 🔴 標記處為腳本計算值，非官方數據。",
        "",
    ]

    # 基本資料
    if base:
        L += ["## 公司基本資料", "", "| 項目 | 內容 |", "| :--- | :--- |"]
        for k in ["公司名稱", "產業別", "上市日期", "成立日期", "董事長", "總經理",
                  "發言人", "住址", "總機電話", "網址", "實收資本額",
                  "已發行普通股數或TDR原股發行股數", "簽證會計師事務所"]:
            if base.get(k):
                L.append(f"| {k} | {base[k]} |")
        L.append("")

    # 股價：日線、週線、月線與均線
    if daily:
        last = daily[-1]
        t = technicals(daily)
        L += [
            "## 股價與技術面",
            "",
            f"**最新交易日 {last['date']}**：收 **{last['close']}**，"
            f"量 {last['volume']:,} 股",
            f"（資料涵蓋 {len(daily)} 個交易日／{t['all']['months']} 個月）",
            "",
        ]

        # 位階
        w = t.get("52w")
        a = t.get("all")
        L += ["### 位階", "", "| 區間 | 最高 | 最低 | 🔴 現價位置 |",
              "| :--- | ---: | ---: | ---: |"]
        if w:
            pct = f"{w['pct']:.0f}%" if w["pct"] is not None else "—"
            L.append(f"| 近 52 週 | {w['high']} | {w['low']} | {pct} |")
        if a:
            pct = f"{a['pct']:.0f}%" if a["pct"] is not None else "—"
            L.append(f"| 全期間 | {a['high']} | {a['low']} | {pct} |")
        L += [
            "",
            "> [!tip] 依 [[基期位階判斷五法]]",
            "> 位置接近 0% 是相對低基期、接近 100% 是相對高基期。但**低基期不等於買點**"
            "——還要看趨勢是否為「高不過高、低破前低」的空頭排列。",
            "",
        ]

        # 均線與乖離
        L += [
            "### 均線與乖離（🔴 皆為腳本計算）",
            "",
            "| 均線 | 數值 | 乖離率 | 價格位置 |",
            "| :--- | ---: | ---: | :---: |",
        ]
        for name, val in t["ma"].items():
            if val is None:
                L.append(f"| {name} | 資料不足 | — | — |")
                continue
            b = t["bias"][name]
            pos = "⬆ 之上" if last["close"] >= val else "⬇ 之下"
            L.append(f"| {name} | {val:.2f} | {b:+.1f}% | {pos} |")
        L += [
            "",
            "> [!important] 兩條關鍵線",
            "> [[雙均線控盤]]：同時站上**月線**與 **20 週均線**＝做多；跌破任一＝空手；"
            "同時跌破＝做空。",
            "> [[乖離率]]：大盤長線乖離常在 ±15%、達 ±20% 要提高警覺；"
            "**個股區間更寬**，中小型股常超過 ±15%。",
            "",
        ]

        # 月線
        mo = t["monthly"]
        if mo:
            L += ["### 月K（近 24 個月）", "",
                  "| 月份 | 開 | 高 | 低 | 收 | 成交股數 |",
                  "| :--- | ---: | ---: | ---: | ---: | ---: |"]
            for r in mo[-24:]:
                L.append(f"| {r['key']} | {r['open']} | {r['high']} | {r['low']} "
                         f"| {r['close']} | {r['volume']:,} |")
            L += ["",
                  "> [!tip] 依 [[月K線大局判讀]]",
                  "> 月K看的是未來幾年處於多頭的夏天還是空頭的冬天。三大工具是"
                  "**切線**（連接數年關鍵高低點）、**長期均線**（6MA/12MA/60MA）、**量能**。",
                  "> 切線需要人工在圖上畫，腳本給不了——但上面的月K數列就是畫線的原料。",
                  ""]

            kd = monthly_kd(mo)
            if kd:
                cur = kd[-1]
                zone = ("🔴 超買區（>80）" if cur["k"] > 80
                        else "🟢 超賣區（<20）" if cur["k"] < 20 else "⚪ 中性")
                L += [
                    "#### 月 KD",
                    "",
                    f"最新（{cur['key']}）：**K {cur['k']:.1f} / D {cur['d']:.1f}**　{zone}",
                    "",
                    "| 月份 | K | D |",
                    "| :--- | ---: | ---: |",
                ]
                for r in kd[-8:]:
                    L.append(f"| {r['key']} | {r['k']:.1f} | {r['d']:.1f} |")
                L += [
                    "",
                    "> [!note] 🔴 腳本計算（9 期 RSV，K/D 各取 1/3 平滑）",
                    "> 宏爺日 KD 不參考——短期雜訊太多；但**月 KD 相對具參考價值**，"
                    "特別留意超過 80 或低於 20。",
                    "",
                ]

        # 週線
        wk = t["weekly"]
        if wk:
            L += ["### 週K（近 16 週）", "",
                  "| 週次 | 開 | 高 | 低 | 收 | 成交股數 |",
                  "| :--- | ---: | ---: | ---: | ---: | ---: |"]
            for r in wk[-16:]:
                L.append(f"| {r['key']} | {r['open']} | {r['high']} | {r['low']} "
                         f"| {r['close']} | {r['volume']:,} |")
            L += ["",
                  "> [!tip] 依 [[週K線判讀]]",
                  "> 有效突破要求：站穩 20 週均線、**週量比前一週增長至少 30%**、"
                  "突破後連續 2–3 週維持高檔不快速回落。",
                  ""]

        # 日線
        L += ["### 日K（近 20 個交易日）", "",
              "| 日期 | 開 | 高 | 低 | 收 | 成交股數 |",
              "| :--- | ---: | ---: | ---: | ---: | ---: |"]
        for r in daily[-20:]:
            L.append(f"| {r['date']} | {r['open']} | {r['high']} | {r['low']} "
                     f"| {r['close']} | {r['volume']:,} |")
        L.append("")

    # 三大法人
    if inst:
        tf = sum(x["foreign"] for x in inst)
        tt = sum(x["trust"] for x in inst)
        td = sum(x["dealer"] for x in inst)
        ta = sum(x["total"] for x in inst)
        L += [
            "## 三大法人買賣超（股）",
            "",
            f"**近 {len(inst)} 個交易日合計**：外資 {tf:+,}／投信 {tt:+,}／"
            f"自營 {td:+,}／三大法人 **{ta:+,}**",
            "",
            "| 日期 | 外資 | 投信 | 自營 | 合計 |",
            "| :--- | ---: | ---: | ---: | ---: |",
        ]
        for x in inst:
            L.append(f"| {x['date']} | {x['foreign']:+,} | {x['trust']:+,} "
                     f"| {x['dealer']:+,} | {x['total']:+,} |")
        L.append("")

    # 集保
    s = summarize_tdcc(tdcc)
    if s:
        L += [
            "## 集保股權分散表",
            "",
            f"資料日期 **{s['date']}**（官方 TDCC Open Data）",
            "",
            "| 項目 | 數值 |",
            "| :--- | ---: |",
            f"| 總股東人數 | {s['total_holders']:,} |",
            f"| 總股數 | {s['total_shares']:,} |",
            f"| 🔴 平均張數/人 | {s['avg_lots']:.2f} |",
            f"| >400 張大股東 | {s['big_ppl']} 人，{s['big_lots']:,.0f} 張，**{s['big_pct']:.2f}%** |",
            f"| >1000 張大股東 | {s['huge_ppl']} 人，{s['huge_lots']:,.0f} 張，**{s['huge_pct']:.2f}%** |",
            "",
            "> [!tip] 流向重於水位",
            "> 單週數字看不出方向。要判斷籌碼集中或分散，需連續數週比對"
            "「總股東人數」與「大股東持有率」的變化。",
            "",
        ]

    # 法說會
    cf = conf or {}
    clist = cf.get("list") or []
    if clist:
        by_year = {}
        for c in clist:
            by_year.setdefault(c["date"][:4], 0)
            by_year[c["date"][:4]] += 1
        L += [
            "## 法人說明會",
            "",
            f"歷年共 **{len(clist)} 場**，最近一場 **{clist[0]['date']}**",
            "",
            "| 年度 | 場次 |",
            "| :--- | ---: |",
        ]
        for y in sorted(by_year, reverse=True):
            L.append(f"| {y} | {by_year[y]} |")
        L += [
            "",
            "> [!tip] 頻率本身是訊號",
            "> 法說會開得勤不勤、是否中斷，反映公司與市場溝通的意願。",
            "",
            "### 最近 5 場",
            "",
            "| 日期 | 中文簡報 | 英文簡報 |",
            "| :--- | :--- | :--- |",
        ]
        for c in clist[:5]:
            L.append(f"| {c['date']} | `{c['pdf_zh']}` | `{c['pdf_en']}` |")
        L += [
            "",
            "下載指令（在 Python 中呼叫）：",
            "",
            "```bash",
            f"python -c \"import sys; sys.path.insert(0,'000_Agent/scripts'); "
            f"import importlib.util as u; s=u.spec_from_file_location('sf','000_Agent/scripts/stock-fetch.py'); "
            f"m=u.module_from_spec(s); s.loader.exec_module(m); "
            f"print(m.download_conference_pdf('{clist[0]['pdf_zh']}','.'))\"",
            "```",
            "",
        ]
        if cf.get("videos"):
            L += ["**法說會影音**（可用 `yt-transcribe.py` 轉逐字稿）：", ""]
            for v in cf["videos"][:5]:
                L.append(f"- {v}")
            L.append("")

    # CMoney 籌碼
    cm = cmoney or {}
    ts = cm.get("tradersum") or []
    fb = cm.get("mainforceoverbuy") or []
    if ts or fb:
        force = {r["Date"]: r.get("OverBuy") for r in fb}
        L += [
            "## 主力買賣超與買賣家數差（CMoney）",
            "",
            "> [!important] 判讀依據",
            "> 依 [[買賣家數差]]：**家數差為負 + 主力買超為正 ＝ 少數人吸收多數人的貨，"
            "主力吃貨**。反之家數差為大正值，代表少數賣方把貨分散給很多買方，偏出貨。",
            "",
            "| 日期 | 主力買賣超(張) | 買方家數 | 賣方家數 | 買賣家數差 | 型態 |",
            "| :--- | ---: | ---: | ---: | ---: | :--- |",
        ]
        for r in ts[-15:]:
            d = r["Date"]
            ob = force.get(d)
            diff = r.get("TraderSum")
            if ob is None or diff is None:
                shape = "—"
            elif ob > 0 and diff < 0:
                shape = "**吃貨**"
            elif ob < 0 and diff > 0:
                shape = "偏出貨"
            else:
                shape = "—"
            L.append(f"| {d} | {ob if ob is not None else '—'} | {r.get('BuyerCount')} "
                     f"| {r.get('SellerCount')} | {diff:+} | {shape} |")
        if fb:
            tot = sum(r.get("OverBuy", 0) for r in fb)
            L += ["", f"期間主力買賣超合計：**{tot:+,} 張**（{len(fb)} 個交易日）", ""]

        conc = concentration(cmoney, daily)
        if conc:
            L += [
                "### 🔴 籌碼集中度（腳本計算）",
                "",
                "公式：主力買賣超累計 ÷ 區間總成交量。宏爺的定義是"
                "「(前15大買超張數 − 前15大賣超張數) ÷ 區間總成交量」，"
                "而 CMoney 的主力買賣超正是那個分子，所以這個數字不必依賴付費工具。",
                "",
                "| 區間 | 主力買賣超累計 | 區間總成交量 | 集中度 | 判定 |",
                "| :--- | ---: | ---: | ---: | :--- |",
            ]
            for w in sorted(conc):
                c = conc[w]
                p = c["pct"]
                if w >= 60:
                    verdict = ("**高度集中**" if p > 10 else "集中" if p > 5
                               else "**主力倒貨**" if p < 0 else "中性")
                else:
                    verdict = "**主力倒貨**" if p < 0 else "偏集中" if p > 5 else "中性"
                L.append(f"| {w} 日 | {c['net_lots']:+,.0f} 張 "
                         f"| {c['volume_lots']:,.0f} 張 | **{p:+.2f}%** | {verdict} |")
            L += [
                "",
                "> [!tip] 判準（第 70 期）",
                "> 高度集中：60 日 > 5%，強者達 10%；120 日 > 3%。"
                "**負值代表主力正在倒貨，上方壓力重重。**",
                "> 要搭配 [[買賣家數差]] 一起看，才能區分「集中」與「主力真的在吃貨」。",
                "",
            ]

    # 融資餘額
    mg = margin or []
    if mg:
        first, last_m = mg[0], mg[-1]
        chg = last_m["balance"] - first["balance"]
        pct = chg / first["balance"] * 100 if first["balance"] else 0
        L += [
            "## 融資餘額（散戶熱度）",
            "",
            f"最新 {last_m['date']}：**{last_m['balance']:,} 張**"
            f"（{len(mg)} 個交易日變化 {chg:+,} 張，{pct:+.1f}%）",
            "",
            "| 日期 | 融資餘額(張) | 日增減 |",
            "| :--- | ---: | ---: |",
        ]
        for r in mg[-10:]:
            L.append(f"| {r['date']} | {r['balance']:,} | {r['balance'] - r['prev']:+,} |")
        L += [
            "",
            "> [!important] 依 [[月K線大局判讀]]",
            "> 融資代表散戶熱度。長期打底後融資**緩步增加**相對健康；"
            "但在**高檔融資持續暴增、跟著指數噴出**，代表散戶陷入瘋狂，是非常危險的訊號。",
            "",
        ]

    # 歷年股利與 EPS
    dv = [d for d in (divs or []) if d.get("eps") is not None]
    if dv:
        last_price = daily[-1]["close"] if daily else None
        L += [
            "## 歷年 EPS 與股利",
            "",
            "> [!important] 宏爺很看重這一段",
            "> 「歷年股息是否**持續增加**」是他不怕套牢的底氣。配息穩定與配息成長"
            "是兩件事——[[為什麼他幾乎不停損]] 的前提是後者。",
            "",
            "| 年度 | EPS | 現金股利 | 盈餘配股 | 🔴 配息率 |",
            "| ---: | ---: | ---: | ---: | ---: |",
        ]
        for d in dv[-12:]:
            eps, cash = d["eps"], d.get("cash") or 0
            ratio = f"{cash / eps * 100:.0f}%" if eps and eps > 0 and cash else "—"
            L.append(f"| {d['year']} | {eps} | {cash or '—'} "
                     f"| {d.get('stock') or '—'} | {ratio} |")
        L.append("")

        paid = [d for d in dv if (d.get("cash") or 0) > 0]
        if paid:
            streak = 0
            for d in reversed(dv):
                if (d.get("cash") or 0) > 0:
                    streak += 1
                else:
                    break
            latest = dv[-1]
            L.append(f"**連續配息 {streak} 年**（{dv[-streak]['year']}–{latest['year']}）")
            if last_price and (latest.get("cash") or 0):
                y = latest["cash"] / last_price * 100
                L.append(f"　🔴 以 {latest['year']} 年股利 {latest['cash']} 元、"
                         f"現價 {last_price} 計，現金殖利率約 **{y:.2f}%**")
            if len(dv) >= 2:
                prev, cur = dv[-2].get("cash") or 0, latest.get("cash") or 0
                if prev and cur < prev:
                    L.append(f"　⚠️ **配息成長中斷**：{dv[-2]['year']} 年 {prev} 元 → "
                             f"{latest['year']} 年 {cur} 元（{(cur - prev) / prev * 100:+.0f}%）")
            L.append("")

    # 財報
    for key, title in [("月營收", "月營收"), ("營益分析", "營益分析"),
                       ("綜合損益", "綜合損益表"), ("資產負債", "資產負債表")]:
        d = api.get(key)
        if not d:
            continue
        L += [f"## {title}", "", "| 項目 | 數值 |", "| :--- | ---: |"]
        for k, v in d.items():
            if v not in ("", None) and k not in ("公司代號", "公司名稱", "出表日期"):
                L.append(f"| {k} | {v} |")
        L.append("")

    L += [
        "## 本腳本抓不到的（需人工）",
        "",
        "- 分點進出明細（證交所買賣日報表，有圖形驗證碼）",
        "- 籌碼集中度與外資成本線（CMoney 網頁上有，但未找到對應 API）",
        "- 董監持股明細",
        "- 集保大戶的歷史趨勢（官方開放資料只有最新一週）",
        "",
        "→ 操作步驟見 [[資料蒐集SOP]]",
        "",
        "## 相關",
        "",
        "- [[判讀SOP]]｜拿到資料後怎麼分析",
        "- [[數據來源清單]]",
        "",
    ]
    return "\n".join(L)


def main():
    p = argparse.ArgumentParser(description="個股公開資料蒐集器")
    p.add_argument("code", help="股票代號，例如 1786")
    p.add_argument("--days", type=int, default=20, help="三大法人抓幾個交易日（預設 20）")
    p.add_argument("--months", type=int, default=36,
                   help="股價抓幾個月（預設 36。20週均線需約 6 個月、"
                        "月線 12MA 需 12 個月、月線 60MA 需 60 個月）")
    p.add_argument("--no-cache", action="store_true", help="強制重新下載")
    args = p.parse_args()

    code = args.code.strip()
    use_cache = not args.no_cache
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    log(f"開始蒐集 {code}")
    market = detect_market(code, use_cache)
    if market is None:
        log("✗ 上市與上櫃都查不到這個代號，請確認是否為興櫃或已下市。")
        return 1
    log(f"市場別：{'上市（證交所）' if market == 'sii' else '上櫃（櫃買中心）'}")

    log("公開資料…")
    api = get_openapi(code, market, use_cache)

    log("股價…")
    daily = get_daily(code, market, args.months, use_cache)

    if market == "sii":
        log("三大法人…")
        inst = get_institutional(code, args.days, use_cache)
        log("融資餘額…")
        margin = get_margin(code, args.days, use_cache)
    else:
        inst, margin = [], []
        log("三大法人與融資：上櫃的歷史逐日資料尚未支援，跳過")

    log("集保股權分散…")
    tdcc = get_tdcc(code, use_cache)
    log("CMoney 籌碼（免登入）…")
    cmoney = get_cmoney(code, days=max(args.days * 3, 60))
    log("法說會…")
    conf = get_conferences(code, market)
    log("歷年股利與 EPS…")
    divs = get_dividends(code)

    report = build_report(code, api, daily, inst, tdcc, cmoney, conf, divs,
                          market, margin)
    out = OUT_DIR / f"{code}.md"
    out.write_text(report, encoding="utf-8")
    log(f"完成 → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
