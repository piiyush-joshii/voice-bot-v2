import { useEffect, useState } from "react";
import { PAYMENT_ORIGIN } from "../store/types";

type Props = {
  captureUrl: string | null;
  expiresAt: string | null;
  onStatus: (status: string) => void;
};

export function SecurePaymentPanel({ captureUrl, expiresAt, onStatus }: Props) {
  const [left, setLeft] = useState<number | null>(null);

  useEffect(() => {
    if (!expiresAt) {
      setLeft(null);
      return;
    }
    const tick = () => {
      const ms = Date.parse(expiresAt) - Date.now();
      setLeft(Number.isNaN(ms) ? null : Math.max(0, Math.ceil(ms / 1000)));
    };
    tick();
    const id = window.setInterval(tick, 1000);
    return () => window.clearInterval(id);
  }, [expiresAt]);

  useEffect(() => {
    if (!captureUrl) return;
    const onMessage = (ev: MessageEvent) => {
      if (ev.origin !== PAYMENT_ORIGIN) return;
      const data = ev.data as { type?: string; status?: string };
      if (data?.type === "payment_status" && typeof data.status === "string") {
        onStatus(data.status);
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [captureUrl, onStatus]);

  if (!captureUrl) return null;

  return (
    <section className="panel capture" aria-label="Secure payment">
      <h2>Secure payment</h2>
      <p className="banner">TEST MODE: use 4111 1111 1111 1111 · 12/30 · 123</p>
      {left !== null && <p className="hint">Expires in {left}s</p>}
      <iframe
        title="Secure card capture"
        src={captureUrl}
        sandbox="allow-scripts allow-forms allow-same-origin"
        referrerPolicy="no-referrer"
      />
    </section>
  );
}
