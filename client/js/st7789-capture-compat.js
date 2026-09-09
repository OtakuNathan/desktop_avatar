/* Make the WebGL backbuffer readable for the optional ST7789 mirror.
 * This is a no-op unless ?st7789=... is present, so normal Desktop Avatar
 * rendering is unchanged.
 */
(() => {
  const pageUrl = new URL(window.location.href);
  if (!pageUrl.searchParams.get("st7789")) return;
  const originalGetContext = HTMLCanvasElement.prototype.getContext;
  HTMLCanvasElement.prototype.getContext = function patchedGetContext(type, options) {
    if (type === "webgl" || type === "experimental-webgl" || type === "webgl2") {
      const requested = options && typeof options === "object" ? { ...options } : {};
      requested.preserveDrawingBuffer = true;
      return originalGetContext.call(this, type, requested);
    }
    return originalGetContext.call(this, type, options);
  };
})();
