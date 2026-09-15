const { Plugin, ItemView, Notice, normalizePath } = require("obsidian");

const VIEW_TYPE = "clinical-home-console-v3";
const TODAY_PATH = "100_Todo/今日要事.md";
const READING_DOCK_PATH = "400_Atlas/閱讀停靠站.md";
const CLINIC_ROOT = "600_Projects/東湖診所開業計畫";

function text(value) {
  return value == null ? "" : String(value).trim();
}

function isIn(file, folder) {
  return file.path.startsWith(`${folder}/`);
}

function priority(value) {
  return (text(value).match(/⭐/g) || []).length;
}

function dateLabel(timestamp) {
  if (!timestamp) return "—";
  return new Date(timestamp).toLocaleDateString("zh-TW", { month: "numeric", day: "numeric" });
}

function withoutDatePrefix(name) {
  return name.replace(/^\d{4}-\d{2}-\d{2}_/, "");
}

class ClinicalHomeConsoleView extends ItemView {
  constructor(leaf, plugin) {
    super(leaf);
    this.plugin = plugin;
    this.activeTab = "guide";
    this.contentEl.empty();
    this.contentEl.addClass("clinical-console");
    this.contentEl.createEl("h2", { cls: "console-bootstrap", text: "臨床主控台正在啟動…" });
  }

  getViewType() { return VIEW_TYPE; }
  getDisplayText() { return "臨床主控台"; }
  getIcon() { return "layout-dashboard"; }

  async onOpen() {
    await this.renderSafely();
  }

  async renderSafely() {
    try {
      await this.render();
    } catch (error) {
      console.error("臨床主控台渲染失敗", error);
      this.renderError(error);
    }
  }

  async render() {
    const root = this.contentEl;
    root.empty();
    root.addClass("clinical-console");
    root.createEl("p", { cls: "console-loading", text: "正在整理今日焦點與知識脈絡…" });
    const data = await this.collectData();
    root.empty();
    this.renderHeader(root, data);
    this.renderTabs(root, data);
  }

  fm(file) {
    return this.app.metadataCache.getFileCache(file)?.frontmatter || {};
  }

  async readFile(path) {
    const file = this.app.vault.getAbstractFileByPath(normalizePath(path));
    if (!file || !file.extension) return "";
    return this.app.vault.read(file);
  }

  async collectData() {
    const files = this.app.vault.getMarkdownFiles();
    const byPath = (path) => this.app.vault.getAbstractFileByPath(normalizePath(path));
    const todayFile = byPath(TODAY_PATH);
    const dockFile = byPath(READING_DOCK_PATH);
    const clinicIndex = byPath(`${CLINIC_ROOT}/index.md`);
    const clinicBase = byPath(`${CLINIC_ROOT}/診所進度儀表板.base`);

    const knowledge = files
      .filter((file) => isIn(file, "400_Atlas/Notes") && text(this.fm(file).type) === "personal-clinical-knowledge")
      .sort((a, b) => b.stat.mtime - a.stat.mtime);
    const questions = files
      .filter((file) => isIn(file, "400_Atlas/Questions"))
      .sort((a, b) => b.stat.mtime - a.stat.mtime);
    const clinicTasks = files
      .filter((file) => isIn(file, `${CLINIC_ROOT}/tasks`))
      .map((file) => ({ file, fm: this.fm(file) }))
      .filter((entry) => text(entry.fm.status) !== "🟢 完成")
      .sort((a, b) => {
        const timeRank = { "今天必達": 5, "本週目標": 4, "本月目標": 3, "本季目標": 2, "未分類": 1 };
        return (timeRank[text(b.fm.時間)] || 0) - (timeRank[text(a.fm.時間)] || 0)
          || priority(b.fm.優先度) - priority(a.fm.優先度)
          || b.file.stat.mtime - a.file.stat.mtime;
      });
    const sideInbox = files
      .filter((file) => {
        const tags = this.app.metadataCache.getFileCache(file)?.tags || [];
        return tags.some((tag) => tag.tag === "#靈感發想" || tag.tag === "#行動與待辦");
      })
      .sort((a, b) => b.stat.mtime - a.stat.mtime);
    const projectIndexes = files
      .filter((file) => file.path.startsWith("600_Projects/") && file.name === "index.md" && file.path.split("/").length === 3)
      .sort((a, b) => b.stat.mtime - a.stat.mtime);

    const todayText = todayFile ? await this.app.vault.read(todayFile) : "";
    const dockText = dockFile ? await this.app.vault.read(dockFile) : "";
    const todayItems = this.extractChecklist(todayText, "今日三件事");
    const dock = this.extractDock(dockText);
    const stage = (label) => knowledge.filter((file) => text(this.fm(file).knowledge_stage) === label);
    const wateredQuestions = questions.filter((file) => text(this.fm(file).stage).includes("澆水"));
    const completedClinic = files.filter((file) => isIn(file, `${CLINIC_ROOT}/tasks`) && text(this.fm(file).status) === "🟢 完成");

    return {
      todayFile, dockFile, clinicIndex, clinicBase,
      todayStatus: todayFile ? text(this.fm(todayFile).status) : "未確認",
      todayDate: todayFile ? text(this.fm(todayFile).date) : "",
      todayItems, dock, knowledge, questions, wateredQuestions, clinicTasks, completedClinic,
      sideInbox, projectIndexes,
      stages: {
        water: stage("🟤 待澆水"),
        review: stage("🔵 待我理解"),
        bloom: stage("🌸 延伸中"),
        integrated: stage("🟢 已整合")
      }
    };
  }

