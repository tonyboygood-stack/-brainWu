---
title: 投資
type: project
status: 🟠 進行中
created: 2026-09-07
tags:
  - 投資
  - 專案
---

# 投資

## 這個專案在做什麼

把 YouTube 財經頻道的內容批次轉成逐字稿，累積成可搜尋、可建卡的原始素材庫。逐字稿本身是**未整理的原文**，性質等同 `400_Atlas/Library/raw/`——先囤起來，之後要出觀點再走 [[note-capture]] 建卡。

## 素材來源

| 頻道 | 影片數 | 總時長 | 備註 |
| :--- | ---: | ---: | :--- |
| [宏爺講股](https://www.youtube.com/@宏爺講股) | 491 | 169 小時 | 平均 20.6 分鐘；多數有 YouTube 字幕軌，少數需轉錄 |

## 逐字稿工具

腳本：[[yt-transcribe.py]]（`000_Agent/scripts/yt-transcribe.py`）

兩段式管線，先快後慢：

1. **快車道** — 影片有 YouTube 字幕軌就直接下載解析，一支 2–5 秒。抽樣顯示絕大多數影片走這條。
2. **慢車道** — 沒字幕軌的（會員影片、硬字幕影片、剛上傳還沒生成字幕的）才下載 m4a 音訊，交給 faster-whisper `large-v3-turbo` 轉錄。

### 常用指令

抓整個頻道最新 30 支：

```bash
python 000_Agent/scripts/yt-transcribe.py "https://www.youtube.com/@宏爺講股/videos" --limit 30
```

先只收有現成字幕的（最快，把便宜的先撈乾淨）：

```bash
python 000_Agent/scripts/yt-transcribe.py "https://www.youtube.com/@宏爺講股/videos" --skip-whisper
```

看有哪些待處理但不執行：

```bash
python 000_Agent/scripts/yt-transcribe.py "https://www.youtube.com/@宏爺講股/videos" --dry-run
```

抓單支（含會員影片）：

```bash
python 000_Agent/scripts/yt-transcribe.py "https://www.youtube.com/watch?v=影片ID"
```

### 設計上的幾個決定

- **已經是繁體的字幕軌不做任何轉換**，原文照抄。OpenCC 的 `s2twp` 會把「數據」改成「資料」、「設備」改成「裝置」，那是竄改講者原話而非轉換字體。只有 Whisper 輸出（必為簡體）才用 `s2tw` 轉，並附一組「臺→台」的台灣財經慣用詞修正表。
- **只下載 m4a 音訊軌（format 140）**，不做轉檔，因此整條管線不需要 ffmpeg。
- **音訊轉完即刪**，不佔硬碟。
- **斷點續傳**：完成紀錄存在 repo 外的 `state.json`，中斷後直接重跑會接續，不會重做。
- **憑證與暫存放在 repo 外**（`C:\Users\user\.config\yt-transcribe\`），確保 Obsidian Git 不會把 cookie 推上 GitHub。

### 相依套件

`yt-dlp`、`faster-whisper`、`opencc-python-reimplemented`，外加 **Deno**（yt-dlp 用來解 YouTube 的 JS 挑戰，缺了會抓不到下載格式）。

## 待辦

- [ ] 決定第一批要抓的範圍（全部 491 支 / 最近 N 支）
- [ ] 跑完後抽幾支校對 Whisper 轉錄品質
- [ ] 逐字稿累積後，挑重點主題走 note-capture 建卡

## 相關

- [[yt-transcribe.py]]
