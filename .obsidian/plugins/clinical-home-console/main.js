const { ItemView, Notice, Plugin } = require("obsidian");

const VIEW_TYPE = "clinical-home-console-v11";
const LEGACY_VIEW_TYPES = ["clinical-home-console", "clinical-home-console-v3", "clinical-home-console-minimal"];
const TODAY_PATH = "100_Todo/今日要事.md";
const READING_DOCK_PATH = "400_Atlas/閱讀停靠站.md";
const CLINIC_ROOT = "600_Projects/東湖診所開業計畫";

const text = (value) => value == null ? "" : String(value).trim();
const titleOf = (file) => file.basename.replace(/^\d{4}-\d{2}-\d{2}_/, "");
const isIn = (file, folder) => file.path.startsWith(`${folder}/`);

class ClinicalHomeConsoleView extends ItemView {
  constructor(leaf) {
    super(leaf);
    this.activeTab = "guide";
  }

  getViewType() { return VIEW_TYPE; }
  getDisplayText() { return "臨床主控台"; }
  getIcon() { return "layout-dashboard"; }

  async onOpen() { await this.renderSafely(); }

  async renderSafely() {
    try {
      await this.render();
    } catch (error) {
      console.error("臨床主控台資料讀取失敗", error);
      const { contentEl } = this;
      contentEl.empty();
      contentEl.addClass("clinical-console");
      const card = contentEl.createDiv({ cls: "cc-panel cc-error" });
      card.createEl("p", { cls: "cc-panel-label", text: "主控台暫時無法讀取資料" });
      card.createEl("h2", { text: "介面仍可用，資料區塊暫停載入。" });
      card.createEl("p", { cls: "cc-panel-copy", text: text(error.message) || "未知錯誤" });
      this.button(card, "重新整理", "accent", () => void this.renderSafely());
    }
  }

  fm(file) {
    return this.app.metadataCache.getFileCache(file)?.frontmatter || {};
  }

  hasTag(file, tag) {
    const tags = this.app.metadataCache.getFileCache(file)?.tags || [];
    return tags.some((item) => item.tag === tag);
  }

  async read(file) {
    if (!file) return "";
    try { return await this.app.vault.read(file); }
    catch (error) { return ""; }
  }

  async collectData() {
    const files = this.app.vault.getMarkdownFiles();
    const byPath = (path) => files.find((file) => file.path === path) || null;
    const todayFile = byPath(TODAY_PATH);
    const dockFile = byPath(READING_DOCK_PATH);
    const clinicIndex = byPath(`${CLINIC_ROOT}/index.md`);
    const todayText = await this.read(todayFile);
    const dockText = await this.read(dockFile);
    const knowledge = files
      .filter((file) => isIn(file, "400_Atlas/Notes") && text(this.fm(file).type) === "personal-clinical-knowledge")
      .sort((a, b) => b.stat.mtime - a.stat.mtime);
    const questions = files
      .filter((file) => isIn(file, "400_Atlas/Questions"))
      .sort((a, b) => b.stat.mtime - a.stat.mtime);
    const clinicTasks = files
      .filter((file) => isIn(file, `${CLINIC_ROOT}/tasks`))
      .filter((file) => text(this.fm(file).status) !== "🟢 完成")
      .sort((a, b) => this.taskRank(b) - this.taskRank(a) || b.stat.mtime - a.stat.mtime);
    const projects = files
      .filter((file) => file.path.startsWith("600_Projects/") && file.name === "index.md" && file.path.split("/").length === 3)
      .sort((a, b) => b.stat.mtime - a.stat.mtime);
    const harvests = files.filter((file) => this.hasTag(file, "#我的收穫")).sort((a, b) => b.stat.mtime - a.stat.mtime);
    const questionsTagged = files.filter((file) => this.hasTag(file, "#我的疑問")).sort((a, b) => b.stat.mtime - a.stat.mtime);
    const inspirations = files.filter((file) => this.hasTag(file, "#靈感發想")).sort((a, b) => b.stat.mtime - a.stat.mtime);
    const actions = files.filter((file) => this.hasTag(file, "#行動與待辦")).sort((a, b) => b.stat.mtime - a.stat.mtime);
    const stage = (label) => knowledge.filter((file) => text(this.fm(file).knowledge_stage) === label);
    return {
      todayFile, dockFile, clinicIndex, today: this.parseToday(todayText), dock: this.parseDock(dockText),
      todayStatus: todayFile ? text(this.fm(todayFile).status) : "未設定",
      knowledge, questions, clinicTasks, projects, harvests, questionsTagged, inspirations, actions,
      stages: { water: stage("🟤 待澆水"), review: stage("🔵 待我理解"), bloom: stage("🌸 延伸中"), integrated: stage("🟢 已整合") },
      wateredQuestions: questions.filter((file) => text(this.fm(file).stage).includes("澆水"))
    };
  }

