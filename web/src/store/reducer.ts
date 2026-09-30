import type { AppState, DebugEvent, GateState } from "./types";

let nextId = 1;
const id = () => nextId++;

export const initialState: AppState = {
  mode: "text",
  accountId: "ACC1001",
  sessionId: null,
  connection: "idle",
  debugConnected: false,
  disconnectWarned: false,
  gateState: "IDLE",
  audioToModel: "open",
  recording: "on",
  framesDropped: 0,
  transcript: [],
  tools: [],
  router: [],
  transitions: [],
  captureUrl: null,
  captureExpiresAt: null,
  paymentResult: null,
  toast: null,
  latency: [],
  scrubberHits: 0,
  framesDroppedSecure: 0,
  micMuted: false,
  voicePaused: false,
  inputLevel: 0,
  outbox: [],
  bill: null,
};

export type Action =
  | { type: "reset_session" }
  | { type: "set_mode"; mode: AppState["mode"] }
  | { type: "set_account"; accountId: string }
  | { type: "session_starting" }
  | { type: "session_started"; sessionId: string }
  | { type: "session_ended" }
  | { type: "debug_status"; connected: boolean }
  | { type: "set_mic_muted"; muted: boolean }
  | { type: "set_input_level"; level: number }
  | { type: "interim_user"; text: string }
  | { type: "assistant_text"; text: string; final: boolean }
  | { type: "debug"; event: DebugEvent }
  | { type: "toast"; message: string | null }
  | { type: "outbox"; items: AppState["outbox"] }
  | { type: "bill"; bill: AppState["bill"] };

function applyDebug(state: AppState, event: DebugEvent): AppState {
  const ts = typeof event.ts === "number" ? event.ts : Date.now() / 1000;
  switch (event.type) {
    case "state_changed": {
      const to = String(event.to) as GateState;
      const voicePaused = to === "SECURE_CAPTURE";
      return {
        ...state,
        gateState: to,
        voicePaused,
        micMuted: voicePaused ? true : state.micMuted,
        transitions: [
          ...state.transitions.slice(-19),
          { id: id(), from: String(event.from), to, reason: event.reason as string | undefined, ts },
        ],
        captureUrl: to === "SECURE_CAPTURE" ? state.captureUrl : to === "PAYMENT_PENDING" || to === "PAYMENT_RESULT" || to === "AUTHENTICATED" ? null : state.captureUrl,
      };
    }
    case "gate_status":
      return {
        ...state,
        audioToModel: event.audio_to_model === "closed" ? "closed" : "open",
        recording: event.recording === "paused" ? "paused" : "on",
        framesDropped: Number(event.frames_dropped ?? state.framesDropped),
      };
    case "transcript": {
      const role = event.role === "assistant" ? "assistant" : "user";
      const text = String(event.text ?? "");
      const final = Boolean(event.final);
      if (!final && role === "user") {
        const last = state.transcript[state.transcript.length - 1];
        if (last && last.role === "user" && !last.final) {
          return { ...state, transcript: [...state.transcript.slice(0, -1), { ...last, text, ts }] };
        }
      }
      return {
        ...state,
        transcript: [...state.transcript, { id: id(), role, text, final, ts }],
      };
    }
    case "router":
      return {
        ...state,
        router: [
          ...state.router.slice(-39),
          { id: id(), intent: String(event.intent), score: Number(event.score), path: String(event.path), ts },
        ],
      };
    case "tool_call":
      return {
        ...state,
        tools: [...state.tools, { id: id(), kind: "call", name: String(event.name), payload: event.args, ts }],
      };
    case "tool_result":
      return {
        ...state,
        tools: [...state.tools, { id: id(), kind: "result", name: String(event.name), payload: event.result, ts }],
      };
    case "secure_capture":
      return {
        ...state,
        captureUrl: String(event.capture_url),
        captureExpiresAt: event.expires_at ? String(event.expires_at) : null,
        voicePaused: true,
        micMuted: true,
      };
    case "payment_result": {
      const paymentResult = {
        status: String(event.status),
        payment_ref: (event.payment_ref as string | null) ?? null,
        last4: (event.last4 as string | null) ?? null,
        failure_code: (event.failure_code as string | null) ?? null,
      };
      const bits = [
        paymentResult.status,
        paymentResult.payment_ref ? `ref ${paymentResult.payment_ref}` : "",
        paymentResult.last4 ? `····${paymentResult.last4}` : "",
      ].filter(Boolean);
      return {
        ...state,
        paymentResult,
        captureUrl: null,
        voicePaused: false,
        toast: bits.join(" · "),
      };
    }
    case "latency":
      return {
        ...state,
        latency: [
          ...state.latency.slice(-29),
          {
            asr_ms: Number(event.asr_ms ?? 0),
            router_ms: Number(event.router_ms ?? 0),
            llm_ttft_ms: Number(event.llm_ttft_ms ?? 0),
            tts_ttfb_ms: Number(event.tts_ttfb_ms ?? 0),
            e2e_ms: Number(event.e2e_ms ?? 0),
            ts,
          },
        ],
      };
    case "leak_counters":
      return {
        ...state,
        scrubberHits: Number(event.scrubber_hits ?? state.scrubberHits),
        framesDroppedSecure: Number(event.frames_dropped_secure ?? state.framesDroppedSecure),
      };
    default:
      return state;
  }
}

