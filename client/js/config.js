/* Desktop-avatar skin selection. The sidecar and wire protocol stay shared. */
const avatarPageUrl = new URL(window.location.href);
const avatarWsProtocol = avatarPageUrl.protocol === "https:" ? "wss:" : "ws:";
const requestedSkin = String(avatarPageUrl.searchParams.get("skin") || "pal").toLowerCase();

const AVATAR_SKINS = Object.freeze({
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

const selectedSkin = requestedSkin === "pal2d"
  ? Object.freeze({ ...AVATAR_SKINS.pal, renderer: "svg" })
  : requestedSkin === "pal3d" ? AVATAR_SKINS.pal
  : AVATAR_SKINS[requestedSkin] || AVATAR_SKINS.pal;
document.documentElement.dataset.avatarSkin = selectedSkin.skin;
document.documentElement.lang = selectedSkin.documentLanguage;

window.AVATAR_CONFIG = {
  wsUrl: `${avatarWsProtocol}//${avatarPageUrl.host}`,
  reconnectDelayMs: 3000,
  idleActionMinMs: 14000,
  idleActionJitterMs: 18000,
  ...selectedSkin,
};