  extractChecklist(content, heading) {
    const part = content.split(`## ${heading}`)[1]?.split("## ")[0] || "";
    return [...part.matchAll(/^- \[([ xX])\]\s+(.+)$/gm)].map((match) => ({ done: match[1].toLowerCase() === "x", label: match[2] }));
  }

  extractDock(content) {
    const field = (key) => {
      const found = content.match(new RegExp(`- \\*\\*${key}\\*\\*：\\s*(.*)`));
      return found ? found[1].trim() : "";
    };
    return {
      source: field("來源"),
      location: field("停在"),
      clue: field("剛抓到的線索"),
      unresolved: field("尚未想完"),
      next: field("下次第一步"),
      parked: field("最後停靠")
    };
  }

  renderHeader(root, data) {
    const header = root.createDiv({ cls: "console-header" });
    const title = header.createDiv({ cls: "console-title" });
    title.createEl("span", { cls: "console-mark", text: "吳" });
    const words = title.createDiv();
    words.createEl("h1", { text: "主控台" });
    words.createEl("p", { text: "今天只看已確認的重點；其他事情留在它們原本的位置。" });
    const tools = header.createDiv({ cls: "console-tools" });
    this.button(tools, "↻ 重新整理", "subtle", () => this.renderSafely());
    this.button(tools, "複製「早安」", "accent", () => this.copy("早安"));

    const metrics = root.createDiv({ cls: "console-metrics" });
    this.metric(metrics, "今日要事", data.todayItems.length, data.todayStatus === "已確認" ? "lime" : "muted");
    this.metric(metrics, "待我理解", data.stages.review.length, "violet");
    this.metric(metrics, "澆水中問題", data.wateredQuestions.length, "blue");
    this.metric(metrics, "診所進行中", data.clinicTasks.length, "orange");
  }

  renderTabs(root, data) {
    const tabs = [
      ["guide", "行動指南"], ["reading", "閱讀學習"], ["knowledge", "我的知識庫"], ["clinic", "診所規劃"]
    ];
    const nav = root.createDiv({ cls: "console-tabs" });
    const body = root.createDiv({ cls: "console-body" });
    const show = (key) => {
      this.activeTab = key;
      [...nav.children].forEach((node) => node.toggleClass("is-active", node.dataset.tab === key));
      body.empty();
      if (key === "guide") this.renderGuide(body, data);
      if (key === "reading") this.renderReading(body, data);
      if (key === "knowledge") this.renderKnowledge(body, data);
      if (key === "clinic") this.renderClinic(body, data);
    };
    tabs.forEach(([key, label]) => {
      const tab = nav.createEl("button", { text: label, cls: "console-tab" });
      tab.dataset.tab = key;
      tab.onclick = () => show(key);
    });
    show(this.activeTab);
  }

