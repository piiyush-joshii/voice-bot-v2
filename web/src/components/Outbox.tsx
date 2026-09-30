import type { Bill, OutboxItem } from "../store/types";

export function Outbox({ items }: { items: OutboxItem[] }) {
  return (
    <section className="panel" aria-label="Outbox">
      <h2>Outbox</h2>
      {items.length === 0 && <p className="muted">No notifications yet.</p>}
      <ul>
        {items.slice(0, 8).map((i, idx) => (
          <li key={`${i.sent_at}-${idx}`}>
            {i.channel} · {i.template} · {i.sent_at}
            <pre>{JSON.stringify(i.payload)}</pre>
          </li>
        ))}
      </ul>
    </section>
  );
}

export function BillViewer({ bill }: { bill: Bill | null }) {
  return (
    <section className="panel" aria-label="Bill">
      <h2>Bill</h2>
      {!bill && <p className="muted">Select an account and start a session.</p>}
      {bill && (
        <dl>
          <dt>ID</dt>
          <dd>{bill.bill_id}</dd>
          <dt>Due</dt>
          <dd>
            {bill.currency} {bill.amount_due.toFixed(2)} ({bill.status})
          </dd>
          <dt>Date</dt>
          <dd>{bill.due_date}</dd>
        </dl>
      )}
    </section>
  );
}
