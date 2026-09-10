"""Regression checks for failures that previously changed investment conclusions."""
import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
import stock_quality as q
import stock_supplement as sup


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sf = load('stock_fetch', 'stock-fetch.py')
sc = load('screener', 'screener.py')


def series(n=20):
    dates = [(datetime(2026, 1, 1) + timedelta(days=i)).strftime('%Y%m%d') for i in range(n)]
    daily = [dict(date=d, volume=100000, open=10, high=11, low=9, close=10) for d in dates]
    flow = {'mainforceoverbuy': [dict(Date=d, OverBuy=10) for d in dates]}
    return daily, flow


class QualityTests(unittest.TestCase):
    def test_aligned_window(self):
        daily, flow = series()
        self.assertEqual(q.aligned_flow(flow, daily)[20]['pct'], 10)

    def test_missing_volume_never_produces_ratio(self):
        daily, flow = series()
        self.assertEqual(q.aligned_flow(flow, daily[:1]), {})

    def test_shifted_dates_are_not_same_period(self):
        daily, flow = series(21)
        flow['mainforceoverbuy'].pop()
        self.assertEqual(q.aligned_flow(flow, daily), {})

    def test_duplicate_and_null_not_zero(self):
        daily, flow = series()
        flow['mainforceoverbuy'][2]['OverBuy'] = None
        self.assertEqual(q.aligned_flow(flow, daily), {})
        daily, flow = series()
        daily[1]['date'] = daily[0]['date']
        self.assertEqual(q.aligned_flow(flow, daily), {})

    def test_roc_and_iso_date_alignment(self):
        self.assertEqual(q.date_key('115/09/08'), '20260908')
        self.assertEqual(q.date_key('2026-09-08'), '20260908')
        self.assertIsNone(q.date_key('2026-02-31'))

    def test_short_history_not_52_weeks(self):
        daily, _ = series(130)
        self.assertFalse(q.full_year(daily))
        self.assertIsNone(sc.analyse(daily))

    def test_failed_months_disable_ma(self):
        daily, _ = series(400)
        for r in daily:
            d = datetime.strptime(r['date'], '%Y%m%d')
            r['date'] = f'{d.year-1911}/{d.month:02d}/{d.day:02d}'
        rows = sf.PriceRows(daily, failed_months=1)
        result = sf.technicals(rows)
        self.assertTrue(all(v is None for v in result['ma'].values()))
        self.assertNotIn('52w', result)

    def test_null_dividend_does_not_shift_year(self):
        html = "categories:['2020','2021','2022','2023','2024'];data:[1,null,3,4,5],name:'EPS(元)';data:[1,2,3,4,5],name:'現金股利(元)'"
        with patch.object(sf, 'fetch', return_value=html.encode()):
            rows = sf.get_dividends('2330')
        self.assertIsNone(rows[1]['eps'])
        self.assertEqual(rows[2]['eps'], 3)

    def test_empty_report_has_gaps(self):
        result = sf.build_report('2330', {}, [], [], [])
        self.assertIn('不足／未取得', result)
        self.assertIn('缺資料＝未確認', result)

    def test_partial_cmoney_does_not_crash(self):
        result = sf.build_report('2330', {}, [], [], [], {'tradersum': [{'Date':'20260908'}]})
        self.assertIn('—', result)

    def test_null_flow_total_is_unknown(self):
        result = sf.build_report('2330', {}, [], [], [], {'mainforceoverbuy': [{'Date':'20260908', 'OverBuy':None}]})
        self.assertIn('缺值，停止加總', result)

    def test_history_internal_month_gap_is_visible(self):
        rows = [dict(date='2026-01-01', stock_id='2330', Trading_Volume=1000,
                     open=10, max=11, min=9, close=10),
                dict(date='2026-03-01', stock_id='2330', Trading_Volume=1000,
                     open=10, max=11, min=9, close=10)]
        with patch.object(sup, 'json_data', return_value=(rows, 'now')):
            result = sf.get_daily('2330', 'sii', 12)
        self.assertEqual(result.failed_months, 1)

    def test_stale_screener_snapshot_refreshes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / 'rev.json').write_bytes(b'old')
            class Response:
                def read(self): return b'new'
            with patch.object(sc, 'CACHE', root), patch.object(sc.urllib.request, 'urlopen', return_value=Response()):
                self.assertEqual(sc.fetch('https://example.org', cache_key='rev.json'), b'new')

    def test_tdcc_same_week_does_not_create_fake_trend(self):
        rows = [dict(證券代號='2330', 資料日期='20260904', 持股分級=k,
                     **{'占集保庫存數比例%':'1', '人數':'5'}) for k in ('12','13','14','15','17')]
        with tempfile.TemporaryDirectory() as td, patch.object(sup, 'DATA', Path(td)):
            sup.save_tdcc_history('2330', rows)
            result = sup.save_tdcc_history('2330', rows)
            self.assertEqual(len(result), 1)

    def test_source_failure_visible(self):
        def fail(*args): raise ValueError('schema changed')
        value = sup.evidence('test', 'https://example.org', fail)
        self.assertIn('未取得', value['status'])
        self.assertEqual(value['rows'], [])

    def test_otc_institutional_totals_and_date(self):
        now = datetime.now()
        while now.weekday() >= 5: now -= timedelta(days=1)
        row = ['0'] * 24
        row[0] = '6488'
        row[10], row[13], row[22], row[23] = '10', '20', '30', '60'
        table = dict(date=now.strftime('%Y/%m/%d'), fields=['x']*23+['三大法人買賣超股數合計'], data=[row])
        with patch.object(sup, 'json_data', return_value=({'tables':[table]}, 'now')), patch.object(sup.time, 'sleep'):
            result = sup.otc_history('6488', 1)
        self.assertEqual(result[0]['total'], 60)

    def test_chip_stage_needs_more_than_a_positive_proxy(self):
        row = {'verify': {'conc60': 2, 'conc20': 1, 'trader_diff': -3},
               'big_chg': None, 'holders_chg': None}
        self.assertEqual(sc.chip_signal(row, 1)[0], '研究優先')
        self.assertEqual(sc.chip_signal(row, 2)[0], '籌碼待驗證')

    def test_chip_stage_waits_for_aligned_tdcc(self):
        row = {'verify': {'conc60': 2, 'conc20': 1, 'trader_diff': -3},
               'big_chg': 0.2, 'holders_chg': -20}
        self.assertEqual(sc.chip_signal(row, 2)[0], '等待突破')

    def test_chip_stage_rejects_conflicting_proxy(self):
        row = {'verify': {'conc60': -2, 'conc20': 1, 'trader_diff': -3},
               'big_chg': 0.2, 'holders_chg': -20}
        self.assertEqual(sc.chip_signal(row, 2)[0], '籌碼待驗證')

    def test_screen_uses_latest_completed_shared_dates(self):
        # Institutional data may contain today's provisional row while the daily
        # price feed still ends yesterday. Shared dates must be sufficient.
        end = datetime.now() - timedelta(days=1)
        dates = [(end - timedelta(days=369-i)).strftime('%Y%m%d') for i in range(370)]
        rows = [dict(date=d, open=10, high=10.4, low=9.4, close=10, volume=100000) for d in dates]
        rows[-1]['close'] = 9.8
        inst = [dict(date=d, foreign=1000, trust=0) for d in dates[-10:]]
        inst.append(dict(date='20270101', foreign=1000, trust=0))
        cfg = dict(converge=3.5, amplitude=35, bias=10, vol_ratio=1,
                   above_20w=True, max_pos=45, buy_days=5,
                   need_revenue=True, need_yield=True)
        results, stats = sc.screen({'1234': rows}, {'1234': '測試'}, {'1234': inst},
                                   {'1234': {'yield': 1}},
                                   {'1234': {'yoy': 1, 'industry': '測試'}}, {}, [], cfg)
        self.assertEqual(len(results), 1)


if __name__ == '__main__':
    unittest.main()