  renderGuide(body, data) {
    const grid = body.createDiv({ cls: "console-grid guide-grid" });
    const today = this.panel(grid, "行動・今天", "今日要事", "今天真正承諾的最多三件事");
    const action = today.createDiv({ cls: "panel-actions" });
    this.button(action, "開啟", "subtle", () => this.open(data.todayFile));
    this.button(action, "早安流程", "accent", () => this.copy("早安"));
    if (data.todayStatus === "已確認" && data.todayItems.length) {
      this.checklist(today, data.todayItems);
    } else {
      this.empty(today, "今天尚未確認焦點。按「早安流程」後，在對話中確認你的三件事。", "不自動替你排程");
    }

    const inbox = this.panel(grid, "旁路收件匣", "靈感與行動", "先保留，不打斷眼前工作");
    this.button(inbox.createDiv({ cls: "panel-actions" }), "開啟收件匣", "subtle", () => this.openPath("100_Todo/讀書旁路收件匣.md"));
    if (data.sideInbox.length) this.fileList(inbox, data.sideInbox.slice(0, 5), "side");
    else this.empty(inbox, "目前沒有標記的靈感或行動。", "閱讀中隨手寫 #靈感發想 或 #行動與待辦");

    const tracking = this.panel(grid, "任務・追蹤", "下一步任務", "只顯示診所專案的高優先度進行項");
    this.button(tracking.createDiv({ cls: "panel-actions" }), "診所看板", "subtle", () => this.open(data.clinicBase));
    this.taskList(tracking, data.clinicTasks.slice(0, 5));

    const longTerm = this.panel(grid, "方向・中長期", "進行中的專案", "進入專案原始頁面看完整脈絡");
    this.fileList(longTerm, data.projectIndexes.slice(0, 5), "project");
  }

  renderReading(body, data) {
    const grid = body.createDiv({ cls: "console-grid reading-grid" });
    const current = this.panel(grid, "閱讀・現在", "正在閱讀", "從停靠點回到下一步，不重新找線索");
    const currentActions = current.createDiv({ cls: "panel-actions" });
    this.button(currentActions, "開啟停靠站", "subtle", () => this.open(data.dockFile));
    const dock = data.dock;
    if (dock.source && !dock.source.includes("尚未設定")) {
      this.detail(current, "來源", dock.source);
      this.detail(current, "停在", dock.location || "尚未標記");
      this.detail(current, "抓到的線索", dock.clue || "尚未標記");
      this.detail(current, "下次第一步", dock.next || "尚未標記", true);
    } else {
      this.empty(current, "尚未設定目前閱讀主線。", "在閱讀停靠站填一行來源與下一步即可開始");
    }

    const harvest = this.panel(grid, "收成・待處理", "收穫與問題", "先看 AI 已補過資料、等待你寫下理解的卡片");
    const harvestActions = harvest.createDiv({ cls: "panel-actions" });
    this.button(harvestActions, "複製收成指令", "accent", () => this.copy("整理新的規則候選"));
    this.section(harvest, "待我理解", data.stages.review, "knowledge");
    this.section(harvest, "澆水中的問題", data.wateredQuestions, "question");
  }

