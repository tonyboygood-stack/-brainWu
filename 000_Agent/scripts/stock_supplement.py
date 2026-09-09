"""Public-source supplement with dated evidence, explicit gaps and raw snapshots.

No credentials required. FINMIND_TOKEN is optional and never saved or printed.
Run: python stock_supplement.py 2330 --market sii
"""
import argparse
import csv
import hashlib
import io
import json
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from stock_quality import date_key, number

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / '600_Projects/投資/個股/_data'
CACHE = DATA / '.cache/supplement'
UA = 'Mozilla/5.0 (compatible; PublicMarketResearch/1.0)'


def _ssl_context():
    """保留憑證驗證，但用 certifi 的 CA bundle。

    證交所與櫃買的憑證缺 Subject Key Identifier，新版 OpenSSL 預設信任庫
    會拒絕。certifi 驗得過，因此不必停用驗證。
    """
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # noqa: BLE001
        return ssl.create_default_context()


SSL_CTX = _ssl_context()


def request(url, use_cache=True, finmind=False):
    """A one-hour cache. Error responses never masquerade as successful data."""
    key = hashlib.sha256(url.encode()).hexdigest()
    path = CACHE / (key + '.json')
    now = datetime.now()
    if use_cache and path.exists():
        saved = json.loads(path.read_text(encoding='utf-8'))
        if (now - datetime.fromisoformat(saved['fetched_at'])).total_seconds() < 3600:
            return saved
    headers = {'User-Agent': UA}
    if finmind and os.environ.get('FINMIND_TOKEN'):
        headers['Authorization'] = 'Bearer ' + os.environ['FINMIND_TOKEN']
    for attempt in range(2):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers),
                                        timeout=25, context=SSL_CTX) as response:
                text = response.read().decode('utf-8-sig')
            break
        except urllib.error.HTTPError as e:
            if e.code == 400 and finmind:
                raise RuntimeError('來源拒絕：需會員權限或參數不被接受（HTTP 400）') from None
            if e.code not in (429, 502, 503, 504) or attempt:
                raise RuntimeError(f'來源 HTTP {e.code}') from None
            time.sleep(1)
    saved = {'source': url, 'fetched_at': now.isoformat(timespec='seconds'), 'text': text}
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(saved, ensure_ascii=False), encoding='utf-8')
    return saved


def json_data(url, use_cache=True, finmind=False):
    response = request(url, use_cache, finmind)
    payload = json.loads(response['text'])
    if finmind:
        if payload.get('status') != 200:
            raise RuntimeError('FinMind 未提供成功資料；權限或使用額度待確認')
        payload = payload.get('data')
    return payload, response['fetched_at']


def evidence(label, url, loader, use_cache=True):
    try:
        rows, fetched = loader(url, use_cache)
        if not isinstance(rows, list):
            raise ValueError('回應不是資料列')
        dates = sorted({str(r[k]) for r in rows for k in
                        ('date', 'Date', '日期', '資料日期', '資料年月', '發言日期', '出表日期') if r.get(k)})
        return dict(label=label, source=url, fetched_at=fetched, status='已取得' if rows else '查詢成功；無符合資料',
                    dates=dates, rows=rows)
    except Exception as e:
        return dict(label=label, source=url, fetched_at=datetime.now().isoformat(timespec='seconds'),
                    status='未取得：' + str(e)[:160], dates=[], rows=[])


def finmind_url(dataset, code, years=3):
    start = (datetime.now() - timedelta(days=int(years * 366))).strftime('%Y-%m-%d')
    return 'https://api.finmindtrade.com/api/v4/data?' + urllib.parse.urlencode(
        dict(dataset=dataset, data_id=code, start_date=start))


