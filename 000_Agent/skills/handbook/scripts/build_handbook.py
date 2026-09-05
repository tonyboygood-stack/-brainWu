# -*- coding: utf-8 -*-
"""
臨床手冊生成器 — 把 400_Atlas/Notes 的卡片組裝成兩本可讀的手冊。

設計原則（老吳自己在總框架 MOC 立的規則）：
    「這是檢視畫面，不是真相來源。只能從卡片濃縮，不新增內容。」

因此本腳本只做機械組裝：讀 frontmatter 的 says / when_to_use / framework / up，
排成清單。導讀（速覽）由人或 AI 寫在 AUTO 標記外面，重生時完全不會被動到。

兩本書用同一批卡、同一份資料，只是目錄順序不同：
    推理層次：章＝L0–L5    小節＝MOC 主題
    主題查詢：章＝MOC 主題  小節＝L0–L5

用法：
    python build_handbook.py            # 重生（只換 AUTO 區塊，速覽原樣保留）
    python build_handbook.py --check    # 只檢查不寫入（冪等性測試用）
    python build_handbook.py --fresh    # 整份重建，會丟掉已寫的速覽——只在初次建立時用
"""
import glob
import io
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

VAULT = r"C:\Users\user\Documents\GitHub\-"
NOTES = os.path.join(VAULT, "400_Atlas", "Notes")
MAPS = os.path.join(VAULT, "400_Atlas", "Maps")
OUT_REASONING = os.path.join(VAULT, "400_Atlas", "臨床手冊_推理層次.md")
OUT_TOPIC = os.path.join(VAULT, "400_Atlas", "臨床手冊_主題查詢.md")

CHECK_ONLY = "--check" in sys.argv
FRESH = "--fresh" in sys.argv

# 沿用總框架 MOC 的六個問句
LAYERS = [
    ("L0", "L0 資源 —「有沒有本錢？」"),
    ("L1", "L1 氣機通道 —「往哪走？路通不通？」"),
    ("L2", "L2 神 —「神定不定？」"),
    ("L3", "L3 邪氣 —「什麼東西塞在那裡？」"),
    ("L4", "L4 策略 —「先做哪一步？做到什麼程度？」"),
    ("L5", "L5 手段執行 —「用什麼手段？多少？怎麼執行？」"),
    ("框架外", "框架外（明確不屬於這套框架，如西醫營養學）"),
    ("未解構", "尚未做框架解構（舊卡，可補）"),
]
LAYER_TITLE = dict(LAYERS)

BANNER = (
    "> **這是檢視畫面，不是真相來源。**\n"
    "> 清單由 `handbook` skill 從卡片自動濃縮，**不新增內容**。要改內容請改卡片，改這裡會被下次重生蓋掉。\n"
    "> 速覽區塊（引言）是人寫的，在 AUTO 標記外面，重生不會動到。\n"
    "> ⬜ ＝ 這張卡還沒填 `when_to_use`（臨床觸發鍵）。\n"
)

SUMMARY_STUB = (
    "> **這層在幹嘛**：（待寫）\n"
    "> **目前掌握**：（待寫）\n"
    "> **最容易錯**：（待寫）\n"
)


def parse_frontmatter(text):
    """回傳 (dict, body)。只做需要的欄位，不引入 yaml 相依。"""
    if not text.startswith("---"):
        return {}, text
    lines = text.split("\n")
    close = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if close is None:
        return {}, text
    fm, out, key = {}, {}, None
    for raw in lines[1:close]:
        if re.match(r"^\S.*?:", raw):
            key = raw.split(":", 1)[0].strip()
            val = raw.split(":", 1)[1].strip()
            out[key] = val.strip('"').strip("'") if val else []
        elif key and re.match(r"^\s+-\s", raw):
            item = raw.split("-", 1)[1].strip().strip('"').strip("'")
            if not isinstance(out.get(key), list):
                out[key] = []
            out[key].append(item)
    return out, "\n".join(lines[close + 1:])


def get_says(fm, body):
    """frontmatter 的 says 優先；舊卡把 says 寫成內文 H2，退而求其次。"""
    s = fm.get("says")
    if isinstance(s, str) and s.strip():
        return s.strip()
    m = re.search(r"^##\s*says[^\n]*\n+(.+?)$", body, re.M)
    if m:
        return m.group(1).strip().lstrip("- ").strip()
    return ""


def layer_of(fm):
    """
    取 framework 第一個 L token（老吳是照框架順序寫的，最左＝主層）。
    區分三種狀況：有層次 / 明確標框架外 / 根本還沒做框架解構。
    """
    f = fm.get("framework")
    if not isinstance(f, str) or not f.strip():
        return "未解構"
    m = re.search(r"L([0-5])", f)
    return "L%s" % m.group(1) if m else "框架外"


def topics_of(fm):
    up = fm.get("up")
    vals = up if isinstance(up, list) else ([up] if isinstance(up, str) and up.strip() else [])
    out = []
    for v in vals:
        v = re.sub(r"^\[\[|\]\]$", "", str(v).strip()).split("/")[-1]
        if v:
            out.append(v)
    return out or ["未歸類"]


