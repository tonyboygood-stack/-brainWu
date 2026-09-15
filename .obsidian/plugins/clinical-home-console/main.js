const { ItemView, Plugin } = require("obsidian");

// Kept deliberately independent of vault data while this first view is verified.
const VIEW_TYPE = "clinical-home-console-minimal";
const LEGACY_VIEW_TYPES = ["clinical-home-console", "clinical-home-console-v3"];

class ClinicalHomeConsoleView extends ItemView {
  getViewType() { return VIEW_TYPE; }
  getDisplayText() { return "臨床主控台"; }
  getIcon() { return "layout-dashboard"; }

  async onOpen() {
    const { contentEl } = this;
    contentEl.empty();
    contentEl.addClass("clinical-console");

    const header = contentEl.createDiv({ cls: "cc-header" });
    header.createEl("p", { cls: "cc-eyebrow", text: "WU CLINICAL SYSTEM" });
    header.createEl("h1", { text: "臨床主控台" });
    header.createEl("p", { cls: "cc-subtitle", text: "先確認介面穩定顯示；資料串接會在下一步逐一加入。" });

    const tabs = contentEl.createDiv({ cls: "cc-tabs" });
    const panel = contentEl.createDiv({ cls: "cc-panel" });
    const tabData = [
      ["行動指南", "今日要事、任務追蹤、靈感與行動、中長期規劃"],
      ["閱讀學習", "正在閱讀，以及等待收成的收穫與問題"],
      ["我的知識庫", "經過澆水、理解與開花後的個人知識卡"],
      ["診所規劃", "東湖診所開業專案的近期排程與下一步"]
    ];
    const show = (name, description, button) => {
      [...tabs.children].forEach((item) => item.toggleClass("is-active", item === button));
      panel.empty();
      panel.createEl("p", { cls: "cc-panel-label", text: "主控台區塊" });
      panel.createEl("h2", { text: name });
      panel.createEl("p", { cls: "cc-panel-copy", text: description });
      panel.createEl("div", { cls: "cc-verified", text: "✓ 視圖已成功載入；下一版開始接入你的實際資料。" });
    };
    tabData.forEach(([name, description], index) => {
      const button = tabs.createEl("button", { cls: "cc-tab", text: name });
      button.onclick = () => show(name, description, button);
      if (index === 0) show(name, description, button);
    });
  }

  async onClose() {
    this.contentEl.empty();
  }
}

module.exports = class ClinicalHomeConsolePlugin extends Plugin {
  onload() {
    this.registerView(VIEW_TYPE, (leaf) => new ClinicalHomeConsoleView(leaf));
    this.addRibbonIcon("layout-dashboard", "開啟臨床主控台", () => void this.activateView());
    this.addCommand({
      id: "open-clinical-home-console",
      name: "開啟臨床主控台",
      callback: () => void this.activateView()
    });
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
