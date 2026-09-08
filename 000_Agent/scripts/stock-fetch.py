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


# ---------------------------------------------------------------- TWSE OpenAPI

OPENAPI = {
    "基本資料": "t187ap03_L",
    "月營收": "t187ap05_L",
    "綜合損益": "t187ap06_L_ci",
    "資產負債": "t187ap07_L_ci",
    "營益分析": "t187ap17_L",
}


def get_openapi(code, use_cache=True):
    """TWSE 開放資料：公司基本資料、月營收、財報。全市場檔案，抓下來過濾。"""
    out = {}
    for name, ep in OPENAPI.items():
        try:
            rows = fetch_json(
                f"https://openapi.twse.com.tw/v1/opendata/{ep}",
                cache_key=f"openapi_{ep}.json", use_cache=use_cache,
            )
            hit = [r for r in rows if str(r.get("公司代號", "")).strip() == code]
            out[name] = hit[0] if hit else None
            log(f"  {name}: {'✓' if hit else '無資料'}")
        except Exception as e:  # noqa: BLE001
            out[name] = None
            log(f"  {name}: ✗ {e}")
    return out


# ---------------------------------------------------------------- 股價

def get_daily(code, months=14, use_cache=True):
    """個股日成交。逐月抓，回傳 [(日期, 開, 高, 低, 收, 量), ...]。"""
    rows = []
    d = datetime.now().replace(day=1)
    for _ in range(months):
        ds = f"{d:%Y%m01}"
        try:
            j = fetch_json(
                f"https://www.twse.com.tw/rwd/zh/afterTrading/STOCK_DAY"
                f"?date={ds}&stockNo={code}&response=json",
                cache_key=f"day_{code}_{ds}.json", use_cache=use_cache, timeout=40,
            )
            if j.get("stat") == "OK":
                for r in j.get("data", []):
                    try:
                        rows.append({
                            "date": r[0],
                            "open": float(r[3].replace(",", "")),
                            "high": float(r[4].replace(",", "")),
                            "low": float(r[5].replace(",", "")),
                            "close": float(r[6].replace(",", "")),
                            "volume": int(r[1].replace(",", "")),
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

def ma_and_bias(daily, weeks=20):
    """用週收盤算 N 週均價與乖離率。這是自行計算，非官方數據。"""
    if len(daily) < weeks * 5:
        return None, None, None
    weekly = []
    cur_week = None
    for r in daily:                          # 民國 115/09/07 格式
        try:
            y, m, dd = r["date"].split("/")
            dt = datetime(int(y) + 1911, int(m), int(dd))
        except ValueError:
            continue
        wk = dt.isocalendar()[:2]
        if wk != cur_week:
            weekly.append(r["close"])
            cur_week = wk
        else:
            weekly[-1] = r["close"]          # 取該週最後一個交易日
    if len(weekly) < weeks:
        return None, None, None
    window = weekly[-weeks:]
    ma = sum(window) / weeks
    last = daily[-1]["close"]
    return ma, (last - ma) / ma * 100, len(weekly)


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

def build_report(code, api, daily, inst, tdcc, cmoney=None):
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

    # 股價
    if daily:
        last = daily[-1]
        ma, bias, nweeks = ma_and_bias(daily)
        closes = [r["close"] for r in daily]
        L += [
            "## 股價",
            "",
            f"**最新交易日 {last['date']}**：收 **{last['close']}**，"
            f"量 {last['volume']:,} 股",
            "",
            "| 指標 | 數值 |",
            "| :--- | ---: |",
            f"| 期間最高 | {max(closes)} |",
            f"| 期間最低 | {min(closes)} |",
            f"| 資料筆數 | {len(daily)} 個交易日 |",
        ]
        if ma:
            L += [
                f"| 🔴 {nweeks and 20} 週均價（腳本計算） | {ma:.2f} |",
                f"| 🔴 乖離率（腳本計算） | {bias:+.1f}% |",
            ]
        L += ["", "### 近 10 個交易日", "",
              "| 日期 | 開 | 高 | 低 | 收 | 成交股數 |",
              "| :--- | ---: | ---: | ---: | ---: | ---: |"]
        for r in daily[-10:]:
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
            L += ["", f"期間主力買賣超合計：**{tot:+,} 張**（{len(fb)} 個交易日）"]
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
        "- 法說會簡報（MOPS 查詢參數為加密字串）",
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
    p.add_argument("--months", type=int, default=14, help="股價抓幾個月（預設 14）")
    p.add_argument("--no-cache", action="store_true", help="強制重新下載")
    args = p.parse_args()

    code = args.code.strip()
    use_cache = not args.no_cache
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    log(f"開始蒐集 {code}")
    log("TWSE 開放資料…")
    api = get_openapi(code, use_cache)
    if not api.get("基本資料"):
        log("⚠ 查無此代號的上市公司基本資料。若為上櫃股票，本腳本目前只支援上市。")

    log("股價…")
    daily = get_daily(code, args.months, use_cache)
    log("三大法人…")
    inst = get_institutional(code, args.days, use_cache)
    log("集保股權分散…")
    tdcc = get_tdcc(code, use_cache)
    log("CMoney 籌碼（免登入）…")
    cmoney = get_cmoney(code, days=max(args.days * 3, 60))

    report = build_report(code, api, daily, inst, tdcc, cmoney)
    out = OUT_DIR / f"{code}.md"
    out.write_text(report, encoding="utf-8")
    log(f"完成 → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
