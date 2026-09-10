/* ============================================================
 * 妹妹的桌面小家 — 主逻辑
 * Pal WebGL / SVG + 双击聊天框 + WebSocket
 * 帧协议（JSON）：见 server/sidecar.py
 * ============================================================ */
(function () {
  "use strict";

  const CFG = window.AVATAR_CONFIG || {};
  const syncRoomMotion = () => document.body.classList.toggle("room-animation-paused", document.hidden);
  document.addEventListener("visibilitychange", syncRoomMotion);
  syncRoomMotion();
  const palController = () => CFG.renderer === "raster" ? window.PalRasterAvatar : CFG.renderer === "svg" ? window.PalSVGAvatar : window.PalWebGLAvatar;
  const WS_URL = CFG.wsUrl || "ws://localhost:8765";

  // ---------- DOM ----------
  const chatPanel = document.getElementById("chat-panel");
  const chatMessages = document.getElementById("chat-messages");
  const chatInput = document.getElementById("chat-input");
  const chatSend = document.getElementById("chat-send");
  const chatClose = document.getElementById("chat-close");
  const chatClearScreen = document.getElementById("chat-clear-screen");
  const chatClearHistory = document.getElementById("chat-clear-history");
  const stateBadge = document.getElementById("state-badge");
  const avatarStage = document.getElementById("avatar-stage");
  const toolWorkspace = window.createToolWorkspace(document.getElementById("tool-workspace"), avatarStage);
  const checklistPanel = document.getElementById("checklist-panel");
  const checklistProgress = document.getElementById("checklist-progress");
  const checklistItems = document.getElementById("checklist-items");

  // ---------- 状态 ----------
  let ws = null;
  let reconnectTimer = null;
  let legacyPendingBubble = null;
  let legacySealTimer = null;
  let composing = false;
  let currentAvatarState = "standby";
  let avatarReadyTimer = null;
  let avatarTapTimer = null;
  let historyCursor = null;
  let historyHasMore = false;
  let historyLoading = false;
  let historyLoadingIndicator = null;
  let idleActionTimer = null;
  let idleActionResetTimer = null;
  let notificationAudioContext = null;
  const notifiedReplyIds = new Set();
  const bubbleMarkdown = new WeakMap();
  const replyBubbles = new Map();
  const interactionBubbles = new Map();
  const LEGACY_BUBBLE_SEAL_MS = 1200;
  const AVATAR_STATE_CLASSES = [
    "avatar-state-standby",
    "avatar-state-sleeping",
    "avatar-state-thinking",
    "avatar-state-working",
    "avatar-state-happy",
    "avatar-state-sad",
    "avatar-state-angry",
    "avatar-state-shock",
    "avatar-state-wink",
    "avatar-state-curious",
    "avatar-state-awkward",
    "avatar-state-smirk",
    "avatar-state-cheeky",
    "avatar-state-excited",
    "avatar-state-shy",
    "avatar-state-proud",
    "avatar-state-confused",
    "avatar-state-love",
    "avatar-state-panic",
    "avatar-state-bored",
    "avatar-state-greeting",
    "avatar-state-celebrate",
    "avatar-state-laugh",
    "avatar-state-clap",
    "avatar-state-agree",
    "avatar-state-complain",
    "avatar-state-dance",
    "avatar-state-snacking",
    "avatar-state-drinking",
    "avatar-state-stretching",
  ];
  const IDLE_ACTIONS = CFG.renderer === "raster" ? [
    { state: "curious", duration: 3000 },
    { state: "snacking", duration: 4200 },
    { state: "confused", duration: 4600 },
  ] : [
    { state: "bored", duration: 4200 },
    { state: "snacking", duration: 5200 },
    { state: "drinking", duration: 4600 },
    { state: "stretching", duration: 4000 },
  ];

  // ---------- Avatar renderer ----------
  async function resolvePalModelPath() {
    const manifestPath = String(
      CFG.skinManifestPath || "./desktop-avatar-skin-manifest.json",
    );
    const response = await fetch(manifestPath, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`Pal skin manifest is unavailable (${response.status})`);
    }
    const manifest = await response.json();
    const digest = String(manifest.sha256 || "").toLowerCase();
    if (!/^[0-9a-f]{64}$/.test(digest)) {
      throw new Error("Pal skin manifest has an invalid SHA-256 digest");
    }
    const modelUrl = new URL(String(manifest.model_url || ""), window.location.href);
    if (modelUrl.origin !== window.location.origin) {
      throw new Error("Pal skin manifest points outside the desktop-avatar origin");
    }
    return modelUrl.href;
  }

  async function initAvatar() {
    const bootstrapLoading = document.createElement("div");
    bootstrapLoading.className = "pal-webgl-loading pal-webgl-bootstrap-loading";
    bootstrapLoading.setAttribute("role", "status");
    bootstrapLoading.setAttribute("aria-live", "polite");
    bootstrapLoading.textContent = "Loading Pal…";
    avatarStage.appendChild(bootstrapLoading);
    try {
      const module = await (CFG.renderer === "raster" ? import("./pal-raster-avatar.js") : CFG.renderer === "svg" ? import("./pal-svg-avatar.js") : import("./pal-webgl-avatar.js"));
      bootstrapLoading.remove();
      await (CFG.renderer === "raster" ? module.initPalRasterAvatar : CFG.renderer === "svg" ? module.initPalSVGAvatar : module.initPalWebGLAvatar)({
        container: avatarStage,
        modelPath: CFG.renderer === "webgl" ? await resolvePalModelPath() : undefined,
        onActionFinished: (state) => {
          if (!ws || ws.readyState !== WebSocket.OPEN) return;
          ws.send(JSON.stringify({ type: "avatar_action_finished", state: state }));
        },
      });
      bindAvatarWhenReady();
    } catch (error) {
      console.error("Pal renderer failed to initialize", error);
      showHint(CFG.renderer !== "webgl" ? "Pal failed to load. Refresh the page to retry." : "Pal's local skin failed to load. Reinstall the model cache, then refresh the page.", true);
    } finally {
      bootstrapLoading.remove();
    }
  }

  function avatarElement() {
    return document.getElementById("pal-raster-widget")
      || document.getElementById("pal-svg-widget")
      || document.getElementById("pal-webgl-widget")
      || document.getElementById("pal-webgl-canvas")
      || document.querySelector("#avatar-stage canvas, body > canvas");
  }

  function bindAvatarWhenReady(attempt) {
    const tries = Number(attempt || 0);
    const avatar = avatarElement();
    const canvas = document.getElementById("pal-raster-canvas")
      || document.getElementById("pal-svg-canvas")
      || document.getElementById("pal-webgl-canvas")
      || document.querySelector("#avatar-stage canvas, body > canvas");
    if (!avatar || !canvas) {
      if (tries < 40) {
        avatarReadyTimer = setTimeout(() => bindAvatarWhenReady(tries + 1), 200);
      }
      return;
    }
    clearTimeout(avatarReadyTimer);
    avatarReadyTimer = null;
    if (avatarStage && avatar.parentElement !== avatarStage) {
      avatarStage.appendChild(avatar);
    }
    const display = CFG.display || {};
    avatar.style.setProperty("--avatar-aspect", `${Number(display.width || 220)} / ${Number(display.height || 420)}`);
    canvas.style.cursor = "pointer";
    canvas.addEventListener("dblclick", (event) => {
      event.stopPropagation();
      clearTimeout(avatarTapTimer);
      avatarTapTimer = null;
      toggleChatPanel();
    });
    canvas.addEventListener("click", (event) => {
      event.stopPropagation();
      clearTimeout(avatarTapTimer);
      avatarTapTimer = setTimeout(() => {
        avatarTapTimer = null;
        playTapInteraction(event);
      }, 220);
    });
    applyAvatarState(currentAvatarState);
    // Optional local ST7789 mirror: enabled only with ?st7789=ws://... .
    window.ST7789Bridge?.attach(canvas);
  }

  function playTapInteraction(event) {
    const choices = ["curious", "wink", "happy"];
    const state = choices[Math.floor(Math.random() * choices.length)];
    cancelIdleAction();
    applyAvatarState(state);
    emitInteractionParticle(event, state);
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "avatar_action", state: state, duration: 1.1 }));
    }
  }

  function emitInteractionParticle(event, state) {
    const particle = document.createElement("span");
    const glyphs = { curious: "?", wink: "✦", happy: "♥" };
    particle.className = "avatar-interaction-particle " + state;
    particle.textContent = glyphs[state] || "✦";
    const fallbackX = Math.max(24, window.innerWidth - 100);
    const fallbackY = Math.max(48, window.innerHeight - 260);
    particle.style.left = Math.round(Number(event && event.clientX) || fallbackX) + "px";
    particle.style.top = Math.round(Number(event && event.clientY) || fallbackY) + "px";
    document.body.appendChild(particle);
    particle.addEventListener("animationend", () => particle.remove(), { once: true });
    setTimeout(() => particle.remove(), 1800);
  }

  // ---------- 聊天 UI ----------
  function renderBubbleMarkdown(bubble, markdown) {
    const source = String(markdown || "");
    bubbleMarkdown.set(bubble, source);
    if (!window.marked || !window.DOMPurify) {
      bubble.textContent = source;
      return;
    }
    try {
      const rendered = window.marked.parse(source, {
        async: false,
        breaks: true,
        gfm: true,
      });
      bubble.innerHTML = window.DOMPurify.sanitize(rendered, {
        USE_PROFILES: { html: true },
        FORBID_TAGS: ["style", "form", "input", "button", "textarea", "select", "iframe", "object", "embed", "svg", "math"],
        FORBID_ATTR: ["style"],
      });
    } catch (_error) {
      bubble.textContent = source;
      return;
    }
    bubble.querySelectorAll("a[href]").forEach((link) => {
      link.target = "_blank";
      link.rel = "noopener noreferrer";
    });
  }

  function createBubble(sender, text) {
    const div = document.createElement("div");
    div.className = "bubble " + sender;
    if (sender === "user") {
      div.textContent = String(text || "");
    } else {
      renderBubbleMarkdown(div, text);
    }
    return div;
  }

  function addBubble(sender, text) {
    const div = createBubble(sender, text);
    chatMessages.appendChild(div);
    scrollToBottom();
    return div;
  }

  function clearRenderedChat() {
    sealBubble();
    interactionBubbles.clear();
    chatMessages.replaceChildren();
    historyCursor = null;
    historyHasMore = false;
    historyLoading = false;
    historyLoadingIndicator = null;
  }

  function setHistoryLoading(loading) {
    historyLoading = loading;
    if (loading && !historyLoadingIndicator) {
      historyLoadingIndicator = document.createElement("div");
      historyLoadingIndicator.className = "history-loading";
      historyLoadingIndicator.textContent = "Loading earlier messages…";
      chatMessages.prepend(historyLoadingIndicator);
    } else if (!loading && historyLoadingIndicator) {
      historyLoadingIndicator.remove();
      historyLoadingIndicator = null;
    }
  }

  function requestOlderHistory() {
    if (!historyHasMore || historyLoading || !historyCursor) return;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    setHistoryLoading(true);
    ws.send(JSON.stringify({ type: "load_chat_history", before: historyCursor }));
  }

  function renderHistory(frame) {
    const mode = String(frame.mode || "replace");
    const messages = Array.isArray(frame.messages) ? frame.messages : [];
    setHistoryLoading(false);
    const oldHeight = chatMessages.scrollHeight;
    const oldTop = chatMessages.scrollTop;
    if (mode === "replace") {
      clearRenderedChat();
    }

    const fragment = document.createDocumentFragment();
    messages.forEach((message) => {
      const sender = message && message.sender === "user" ? "user" : "avatar";
      const bubble = createBubble(sender, message && message.text || "");
      bubble.dataset.historyId = String(message && message.id || "");
      const turnId = String(message && message.turn_id || "");
      if (sender === "avatar" && message && message.complete === false && turnId) {
        replyBubbles.set(turnId, bubble);
      }
      fragment.appendChild(bubble);
    });
    if (mode === "prepend") {
      chatMessages.insertBefore(fragment, chatMessages.firstChild);
      chatMessages.scrollTop = oldTop + (chatMessages.scrollHeight - oldHeight);
    } else {
      chatMessages.appendChild(fragment);
      scrollToBottom();
    }
    historyCursor = frame.cursor && typeof frame.cursor === "object" ? frame.cursor : null;
    historyHasMore = !!frame.has_more;
  }

  function beginAvatarMessage(messageId) {
    const normalizedId = String(messageId || "");
    if (!normalizedId) sealBubble();
    notifyIncomingReply(normalizedId);
  }

  function appendAvatarText(text, messageId) {
    const normalizedId = String(messageId || "");
    let bubble = null;
    if (normalizedId) {
      bubble = replyBubbles.get(normalizedId) || null;
      if (!bubble) {
        notifyIncomingReply(normalizedId);
        bubble = addBubble("avatar", "");
        replyBubbles.set(normalizedId, bubble);
      }
    } else {
      if (!legacyPendingBubble) {
        notifyIncomingReply("");
        legacyPendingBubble = addBubble("avatar", "");
      }
      bubble = legacyPendingBubble;
    }
    renderBubbleMarkdown(
      bubble,
      (bubbleMarkdown.get(bubble) || "") + String(text || ""),
    );
    scrollToBottom();
    clearTimeout(legacySealTimer);
    if (!normalizedId) {
      // Compatibility with older sidecars that did not send explicit
      // message_start/message_done boundaries.
      legacySealTimer = setTimeout(sealBubble, LEGACY_BUBBLE_SEAL_MS);
    }
  }

  function sealBubble(messageId) {
    clearTimeout(legacySealTimer);
    legacySealTimer = null;
    const normalizedId = String(messageId || "");
    if (normalizedId) {
      const bubble = replyBubbles.get(normalizedId);
      if (bubble && !(bubbleMarkdown.get(bubble) || "").trim()) bubble.remove();
      replyBubbles.delete(normalizedId);
      notifiedReplyIds.delete(normalizedId);
      return;
    }
    if (legacyPendingBubble && !(bubbleMarkdown.get(legacyPendingBubble) || "").trim()) {
      legacyPendingBubble.remove();
    }
    legacyPendingBubble = null;
    replyBubbles.forEach((bubble) => {
      if (!(bubbleMarkdown.get(bubble) || "").trim()) bubble.remove();
    });
    replyBubbles.clear();
    notifiedReplyIds.clear();
  }

  function audioContextConstructor() {
    return window.AudioContext || window.webkitAudioContext || null;
  }

  function ensureNotificationAudio() {
    if (!CFG.messageBeepEnabled) return null;
    if (notificationAudioContext) return notificationAudioContext;
    const AudioContext = audioContextConstructor();
    if (!AudioContext) return null;
    try {
      notificationAudioContext = new AudioContext();
    } catch (_error) {
      return null;
    }
    return notificationAudioContext;
  }

  function primeNotificationAudio() {
    const context = ensureNotificationAudio();
    if (context && context.state === "suspended") {
      context.resume().catch(() => {});
    }
  }

  function notifyIncomingReply(messageId) {
    if (!CFG.messageBeepEnabled) return;
    const normalizedId = String(messageId || "legacy");
    if (notifiedReplyIds.has(normalizedId)) return;
    notifiedReplyIds.add(normalizedId);
    const context = ensureNotificationAudio();
    if (!context || context.state !== "running") return;
    const now = context.currentTime;
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    const frequency = Math.max(120, Number(CFG.messageBeepFrequencyHz || 880));
    const volume = Math.min(0.12, Math.max(0.001, Number(CFG.messageBeepVolume || 0.045)));
    oscillator.type = "sine";
    oscillator.frequency.setValueAtTime(frequency, now);
    oscillator.frequency.exponentialRampToValueAtTime(frequency * 1.18, now + 0.07);
    gain.gain.setValueAtTime(0.0001, now);
    gain.gain.exponentialRampToValueAtTime(volume, now + 0.008);
    gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.09);
    oscillator.connect(gain);
    gain.connect(context.destination);
    oscillator.start(now);
    oscillator.stop(now + 0.095);
  }

  function configureSkinUi() {
    const ui = CFG.ui || {};
    document.title = CFG.title || "Desktop Companion";
    const chatTitle = document.querySelector(".chat-title");
    if (chatTitle) chatTitle.textContent = `${CFG.displayName || "Pal"} 💬`;
    if (chatPanel) chatPanel.setAttribute("aria-label", ui.chatAriaLabel || "Desktop companion chat");
    if (avatarStage) avatarStage.setAttribute("aria-label", ui.avatarAriaLabel || "Desktop companion");
    if (chatInput) chatInput.placeholder = ui.inputPlaceholder || "Message the desktop companion…";
    if (chatSend) chatSend.textContent = ui.send || "Send";
    if (chatClearScreen) {
      chatClearScreen.textContent = ui.clearView || "Clear view";
      chatClearScreen.title = ui.clearViewTitle || "Clear the current view";
    }
    if (chatClearHistory) {
      chatClearHistory.textContent = ui.clearHistory || "Clear history";
      chatClearHistory.title = ui.clearHistoryTitle || "Clear chat history";
    }
    if (chatClose) chatClose.setAttribute("aria-label", ui.closeTitle || "Close chat");
    const checklistTitle = document.querySelector(".checklist-header > span:first-child");
    if (checklistTitle) checklistTitle.textContent = ui.checklistTitle || "In progress";
  }

  function renderInteraction(frame) {
    const interaction = frame && typeof frame.interaction === "object" ? frame.interaction : {};
    const interactionId = String(interaction.interaction_id || "").trim();
    if (!interactionId) return;
    let bubble = interactionBubbles.get(interactionId);
    if (!bubble) {
      bubble = document.createElement("div");
      bubble.className = "bubble avatar interaction";
      const content = document.createElement("div");
      content.className = "interaction-content";
      const actions = document.createElement("div");
      actions.className = "interaction-actions";
      bubble.append(content, actions);
      chatMessages.appendChild(bubble);
      interactionBubbles.set(interactionId, bubble);
    }

    const content = bubble.querySelector(".interaction-content");
    const actions = bubble.querySelector(".interaction-actions");
    renderBubbleMarkdown(content, interaction.text || "");
    actions.replaceChildren();

    const event = String(frame.event || "update");
    const active = event === "open" || event === "update";
    bubble.classList.toggle("resolved", !active);
    if (active) {
      const rows = Array.isArray(interaction.buttons) ? interaction.buttons : [];
      rows.forEach((row) => {
        if (!Array.isArray(row) || !row.length) return;
        const rowElement = document.createElement("div");
        rowElement.className = "interaction-row";
        row.forEach((item) => {
          const label = String(item && item.label || "").trim();
          const token = String(item && item.token || "").trim();
          if (!label || !token) return;
          const button = document.createElement("button");
          button.type = "button";
          button.className = "interaction-button";
          button.textContent = label;
          button.addEventListener("click", () => {
            if (!ws || ws.readyState !== WebSocket.OPEN) {
              showHint("The connection is not ready. The action was not sent.", true);
              return;
            }
            actions.querySelectorAll("button").forEach((candidate) => { candidate.disabled = true; });
            ws.send(JSON.stringify({
              type: "interaction_result",
              interaction_id: interactionId,
              button_token: token,
            }));
          });
          rowElement.appendChild(button);
        });
        if (rowElement.childElementCount) actions.appendChild(rowElement);
      });
    }
    scrollToBottom();
  }

  function renderChecklist(frame) {
    const payload = frame && typeof frame.payload === "object" ? frame.payload : {};
    const action = String(payload.action || "update").toLowerCase();
    const active = action !== "clear" && payload.active !== false;
    if (!active) {
      checklistPanel.classList.add("hidden");
      avatarStage.classList.remove("has-checklist");
      checklistItems.replaceChildren();
      checklistProgress.textContent = "";
      return;
    }

    const plan = Array.isArray(payload.plan) ? payload.plan : [];
    const done = Math.max(0, Number(payload.done) || 0);
    const total = Math.max(plan.length, Number(payload.total) || 0);
    checklistProgress.textContent = done + "/" + total;
    checklistItems.replaceChildren();
    const visible = plan.slice(0, 6);
    visible.forEach((item) => {
      const status = String(item && item.status || "pending").replace("_", "-");
      const row = document.createElement("li");
      row.className = "checklist-item " + status;
      const icon = document.createElement("span");
      icon.textContent = status === "completed" ? "✓" : status === "in-progress" ? "◉" : "○";
      const label = document.createElement("span");
      label.className = "checklist-item-text";
      label.textContent = String(item && item.step || "");
      row.append(icon, label);
      checklistItems.appendChild(row);
    });
    if (plan.length > visible.length) {
      const overflow = document.createElement("li");
      overflow.className = "checklist-overflow";
      overflow.textContent = (plan.length - visible.length) + " more items";
      checklistItems.appendChild(overflow);
    }
    checklistPanel.classList.remove("hidden");
    avatarStage.classList.add("has-checklist");
  }

  function scrollToBottom() {
    chatMessages.scrollTop = chatMessages.scrollHeight;
  }

  function toggleChatPanel() {
    chatPanel.classList.toggle("hidden");
    if (!chatPanel.classList.contains("hidden")) {
      chatInput.focus();
    }
  }

  function autosizeChatInput() {
    chatInput.style.height = "auto";
    chatInput.style.height = Math.min(chatInput.scrollHeight, 120) + "px";
  }

  function sendMessage() {
    const text = chatInput.value.trim();
    if (!text) return;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      showHint("The connection is not ready. The message was not sent.", true);
      chatInput.focus();
      return;
    }
    cancelIdleAction();
    stopNativeMotion();
    chatInput.value = "";
    autosizeChatInput();
    ws.send(JSON.stringify({ type: "chat_message", text: text }));
  }

  // ---------- 状态机渲染 ----------
  const STATE_LABEL = {
    standby: "Idle",
    sleeping: "Sleeping 😴",
    thinking: "Thinking…",
    working: "Working…",
    happy: "Happy 😊",
    sad: "Sad 🥺",
    angry: "Angry 😠",
    shock: "Shocked 😱",
    wink: "Winking 😉",
    curious: "Curious 🤔",
    awkward: "Awkward 😅",
    smirk: "Smirking 😏",
    cheeky: "Cheeky 😜",
    excited: "Excited 🤩",
    shy: "Shy ☺️",
    proud: "Proud 😌",
    confused: "Confused 😵‍💫",
    love: "Affectionate 💗",
    panic: "Panicking 😰",
    bored: "Bored 🫠",
    greeting: "Greeting 👋",
    celebrate: "Celebrating 🎉",
    laugh: "Laughing 😆",
    clap: "Clapping 👏",
    agree: "Agreeing 👍",
    complain: "Complaining 😮‍💨",
    dance: "Dancing 🕺",
    snacking: "Snacking 🍟",
    drinking: "Drinking 🥤",
    stretching: "Stretching 🙆",
  };

  const STATE_ALIASES = {
    sleepy: "sleeping",
    crying: "sad",
    error: "shock",
    embarrassed: "awkward",
    smug: "smirk",
    playful: "cheeky",
    surprised: "shock",
    wave: "greeting",
    snack: "snacking",
    drink: "drinking",
    stretch: "stretching",
  };

  function normalizeState(state) {
    const value = String(state || "standby").toLowerCase();
    return STATE_ALIASES[value] || (STATE_LABEL[value] ? value : "standby");
  }

  function renderState(state) {
    currentAvatarState = normalizeState(state);
    cancelIdleAction();
    stateBadge.textContent = STATE_LABEL[currentAvatarState];
    stateBadge.className = "state-badge " + currentAvatarState;
    applyAvatarState(currentAvatarState);
    if (currentAvatarState === "standby") scheduleIdleAction();
  }

  function applyAvatarState(state) {
    const normalized = normalizeState(state);
    const avatar = avatarElement();
    if (!avatar) return;
    avatar.classList.remove(...AVATAR_STATE_CLASSES);
    // Restart one-shot expressive animations even when the same state repeats.
    void avatar.offsetWidth;
    avatar.classList.add("avatar-state-" + normalized);
    avatar.dataset.avatarState = normalized;
    playNativeMotion(normalized);
  }

  function playNativeMotion(state) {
    const controller = palController();
    if (!controller) return false;
    controller.setState(state);
    return true;
  }

  function stopNativeMotion() {
    palController()?.stopMotion();
  }

  function cancelIdleAction() {
    clearTimeout(idleActionTimer);
    clearTimeout(idleActionResetTimer);
    idleActionTimer = null;
    idleActionResetTimer = null;
  }

  function scheduleIdleAction() {
    cancelIdleAction();
    if (currentAvatarState !== "standby") return;
    const minimumDelay = Math.max(1000, Number(CFG.idleActionMinMs ?? 14000));
    const jitter = Math.max(0, Number(CFG.idleActionJitterMs ?? 18000));
    const delay = minimumDelay + Math.floor(Math.random() * jitter);
    idleActionTimer = setTimeout(playIdleAction, delay);
  }

  function playIdleAction() {
    idleActionTimer = null;
    if (currentAvatarState !== "standby") return;
    const action = IDLE_ACTIONS[Math.floor(Math.random() * IDLE_ACTIONS.length)];
    stopNativeMotion();
    stateBadge.textContent = STATE_LABEL[action.state];
    stateBadge.className = "state-badge " + action.state;
    applyAvatarState(action.state);
    idleActionResetTimer = setTimeout(() => {
      idleActionResetTimer = null;
      if (currentAvatarState !== "standby") return;
      stopNativeMotion();
      stateBadge.textContent = STATE_LABEL.standby;
      stateBadge.className = "state-badge standby";
      applyAvatarState("standby");
      scheduleIdleAction();
    }, action.duration);
  }

  // ---------- WebSocket ----------
  function connect() {
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
    showHint("Connecting…");
    try {
      ws = new WebSocket(WS_URL);
    } catch (e) {
      scheduleReconnect();
      return;
    }
    ws.onopen = () => {
      setConnected(true);
      showHint("Connected 💬");
      ws.send(JSON.stringify({ type: "ping" }));
    };
    ws.onmessage = (ev) => {
      let frame;
      try { frame = JSON.parse(ev.data); } catch (e) { return; }
      handleFrame(frame);
      const deliveryId = String(frame._avatar_delivery_id || "");
      if (deliveryId && ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({
          type: "browser_delivery_ack",
          delivery_id: deliveryId,
        }));
      }
    };
    ws.onclose = () => {
      setConnected(false);
      sealBubble();
      showHint("Connection lost. Reconnecting…", true);
      scheduleReconnect();
    };
    ws.onerror = () => { /* onclose 处理重连 */ };
  }

  function setConnected(connected) {
    chatSend.disabled = !connected;
    chatInput.setAttribute("aria-invalid", connected ? "false" : "true");
  }

  function scheduleReconnect() {
    if (reconnectTimer) return;
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      connect();
    }, CFG.reconnectDelayMs || 3000);
  }

  function handleFrame(frame) {
    const kind = frame.type;
    if (kind === "chat_message") {
      if (frame.sender === "avatar") {
        const event = String(frame.event || "delta");
        if (event === "start") {
          beginAvatarMessage(frame.message_id);
        } else if (event === "done") {
          sealBubble(frame.message_id);
        } else if (event === "notification") {
          appendAvatarText(frame.text || "", frame.message_id);
          sealBubble(frame.message_id);
        } else {
          appendAvatarText(frame.text || "", frame.message_id);
        }
      } else {
        addBubble("user", frame.text || "");
      }
    } else if (kind === "tool_activity") {
      toolWorkspace.handle(frame.payload || {});
    } else if (kind === "avatar_state") {
      renderState(frame.state || "standby");
      if (frame.state === "standby") sealBubble();
    } else if (kind === "chat_interaction") {
      renderInteraction(frame);
    } else if (kind === "tagged_message" && frame.tag === "checklist") {
      renderChecklist(frame);
    } else if (kind === "chat_history") {
      renderHistory(frame);
    } else if (kind === "chat_history_cleared") {
      clearRenderedChat();
      showHint("Chat history cleared.");
    } else if (kind === "history_error") {
      setHistoryLoading(false);
      showHint(frame.error || "Chat history operation failed.", true);
    } else if (kind === "error" || kind === "delivery_failed") {
      showHint(frame.error || "Operation failed.", true);
    } else if (kind === "pong") {
      // 保活，无需处理
    }
  }

  // ---------- 提示条 ----------
  let hintTimer = null;
  function showHint(text, isError) {
    let hint = document.querySelector(".hint");
    if (!hint) {
      hint = document.createElement("div");
      hint.className = "hint";
      document.body.appendChild(hint);
    }
    hint.textContent = text;
    hint.classList.toggle("error", !!isError);
    clearTimeout(hintTimer);
    hintTimer = setTimeout(() => { hint.remove(); }, isError ? 5000 : 2500);
  }

  // ---------- 事件绑定 ----------
  chatSend.addEventListener("click", sendMessage);
  chatInput.addEventListener("compositionstart", () => { composing = true; });
  chatInput.addEventListener("compositionend", () => { composing = false; });
  chatInput.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" || e.isComposing || composing) return;
    if (e.shiftKey) return;
    e.preventDefault();
    sendMessage();
  });
  chatInput.addEventListener("input", autosizeChatInput);
  chatClose.addEventListener("click", () => chatPanel.classList.add("hidden"));
  chatClearScreen.addEventListener("click", () => {
    clearRenderedChat();
    showHint("The current view was cleared. Chat history was preserved.");
  });
  chatClearHistory.addEventListener("click", () => {
    if (!window.confirm("Permanently clear all desktop avatar chat history? This cannot be undone.")) return;
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      showHint("The connection is not ready. Chat history was not cleared.", true);
      return;
    }
    ws.send(JSON.stringify({ type: "clear_chat_history" }));
  });
  chatMessages.addEventListener("scroll", () => {
    if (chatMessages.scrollTop <= 48) requestOlderHistory();
  });
  chatMessages.addEventListener("wheel", (event) => {
    if (event.deltaY < 0 && chatMessages.scrollTop <= 1) requestOlderHistory();
  }, { passive: true });
  document.addEventListener("keydown", (e) => {
    primeNotificationAudio();
    if (e.key === "Escape" && !chatPanel.classList.contains("hidden")) {
      chatPanel.classList.add("hidden");
    }
  });

  // ---------- 启动 ----------
  document.addEventListener("pointerdown", primeNotificationAudio, { passive: true });
  configureSkinUi();
  setConnected(false);
  initAvatar();
  connect();
})();