  taskRank(file) {
    const fm = this.fm(file);
    const time = { "今天必達": 50, "本週目標": 40, "本月目標": 30, "本季目標": 20, "未分類": 10 }[text(fm.時間)] || 0;
    return time + (text(fm.優先度).match(/⭐/g) || []).length;
  }

  parseToday(content) {
    const part = content.split("## 今日三件事")[1]?.split("## ")[0] || "";
    return [...part.matchAll(/^- \[([ xX])\]\s+(.+)$/gm)].map((match) => ({ done: match[1].toLowerCase() === "x", label: match[2] }));
  }

  parseDock(content) {
    const field = (name) => content.match(new RegExp(`- \\*\\*${name}\\*\\*：\\s*(.*)`))?.[1]?.trim() || "";
    return { source: field("來源"), location: field("停在"), clue: field("剛抓到的線索"), next: field("下次第一步") };
  }

  async render() {
    const data = await this.collectData();
    const { contentEl } = this;
    contentEl.empty();
    contentEl.addClass("clinical-console");
    this.renderHeader(contentEl, data);
    const tabs = contentEl.createDiv({ cls: "cc-tabs" });
    const body = contentEl.createDiv({ cls: "cc-body" });
    const choices = [["guide", "行動指南"], ["reading", "閱讀學習"], ["knowledge", "我的知識庫"], ["clinic", "診所規劃"]];
    const show = (key) => {
      this.activeTab = key;
      [...tabs.children].forEach((item) => item.toggleClass("is-active", item.dataset.tab === key));
      body.empty();
      if (key === "guide") this.renderGuide(body, data);
      if (key === "reading") this.renderReading(body, data);
      if (key === "knowledge") this.renderKnowledge(body, data);
      if (key === "clinic") this.renderClinic(body, data);
    };
    choices.forEach(([key, label]) => {
      const button = tabs.createEl("button", { cls: "cc-tab", text: label });
      button.dataset.tab = key;
      button.onclick = () => show(key);
    });
    show(this.activeTab);
  }

  renderHeader(root, data) {
    const header = root.createDiv({ cls: "cc-header" });
    const title = header.createDiv();
    title.createEl("p", { cls: "cc-eyebrow", text: "WU CLINICAL SYSTEM" });
    title.createEl("h1", { text: "臨床主控台" });
    title.createEl("p", { cls: "cc-subtitle", text: "把今天、學習、個人知識與診所專案放在同一個清楚的入口。" });
    const tools = header.createDiv({ cls: "cc-tools" });
    this.button(tools, "↻ 更新資料", "quiet", () => void this.renderSafely());
    this.button(tools, "複製「早安」", "accent", () => this.copy("早安"));
    const metrics = root.createDiv({ cls: "cc-metrics" });
    this.metric(metrics, "今日要事", data.today.length, "lime");
    this.metric(metrics, "待我理解", data.stages.review.length, "violet");
    this.metric(metrics, "澆水中問題", data.wateredQuestions.length, "blue");
    this.metric(metrics, "診所進行中", data.clinicTasks.length, "orange");
  }

  renderGuide(root, data) {
    const grid = root.createDiv({ cls: "cc-grid cc-guide" });
    const today = this.panel(grid, "行動・今天", "今日要事", "只顯示「早安」後由你確認的焦點。", "large");
    this.button(today, "開啟今日要事", "quiet", () => this.open(data.todayFile));
    if (data.todayStatus === "已確認" && data.today.length) this.checklist(today, data.today);
    else this.empty(today, "今天尚未確認焦點。", "在對話中說「早安」，確認後才會寫入這裡。");

    const inbox = this.panel(grid, "旁路收件匣", "靈感與行動", "閱讀中先記下，不要求立即處理。", "side");
    this.miniList(inbox, "靈感發想", data.inspirations, "目前沒有標記的靈感。");
    this.miniList(inbox, "行動與待辦", data.actions, "目前沒有待處理行動。");

    const tasks = this.panel(grid, "任務・追蹤", "診所近期任務", "依時間層級與優先度排序；完整管理仍在專案看板。", "wide");
    this.fileList(tasks, data.clinicTasks.slice(0, 6), (file) => `${text(this.fm(file).area) || "未分類"}・${text(this.fm(file).時間) || "未分類"}`);

    const projects = this.panel(grid, "方向・中長期", "進行中的專案", "需要完整脈絡時，再回到各專案首頁。", "side");
    this.fileList(projects, data.projects.slice(0, 5), () => "專案總覽");
  }