export function reducer(state: AppState, action: Action): AppState {
  switch (action.type) {
    case "reset_session":
      return {
        ...initialState,
        mode: state.mode,
        accountId: state.accountId,
      };
    case "set_mode":
      return { ...state, mode: action.mode };
    case "set_account":
      return { ...state, accountId: action.accountId };
    case "session_starting":
      return { ...state, connection: "connecting", disconnectWarned: false, toast: null };
    case "session_started":
      return { ...state, sessionId: action.sessionId, connection: "connected" };
    case "session_ended":
      return {
        ...state,
        sessionId: null,
        connection: "idle",
        debugConnected: false,
        captureUrl: null,
        voicePaused: false,
        inputLevel: 0,
      };
    case "debug_status":
      return {
        ...state,
        debugConnected: action.connected,
        disconnectWarned: action.connected ? false : state.sessionId !== null,
      };
    case "set_mic_muted":
      return { ...state, micMuted: action.muted };
    case "set_input_level":
      return { ...state, inputLevel: action.level };
    case "interim_user": {
      const last = state.transcript[state.transcript.length - 1];
      if (last && last.role === "user" && !last.final) {
        return { ...state, transcript: [...state.transcript.slice(0, -1), { ...last, text: action.text }] };
      }
      return {
        ...state,
        transcript: [...state.transcript, { id: id(), role: "user", text: action.text, final: false, ts: Date.now() / 1000 }],
      };
    }
    case "assistant_text": {
      if (!action.final) {
        const last = state.transcript[state.transcript.length - 1];
        if (last && last.role === "assistant" && !last.final) {
          return {
            ...state,
            transcript: [...state.transcript.slice(0, -1), { ...last, text: `${last.text} ${action.text}`.trim() }],
          };
        }
        return {
          ...state,
          transcript: [
            ...state.transcript,
            { id: id(), role: "assistant", text: action.text, final: false, ts: Date.now() / 1000 },
          ],
        };
      }
      const last = state.transcript[state.transcript.length - 1];
      if (last && last.role === "assistant" && !last.final) {
        return { ...state, transcript: [...state.transcript.slice(0, -1), { ...last, text: action.text || last.text, final: true }] };
      }
      return {
        ...state,
        transcript: [
          ...state.transcript,
          { id: id(), role: "assistant", text: action.text, final: true, ts: Date.now() / 1000 },
        ],
      };
    }
    case "debug":
      return applyDebug(state, action.event);
    case "toast":
      return { ...state, toast: action.message };
    case "outbox":
      return { ...state, outbox: action.items };
    case "bill":
      return { ...state, bill: action.bill };
  }
}
