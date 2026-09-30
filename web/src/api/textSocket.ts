export type TextHandlers = {
  onAssistant: (text: string, final: boolean) => void;
  onRejected: (reason: string) => void;
};

export function openTextSocket(url: string, handlers: TextHandlers) {
  const ws = new WebSocket(url);
  const ready = new Promise<void>((resolve, reject) => {
    ws.onopen = () => resolve();
    ws.onerror = () => reject(new Error("text websocket failed"));
  });

  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data as string) as {
      type: string;
      text?: string;
      final?: boolean;
      reason?: string;
    };
    if (msg.type === "assistant_text") handlers.onAssistant(msg.text ?? "", Boolean(msg.final));
    if (msg.type === "rejected") handlers.onRejected(msg.reason ?? "rejected");
  };

  return {
    ready,
    send(text: string) {
      ws.send(JSON.stringify({ type: "user_text", text }));
    },
    close() {
      ws.close();
    },
  };
}