  renderKnowledge(body, data) {
    const top = body.createDiv({ cls: "knowledge-summary" });
    const statement = top.createDiv();
    statement.createEl("span", { text: "我的臨床知識" });
    statement.createEl("h2", { text: "開花後，才進入這裡。" });
    statement.createEl("p", { text: "這裡只呈現經過資料補充、你閱讀過並整合到自己臨床網絡的知識卡。" });
    const counts = top.createDiv({ cls: "knowledge-counts" });
    [["待澆水", data.stages.water.length], ["待我理解", data.stages.review.length], ["延伸中", data.stages.bloom.length], ["已整合", data.stages.integrated.length]].forEach(([label, value]) => this.metric(counts, label, value, "muted"));
    const grid = body.createDiv({ cls: "console-grid knowledge-grid" });
    const integrated = this.panel(grid, "知識庫・已整合", "最近開花的知識", "開啟原卡或回到臨床知識箱");
    this.button(integrated.createDiv({ cls: "panel-actions" }), "臨床知識箱", "subtle", () => this.openPath("400_Atlas/Maps/我的臨床知識箱 MOC.md"));
    this.fileList(integrated, data.stages.integrated.slice(0, 8), "knowledge");
    const growing = this.panel(grid, "知識庫・成長中", "等待你理解與延伸", "不是待辦壓力，而是下一次回來時可繼續想的地方");
    this.section(growing, "待我理解", data.stages.review, "knowledge");
    this.section(growing, "延伸中", data.stages.bloom, "knowledge");
  }

  renderClinic(body, data) {
    const hero = body.createDiv({ cls: "clinic-hero" });
    const copy = hero.createDiv();
    copy.createEl("span", { text: "平衡木中醫診所・開業計畫" });
    copy.createEl("h2", { text: "只盯住會推動開業的下一步。" });
    copy.createEl("p", { text: `共 ${data.clinicTasks.length + data.completedClinic.length} 項任務；目前 ${data.clinicTasks.length} 項尚在進行或待辦。` });
    const actions = hero.createDiv({ cls: "hero-actions" });
    this.button(actions, "開啟專案脈絡", "subtle", () => this.open(data.clinicIndex));
    this.button(actions, "開啟任務看板", "accent", () => this.open(data.clinicBase));
    const grid = body.createDiv({ cls: "console-grid clinic-grid" });
    const focus = this.panel(grid, "診所・近期焦點", "本週／本月優先任務", "依時間層級與優先度排序；完整清單留在看板");
    this.taskList(focus, data.clinicTasks.slice(0, 10));
    const routes = this.panel(grid, "診所・常用入口", "專案操作", "需要完整時程、財務或任務分類時再進入");
    this.linkButton(routes, "開業計畫總覽", data.clinicIndex);
    this.linkButton(routes, "診所進度儀表板", data.clinicBase);
    this.linkButton(routes, "財務規劃", this.app.vault.getAbstractFileByPath(`${CLINIC_ROOT}/財務/index.md`));
    this.empty(routes, "主控台不複製 82 張任務卡。", "原始任務仍由專案看板管理");
  }

  panel(parent, eyebrow, title, description) {
    const panel = parent.createDiv({ cls: "console-panel" });
    panel.createEl("span", { cls: "panel-eyebrow", text: eyebrow });
    panel.createEl("h2", { text: title });
    panel.createEl("p", { cls: "panel-description", text: description });
    return panel;
  }

  metric(parent, label, value, tone) {
    const metric = parent.createDiv({ cls: `console-metric ${tone}` });
    metric.createEl("strong", { text: String(value) });
    metric.createEl("span", { text: label });
  }

  button(parent, label, tone, handler) {
    const button = parent.createEl("button", { cls: `console-button ${tone}`, text: label });
    button.onclick = handler;
    return button;
  }

  detail(parent, label, value, emphasis = false) {
    const row = parent.createDiv({ cls: `detail-row ${emphasis ? "emphasis" : ""}` });
    row.createEl("span", { text: label });
    row.createEl("p", { text: value });
  }

  checklist(parent, items) {
    const list = parent.createDiv({ cls: "console-list checklist" });
    items.forEach((item) => {
      const row = list.createDiv({ cls: item.done ? "is-done" : "" });
      row.createEl("span", { text: item.done ? "✓" : "○" });
      row.createEl("p", { text: item.label });
    });
  }