def load_cards():
    cards = []
    for path in sorted(glob.glob(os.path.join(NOTES, "*.md"))):
        name = os.path.splitext(os.path.basename(path))[0]
        if name == "臨床成長記錄":  # 那是日誌，不是知識卡
            continue
        text = open(path, encoding="utf-8").read()
        fm, body = parse_frontmatter(text)
        wtu = fm.get("when_to_use")
        cards.append({
            "name": name,
            "says": get_says(fm, body),
            "layer": layer_of(fm),
            "topics": topics_of(fm),
            "has_wtu": isinstance(wtu, str) and bool(wtu.strip()),
        })
    return cards


def card_line(c):
    says = c["says"] or "（這張卡還沒寫 says）"
    mark = "" if c["has_wtu"] else "  ⬜"
    return "- [[%s]] — %s%s" % (c["name"], says, mark)


def render_block(cards, subkey):
    """
    組一章的內容：依 subkey 分小節。
    一張卡在同一章只會出現一次——多值欄位（如 up）取第一個當主小節，
    否則多主題的卡會在同一章重複列出，讀起來像跳針。
    """
    buckets = {}
    for c in cards:
        v = c[subkey]
        k = (v[0] if v else "未歸類") if isinstance(v, list) else (v or "未分層")
        buckets.setdefault(k, []).append(c)
    out = []
    for k in sorted(buckets, key=lambda x: (-len(buckets[x]), x)):
        out.append("### %s（%d）" % (LAYER_TITLE.get(k, k), len(buckets[k])))
        out.append("")
        for c in sorted(buckets[k], key=lambda c: c["name"], reverse=True):
            out.append(card_line(c))
        out.append("")
    return "\n".join(out).rstrip()


def splice(existing, chapters):
    """
    chapters: [(key, heading, generated_body), ...]
    只重寫 AUTO 標記之間的內容；標記外的散文原樣保留。
    檔案裡還沒有的章節，附加一個含速覽佔位的新章。
    """
    if existing is None:
        parts = ["# 臨床手冊", "", BANNER, ""]
        for key, heading, body in chapters:
            parts += ["## %s" % heading, "", SUMMARY_STUB, "",
                      "<!-- AUTO:START:%s -->" % key, body, "<!-- AUTO:END:%s -->" % key, "", "---", ""]
        return "\n".join(parts).rstrip() + "\n"

    text = existing
    for key, heading, body in chapters:
        pat = re.compile(
            r"(<!-- AUTO:START:%s -->\n).*?(\n<!-- AUTO:END:%s -->)" % (re.escape(key), re.escape(key)),
            re.DOTALL,
        )
        if pat.search(text):
            text = pat.sub(lambda m: m.group(1) + body + m.group(2), text)
        else:  # 新章節：附加在最後
            text = text.rstrip() + "\n\n## %s\n\n%s\n\n<!-- AUTO:START:%s -->\n%s\n<!-- AUTO:END:%s -->\n\n---\n" % (
                heading, SUMMARY_STUB, key, body, key)
    return text


def write(path, content):
    old = open(path, encoding="utf-8").read() if os.path.exists(path) else None
    if old == content:
        return "unchanged"
    if not CHECK_ONLY:
        open(path, "w", encoding="utf-8", newline="\n").write(content)
    return "would change" if CHECK_ONLY else "written"


def main():
    cards = load_cards()
    print("讀入 %d 張知識卡" % len(cards))

    # 推理手冊：章＝層次，小節＝主題
    by_layer = {}
    for c in cards:
        by_layer.setdefault(c["layer"] or "框架外", []).append(c)
    chapters_r = [
        (key, title, render_block(by_layer.get(key, []), "topics") or "（這一層目前沒有卡片）")
        for key, title in LAYERS
    ]

    # 主題手冊：章＝主題，小節＝層次
    by_topic = {}
    for c in cards:
        for t in c["topics"]:
            by_topic.setdefault(t, []).append(c)
    chapters_t = [
        (t, t, render_block(by_topic[t], "layer"))
        for t in sorted(by_topic, key=lambda x: (-len(by_topic[x]), x))
    ]

    for path, chapters, label in [
        (OUT_REASONING, chapters_r, "推理層次"),
        (OUT_TOPIC, chapters_t, "主題查詢"),
    ]:
        existing = None if FRESH else (
            open(path, encoding="utf-8").read() if os.path.exists(path) else None)
        status = write(path, splice(existing, chapters))
        print("  %-6s %-12s %d 章" % (status, label, len(chapters)))

    print()
    print("層次分佈：" + "　".join(
        "%s:%d" % (k, len(by_layer.get(k, []))) for k, _ in LAYERS))
    no_wtu = sum(1 for c in cards if not c["has_wtu"])
    print("還沒填 when_to_use（手冊裡標 ⬜）：%d / %d 張" % (no_wtu, len(cards)))
    no_says = [c["name"] for c in cards if not c["says"]]
    if no_says:
        print("沒有 says 的卡 %d 張：%s" % (len(no_says), "、".join(n[:22] for n in no_says[:6])))


if __name__ == "__main__":
    main()
