#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
回填文獻庫的醫家標記（第一階段）

在每一頁 frontmatter 補上：
  醫家:        list，本頁內容涉及哪些醫家的主張/經驗
  source:      文獻出處
  attribution: 原創 | 化裁 | 收錄 | 待判定

用法：
  python backfill_attribution.py            # dry-run，只印報告不改檔
  python backfill_attribution.py --write    # 實際寫入
"""
import re
import sys
import glob
import os
import collections

VAULT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
WIKI = os.path.join(VAULT, "400_Atlas", "Library", "wiki")

# 醫家判定：出處字串 → 醫家
SOURCE_TO_AUTHOR = {
    "趙紹琴": "趙紹琴",
    "臨證400法": "趙紹琴",
}
# 疼痛科學課程來源的頁面，靠內文提及判定歸屬
COURSE_AUTHORS = {
    "揚達（Janda）": ["揚達", "Janda"],
    "Ida Rolf": ["Ida Rolf", "Rolfing", "結構整合"],
}


def parse_frontmatter(text):
    """回傳 (frontmatter字串, 內文字串)；無 frontmatter 則回 (None, text)"""
    if not text.startswith("---\n"):
        return None, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return None, text
    return text[4:end + 1], text[end + 5:]


def detect_source(text):
    """從 `## 出處` 區塊或既有 source: 欄位抓出處字串"""
    m = re.search(r"^source: (.+)$", text, re.M)
    if m:
        return m.group(1).strip()
    m = re.search(r"^author: (.+)$", text, re.M)
    if m:
        return m.group(1).strip()
    m = re.search(r"^## 出處\s*\n+(.+?)(?:\n\n|\n##|\Z)", text, re.M | re.S)
    if m:
        return m.group(1).strip().split("\n")[0].strip()
    return ""


def detect_authors(text, source, folder):
    """回傳 (醫家list, 判定依據)"""
    for key, author in SOURCE_TO_AUTHOR.items():
        if key in source:
            return [author], f"出處含「{key}」"

    found = []
    for author, keys in COURSE_AUTHORS.items():
        if any(k in text for k in keys):
            found.append(author)
    if found:
        return found, "內文提及該醫家"

    if folder == "醫家":
        m = re.search(r"^title: (.+)$", text, re.M)
        if m:
            return [m.group(1).strip()], "醫家頁自指"

    return [], "無法判定"


def detect_attribution(text, folder, authors):
    """回傳 (attribution, 判定依據)"""
    if folder in ("藥物本草", "穴位經絡"):
        return "收錄", "共用節點，歸屬看各醫家分區"
    if not authors:
        return "待判定", "醫家未定"
    if folder == "方劑":
        # 「原文未明言仿何方」是否定句，意思是趙自擬，不可當化裁證據
        stripped = re.sub("原文未明言仿[^。]*", "", text)
        if re.search(r"仿|化裁|方意", stripped):
            return "化裁", "內文明言仿某方/化裁"
        if "未明言仿" in text:
            return "原創", "原文明言未仿他方"
        return "原創", "無化裁標記"
    if folder in ("病機病理", "治法技法", "解剖生理", "診斷評估", "辨析", "典籍", "醫家"):
        return "原創", f"{folder}頁，依出處歸屬"
    return "待判定", "未涵蓋的分類"


def build_insert(authors, source, attribution):
    lines = ["醫家:"]
    if authors:
        lines += [f"  - {a}" for a in authors]
    else:
        lines = ["醫家: []"]
    if source:
        lines.append(f"source: {source}")
    lines.append(f"attribution: {attribution}")
    return "\n".join(lines) + "\n"


def process(path, write):
    text = open(path, encoding="utf-8").read()
    fm, body = parse_frontmatter(text)
    folder = os.path.basename(os.path.dirname(path))

    if fm is None:
        return dict(path=path, folder=folder, status="無 frontmatter", authors=[],
                    attribution="-", why="跳過")
    if re.search(r"^醫家:", fm, re.M):
        return dict(path=path, folder=folder, status="已標記", authors=[],
                    attribution="-", why="跳過")

    source = detect_source(text)
    authors, why_a = detect_authors(text, source, folder)
    attribution, why_b = detect_attribution(text, folder, authors)

    insert = build_insert(authors, source, attribution)

    # 插在 discipline 之後；若無 discipline 則插在 frontmatter 開頭
    if re.search(r"^discipline: .+$", fm, re.M):
        new_fm = re.sub(r"^(discipline: .+\n)", r"\1" + insert, fm, count=1, flags=re.M)
    else:
        new_fm = insert + fm
    # 移除重複的舊 source 行（保留新插入那一行）
    if source:
        head, sep, tail = new_fm.partition(insert)
        tail = re.sub(r"^source: .+\n", "", tail, flags=re.M)
        new_fm = head + sep + tail

    if write:
        open(path, "w", encoding="utf-8", newline="").write("---\n" + new_fm + "---\n" + body)

    return dict(path=path, folder=folder, status="回填", authors=authors,
                attribution=attribution, why=f"{why_a}／{why_b}")


def main():
    write = "--write" in sys.argv
    files = sorted(glob.glob(os.path.join(WIKI, "*", "*.md")))
    results = [process(f, write) for f in files]

    by_folder = collections.defaultdict(collections.Counter)
    flagged = []
    for r in results:
        key = f"{'+'.join(r['authors']) or '（無）'} / {r['attribution']}"
        by_folder[r["folder"]][key] += 1
        if r["attribution"] == "待判定" or not r["authors"]:
            if r["status"] == "回填":
                flagged.append(r)

    mode = "實際寫入" if write else "DRY-RUN（未改檔）"
    print(f"=== 回填報告　{mode} ===")
    print(f"掃描 {len(files)} 頁，回填 {sum(1 for r in results if r['status']=='回填')} 頁，"
          f"跳過 {sum(1 for r in results if r['status']!='回填')} 頁\n")

    for folder in sorted(by_folder):
        print(f"[{folder}]")
        for key, n in by_folder[folder].most_common():
            print(f"    {n:4d}  {key}")
    print()

    if flagged:
        print(f"=== ⚠️ 需老吳抽查：{len(flagged)} 頁無法判定 ===")
        for r in flagged[:40]:
            print(f"  {r['folder']}/{os.path.basename(r['path'])}　（{r['why']}）")
    else:
        print("=== 無待判定頁面 ===")

    # 化裁判定清單供抽查
    hz = [r for r in results if r["attribution"] == "化裁"]
    if hz:
        print(f"\n=== 判為「化裁」的 {len(hz)} 頁（候選，請抽查）===")
        for r in hz[:60]:
            print(f"  {os.path.basename(r['path'])[:-3]}")


if __name__ == "__main__":
    main()
