<!-- AI 分身起始助手紀錄:START -->
<!-- AI 分身起始助手 by 雷小蒙 v1.0 · 2026-04-22 · by 雷蒙（Raymond Hou）· https://github.com/Raymondhou0917/claude-code-resources · CC BY-NC-SA 4.0 -->

# 老吳 的 AI 分身記憶

> 這裡存我跟 AI 之間跨 session 的偏好、經驗、踩坑紀錄。
> AI 每次 session 開始會自動讀這個檔案。

---

## 用戶偏好

- 知識卡片顯示 collection 選項時，**保留中文說明**讓老吳更好理解

---

## Feedback（AI 學到的原則）

- 錯誤做法：collection 用自由文字（如 `奇經八脈`、`臨床思路`）→ 正確做法：只能從以下 5 種標準選項擇一 → 原因：這是 Obsidian 知識庫的統一分類架構

**知識卡片 collection 標準選項（只能選這五個）：**

| 選項 | 中文說明 |
| ---- | -------- |
| `[[Things]]` | 這是什麼？概念、框架、工具 |
| `[[Statements]]` | 我怎麼想？觀點、洞察、原則 |
| `[[Questions]]` | 我好奇什麼？待探索的問題 |
| `[[Quotes]]` | 別人怎麼說？引言 |
| `[[People]]` | 這個人是誰？人物筆記 |

---

## 上次做到哪（2026-04-30）

- 完成衝脈第一條路線知識卡（含針刺10步流程）
- 解決手機/電腦分支不同步問題（SessionStart hook）
- 知識卡 collection 格式修正，模板合到 main
- 病案：許玲玲（衝脈1/2/5，效果不足待深究）、蘇俊（肥大細胞增生，疏肝改善中）、宛如阿姨（三叉神經痛，5/4回饋）
- 日記：4/30 已存

---

## 踩坑筆記

- **分支不同步**：Obsidian Git 推到 `main`，Claude session 預設建 `claude/xxx` 分支 → 已透過 `.claude/settings.json` SessionStart hook 解決，session 開始自動切回 `main`
- **製作知識卡前必須先 fetch origin/main**：避免用舊版本覆蓋最新內容
- **讀書方法**：老吳有效的方式是「讀一條 → 當天用一次 → 記一筆回饋」，不需要提醒，他記臨床筆記時自然會觸發

---

## 環境速查表

| 項目             | 值                                              |
| :--------------- | :---------------------------------------------- |
| AI 分身母資料夾  | `C:\Users\user\Documents\GitHub\-`              |
| 建立日期         | `2026-04-22`                                    |
| Skills symlink   | ✅ `~/.claude/skills` → `000_Agent/skills/`     |
| 記憶系統啟用     | ✅                                              |
| 每日日記         | ✅ `300_Journal/YYYY-MM/`                       |

<!-- AI 分身起始助手紀錄:END -->
