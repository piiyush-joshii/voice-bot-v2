import type { TranscriptItem } from "../store/types";

type Props = { items: TranscriptItem[] };

export function Transcript({ items }: Props) {
  return (
    <section className="panel transcript" aria-label="Transcript">
      {items.length === 0 && <p className="muted">No turns yet.</p>}
      {items.map((item) => (
        <article key={item.id} className={`bubble ${item.role} ${item.final ? "" : "interim"}`}>
          <header>
            {item.role}
            {item.text.includes("[REDACTED_") && <span className="badge">redacted</span>}
          </header>
          <p>{item.text}</p>
        </article>
      ))}
    </section>
  );
}
