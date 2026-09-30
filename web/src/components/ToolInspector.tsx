import { useState } from "react";
import type { RouterItem, ToolItem } from "../store/types";

type Props = { tools: ToolItem[]; router: RouterItem[] };

export function ToolInspector({ tools, router }: Props) {
  const [open, setOpen] = useState<number | null>(null);
  return (
    <section className="panel" aria-label="Tool inspector">
      <h2>Tools &amp; router</h2>
      <ul className="router-list">
        {router.slice(-6).map((r) => (
          <li key={r.id}>
            <code>{r.intent}</code> {r.score.toFixed(2)} · {r.path}
          </li>
        ))}
      </ul>
      <ol className="tool-list">
        {tools.slice(-20).map((t) => (
          <li key={t.id}>
            <button type="button" onClick={() => setOpen(open === t.id ? null : t.id)}>
              {t.kind === "call" ? "→" : "←"} {t.name}
            </button>
            {open === t.id && <pre>{JSON.stringify(t.payload, null, 2)}</pre>}
          </li>
        ))}
      </ol>
    </section>
  );
}
