/* Optional local Desktop Avatar -> ST7789 frame bridge.
 * Enable with: ?st7789=ws://127.0.0.1:8766
 * It is deliberately disabled unless the query parameter is present.
 */
(() => {
  const pageUrl = new URL(window.location.href);
  const bridgeUrl = pageUrl.searchParams.get("st7789");
  if (!bridgeUrl) return;

  let socket = null;
  let canvas = null;
  let timer = null;
  let busy = false;
  let stopped = false;
  const output = document.createElement("canvas");
  // Attached panel is rectangular ST7789 240x320.
  output.width = 240;
  output.height = 320;
  const context = output.getContext("2d", { alpha: false });

  function schedule() {
    if (stopped) return;
    clearTimeout(timer);
    timer = setTimeout(capture, 125); // target 8 fps; SPI remains the bottleneck
  }

  function capture() {
    if (stopped || busy || !canvas || !socket || socket.readyState !== WebSocket.OPEN) {
      schedule();
      return;
    }
    const width = canvas.width;
    const height = canvas.height;
    if (!width || !height) {
      schedule();
      return;
    }
    busy = true;
    context.fillStyle = "#0a0e18";
    context.fillRect(0, 0, output.width, output.height);
    const scale = Math.min(output.width / width, output.height / height);
    const drawWidth = Math.max(1, Math.round(width * scale));
    const drawHeight = Math.max(1, Math.round(height * scale));
    context.drawImage(
      canvas,
      (output.width - drawWidth) / 2,
      (output.height - drawHeight) / 2,
      drawWidth,
      drawHeight,
    );
    output.toBlob((blob) => {
      busy = false;
      if (blob && socket && socket.readyState === WebSocket.OPEN) socket.send(blob);
      schedule();
    }, "image/jpeg", 0.72);
  }

  function connect() {
    if (stopped) return;
    try {
      socket = new WebSocket(bridgeUrl);
      socket.binaryType = "arraybuffer";
      socket.onopen = () => {
        console.info(`[st7789] connected: ${bridgeUrl}`);
        schedule();
      };
      socket.onclose = () => {
        socket = null;
        if (!stopped) setTimeout(connect, 2000);
      };
      socket.onerror = () => console.warn("[st7789] bridge connection failed");
    } catch (error) {
      console.warn("[st7789] invalid bridge URL", error);
      setTimeout(connect, 3000);
    }
  }

  window.ST7789Bridge = {
    attach(nextCanvas) {
      canvas = nextCanvas;
      connect();
      return true;
    },
    stop() {
      stopped = true;
      clearTimeout(timer);
      socket?.close();
      socket = null;
    },
  };
})();
