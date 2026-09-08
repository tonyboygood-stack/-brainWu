#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
潛龍股篩選器｜宏爺十字口訣核心版
================================

「價平、量平，大戶持續加碼」——第 70 期。

找的不是已經在漲的股票，而是**還沒動但大戶在偷偷吃貨**的。
第 83 期用乾卦形容：潛龍勿用，龍還在水裡，市場沒人氣、成交量稀疏，
但那正是築底期常見的樣子。

用法：
  python screener.py                    # 預設條件跑全市場
  python screener.py --top 30           # 只列前 30 名
  python screener.py --days 140         # 抓更多天（20週均線需約 100 個交易日）
  python screener.py --loose            # 放寬條件（初次跑若命中太少可用）
  python screener.py --no-cache         # 強制重抓

產出：
  600_Projects/投資/選股/潛龍名單_YYYY-MM-DD.md

限制（務必先讀）：
  - 產出的是**口袋名單**，不是買進清單。宏爺的流程是：
    口袋名單 → 等利空不跌驗證 → 長紅突破才進場。
  - 只涵蓋上市股票（櫃買的全市場歷史行情端點不穩）。
  - 「大戶加碼」首次執行時以**三大法人連續買超**代理。集保大戶持股率
    的官方開放資料只有最新一週，本腳本每次執行會存檔，跑過幾週之後
    就能改用真正的大戶流向。
