import { BACKEND_URL, type Bill, type OutboxItem } from "../store/types";

export async function fetchBill(accountId: string): Promise<Bill> {
  const res = await fetch(`${BACKEND_URL}/bills/${accountId}`);
  if (!res.ok) throw new Error("bill fetch failed");
  return res.json() as Promise<Bill>;
}

export async function fetchOutbox(accountId?: string): Promise<OutboxItem[]> {
  const q = accountId ? `?account_id=${encodeURIComponent(accountId)}` : "";
  const res = await fetch(`${BACKEND_URL}/notifications/outbox${q}`);
  if (!res.ok) throw new Error("outbox fetch failed");
  return res.json() as Promise<OutboxItem[]>;
}

export async function resetBackend(): Promise<void> {
  await fetch(`${BACKEND_URL}/admin/reset`, { method: "POST" });
}