def otc_history(code, days=20, kind='institutional', use_cache=True):
    out, errors = [], []
    d = datetime.now()
    for _ in range(days * 3 + 10):
        if len(out) >= days:
            break
        day = d.strftime('%Y%m%d')
        query_date = d.strftime('%Y/%m/%d')
        weekday = d.weekday()
        d -= timedelta(days=1)
        if weekday >= 5:
            continue
        endpoint = 'insti/dailyTrade' if kind == 'institutional' else 'margin/balance'
        url = f'https://www.tpex.org.tw/www/zh-tw/{endpoint}?' + urllib.parse.urlencode(
            dict(date=query_date, type='Daily', response='json'))
        try:
            j, _ = json_data(url, use_cache)
            table = next((t for t in j.get('tables', []) if t.get('data')), None)
            if not table:
                continue
            if date_key(table.get('date') or j.get('date')) != day:
                raise ValueError('回傳日期與要求日期不一致')
            row = next((r for r in table['data'] if str(r[0]).strip() == code), None)
            if not row:
                continue
            fields = table.get('fields', [])
            if kind == 'institutional':
                # The official table has seven 3-column groups; aggregate foreign,
                # trust and dealer groups are 8..10, 11..13, 20..22.
                if len(fields) != 24 or fields[-1] != '三大法人買賣超股數合計':
                    raise ValueError('上櫃法人欄位結構改變')
                values = [number(row[i]) for i in (10, 13, 22, 23)]
                if any(v is None for v in values) or sum(values[:3]) != values[3]:
                    raise ValueError('上櫃法人合計檢查失敗')
                out.append(dict(date=day, **dict(zip(('foreign', 'trust', 'dealer', 'total'), map(int, values)))))
            else:
                mapped = dict(zip(fields, row))
                values = [number(mapped.get(k)) for k in ('資餘額', '前資餘額(張)', '券餘額')]
                if any(v is None for v in values):
                    raise ValueError('上櫃融資融券欄位缺漏')
                out.append(dict(date=day, balance=int(values[0]), prev=int(values[1]), short_balance=int(values[2])))
        except Exception as e:
            errors.append(f'{day}: {e}')
        time.sleep(0.2)
    print(f'上櫃 {kind}: {len(out)}/{days} 日；錯誤 {len(errors)} 次', flush=True)
    if errors:
        print(errors[0], flush=True)
    return sorted(out, key=lambda r: r['date'])


def fred_loader(url, use_cache):
    response = request(url, use_cache)
    rows = list(csv.DictReader(io.StringIO(response['text'])))
    if not rows or 'observation_date' not in rows[0]:
        raise ValueError('FRED 欄位不符')
    series = next(k for k in rows[0] if k != 'observation_date')
    return [dict(date=r['observation_date'], value=number(r[series])) for r in rows
            if number(r[series]) is not None], response['fetched_at']


def tdcc_loader(url, use_cache):
    response = request(url, use_cache)
    rows = list(csv.DictReader(io.StringIO(response['text'])))
    if not rows or '持股分級' not in rows[0]:
        raise ValueError('集保欄位不符')
    return rows, response['fetched_at']


def save_tdcc_history(code, rows):
    directory = DATA / '.cache/tdcc_by_stock' / code
    directory.mkdir(parents=True, exist_ok=True)
    hit = [r for r in rows if str(r.get('證券代號', '')).strip() == code]
    dates = {date_key(r.get('資料日期')) for r in hit}
    if len(dates) == 1 and None not in dates:
        day = next(iter(dates))
        (directory / f'{day}.json').write_text(json.dumps(hit, ensure_ascii=False), encoding='utf-8')
    snapshots = []
    for path in sorted(directory.glob('*.json')):
        rs = json.loads(path.read_text(encoding='utf-8'))
        by = {str(r['持股分級']).strip(): r for r in rs}
        if not all(k in by for k in ('12', '13', '14', '15', '17')):
            continue
        snapshots.append(dict(date=path.stem, big_pct=sum(float(by[k]['占集保庫存數比例%']) for k in ('12','13','14','15')),
                              huge_pct=float(by['15']['占集保庫存數比例%']), holders=int(by['17']['人數'])))
    return snapshots


