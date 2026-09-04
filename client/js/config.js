/* Desktop-avatar skin selection. The sidecar and wire protocol stay shared. */
const avatarPageUrl = new URL(window.location.href);
const avatarWsProtocol = avatarPageUrl.protocol === "https:" ? "wss:" : "ws:";
const requestedSkin = String(avatarPageUrl.searchParams.get("skin") || "umaru").toLowerCase();

const AVATAR_SKINS = Object.freeze({
  umaru: Object.freeze({
    skin: "umaru",
    renderer: "live2d",
    title: "妹妹的桌面小家",
    displayName: "妹妹",
    documentLanguage: "zh-CN",
    modelPath: "./assets/model/umaru/model.json",
    messageBeepEnabled: false,
    display: Object.freeze({ width: 220, height: 420, hOffset: 10, vOffset: -10 }),
    ui: Object.freeze({
      chatAriaLabel: "和妹妹聊天",
      avatarAriaLabel: "妹妹的桌面形象",
      inputPlaceholder: "和妹妹说点什么…（Shift+Enter 换行）",
      send: "发送",
      clearView: "清屏",
      clearViewTitle: "只清空当前画面，不删除记录",
      clearHistory: "清空记录",
      clearHistoryTitle: "永久删除全部桌宠聊天记录",
      closeTitle: "关闭聊天框",
      checklistTitle: "正在做",
    }),
  }),
  pal: Object.freeze({
    skin: "pal",
    renderer: "webgl",
    title: "Pal Desktop Companion",
    displayName: "Pal",
    documentLanguage: "en",
    skinManifestPath: "./desktop-avatar-skin-manifest.json",
    messageBeepEnabled: true,
    messageBeepFrequencyHz: 880,
    messageBeepVolume: 0.045,
    display: Object.freeze({ width: 260, height: 520, hOffset: 0, vOffset: -6 }),
    ui: Object.freeze({
      chatAriaLabel: "Chat with Pal",
      avatarAriaLabel: "Pal desktop companion",
      inputPlaceholder: "Message Pal… (Shift+Enter for a new line)",
      send: "Send",
      clearView: "Clear view",
      clearViewTitle: "Clear the current view without deleting history",
      clearHistory: "Clear history",
      clearHistoryTitle: "Permanently delete desktop companion chat history",
      closeTitle: "Close chat",
      checklistTitle: "In progress",
    }),
  }),
});

const selectedSkin = AVATAR_SKINS[requestedSkin] || AVATAR_SKINS.umaru;
document.documentElement.dataset.avatarSkin = selectedSkin.skin;
document.documentElement.lang = selectedSkin.documentLanguage;

window.AVATAR_CONFIG = {
  wsUrl: `${avatarWsProtocol}//${avatarPageUrl.host}`,
  reconnectDelayMs: 3000,
  idleActionMinMs: 14000,
  idleActionJitterMs: 18000,
  ...selectedSkin,
};
