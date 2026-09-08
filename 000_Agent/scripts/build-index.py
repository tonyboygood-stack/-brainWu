#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
產生 600_Projects/投資/索引/知識點索引.md

掃描 知識卡/ 與 框架/ 的 YAML frontmatter，組成一張可一眼掃完的總表。
新增或修改知識卡之後重跑即可，索引不會過期。

用法：
  python 000_Agent/scripts/build-index.py
"""

import re
import sys
from datetime import datetime
from pathlib import Path

VAULT = Path(r"C:\Users\user\Documents\GitHub\-")
BASE = VAULT / "600_Projects" / "投資"
CARD_DIR = BASE / "知識卡"
FRAME_DIR = BASE / "框架"
OUT = BASE / "索引" / "知識點索引.md"

LAYER_ORDER = ["L0", "L1", "L2", "L3", "L4", "L5", "貫穿層", "工具層"]
LAYER_TITLE = {
    "L0": "L0 資金環境｜錢從哪來、往哪去？",
    "L1": "L1 市場位階｜現在在週期的哪一段？",
    "L2": "L2 籌碼意圖｜誰在買、誰在賣？　★核心層",
    "L3": "L3 標的體質｜這家公司撐得住嗎？",
    "L4": "L4 進出時機｜什麼時候動手？",
    "L5": "L5 部位與風控｜錯了怎麼辦？",
    "貫穿層": "貫穿層 心理紀律｜我在騙自己嗎？",
    "工具層": "工具層｜用什麼看？",
}


def parse_frontmatter(path):
    """讀出 YAML frontmatter 的簡單欄位（不引入 yaml 相依）。"""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    fm = {}
    for line in text[3:end].splitlines():
        m = re.match(r"^([a-z_]+):\s*(.*)$", line.strip())
        if m:
            key, val = m.group(1), m.group(2).strip().strip('"')
            fm[key] = val
    return fm


def episodes_of(fm):
    raw = fm.get("source_episodes", "")
    nums = re.findall(r"\d+", raw)
    return ", ".join(nums) if nums else "—"


def main():
    if not CARD_DIR.is_dir():
        print(f"找不到 {CARD_DIR}", file=sys.stderr)
        return 1

    cards = []
    for f in sorted(CARD_DIR.glob("*.md")):
        fm = parse_frontmatter(f)
        if not fm:
            continue
        cards.append({
            "name": f.stem,
            "layer": fm.get("layer", "?"),
            "question": fm.get("question", ""),
            "episodes": episodes_of(fm),
            "actionable": fm.get("actionable", "—"),
            "confidence": fm.get("confidence", "—"),
            "warning": fm.get("warning", ""),
        })

    frames = {}
    for f in sorted(FRAME_DIR.glob("*.md")):
        fm = parse_frontmatter(f)
        if fm and fm.get("type") == "moc":
            frames[fm.get("layer", "?")] = f.stem

    out = [
        "---",
        "title: 知識點索引",
        "type: index",
        f"generated: {datetime.now():%Y-%m-%d %H:%M}",
        "generator: 000_Agent/scripts/build-index.py",
        "tags:",
        "  - 投資",
        "  - 索引",
        "---",
        "",
        "# 知識點索引",
        "",
        "> [!note] 這份檔案是自動產生的",
        "> 由 `000_Agent/scripts/build-index.py` 掃描各卡片的 frontmatter 組成。",
        "> **不要手動編輯**——新增或修改知識卡後重跑腳本即可。",
        "",
        f"目前共 **{len(cards)} 張知識卡**，涵蓋 {len(frames)} 個層級。",
        "",
        "欄位說明：**可操作性**指能不能直接拿來執行；**可信度**指逐字稿的清晰程度，"
        "標「中」的引用前建議回原片確認。",
        "",
    ]

    for layer in LAYER_ORDER:
        group = [c for c in cards if c["layer"] == layer]
        if not group:
            continue
        title = LAYER_TITLE.get(layer, layer)
        out.append(f"## {title}")
        out.append("")
        if layer in frames:
            out.append(f"層級總覽：[[{frames[layer]}]]")
            out.append("")
        out.append("| 知識卡 | 觸發問句 | 來源期數 | 可操作性 | 可信度 |")
        out.append("| :--- | :--- | :--- | :---: | :---: |")
        for c in sorted(group, key=lambda x: x["name"]):
            flag = " ⚠️" if c["warning"] else ""
            out.append(
                f"| [[{c['name']}]]{flag} | {c['question']} | {c['episodes']} "
                f"| {c['actionable']} | {c['confidence']} |"
            )
        out.append("")

    warned = [c for c in cards if c["warning"]]
    if warned:
        out += ["## ⚠️ 需要特別注意的卡片", ""]
        for c in warned:
            out.append(f"- [[{c['name']}]]｜{c['warning']}")
        out.append("")

    out += [
        "## 相關",
        "",
        "- [[00_總框架]]｜單一入口",
        "- [[判讀SOP]]｜遇到問題時的逐層流程",
        "- [[術語表]]｜逐字稿錯字對照",
        "- [[數據來源清單]]｜外部資料源",
        "",
    ]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(out), encoding="utf-8")
    print(f"已產生 {OUT}")
    print(f"  知識卡 {len(cards)} 張，層級 {len(frames)} 個")
    for layer in LAYER_ORDER:
        n = len([c for c in cards if c["layer"] == layer])
        if n:
            print(f"    {layer}: {n} 張")
    return 0


if __name__ == "__main__":
    sys.exit(main())
