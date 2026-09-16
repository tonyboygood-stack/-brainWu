/**
 * QuickAdd user script: copy a scoped instruction for the active Markdown file.
 * It deliberately does not call an API or create notes. The user pastes the
 * copied instruction into the current Codex/GPT conversation, which keeps the
 * clinical context and final judgement with the user.
 */
module.exports = async (params) => {
    const { app } = params;
    const file = app.workspace.getActiveFile();

    if (!file || file.extension !== "md") {
        new Notice("請先開啟要交給 AI 的 Markdown 筆記。");
        return;
    }

    const noteLink = `[[${file.path.replace(/\.md$/i, "")}]]`;
    const prompt = `請處理我目前閱讀的這一篇筆記。

來源檔案（Vault 相對路徑）：\`${file.path}\`
Obsidian 連結：${noteLink}

先閱讀 \`000_Agent/workflows/clinical-knowledge-harvest.md\`，並以它作為本次的工作規則。

本次處理範圍：
1. 優先處理這篇中所有尚未處理的 \`#需求\` 區塊；同一區塊的 \`#靈感發想\` 或 \`#行動與待辦\` 只有在帶有 \`#需求\` 時才可處理。
2. 若本頁沒有 \`#需求\`，才收成仍標記為 \`#我的收穫\`、\`#我的疑問\` 的區塊。
3. 不要重讀整個 Vault；只讀本頁相關區塊與必要上下文，再做有目的的本機檢索。\`>[!tip]\`、\`>[!question]\` 等 callout 中的實際標籤可正常處理；只有反引號、程式碼區塊或模板說明文字中的標籤必須忽略。

請依產物用途決定去處，而不是建立泛用 AI 輸出資料夾：
- 可重用的臨床比較、經驗、鑑別或理解 → \`400_Atlas/Notes/\`，初始為 \`🔵 待我理解\`。
- 尚不能判定、需繼續找資料或病例 → \`400_Atlas/Questions/\`，初始為 \`🔵 澆水中\`。
- 只服務於這一頁、沒有獨立重用價值的小回答 → 寫回原頁的 \`## AI 處理結果\`，不另建卡。
- 僅在需求明說「建立待辦／納入專案／排入計畫」時，才新增或調整 \`100_Todo/\` 或 \`600_Projects/\` 的工作項目。
- 除非我明說，請不要建立 Library 條目。

若 \`#需求\` 有 \`產出：\` 指定，優先採用；未指定時自行判斷去處並說明理由。先搜尋既有 Notes，能補既有卡便不要重複建卡。所有獨立產物都要回連此來源頁、標出來源和不確定處，並連到合適的 MOC。

完成後，只更新已處理的來源區塊：\`#需求\` 改為 \`#已處理\`，並加入 \`產出：[[...]]\`。不得改動未處理的相鄰標記。最後給我一段很短的處理摘要，以及我下一步最值得判讀或決定的地方。`;

    try {
        await navigator.clipboard.writeText(prompt);
    } catch (clipboardError) {
        const textarea = document.createElement("textarea");
        textarea.value = prompt;
        textarea.style.position = "fixed";
        textarea.style.opacity = "0";
        document.body.appendChild(textarea);
        textarea.select();
        const copied = document.execCommand("copy");
        textarea.remove();
        if (!copied) throw clipboardError;
    }

    new Notice("已複製「交給 AI」指令；切到 Codex/GPT 後直接貼上即可。");
};