  renderReading(root, data) {
    const grid = root.createDiv({ cls: "cc-grid cc-reading" });
    const reading = this.panel(grid, "閱讀・現在", "正在閱讀", "下次回來時，從停靠點開始，而不是重新找脈絡。", "large");
    this.button(reading, "開啟停靠站", "quiet", () => this.open(data.dockFile));
    if (data.dock.source && !data.dock.source.includes("尚未設定")) {
      this.detail(reading, "來源", data.dock.source);
      this.detail(reading, "停在", data.dock.location || "尚未標記");
      this.detail(reading, "線索", data.dock.clue || "尚未標記");
      this.detail(reading, "下次第一步", data.dock.next || "尚未標記", true);
    } else this.empty(reading, "目前尚未設定閱讀主線。", "只要在閱讀停靠站補一行來源與下次第一步即可。");

    const harvest = this.panel(grid, "收成・待處理", "收穫與問題", "先收集你標記的想法；AI 收成後再寫進個人知識卡。", "side");
    this.button(harvest, "複製「收成這一篇」", "accent", () => this.copy("收成這一篇"));
    this.miniList(harvest, "我的收穫", data.harvests, "尚未有 #我的收穫 標記。", 4);
    this.miniList(harvest, "我的疑問", data.questionsTagged, "尚未有 #我的疑問 標記。", 4);
  }

  renderKnowledge(root, data) {
    const hero = root.createDiv({ cls: "cc-hero" });
    hero.createEl("p", { cls: "cc-eyebrow", text: "MY CLINICAL KNOWLEDGE" });
    hero.createEl("h2", { text: "開花後，才進入我的知識庫。" });
    hero.createEl("p", { text: "不是規則才值得留下；經過資料補充、討論與你自己的理解，才成為臨床筆記。" });
    const grid = root.createDiv({ cls: "cc-grid cc-knowledge" });
    const growing = this.panel(grid, "知識・成長中", "等待你理解", "AI 已澆水或補充，你下次可以從這裡接續。", "side");
    this.miniList(growing, "待我理解", data.stages.review, "目前沒有待理解卡。", 6);
    this.miniList(growing, "延伸中", data.stages.bloom, "目前沒有延伸卡。", 6);
    const integrated = this.panel(grid, "知識・已整合", "已開花的知識", "這裡只列你已確認並能放進臨床網絡的卡。", "side");
    this.miniList(integrated, "已整合", data.stages.integrated, "目前尚未有已整合卡。", 8);
    const questions = this.panel(grid, "問題花園", "澆水中的問題", "問題不是失敗；它們是下一張知識卡的入口。", "wide");
    this.fileList(questions, data.wateredQuestions.slice(0, 8), (file) => text(this.fm(file).stage) || "待澆水");
  }

  renderClinic(root, data) {
    const hero = root.createDiv({ cls: "cc-hero" });
    hero.createEl("p", { cls: "cc-eyebrow", text: "BALANCE BEAM CLINIC" });
    hero.createEl("h2", { text: "診所開業，只盯住能推進下一步的事。" });
    hero.createEl("p", { text: `目前有 ${data.clinicTasks.length} 項尚未完成的專案任務；完整規劃維持在東湖診所專案內。` });
    this.button(hero, "開啟開業計畫", "accent", () => this.open(data.clinicIndex));
    const grid = root.createDiv({ cls: "cc-grid cc-clinic" });
    const focus = this.panel(grid, "診所・近期焦點", "本週／本月優先任務", "把日常決策與專案排程分開，避免淹沒今日要事。", "large");
    this.fileList(focus, data.clinicTasks.slice(0, 10), (file) => `${text(this.fm(file).area) || "未分類"}・${text(this.fm(file).時間) || "未分類"}`);
    const note = this.panel(grid, "診所・使用原則", "主控台不是第二份看板", "在這裡找下一步；需要編輯狀態、排程或細節時，回到專案原始任務卡。", "side");
    this.empty(note, "你不需要在兩處維護同一件事。", "主控台負責看見，原始任務卡負責管理。");
  }

