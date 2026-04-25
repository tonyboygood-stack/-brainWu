---
name: note-capture
description: LYT 知識卡片建立技能。當使用者說「建立筆記」「生成筆記」時觸發。自動填入 up（MOC連結）、collection（筆記類型）、related（雙向連結）、says（核心觀點），詢問確認後存入對應資料夾，並更新 MOC 檔案加入此卡連結。
triggers:
  - 建立筆記
  - 生成筆記
---

# Note Capture Skill — LYT 筆記建立流程

## 筆記模板

```yaml
---
up:
  - "[[MOC名稱]]"
collection:
  - "[[Things這是什麼]]"
related:
  - "[[相關筆記]]"
created: YYYY-MM-DD
says: "核心觀點一句話"
---

內文
```

---

## 五種筆記類型（collection）

| 類型 | 適用情境 |
|------|---------|
| `[[Things這是什麼]]` | 概念、框架、工具 |
| `[[Statements我怎麼想]]` | 你的觀點、洞察、原則 |
| `[[Questions我好奇什麼]]` | 待探索的問題 |
| `[[Quotes別人怎麼說]]` | 引言 |
| `[[People這個人是誰]]` | 人物筆記 |

---

## 建立筆記流程（嚴格按順序，逐步詢問確認）

### 第一步：判斷 collection 類型
根據輸入內容自動判斷筆記類型，顯示建議並詢問確認：
```
這張筆記我判斷是「Things這是什麼」（概念類），這樣對嗎？
```

### 第二步：尋找 up（上級 MOC）
1. 讀取 `400_Atlas/Maps/` 內所有 MOC 檔案
2. 根據內容推薦 1-3 個相關 MOC，一張卡片可屬於多個 MOC
3. 若無相符的 MOC，提議新建：
```
目前沒有符合的 MOC，我建議新建「XXX MOC」，可以嗎？
```
4. 新建 MOC 時，在 `400_Atlas/Maps/` 建立以下格式：
```markdown
---
type: MOC
created: YYYY-MM-DD
---

# XXX MOC

## 筆記
```

### 第三步：尋找 related（橫向連結）
1. 搜尋 `400_Atlas/Notes/` 和 `400_Atlas/Case/` 中的相關筆記
2. 列出候選清單讓使用者確認：
```
找到以下可能相關的筆記，要建立雙向連結嗎？
- [[筆記A]]
- [[病案 2026-04-20 頭痛]]
```
3. 確認後，在對應筆記的 `related` 欄位加入本筆記的反向連結

### 第四步：生成 says
根據內文自動生成一句話核心觀點，詢問確認或修改：
```
says 建議：「XXX」
這樣可以嗎？或說「改成：...」讓我調整。
```

### 第五步：顯示完整草稿，最終確認
顯示完整 frontmatter + 內文，詢問：
```
這樣可以嗎？確認後我就存起來。（也可以說「修改：...」讓我調整）
```

### 第六步：存檔 + 更新 MOC

**存檔規則：**
- collection 為 `[Questions]` → 存入 `400_Atlas/Questions/`
- 其他類型 → 存入 `400_Atlas/Notes/`
- 檔名格式：`YYYY-MM-DD_筆記標題.md`

**更新 MOC：**
在 up 提到的每個 MOC 檔案中，加入本筆記的連結：
```markdown
- [[YYYY-MM-DD_筆記標題]]
```

---

## 深入討論前的 Context 檢索規則

每當展開一個主題討論時，先執行：
1. 讀取 `400_Atlas/Maps/` 找對應 MOC
2. 讀取 MOC 中所有連結的筆記
3. 回報：「這個主題下你有 N 張相關筆記，帶入脈絡繼續討論」
4. 若無對應 MOC，告知使用者並詢問是否新建

---

## 注意事項
- 每個步驟逐一確認，不跳步
- related 搜尋範圍：`400_Atlas/Notes/` + `400_Atlas/Case/`
- 雙向連結必須同時更新兩端的 related 欄位
- MOC 若是新建的，同樣要加入 up 並在 Maps/ 建立檔案
- 圖片統一存放於 `400_Atlas/Assets/`，在筆記內以相對路徑引用：`![說明](../Assets/檔名.jpg)`
