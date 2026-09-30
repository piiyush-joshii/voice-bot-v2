import { VOICE_URL, type Mode } from "../store/types";

export type CreatedSession = {
  session_id: string;
  ws_debug_url: string;
  ws_text_url?: string;
  webrtc_offer_url?: string;
};

export async function createSession(mode: Mode): Promise<CreatedSession> {
  const res = await fetch(`${VOICE_URL}/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode }),
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(body || `session create failed (${res.status})`);
  }
  return res.json() as Promise<CreatedSession>;
}

export async function endHandoff(sessionId: string): Promise<{ handoff_id: string; summary: string }> {
  const res = await fetch(`${VOICE_URL}/sessions/${sessionId}/handoff`, { method: "POST" });
  if (!res.ok) throw new Error("handoff failed");
  return res.json() as Promise<{ handoff_id: string; summary: string }>;
}

export async function postOffer(body: {
  sdp: string;
  type: string;
  session_id: string;
  pc_id?: string | null;
}): Promise<{ sdp: string; type: string; pc_id: string }> {
  const res = await fetch(`${VOICE_URL}/api/offer`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`offer failed (${res.status})`);
  return res.json() as Promise<{ sdp: string; type: string; pc_id: string }>;
}
