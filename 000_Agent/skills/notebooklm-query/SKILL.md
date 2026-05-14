---
name: notebooklm-query
description: 查詢 Google NotebookLM 知識庫，將完整原始回應存入 Inbox。當使用者說「去 NotebookLM 查」「查 [知識庫名稱] 的 [問題]」「NotebookLM 查詢」時觸發。
triggers:
  - 去 NotebookLM 查
  - NotebookLM 查詢
  - 查知識庫
---

# NotebookLM 查詢技能

## 觸發範例

```
去 NotebookLM 查補肝血的食物
去古典針灸飲食衛教知識庫查補腎陽的方法
NotebookLM 查詢：子宮肌瘤的飲食禁忌
```

---

## 執行步驟

### 第一步：解析輸入

從使用者訊息中提取：
- **查詢問題**（必填）
- **知識庫名稱**（選填）

若未指定知識庫名稱 → 執行「列出選單」流程（見下方）。

---

### 第二步：載入 Chrome MCP 工具

使用 ToolSearch 載入以下工具：
```
select:mcp__Claude_in_Chrome__tabs_context_mcp,mcp__Claude_in_Chrome__navigate,mcp__Claude_in_Chrome__get_page_text,mcp__Claude_in_Chrome__find,mcp__Claude_in_Chrome__form_input,mcp__Claude_in_Chrome__javascript_tool
```

---

### 第三步：取得分頁 ID

呼叫 `tabs_context_mcp`（`createIfEmpty: true`）取得 tabId。

---

### 第四步：前往 NotebookLM 首頁，找到目標知識庫

1. 導覽至 `https://notebooklm.google.com`
2. 呼叫 `get_page_text` 取得筆記本清單

**若有指定知識庫名稱：**
- 在頁面文字中比對名稱（模糊比對即可）
- 從 `read_page`（`filter: interactive`）取得對應的筆記本連結 href
- 若找不到 → 告知使用者，列出所有筆記本讓他選

**若未指定知識庫名稱（選單流程）：**
- 列出所有筆記本名稱，格式如下：
```
找到以下知識庫，要查哪一個？
1. 古典針灸飲食衛教知識庫
2. 李辛老師資料庫
3. 結構與治療知識庫
...
```
- 等使用者回覆後繼續

---

### 第五步：進入目標筆記本

導覽至 `https://notebooklm.google.com/notebook/{notebook-id}`

確認 tab title 包含筆記本名稱後繼續。

---

### 第六步：提交查詢

1. 用 `find` 找到查詢輸入框（「查詢方塊」textarea）
2. 用 JavaScript 正確觸發 React 輸入事件：
```javascript
const textarea = document.querySelector('textarea');
const setter = Object.getOwnPropertyDescriptor(
  window.HTMLTextAreaElement.prototype, 'value'
).set;
setter.call(textarea, '{{查詢問題}}');
textarea.dispatchEvent(new Event('input', { bubbles: true }));
```
3. 找到**未 disabled** 的送出按鈕並點擊：
```javascript
const btns = Array.from(document.querySelectorAll('button[aria-label="提交"]'));
const active = btns.find(b => !b.disabled);
if (active) active.click();
```

---

### 第七步：等待回應完成

輪詢偵測回應是否生成完畢（最多等 30 秒）：

```javascript
// 每 3 秒讀一次頁面長度，連續兩次相同且 > 初始長度即視為完成
document.body.innerText.length
```

判斷邏輯：
- 記錄送出前的頁面文字長度（baseline）
- 每 3 秒取樣一次
- 連續兩次長度相同 **且** 長度 > baseline + 500 → 視為完成
- 超過 30 秒仍未穩定 → 直接抓現有內容，備註「可能未完整」

---

### 第八步：擷取完整回應

用 JavaScript 定位最後一則回應：

```javascript
const allText = document.body.innerText;
// 找最後一個回應區塊（NotebookLM 回應通常在頁面底部）
// 以查詢問題為錨點往後截取
const idx = allText.lastIndexOf('{{查詢問題的前幾個字}}');
allText.slice(idx > 0 ? idx : allText.length - 6000);
```

取完整段落，**不做任何摘要或篩選**。

---

### 第九步：存入 Inbox

將完整內容以以下格式附加至 `500_Inbox/inbox.md`：

```markdown

---

## NotebookLM 查詢｜YYYY-MM-DD HH:MM

**知識庫：** {{知識庫名稱}}
**查詢：** {{查詢問題}}

{{完整原始回應}}

> 來源：NotebookLM — 尚未整理為筆記
```

---

### 第十步：回報完成

告知使用者：
```
完成！回應已完整存入 Inbox。
共約 XXX 字，來自「{{知識庫名稱}}」。
要現在整理成 NOTE 嗎？
```

---

## 注意事項

- **不做任何內容摘要**：完整原始回應原封不動存入 Inbox
- **不自動整理成 NOTE**：等使用者確認後再走 note-capture 流程
- Chrome MCP 工具使用前必須先呼叫 `tabs_context_mcp` 取得 tabId
- NotebookLM 頁面為 React SPA，`form_input` 後必須用 JavaScript 觸發 input 事件，否則 React 不會偵測到
- 送出按鈕有兩個（一個 disabled、一個 active），必須點擊 **未 disabled** 的那個
- 若頁面因 JS 操作發生非預期導航，重新導覽回正確的 notebook URL 再繼續