"""

import argparse
import csv
import io
import json
import ssl
import sys
import time
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

VAULT = Path(r"C:\Users\user\Documents\GitHub\-")
OUT_DIR = VAULT / "600_Projects" / "投資" / "選股"
CACHE = Path(r"C:\Users\user\.config\stock-data\market")
TDCC_HIST = Path(r"C:\Users\user\.config\stock-data\tdcc_history")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

# 排除非普通股：ETF、受益證券、存託憑證、特別股等
EXCLUDE_PREFIX = ("00", "01", "02", "03", "91")


def log(m):
    print(f"[{datetime.now():%H:%M:%S}] {m}", flush=True)


def fetch(url, cache_key=None, use_cache=True, timeout=90):
    if cache_key and use_cache:
        f = CACHE / cache_key
        if f.exists() and f.stat().st_size > 0:
            return f.read_bytes()
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    data = urllib.request.urlopen(req, timeout=timeout, context=CTX).read()
    if cache_key:
        CACHE.mkdir(parents=True, exist_ok=True)
        (CACHE / cache_key).write_bytes(data)
    return data


def to_f(s):
    try:
        return float(str(s).replace(",", "").strip())
    except (ValueError, AttributeError):
        return None


def to_i(s):
    try:
        return int(float(str(s).replace(",", "").strip()))
    except (ValueError, AttributeError):
        return 0


# ---------------------------------------------------------------- 全市場行情

def market_daily(days=130, use_cache=True):
    """全市場每日收盤行情。

    MI_INDEX 一次回傳當日全部上市個股（約 1,380 檔），所以抓 N 天
    就能組出每一檔的價量序列，不必逐檔請求。
    """
    hist = defaultdict(list)
    names = {}
    d = datetime.now()
    got = tries = 0
    while got < days and tries < days * 2:
        tries += 1
        ds = f"{d:%Y%m%d}"
        d -= timedelta(days=1)
        if datetime.strptime(ds, "%Y%m%d").weekday() >= 5:
            continue
        try:
            raw = fetch(
                f"https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX"
                f"?date={ds}&type=ALLBUT0999&response=json",
                cache_key=f"mi_{ds}.json", use_cache=use_cache, timeout=90,
            )
            j = json.loads(raw)
            if j.get("stat") != "OK":
                continue
            tbl = None
            for t in j.get("tables", []):
                if t.get("fields") and "證券代號" in t["fields"]:
                    tbl = t
                    break
            if not tbl:
                continue
            f = tbl["fields"]
            idx = {k: f.index(k) for k in f}
            for r in tbl["data"]:
                code = r[idx["證券代號"]].strip()
                c = to_f(r[idx.get("收盤價", -1)]) if "收盤價" in idx else None
                o = to_f(r[idx["開盤價"]]) if "開盤價" in idx else None
                hi = to_f(r[idx["最高價"]]) if "最高價" in idx else None
                lo = to_f(r[idx["最低價"]]) if "最低價" in idx else None
                v = to_i(r[idx["成交股數"]]) if "成交股數" in idx else 0
                if c is None:
                    continue
                names[code] = r[idx["證券名稱"]].strip()
                hist[code].append({"date": ds, "open": o, "high": hi,
                                   "low": lo, "close": c, "volume": v})
            got += 1
            if got % 20 == 0:
                log(f"  已取得 {got} 個交易日")
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.35)
    for c in hist:
        hist[c].sort(key=lambda x: x["date"])
    log(f"  全市場行情：{got} 個交易日、{len(hist)} 檔")
    return hist, names


def market_institutional(days=20, use_cache=True):
    """全市場三大法人買賣超（T86 一次回傳全部個股）。"""
    out = defaultdict(list)
    d = datetime.now()
    got = tries = 0
    while got < days and tries < days * 2:
        tries += 1
        ds = f"{d:%Y%m%d}"
        d -= timedelta(days=1)
        if datetime.strptime(ds, "%Y%m%d").weekday() >= 5:
            continue
        try:
            j = json.loads(fetch(
                f"https://www.twse.com.tw/rwd/zh/fund/T86"
                f"?date={ds}&selectType=ALL&response=json",
                cache_key=f"t86_{ds}.json", use_cache=use_cache, timeout=60))
            if j.get("stat") != "OK":
                continue
            f = j["fields"]
            fi = next((i for i, x in enumerate(f) if "外陸資買賣超" in x or "外資買賣超" in x), None)
            ti = next((i for i, x in enumerate(f) if "投信買賣超" in x), None)
            for r in j["data"]:
                code = r[0].strip()
                out[code].append({
                    "date": ds,
                    "foreign": to_i(r[fi]) if fi is not None else 0,
                    "trust": to_i(r[ti]) if ti is not None else 0,
                })
            got += 1
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.35)
    for c in out:
        out[c].sort(key=lambda x: x["date"])
    log(f"  三大法人：{got} 個交易日")
    return out


def market_valuation(use_cache=True):
    """本益比、殖利率、股價淨值比（全市場）。"""
    try:
        j = json.loads(fetch(
            "https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_ALL?response=json",
            cache_key="bwibbu.json", use_cache=use_cache, timeout=60))
        out = {}
        for r in j.get("data", []):
            out[r[0].strip()] = {
                "pe": to_f(r[2]), "yield": to_f(r[3]), "pb": to_f(r[4]),
            }
        log(f"  評價指標：{len(out)} 檔")
        return out
    except Exception as e:  # noqa: BLE001
        log(f"  評價指標：✗ {e}")
        return {}


def market_revenue(use_cache=True):
    """全市場月營收。"""
    try:
        rows = json.loads(fetch(
            "https://openapi.twse.com.tw/v1/opendata/t187ap05_L",
            cache_key="rev.json", use_cache=use_cache, timeout=90))
        out = {}
        for r in rows:
            code = str(r.get("公司代號", "")).strip()
            out[code] = {
                "yoy": to_f(r.get("營業收入-去年同月增減(%)")),
                "cum_yoy": to_f(r.get("累計營業收入-前期比較增減(%)")),
                "industry": r.get("產業別", ""),
            }
        log(f"  月營收：{len(out)} 檔")
        return out
    except Exception as e:  # noqa: BLE001
        log(f"  月營收：✗ {e}")
        return {}


def market_tdcc(use_cache=True):
    """集保股權分散表。同時存檔，累積成歷史以便日後看流向。"""
    try:
        raw = fetch("https://opendata.tdcc.com.tw/getOD.ashx?id=1-5",
                    cache_key="tdcc.csv", use_cache=use_cache, timeout=150)
        rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig", "replace"))))
        agg = {}
        date = rows[0]["資料日期"] if rows else ""
        for r in rows:
            code = r["證券代號"].strip()
            lvl = r["持股分級"].strip()
            a = agg.setdefault(code, {"big_pct": 0.0, "holders": 0})
            if lvl in ("12", "13", "14", "15"):
                a["big_pct"] += float(r["占集保庫存數比例%"] or 0)
            elif lvl == "17":
                a["holders"] = int(r["人數"] or 0)
        # 存快照，未來就能比對流向
        TDCC_HIST.mkdir(parents=True, exist_ok=True)
        snap = TDCC_HIST / f"{date}.json"
        if not snap.exists():
            snap.write_text(json.dumps(agg, ensure_ascii=False), encoding="utf-8")
        hist_files = sorted(TDCC_HIST.glob("*.json"))
        log(f"  集保：{len(agg)} 檔（資料日 {date}；已累積 {len(hist_files)} 週快照）")
        return agg, date, hist_files
    except Exception as e:  # noqa: BLE001
        log(f"  集保：✗ {e}")
        return {}, "", []


# ---------------------------------------------------------------- 指標

def sma(xs, n):
    return sum(xs[-n:]) / n if len(xs) >= n else None


def weekly_closes(rows):
    out, cur = [], None
    for r in rows:
        dt = datetime.strptime(r["date"], "%Y%m%d")
        wk = dt.isocalendar()[:2]
        if wk != cur:
            out.append(r["close"])
            cur = wk
        else:
            out[-1] = r["close"]
    return out


def analyse(rows):
    """算出十字口訣需要的指標。"""
    if len(rows) < 100:
        return None
    closes = [r["close"] for r in rows]
    vols = [r["volume"] for r in rows]
    last = closes[-1]
    wc = weekly_closes(rows)

    ma20 = sma(closes, 20)
    ma60 = sma(closes, 60)
    ma20w = sma(wc, 20)
    if not all([ma20, ma60, ma20w]):
        return None

    mas = [ma20, ma60, ma20w]
    converge = (max(mas) - min(mas)) / min(mas) * 100      # 均線糾結程度

    v20 = sma(vols, 20)
    v60 = sma(vols, 60)
    vol_ratio = v20 / v60 if v60 else None                  # <1 代表量縮

    win = rows[-60:]
    hi = max(r["high"] or r["close"] for r in win)
    lo = min(r["low"] or r["close"] for r in win)
    amplitude = (hi - lo) / lo * 100                        # 60 日振幅

    span = rows[-250:] if len(rows) >= 250 else rows
    h52 = max(r["high"] or r["close"] for r in span)
    l52 = min(r["low"] or r["close"] for r in span)
    pos = (last - l52) / (h52 - l52) * 100 if h52 > l52 else None

    return {
        "close": last, "ma20": ma20, "ma60": ma60, "ma20w": ma20w,
        "converge": converge,
        "bias20w": (last - ma20w) / ma20w * 100,
        "bias60": (last - ma60) / ma60 * 100,
        "vol_ratio": vol_ratio, "amplitude": amplitude,
        "pos52": pos, "avg_vol20": v20,
    }


def chip_score(inst_rows, avg_vol):
    """大戶加碼的代理指標：法人連續與淨買超。"""
    if not inst_rows:
        return None
    recent = inst_rows[-10:]
    f_net = sum(x["foreign"] for x in recent)
    t_net = sum(x["trust"] for x in recent)
    streak = 0
    for x in reversed(inst_rows):
        if x["foreign"] > 0:
            streak += 1
        else:
            break
    buy_days = sum(1 for x in recent if x["foreign"] > 0)
    ratio = f_net / (avg_vol * len(recent)) * 100 if avg_vol else 0
    return {"f_net": f_net, "t_net": t_net, "streak": streak,
            "buy_days": buy_days, "ratio": ratio}


# ---------------------------------------------------------------- 篩選

def screen(hist, names, inst, val, rev, tdcc, tdcc_hist, cfg):
    """三關篩選：價平量平 → 大戶加碼 → 體質過濾。"""
    # 若已累積兩週以上集保快照，就能算真正的大戶流向
    prev_tdcc = {}
    if len(tdcc_hist) >= 2:
        prev_tdcc = json.loads(tdcc_hist[-2].read_text(encoding="utf-8"))

    results = []
    stats = defaultdict(int)
    for code, rows in hist.items():
        if len(code) != 4 or not code.isdigit() or code.startswith(EXCLUDE_PREFIX):
            continue
        stats["候選"] += 1
        a = analyse(rows)
        if not a:
            stats["資料不足"] += 1
            continue

        # ── 第一關：價平量平 ──────────────────────────
        if a["converge"] > cfg["converge"]:
            stats["均線未糾結"] += 1
            continue
        if a["amplitude"] > cfg["amplitude"]:
            stats["振幅過大"] += 1
            continue
        if abs(a["bias60"]) > cfg["bias"]:
            stats["乖離過大"] += 1
            continue
        if a["vol_ratio"] and a["vol_ratio"] > cfg["vol_ratio"]:
            stats["量未縮"] += 1
            continue
        if cfg["above_20w"] and a["close"] < a["ma20w"] * 0.97:
            stats["未站上20週線"] += 1
            continue
        # 基期要低。第 32 期外資籌碼選股明列「基期低」，
        # 第 24 期心法：低基期大機會起漲，高基期大機會是最後絢麗的煙火。
        if a["pos52"] is not None and a["pos52"] > cfg["max_pos"]:
            stats["基期過高"] += 1
            continue

        # ── 第二關：大戶加碼 ──────────────────────────
        c = chip_score(inst.get(code, []), a["avg_vol20"])
        if not c or c["f_net"] <= 0 or c["buy_days"] < cfg["buy_days"]:
            stats["法人未加碼"] += 1
            continue

        # 集保大戶流向（累積兩週以上才有）
        big_now = (tdcc.get(code) or {}).get("big_pct")
        big_prev = (prev_tdcc.get(code) or {}).get("big_pct")
        big_chg = (big_now - big_prev) if (big_now and big_prev) else None
        holders_now = (tdcc.get(code) or {}).get("holders")
        holders_prev = (prev_tdcc.get(code) or {}).get("holders")
        holders_chg = (holders_now - holders_prev) if (holders_now and holders_prev) else None
        if big_chg is not None and big_chg < 0:
            stats["大戶減碼"] += 1
            continue

        # ── 第三關：體質 ────────────────────────────
        r = rev.get(code, {})
        v = val.get(code, {})
        if cfg["need_revenue"] and (r.get("yoy") is None or r["yoy"] < 0):
            stats["營收衰退"] += 1
            continue
        if cfg["need_yield"] and not (v.get("yield") or 0) > 0:
            stats["無配息"] += 1
            continue

        # ── 評分 ──────────────────────────────────
        score = 0.0
        score += max(0, (cfg["converge"] - a["converge"])) * 3   # 越糾結越好
        score += min(c["streak"], 5) * 4                          # 連續買超天數
        score += min(c["ratio"], 10) * 2                          # 買超佔量比重
        score += max(0, 100 - (a["pos52"] or 100)) * 0.15        # 位階越低越好
        if a["vol_ratio"]:
            score += max(0, (1 - a["vol_ratio"])) * 15            # 量縮程度
        if big_chg:
            score += big_chg * 10
        if c["t_net"] > 0:
            score += 5                                            # 投信同向
        if (r.get("yoy") or 0) > 0:
            score += min(r["yoy"] / 5, 6)

        results.append({
            "code": code, "name": names.get(code, ""), "a": a, "c": c,
            "rev": r, "val": v, "score": score,
            "big_pct": big_now, "big_chg": big_chg, "holders_chg": holders_chg,
        })
        stats["入選"] += 1

    results.sort(key=lambda x: -x["score"])
    return results, stats


def build_report(results, stats, cfg, tdcc_date, snapshots, top):
    now = datetime.now()
    L = [
        "---",
        f"title: 潛龍名單 {now:%Y-%m-%d}",
        "type: 選股結果",
        f"generated: {now:%Y-%m-%d %H:%M}",
        "generator: 000_Agent/scripts/screener.py",
        "strategy: 十字口訣（價平量平，大戶持續加碼）",
        "tags:",
        "  - 投資",
        "  - 選股",
        "---",
        "",
        f"# 潛龍名單｜{now:%Y-%m-%d}",
        "",
        "> [!warning] 這是口袋名單，不是買進清單",
        "> 依 [[大戶籌碼選股術]]，篩出來只是第一步。宏爺的流程是：",
        "> **口袋名單 → 等利空不跌驗證 → 長紅突破才進場**。",
        "> 我不是持牌投資顧問，這裡不提供買賣建議。",
        "",
        "## 這次用的條件",
        "",
        "| 關卡 | 條件 | 設定 |",
        "| :--- | :--- | ---: |",
        f"| 價平 | 月線／季線／20週均線 收斂度 ≤ | {cfg['converge']}% |",
        f"| 價平 | 60 日振幅 ≤ | {cfg['amplitude']}% |",
        f"| 價平 | 對季線乖離 ≤ | ±{cfg['bias']}% |",
        f"| 量平 | 20日均量 ÷ 60日均量 ≤ | {cfg['vol_ratio']} |",
        f"| 位置 | 站上 20 週均線 | {'是' if cfg['above_20w'] else '不限'} |",
        f"| 位階 | 52 週區間位置 ≤ | {cfg['max_pos']}% |",
        f"| 大戶 | 近 10 日外資買超天數 ≥ | {cfg['buy_days']} 天 |",
        f"| 體質 | 月營收 YoY > 0 | {'是' if cfg['need_revenue'] else '不限'} |",
        f"| 體質 | 有配息 | {'是' if cfg['need_yield'] else '不限'} |",
        "",
        "## 漏斗",
        "",
        "| 階段 | 檔數 |",
        "| :--- | ---: |",
    ]
    for k in ["候選", "資料不足", "均線未糾結", "振幅過大", "乖離過大", "量未縮",
              "未站上20週線", "基期過高", "法人未加碼", "大戶減碼",
              "營收衰退", "無配息", "入選"]:
        if stats.get(k):
            L.append(f"| {k} | {stats[k]} |")
    L.append("")

    if not results:
        L += ["## 結果", "", "**本次沒有標的通過全部條件。**", "",
              "這不一定是壞事——[[大戶籌碼選股術]] 的條件本來就嚴苛，"
              "宏爺自己也說「好的股票不是選一次就會遇到」。",
              "可以用 `--loose` 放寬後再跑一次看看邊緣標的。", ""]
    else:
        L += [
            f"## 入選 {len(results)} 檔（依分數排序，列出前 {min(top, len(results))} 檔）",
            "",
            "| # | 代號 | 名稱 | 收盤 | 均線糾結 | 20週乖離 | 量縮比 | 52週位階 | 外資10日 | 連買 | 營收YoY | 殖利率 |",
            "| ---: | :--- | :--- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
        for i, r in enumerate(results[:top], 1):
            a, c, v = r["a"], r["c"], r["val"]
            yoy = r["rev"].get("yoy")
            L.append(
                f"| {i} | **{r['code']}** | {r['name']} | {a['close']:.2f} "
                f"| {a['converge']:.1f}% | {a['bias20w']:+.1f}% "
                f"| {a['vol_ratio']:.2f} | {a['pos52']:.0f}% "
                f"| {c['f_net'] / 1000:+,.0f}張 | {c['streak']}天 "
                f"| {yoy:+.1f}% | {v.get('yield') or 0:.2f}% |"
            )
        L += ["", "### 產業分布", "", "| 產業 | 檔數 |", "| :--- | ---: |"]
        ind = defaultdict(int)
        for r in results:
            ind[r["rev"].get("industry") or "（未分類）"] += 1
        for k, n in sorted(ind.items(), key=lambda x: -x[1]):
            L.append(f"| {k} | {n} |")
        L.append("")

    L += [
        "## 欄位怎麼看",
        "",
        "| 欄位 | 含義 | 依據 |",
        "| :--- | :--- | :--- |",
        "| 均線糾結 | 三條均線的最大差距百分比，**越小代表成本越集中** | [[大漲的訊號]] |",
        "| 20週乖離 | 對 20 週均線的偏離 | [[乖離率]]、[[雙均線控盤]] |",
        "| 量縮比 | 20日均量÷60日均量，**小於 1 代表量縮** | [[量價關係與背離]] |",
        "| 52週位階 | 現價在近 52 週高低區間的位置 | [[基期位階判斷五法]] |",
        "| 外資10日／連買 | 大戶加碼的代理指標 | [[大戶籌碼選股術]] |",
        "",
        "> [!important] 下一步該做什麼",
        "> 這份名單只完成了「價平量平＋大戶加碼」。接著要：",
        "> 1. 逐檔跑 `stock-fetch.py <代號>` 看完整資料",
        "> 2. 檢查產業是不是「過去很少、現在開始、未來很多」——**這關要你判斷**",
        "> 3. 等**利空不跌**驗證籌碼強度",
        "> 4. 等**長紅突破**才是進場訊號（[[大漲的訊號]]）",
        "",
    ]

    if snapshots < 2:
        L += [
            "> [!note] 大戶流向尚未啟用",
            f"> 集保開放資料只有最新一週（資料日 {tdcc_date}），目前累積 {snapshots} 週快照。",
            "> 本次的「大戶加碼」是用**三大法人連續買超**代理。"
            "每週跑一次，累積兩週以上之後就會自動改用真正的大戶持股率變化。",
            "",
        ]

    L += ["## 相關", "", "- [[大戶籌碼選股術]]｜十字口訣的完整流程",
          "- [[判讀SOP]]｜挑出標的後怎麼分析", "- [[資料蒐集SOP]]", ""]
    return "\n".join(L)


def main():
    p = argparse.ArgumentParser(description="潛龍股篩選器（十字口訣核心版）")
    p.add_argument("--days", type=int, default=130, help="行情天數（20週均線需約 100 天）")
    p.add_argument("--inst-days", type=int, default=20, help="法人資料天數")
    p.add_argument("--top", type=int, default=40, help="報表列出前幾名")
    p.add_argument("--loose", action="store_true", help="放寬條件")
    p.add_argument("--no-cache", action="store_true")
    args = p.parse_args()

    cfg = dict(converge=3.5, amplitude=35.0, bias=10.0, vol_ratio=1.0,
               above_20w=True, max_pos=45.0, buy_days=5,
               need_revenue=True, need_yield=True)
    if args.loose:
        cfg.update(converge=9.0, amplitude=50.0, bias=15.0, vol_ratio=1.25,
                   above_20w=False, max_pos=75.0, buy_days=3,
                   need_revenue=False, need_yield=False)

    use_cache = not args.no_cache
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    log("抓取全市場行情…（首次執行較久，之後有快取）")
    hist, names = market_daily(args.days, use_cache)
    if not hist:
        log("✗ 沒有取得任何行情資料")
        return 1
    log("抓取三大法人…")
    inst = market_institutional(args.inst_days, use_cache)
    log("抓取評價指標…")
    val = market_valuation(use_cache)
    log("抓取月營收…")
    rev = market_revenue(use_cache)
    log("抓取集保…")
    tdcc, tdcc_date, snaps = market_tdcc(use_cache)

    log("開始篩選…")
    results, stats = screen(hist, names, inst, val, rev, tdcc, snaps, cfg)
    log(f"入選 {len(results)} 檔")

    out = OUT_DIR / f"潛龍名單_{datetime.now():%Y-%m-%d}.md"
    out.write_text(build_report(results, stats, cfg, tdcc_date, len(snaps), args.top),
                   encoding="utf-8")
    log(f"完成 → {out}")
    for r in results[:10]:
        a = r["a"]
        print(f"    {r['code']} {r['name']:6} 收{a['close']:>7.2f} "
              f"糾結{a['converge']:>5.1f}% 位階{a['pos52']:>3.0f}% "
              f"外資{r['c']['f_net'] / 1000:>+7.0f}張 分數{r['score']:.0f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
