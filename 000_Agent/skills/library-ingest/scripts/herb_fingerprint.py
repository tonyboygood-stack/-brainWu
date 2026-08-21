#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
用藥指紋統計（第三階段）

依 frontmatter 的「醫家」欄位分組，統計 wiki/方劑/ 各醫家的用藥習慣。
輸出全部來自本庫實際資料，屬 🟢 原文直述層級，非 AI 印象。

用法：
  python herb_fingerprint.py            # 只印報告
  python herb_fingerprint.py --write    # 另寫入 wiki/醫家/指紋/<醫家>_用藥指紋.md
"""
import re
import os
import sys
import glob
import statistics
import collections
from datetime import date

VAULT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
WIKI = os.path.join(VAULT, "400_Atlas", "Library", "wiki")

# 力度分級用的查詢清單（僅作為統計篩選條件，不代表對這些藥的主張）
JUNXIA = ["大黃", "芒硝", "元明粉", "巴豆", "甘遂", "大戟", "芫花", "牽牛子", "商陸"]
WENYANG = ["附子", "肉桂", "乾薑", "細辛", "吳茱萸", "仙茅", "淫羊藿"]
QINGQING = ["蘇葉", "薄荷", "防風", "前胡", "桑葉", "菊花", "蟬蛻", "荊芥", "淡豆豉", "杏仁"]
JUNBU = ["人參", "熟地黃", "鹿茸", "黃芪", "阿膠", "紫河車"]

UNIT = "克|枚|片|個|條|支|對|節|毫升|ml"
SEP = "[\u3000 \n]+"          # 全形空白／半形空白／換行
HAN = "[\u4e00-\u9fff]"       # 漢字


def expand_each(block):
    """把「生、熟地各10克」展開成兩項，讓項數對得上組成清單"""
    pat = "(" + HAN + "{1,4})、(" + HAN + "{1,4})各([0-9.]+)" + r"\s*" + "(" + UNIT + ")"

    def rep(m):
        a, b, g, u = m.groups()
        return a + g + u + "\u3000" + b + g + u

    return re.sub(pat, rep, block)


def parse_doses(herbs, block):
    """三段式：展開「各」→ 依序對齊 → 名稱比對兜底。只統計「克」。"""
    block = expand_each(block)
    items = [x for x in re.split(SEP, block.strip()) if x]

    def grams(item):
        m = re.search("([0-9.]+)" + r"\s*" + "(" + UNIT + ")", item)
        if not m or m.group(2) != "克":
            return None          # 枚／片等單位不可與克混算
        return float(m.group(1))

    doses = {}
    if len(items) == len(herbs):
        # 順序對齊：可正確處理「淡幹薑」「炙草」這類炮製名／簡稱
        for h, it in zip(herbs, items):
            g = grams(it)
            if g is not None:
                doses[h] = g
        return doses
    for h in herbs:              # 兜底：逐藥名比對
        m = re.search(re.escape(h) + "[^0-9]{0,4}([0-9.]+)" + r"\s*" + "克", block)
        if m:
            doses[h] = float(m.group(1))
    return doses


def read_pages():
    """讀 wiki/方劑/，回傳 {醫家: [(檔名, 組成list, {藥:劑量}), ...]}"""
    groups = collections.defaultdict(list)
    for path in sorted(glob.glob(os.path.join(WIKI, "方劑", "*.md"))):
        text = open(path, encoding="utf-8").read()
        fm = re.search("^醫家:\n((?:  - .+\n)*)", text, re.M)
        authors = re.findall("^  - (.+)$", fm.group(1), re.M) if fm else []
        m = re.search("^組成: (.+)$", text, re.M)
        herbs = [h.strip() for h in m.group(1).split("、") if h.strip()] if m else []
        block = re.search("## 組成與劑量\n(.+?)(?=\n## )", text, re.S)
        doses = parse_doses(herbs, block.group(1)) if (block and herbs) else {}
        for a in authors:
            groups[a].append((os.path.basename(path)[:-3], herbs, doses))
    return groups


# 炮製／產地前綴，用於偵測同藥異名候選（僅偵測，不自動合併——合併需老吳的專業判斷）
PREFIX = ["生炒", "土炒", "焦", "炒", "炙", "淡", "煨", "醋", "酒", "鮮", "川",
          "杭", "雲", "淨", "生", "法", "薑", "朱", "廣"]
# 非單味藥判定：成方、成藥、或並列選項
NOT_SINGLE = ["湯", "丸", "散", "膏", "丹", "飲", "或", "／", "/"]


def is_single_herb(name):
    return not any(k in name for k in NOT_SINGLE)


def alias_candidates(freq):
    """找出「某藥」與「前綴＋某藥」並存的情形，列為待裁決的合併候選"""
    names = set(freq)
    pairs = collections.defaultdict(list)
    for n in names:
        for pre in PREFIX:
            if n.startswith(pre) and len(n) > len(pre) and n[len(pre):] in names:
                pairs[n[len(pre):]].append(n)
                break
    return dict(sorted(pairs.items(), key=lambda x: -freq[x[0]]))


def analyse(pages):
    freq = collections.Counter()
    doses = collections.defaultdict(list)
    for _, herbs, ds in pages:
        freq.update(herbs)
        for h, g in ds.items():
            doses[h].append(g)
    return freq, doses


def rng_str(d):
    if not d:
        return "—"
    lo, hi = min(d), max(d)
    return ("%g 克" % lo) if lo == hi else ("%g–%g 克" % (lo, hi))


def render(author, pages, freq, doses):
    total = len(pages)
    all_doses = [g for v in doses.values() for g in v]
    covered = sum(len(ds) for _, _, ds in pages)
    items = sum(len(hs) for _, hs, _ in pages)
    L = []
    A = L.append
    A("# %s 用藥指紋" % author)
    A("")
    A("> 🟢 由 `herb_fingerprint.py` 從本庫 **%d 個方劑頁**自動統計，非 AI 印象。" % total)
    A("> 統計日期 %s。劑量僅取「組成與劑量」區塊的基礎方，不含加減法；"
      "劑量解析涵蓋率 %.0f%%（%d/%d 項）。" % (date.today(), covered / items * 100, covered, items))
    A("")
    A("## 總覽")
    A("")
    A("- 方劑數：**%d**" % total)
    compounds = {h: c for h, c in freq.items() if not is_single_herb(h)}
    singles = {h: c for h, c in freq.items() if is_single_herb(h)}
    A("- 組成欄不同條目：**%d**（其中 %d 條為成方／成藥引用，非單味藥）"
      % (len(freq), len(compounds)))
    once = sum(1 for c in singles.values() if c == 1)
    A("- 只用過一次的單味藥：**%d** 味（%.0f%%）——用藥面寬、核心圈窄"
      % (once, once / len(singles) * 100))
    _al = alias_candidates(freq)
    if _al:
        A("- ⚠️ 偵測到 **%d** 組同藥異名候選（如生白芍／白芍），共 %d 個異名條目；"
          "**未自動合併**，合併後實際藥味數會更少（見文末清單）"
          % (len(_al), sum(len(v) for v in _al.values())))
    top10 = sum(c for _, c in freq.most_common(10))
    A("- 前 10 味藥合計出現 %d 次，平均每方有 %.1f 味來自核心圈" % (top10, top10 / total))
    if all_doses:
        q = statistics.quantiles(all_doses, n=4)
        A("- 劑量分佈：中位數 **%g 克**，四分位 %g／%g 克，最大 %g 克"
          % (statistics.median(all_doses), q[0], q[2], max(all_doses)))
    A("")
    A("## 高頻藥 TOP 30")
    A("")
    A("| 藥 | 出現方數 | 佔比 | 劑量範圍 | 中位 |")
    A("|---|---:|---:|---|---:|")
    for h, c in freq.most_common(30):
        d = doses.get(h, [])
        med = ("%g" % statistics.median(d)) if d else "—"
        A("| [[%s]] | %d | %.0f%% | %s | %s |" % (h, c, c / total * 100, rng_str(d), med))
    A("")
    A("## 力度指標")
    A("")
    A("> 下列分組僅為統計查詢用的篩選條件，不代表對這些藥的主張。")
    A("")
    A("| 分組 | 用到的藥（後方數字為方數） | 合計 | 佔全部方劑 |")
    A("|---|---|---:|---:|")
    for label, names in [("峻下", JUNXIA), ("溫陽", WENYANG),
                         ("輕清宣透", QINGQING), ("峻補", JUNBU)]:
        hit = {n: freq[n] for n in names if freq.get(n)}
        n = sum(hit.values())
        detail = "、".join("%s%d" % (k, v) for k, v in sorted(hit.items(), key=lambda x: -x[1])) or "—"
        A("| %s | %s | %d | %.0f%% |" % (label, detail, n, n / total * 100))
    A("")
    A("### 峻藥的實際劑量")
    A("")
    A("| 藥 | 用於幾方 | 劑量範圍 | 中位 |")
    A("|---|---:|---|---:|")
    for h in JUNXIA + JUNBU:
        d = doses.get(h, [])
        if freq.get(h) and d:
            A("| [[%s]] | %d | %s | %g |" % (h, freq[h], rng_str(d), statistics.median(d)))
    A("")
    A("## 長尾：只用過一次的單味藥")
    A("")
    A("、".join(sorted(h for h, c in freq.items() if c == 1 and is_single_herb(h))))
    A("")
    _cp = sorted(h for h in freq if not is_single_herb(h))
    if _cp:
        A("## ⚠️ 組成欄中的非單味藥條目")
        A("")
        A("> 成方／成藥引用或並列選項，不應計入藥味統計，建議裁決是否改寫組成欄。")
        A("")
        for h in _cp:
            A("- %s（%d 方）" % (h, freq[h]))
        A("")
    _al = alias_candidates(freq)
    if _al:
        A("## ⚠️ 同藥異名合併候選（待老吳裁決）")
        A("")
        A("> 偵測依據：某藥名與「炮製／產地前綴＋該藥名」並存。")
        A("> **未自動合併**——炮薑與乾薑是否算同一味，屬專業判斷。")
        A("")
        A("| 基準名 | 方數 | 異名候選 |")
        A("|---|---:|---|")
        for base, vs in _al.items():
            A("| %s | %d | %s |" % (base, freq[base],
              "、".join("%s（%d 方）" % (v, freq[v]) for v in sorted(vs))))
    A("")
    return "\n".join(L) + "\n"


def main():
    write = "--write" in sys.argv
    groups = read_pages()
    outdir = os.path.join(WIKI, "醫家", "指紋")
    for author, pages in sorted(groups.items(), key=lambda x: -len(x[1])):
        if len(pages) < 5:
            print("[跳過] %s：僅 %d 方，樣本不足以構成指紋\n" % (author, len(pages)))
            continue
        freq, doses = analyse(pages)
        body = render(author, pages, freq, doses)
        print(body)
        if write:
            os.makedirs(outdir, exist_ok=True)
            fm = ("---\ntitle: %s 用藥指紋\nsource_type: 醫家\ndiscipline: 中醫\n"
                  "醫家:\n  - %s\nattribution: 原創\ntags:\n  - 用藥指紋\n"
                  "related:\n  - \"[[%s]]\"\ncreated: %s\n"
                  "generated_by: herb_fingerprint.py\n---\n\n"
                  % (author, author, author, date.today()))
            p = os.path.join(outdir, "%s_用藥指紋.md" % author)
            open(p, "w", encoding="utf-8", newline="").write(fm + body)
            print("→ 已寫入 %s\n" % os.path.relpath(p, VAULT))


if __name__ == "__main__":
    main()