def collect(code, market='sii', use_cache=True):
    results = []
    base = 'https://openapi.twse.com.tw/v1/opendata/' if market == 'sii' else 'https://www.tpex.org.tw/openapi/v1/mopsfin_'
    suffix = 'L' if market == 'sii' else 'O'
    for label, dataset in [('董監持股與質押', 't187ap11'), ('重大訊息（當日公告）', 't187ap04'),
                           ('內部人轉讓申報（不等於已賣出）', 't187ap12')]:
        def loader(url, cache):
            rows, fetched = json_data(url, cache)
            if not isinstance(rows, list):
                raise ValueError('官方欄位結構改變')
            return [r for r in rows if str(r.get('公司代號', r.get('SecuritiesCompanyCode', ''))).strip() == code], fetched
        results.append(evidence(label, base + dataset + '_' + suffix, loader, use_cache))

    for label, dataset, years in [('歷季損益', 'TaiwanStockFinancialStatements', 3),
                                  ('歷季資產負債', 'TaiwanStockBalanceSheet', 3),
                                  ('歷季現金流', 'TaiwanStockCashFlowsStatement', 3),
                                  ('歷年月營收', 'TaiwanStockMonthRevenue', 3),
                                  ('除權息事件', 'TaiwanStockDividendResult', 6),
                                  ('集保歷史（FinMind）', 'TaiwanStockHoldingSharesPer', 0.3)]:
        url = finmind_url(dataset, code, years)
        results.append(evidence(label, url, lambda u, c: json_data(u, c, True), use_cache))

    tdcc = evidence('集保官方快照', 'https://opendata.tdcc.com.tw/getOD.ashx?id=1-5', tdcc_loader, use_cache)
    if tdcc['rows']:
        history = save_tdcc_history(code, tdcc['rows'])
        tdcc['rows'] = [r for r in tdcc['rows'] if str(r.get('證券代號', '')).strip() == code]
        tdcc['dates'] = sorted({r['資料日期'] for r in tdcc['rows']})
        results.append(dict(label='集保本機週次累積', source=tdcc['source'], fetched_at=tdcc['fetched_at'],
                            status='已有多週；需核對連續性' if len(history) >= 2 else '不足兩週；不能確認流向',
                            dates=[r['date'] for r in history], rows=history))
    results.append(tdcc)

    for label, endpoint in [('法人期貨部位', 'MarketDataOfMajorInstitutionalTradersDetailsOfFuturesContractsBytheDate'),
                            ('法人選擇權部位', 'MarketDataOfMajorInstitutionalTradersDetailsOfOptionsContractsBytheDate'),
                            ('買權賣權分計', 'MarketDataOfMajorInstitutionalTradersDetailsOfCallsAndPutsBytheDate'),
                            ('期交所外幣參考匯率', 'DailyForeignExchangeRates')]:
        results.append(evidence(label, 'https://openapi.taifex.com.tw/v1/' + endpoint, json_data, use_cache))

    for series, label in [('DFF', '有效聯邦基金利率（%）'), ('DGS10', '美債10年殖利率（%）'),
                           ('DTWEXBGS', '廣義美元指數（非DXY）'), ('DEXTAUS', '美元兌台幣（台幣／美元）'),
                           ('CPIAUCSL', '美國CPI指數'), ('M2SL', '美國M2（十億美元）'),
                           ('UNRATE', '美國失業率（%）')]:
        url = 'https://fred.stlouisfed.org/graph/fredgraph.csv?' + urllib.parse.urlencode(
            dict(id=series, cosd=(datetime.now() - timedelta(days=800)).strftime('%Y-%m-%d')))
        results.append(evidence(label, url, fred_loader, use_cache))

    # Market-level daily series supplied independently of the individual stock.
    for label, endpoint in [('加權指數（當月）', 'FMTQIK')]:
        url = f'https://www.twse.com.tw/rwd/zh/afterTrading/{endpoint}?response=json'
        def index_loader(u, c):
            j, fetched = json_data(u, c)
            if j.get('stat') != 'OK':
                raise ValueError('大盤行情未回傳成功')
            return [dict(zip(j['fields'], r)) for r in j['data']], fetched
        results.append(evidence(label, url, index_loader, use_cache))

    DATA.mkdir(parents=True, exist_ok=True)
    bundle = dict(code=code, market=market, generated=datetime.now().isoformat(timespec='seconds'), sources=results)
    (DATA / f'{code}_supplement.json').write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding='utf-8')
    return bundle


def cell(value):
    return str(value).replace('|', '／').replace('\n', ' ').replace('\r', ' ')


