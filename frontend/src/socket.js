const WS_BASE = import.meta.env.VITE_WS_BASE_URL ?? 'ws://localhost:8000';

export function openSocket(sessionId, token, { onEvent, onOpen, onClose } = {}) {
  const url = `${WS_BASE}/ws/sessions/${sessionId}?token=${encodeURIComponent(token)}`;
  const ws = new WebSocket(url);
  const queue = [];

  ws.onopen = () => {
    while (queue.length) ws.send(queue.shift());
    onOpen?.();
  };
  ws.onclose   = () => onClose?.();
  ws.onmessage = (e) => {
    try { onEvent?.(JSON.parse(e.data)); } catch { /* ignore malformed frames */ }
  };

  return {
    send(payload) {
      const frame = JSON.stringify(payload);
      if (ws.readyState === WebSocket.CONNECTING) {
        queue.push(frame);
      } else if (ws.readyState === WebSocket.OPEN) {
        ws.send(frame);
      } else {
        console.warn('WebSocket send dropped: socket is closing or closed');
      }
    },
    close() { ws.close(); },
    // Close without triggering the "closed before connection established" browser
    // warning. If still connecting, wait for open then close immediately.
    closeWhenReady() {
      if (ws.readyState === WebSocket.CONNECTING) {
        ws.addEventListener('open', () => ws.close(), { once: true });
      } else {
        ws.close();
      }
    },
    get readyState() { return ws.readyState; },
  };
}
