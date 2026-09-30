import type { DebugEvent } from "../store/types";

export type DebugHandlers = {
  onEvent: (event: DebugEvent) => void;
  onStatus: (connected: boolean) => void;
};

export function openDebugSocket(url: string, handlers: DebugHandlers): () => void {
  let closed = false;
  let ws: WebSocket | null = null;
  let attempt = 0;
  let timer: number | null = null;

  const connect = () => {
    if (closed) return;
    ws = new WebSocket(url);
    ws.onopen = () => {
      attempt = 0;
      handlers.onStatus(true);
    };
    ws.onmessage = (ev) => {
      try {
        handlers.onEvent(JSON.parse(ev.data as string) as DebugEvent);
      } catch {
        /* ignore malformed */
      }
    };
    ws.onclose = () => {
      handlers.onStatus(false);
      if (closed) return;
      const delay = Math.min(8000, 400 * 2 ** attempt);
      attempt += 1;
      timer = window.setTimeout(connect, delay);
    };
    ws.onerror = () => ws?.close();
  };

  connect();
  return () => {
    closed = true;
    if (timer !== null) window.clearTimeout(timer);
    ws?.close();
  };
}