def render(bundle):
    lines = ['## 補充資料與來源稽核', '', f'蒐集時間：{bundle["generated"]}', '',
             '> 已取得只表示有資料，不表示足以判斷。資料期末日不等於公告日；不得直接用於無前視偏誤的回測。',
             '> 每一來源均保留原始列於同代號 `_supplement.json`；下列只顯示摘要。', '',
             '| 資料 | 取得狀態 | 筆數 | 來源資料日期 |', '| :--- | :--- | ---: | :--- |']
    for item in bundle['sources']:
        dates = item['dates']
        lines.append(f'| [{item["label"]}]({item["source"]}) | {cell(item["status"])} | {len(item["rows"])} | {dates[0] if dates else "未提供"}～{dates[-1] if dates else "未提供"} |')
    for item in bundle['sources']:
        rows, label = item['rows'], item['label']
        if not rows:
            continue
        lines += ['', f'### {label}', '', f'來源擷取：{item["fetched_at"]}', '']
        if 'type' in rows[0] and 'value' in rows[0]:
            latest = sorted({r['date'] for r in rows})[-8:]
            wanted = ('CashFlowsFromOperatingActivities', 'PropertyAndPlantAndEquipment',
                      'CashProvidedByInvestingActivities', 'CashFlowsProvidedFromFinancingActivities',
                      'EPS', 'Revenue', 'IncomeAfterTaxes', 'TotalAssets', 'TotalLiabilities',
                      'Liabilities', 'CashAndCashEquivalents', 'CurrentAssets', 'CurrentLiabilities',
                      'Equity', 'OperatingIncome', 'GrossProfit')
            selected = [r for r in rows if r['date'] in latest and r['type'] in wanted]
            lines += ['> 原始財報值：EPS為元／股，其餘金額依來源為元。現金流各期是否累計須核對，不直接相加；EPS亦不直接跨季相加。', '']
            if not selected:
                selected = rows[-12:]
            columns = ['date', 'type', 'origin_name', 'value']
        elif rows[0].keys() == {'date', 'value'}:
            selected = rows[-5:]
            columns = ['date', 'value']
            latest = date_key(selected[-1]['date'])
            age = (datetime.now() - datetime.strptime(latest, '%Y%m%d')).days
            limit = 65 if any(t in label for t in ('CPI', 'M2', '失業率')) else 10
            if age > limit:
                lines += [f'> 資料距今 {age} 日，超出更新容許期間；不可當成目前值。', '']
        elif label.startswith('法人') or label == '買權賣權分計':
            selected = [r for r in rows if '外資' in str(r.get('Item', ''))]
            if not selected:
                selected = rows[:12]
            columns = [k for k in rows[0] if k in ('Date', 'ContractCode', 'Item') or 'OpenInterest' in k or 'Call' in k or 'Put' in k]
            lines += ['> 各契約分開列示，不將大台／小台／微台口數直接相加，也不套用未確認的換算係數。', '']
        else:
            selected = sorted(rows, key=lambda r: str(r.get('date', r.get('Date', ''))))[-12:]
            columns = list(rows[0])
        lines += ['| ' + ' | '.join(map(cell, columns)) + ' |', '| ' + ' | '.join([':---'] * len(columns)) + ' |']
        for row in selected:
            lines.append('| ' + ' | '.join(cell(row.get(k, '—')) for k in columns) + ' |')
    lines += ['', '### 尚待補足的評估證據', '',
              '- 分點歷史與經驗證集中度、外資成本線：尚未接入；代理值不得冒充。',
              '- 法說會簡報／影音內容及產業競爭分析：清單不代表完成閱讀。',
              '- 重大訊息為當日快照；空資料不代表公司沒有歷史事件。',
              '- 股價目前未還原：除權息、減資、分割需另核對，相關期間技術訊號為待確認。',
              '- 個人持股、成本、現金、借款與風險預算：需本人資料，不能從公開市場推測。', '']
    return '\n'.join(lines)


def main():
    p = argparse.ArgumentParser(description='宏爺股票助手補充資料')
    p.add_argument('code')
    p.add_argument('--market', choices=['sii', 'otc'], default='sii')
    p.add_argument('--no-cache', action='store_true')
    args = p.parse_args()
    if not args.code.isdigit():
        p.error('股票代號須為數字')
    bundle = collect(args.code, args.market, not args.no_cache)
    path = DATA / f'{args.code}_supplement.md'
    path.write_text(render(bundle), encoding='utf-8')
    for source in bundle['sources']:
        print(source['label'], source['status'], len(source['rows']), flush=True)
    print(path)


if __name__ == '__main__':
    main()
