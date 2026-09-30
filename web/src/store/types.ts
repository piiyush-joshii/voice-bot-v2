export type Mode = "voice" | "text";

export type GateState =
  | "IDLE"
  | "UNAUTHENTICATED"
  | "AUTHENTICATED"
  | "PAYMENT_PENDING"
  | "SECURE_CAPTURE"
  | "PAYMENT_RESULT"
  | "HANDOFF";

export type Connection = "idle" | "connecting" | "connected" | "disconnected";

export type TranscriptItem = {
  id: number;
  role: "user" | "assistant";
  text: string;
  final: boolean;
  ts: number;
};

export type ToolItem = {
  id: number;
  kind: "call" | "result";
  name: string;
  payload: unknown;
  ts: number;
};

export type RouterItem = {
  id: number;
  intent: string;
  score: number;
  path: string;
  ts: number;
};

export type Transition = {
  id: number;
  from: string;
  to: string;
  reason?: string;
  ts: number;
};

export type LatencySample = {
  asr_ms: number;
  router_ms: number;
  llm_ttft_ms: number;
  tts_ttfb_ms: number;
  e2e_ms: number;
  ts: number;
};

export type PaymentResult = {
  status: string;
  payment_ref?: string | null;
  last4?: string | null;
  failure_code?: string | null;
};

export type OutboxItem = {
  account_id: string;
  channel: string;
  template: string;
  payload: Record<string, unknown>;
  sent_at: string;
};

export type Bill = {
  bill_id: string;
  amount_due: number;
  currency: string;
  due_date: string;
  status: string;
};

export type DebugEvent = {
  type: string;
  ts?: number;
  [key: string]: unknown;
};

export type AppState = {
  mode: Mode;
  accountId: string;
  sessionId: string | null;
  connection: Connection;
  debugConnected: boolean;
  disconnectWarned: boolean;
  gateState: GateState;
  audioToModel: "open" | "closed";
  recording: "on" | "paused";
  framesDropped: number;
  transcript: TranscriptItem[];
  tools: ToolItem[];
  router: RouterItem[];
  transitions: Transition[];
  captureUrl: string | null;
  captureExpiresAt: string | null;
  paymentResult: PaymentResult | null;
  toast: string | null;
  latency: LatencySample[];
  scrubberHits: number;
  framesDroppedSecure: number;
  micMuted: boolean;
  voicePaused: boolean;
  inputLevel: number;
  outbox: OutboxItem[];
  bill: Bill | null;
};

export const ACCOUNTS: { id: string; verifier: string; note: string }[] = [
  { id: "ACC1001", verifier: "4321", note: "due $84.50" },
  { id: "ACC1002", verifier: "1234", note: "nothing due" },
  { id: "ACC1003", verifier: "5678", note: "overdue $210.00" },
];

export const OTP = "123456";
export const PAYMENT_ORIGIN = "http://localhost:8002";
export const VOICE_URL = "http://localhost:7860";
export const BACKEND_URL = "http://localhost:8001";
