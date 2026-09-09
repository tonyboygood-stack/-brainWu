"""Shared, conservative validation for market data (standard library only)."""
import math
import re
from datetime import datetime, timedelta


def date_key(value):
    s = str(value).strip()
    parts = re.split(r'[/.-]', s[:10])
    try:
        if len(parts) == 3:
            y, m, d = map(int, parts)
        elif len(s) in (7, 8) and s.isdigit():
            y, m, d = int(s[:-4]), int(s[-4:-2]), int(s[-2:])
        else:
            return None
        return datetime(y + 1911 if y < 1911 else y, m, d).strftime('%Y%m%d')
    except ValueError:
        return None


def number(value):
    try:
        n = float(str(value).replace(',', '').strip())
        return n if math.isfinite(n) else None
    except (ValueError, TypeError):
        return None


def aligned_flow(cmoney, daily, windows=(20, 60, 120)):
    """Proxy only; require identical full windows, unique dates, and numeric values."""
    flows, volumes = {}, {}
    for r in (cmoney or {}).get('mainforceoverbuy', []):
        key = date_key(r.get('Date'))
        if not key or key in flows:
            return {}
        flows[key] = number(r.get('OverBuy'))
    for r in daily:
        key = date_key(r.get('date'))
        if not key or key in volumes:
            return {}
        volumes[key] = number(r.get('volume'))
    out = {}
    for w in windows:
        dates = sorted(flows)[-w:]
        if len(dates) != w or dates != sorted(volumes)[-w:]:
            continue
        if any(flows[d] is None or volumes[d] is None or volumes[d] < 0 for d in dates):
            continue
        vol = sum(volumes[d] for d in dates) / 1000
        if vol <= 0:
            continue
        net = sum(flows[d] for d in dates)
        out[w] = dict(net_lots=net, volume_lots=vol, pct=net / vol * 100,
                      start=dates[0], end=dates[-1], matched_days=w, proxy=True)
    return out


def full_year(rows):
    dates = sorted(filter(None, (date_key(r.get('date')) for r in rows)))
    return bool(len(dates) >= 200 and
                (datetime.strptime(dates[-1], '%Y%m%d') -
                 datetime.strptime(dates[0], '%Y%m%d')).days >= 350)


def quality_markdown(api, daily, inst, tdcc, cmoney, conf, divs, margin,
                     expected_days=20):
    lines = ['## 資料品質與評估限制', '',
             '> 尚非完整六層評估。缺資料＝未確認，不代表中性、零或通過。',
             '> 股價未還原除權息；本週／本月 K 為暫定值，不能當成收週／收月突破。', '',
             '| 項目 | 狀態 | 筆數／日期 |', '| :--- | :--- | :--- |']
    datasets = [('日行情', daily, 'date', 200), ('法人買賣超', inst, 'date', expected_days),
                ('融資', margin or [], 'date', expected_days),
                ('集保單週', tdcc, '資料日期', 1),
                ('主力買賣超', (cmoney or {}).get('mainforceoverbuy', []), 'Date', 60),
                ('買賣家數差', (cmoney or {}).get('tradersum', []), 'Date', 20),
                ('法說清單（非內容）', (conf or {}).get('list', []) if isinstance(conf, dict) else [], 'date', 1),
                ('EPS／股利', divs or [], 'year', 1)]
    for label, rows, field, required in datasets:
        dates = sorted(str(r.get(field, '')) for r in rows)
        status = '已取得；仍須核對期間' if len(rows) >= required else '不足／未取得'
        latest = date_key(dates[-1]) if dates else None
        if latest and label not in ('法說清單（非內容）', 'EPS／股利'):
            age = (datetime.now() - datetime.strptime(latest, '%Y%m%d')).days
            if age > (10 if label == '集保單週' else 7):
                status = '過期；不可當成目前狀況'
        lines.append(f'| {label} | {status} | {len(rows)} 筆；{dates[0] if dates else "—"}～{dates[-1] if dates else "—"} |')
        if getattr(rows, 'source', None):
            lines.append(f'| {label}來源 | {rows.source} | — |')
    for label in ('基本資料', '月營收', '綜合損益', '資產負債'):
        row = api.get(label) or {}
        period = '；'.join(f'{k}={v}' for k, v in row.items() if any(x in k for x in ('日期', '年度', '季別', '年月')))
        lines.append(f'| {label} | {"已取得快照" if row else "未取得"} | {period or "期間待確認"} |')
    if not full_year(daily):
        lines += ['', '> 52 週資料不足：不提供 52 週位階結論。']
    if getattr(daily, 'failed_months', 0):
        lines += ['', f'> 有 {daily.failed_months} 個月份抓取失敗：停用均線、月KD及52週位階，補齊後才能判讀。']
    if getattr(daily, 'source', None):
        lines += ['', f'行情來源：{daily.source}']
    lines += ['', '> 主力淨買超占量比是代理指標，未驗證等同區間前15大分點集中度；不可套用宏爺集中度門檻。',
              '> 下方補充資料另列來源狀態。分點、產業判讀、法說內容與個人部位未確認前，不得宣稱完整評估。', '']
    return '\n'.join(lines)