  panel(parent, eyebrow, title, description, size = "") {
    const panel = parent.createDiv({ cls: `cc-panel ${size}` });
    panel.createEl("p", { cls: "cc-panel-label", text: eyebrow });
    panel.createEl("h2", { text: title });
    panel.createEl("p", { cls: "cc-panel-copy", text: description });
    return panel;
  }

  metric(parent, label, value, tone) {
    const metric = parent.createDiv({ cls: `cc-metric ${tone}` });
    metric.createEl("strong", { text: String(value) });
    metric.createEl("span", { text: label });
  }

  button(parent, label, tone, handler) {
    const button = parent.createEl("button", { cls: `cc-button ${tone}`, text: label });
    button.onclick = handler;
    return button;
  }

  detail(parent, label, value, emphasis = false) {
    const row = parent.createDiv({ cls: `cc-detail ${emphasis ? "emphasis" : ""}` });
    row.createEl("span", { text: label });
    row.createEl("p", { text: value });
  }

  checklist(parent, items) {
    const list = parent.createDiv({ cls: "cc-list cc-checklist" });
    items.forEach((item) => {
      const row = list.createDiv({ cls: item.done ? "done" : "" });
      row.createEl("span", { text: item.done ? "✓" : "○" });
      row.createEl("p", { text: item.label });
    });
  }

  miniList(parent, title, files, emptyText, limit = 3) {
    const section = parent.createDiv({ cls: "cc-mini" });
    section.createEl("h3", { text: `${title} (${files.length})` });
    if (files.length) this.fileList(section, files.slice(0, limit), (file) => new Date(file.stat.mtime).toLocaleDateString("zh-TW", { month: "numeric", day: "numeric" }));
    else section.createEl("p", { cls: "cc-empty-copy", text: emptyText });
  }

  fileList(parent, files, subtitle) {
    if (!files.length) return this.empty(parent, "目前沒有可顯示項目。", "資料出現後會自動列在這裡。");
    const list = parent.createDiv({ cls: "cc-list" });
    files.forEach((file) => {
      const row = list.createEl("button", { cls: "cc-row" });
      row.onclick = () => this.open(file);
      row.createEl("strong", { text: titleOf(file) });
      row.createEl("span", { text: subtitle(file) });
    });
  }

  empty(parent, message, hint) {
    const empty = parent.createDiv({ cls: "cc-empty" });
    empty.createEl("p", { text: message });
    if (hint) empty.createEl("span", { text: hint });
  }

  async open(file) {
    if (!file?.path) return new Notice("找不到對應筆記。");
    await this.app.workspace.openLinkText(file.path, "", false);
  }

  async copy(value) {
    try {
      await navigator.clipboard.writeText(value);
      new Notice(`已複製：${value}`);
    } catch (error) {
      new Notice(`請手動輸入：${value}`);
    }
  }
}

module.exports = class ClinicalHomeConsolePlugin extends Plugin {
  onload() {
    this.registerView(VIEW_TYPE, (leaf) => new ClinicalHomeConsoleView(leaf));
    this.addRibbonIcon("layout-dashboard", "開啟臨床主控台", () => void this.activateView());
    this.addCommand({ id: "open-clinical-home-console", name: "開啟臨床主控台", callback: () => void this.activateView() });
    this.app.workspace.onLayoutReady(() => {
      LEGACY_VIEW_TYPES.forEach((type) => this.app.workspace.getLeavesOfType(type).forEach((leaf) => leaf.detach()));
      void this.activateView();
    });
  }

  async activateView() {
    let leaf = this.app.workspace.getLeavesOfType(VIEW_TYPE)[0];
    if (!leaf) {
      leaf = this.app.workspace.getLeaf(true);
      await leaf.setViewState({ type: VIEW_TYPE, active: true });
    }
    await this.app.workspace.revealLeaf(leaf);
  }

  onunload() {
    this.app.workspace.getLeavesOfType(VIEW_TYPE).forEach((leaf) => leaf.detach());
  }
};