  taskList(parent, entries) {
    if (!entries.length) return this.empty(parent, "目前沒有可顯示的進行中任務。", "可從診所任務看板新增或調整狀態");
    const list = parent.createDiv({ cls: "console-list task-list" });
    entries.forEach(({ file, fm }) => {
      const row = list.createEl("button", { cls: "console-row" });
      row.onclick = () => this.open(file);
      const main = row.createDiv();
      main.createEl("strong", { text: text(fm.目標) || withoutDatePrefix(file.basename) });
      main.createEl("span", { text: `${text(fm.area) || "未分類"}・${text(fm.時間) || "未分類"}` });
      const badge = row.createEl("em", { text: text(fm.優先度) || text(fm.status) || "待辦" });
      badge.addClass("task-badge");
    });
  }

  fileList(parent, files, type) {
    if (!files.length) return this.empty(parent, "目前沒有項目。", "資料出現後會自動顯示在這裡");
    const list = parent.createDiv({ cls: `console-list file-list ${type}` });
    files.forEach((file) => {
      const row = list.createEl("button", { cls: "console-row" });
      row.onclick = () => this.open(file);
      row.createEl("strong", { text: withoutDatePrefix(file.basename) });
      const fm = this.fm(file);
      row.createEl("span", { text: text(fm.says) || text(fm.knowledge_stage) || dateLabel(file.stat.mtime) });
    });
  }

  section(parent, title, files, type) {
    const section = parent.createDiv({ cls: "mini-section" });
    section.createEl("h3", { text: `${title} (${files.length})` });
    if (files.length) this.fileList(section, files.slice(0, 5), type);
    else section.createEl("p", { cls: "empty-copy", text: "目前沒有項目。" });
  }

  linkButton(parent, label, file) {
    if (!file) return;
    this.button(parent, label, "wide", () => this.open(file));
  }

  empty(parent, message, hint) {
    const empty = parent.createDiv({ cls: "console-empty" });
    empty.createEl("p", { text: message });
    if (hint) empty.createEl("span", { text: hint });
  }

  renderError(error) {
    const root = this.contentEl;
    root.empty();
    root.addClass("clinical-console");
    const card = root.createDiv({ cls: "console-error" });
    card.createEl("span", { text: "主控台需要重新載入" });
    card.createEl("h2", { text: "資料讀取時出現一個可修正的錯誤。" });
    card.createEl("p", { text: "請按下方重新載入；若仍出現，將錯誤文字截圖傳給我即可。" });
    card.createEl("code", { text: text(error?.message) || "未知的渲染錯誤" });
    this.button(card, "↻ 重新載入主控台", "accent", () => this.renderSafely());
  }

  async open(file) {
    if (!file) return new Notice("找不到對應筆記。");
    await this.app.workspace.getLeaf(false).openFile(file);
  }

  async openPath(path) {
    const file = this.app.vault.getAbstractFileByPath(normalizePath(path));
    await this.open(file);
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
  async onload() {
    this.registerView(VIEW_TYPE, (leaf) => new ClinicalHomeConsoleView(leaf, this));
    this.addRibbonIcon("layout-dashboard", "開啟臨床主控台", () => this.activateView());
    this.addCommand({ id: "open-clinical-home-console", name: "開啟臨床主控台", callback: () => this.activateView() });
    this.app.workspace.onLayoutReady(() => {
      // Do not reuse the old side-pane tab. It can survive a plugin reload as
      // an empty placeholder, so start the console as a real central workspace.
      setTimeout(() => void this.activateView(true), 80);
    });
  }

  async activateView(startFresh = false) {
    const existing = this.app.workspace.getLeavesOfType(VIEW_TYPE);
    if (startFresh) existing.forEach((oldLeaf) => oldLeaf.detach());
    let leaf = startFresh ? null : existing.find((item) => item.view instanceof ClinicalHomeConsoleView);
    if (!leaf) {
      leaf = this.app.workspace.getLeaf("tab");
      await leaf.setViewState({ type: VIEW_TYPE, active: true });
    }
    const view = leaf.view;
    if (view && typeof view.renderSafely === "function") await view.renderSafely();
    this.app.workspace.revealLeaf(leaf);
  }

  async onunload() {
    this.app.workspace.getLeavesOfType(VIEW_TYPE).forEach((leaf) => leaf.detach());
  }
};
