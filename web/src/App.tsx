import { useCallback, useEffect, useReducer, useRef } from "react";
import { fetchBill, fetchOutbox } from "./api/backend";
import { openDebugSocket } from "./api/debugSocket";
import { createSession, endHandoff } from "./api/sessions";
import { openTextSocket } from "./api/textSocket";
import { CallControls } from "./components/CallControls";
import { LatencyPanel } from "./components/LatencyPanel";
import { LeakCounters } from "./components/LeakCounters";
import { BillViewer, Outbox } from "./components/Outbox";
import { ScenarioRunner } from "./components/ScenarioRunner";
import { SecurePaymentPanel } from "./components/SecurePaymentPanel";
import { StateGatePanel } from "./components/StateGatePanel";
import { TextInput } from "./components/TextInput";
import { ToolInspector } from "./components/ToolInspector";
import { Transcript } from "./components/Transcript";
import { initialState, reducer } from "./store/reducer";
import type { Mode } from "./store/types";
import { startVoice, type VoiceClient } from "./voice/webrtc";

type TextSock = ReturnType<typeof openTextSocket>;

export default function App() {
  const [state, dispatch] = useReducer(reducer, initialState);
  const textRef = useRef<TextSock | null>(null);
  const debugStop = useRef<(() => void) | null>(null);
  const voiceRef = useRef<VoiceClient | null>(null);
  const meterTimer = useRef<number | null>(null);
  const stateRef = useRef(state);
  stateRef.current = state;
  window.__ebppState = state.gateState;
  window.__ebppPay = state.paymentResult?.status;
  window.__ebppReply = [...state.transcript].reverse().find((t) => t.role === "assistant")?.text ?? "";

  const refreshBackend = useCallback(async (accountId: string) => {
    try {
      const [bill, outbox] = await Promise.all([fetchBill(accountId), fetchOutbox(accountId)]);
      dispatch({ type: "bill", bill });
      dispatch({ type: "outbox", items: outbox });
    } catch {
      /* backend may be down during first paint */
    }
  }, []);

  useEffect(() => {
    void refreshBackend(state.accountId);
  }, [state.accountId, refreshBackend]);

  useEffect(() => {
    if (state.gateState === "PAYMENT_RESULT" || state.paymentResult) {
      void refreshBackend(state.accountId);
    }
  }, [state.gateState, state.paymentResult, state.accountId, refreshBackend]);

  const stopMeter = () => {
    if (meterTimer.current !== null) {
      window.clearInterval(meterTimer.current);
      meterTimer.current = null;
    }
  };

  const teardown = useCallback(() => {
    stopMeter();
    debugStop.current?.();
    debugStop.current = null;
    textRef.current?.close();
    textRef.current = null;
    voiceRef.current?.close();
    voiceRef.current = null;
    dispatch({ type: "session_ended" });
  }, []);

  const start = async () => {
    teardown();
    dispatch({ type: "reset_session" });
    dispatch({ type: "set_mode", mode: state.mode });
    dispatch({ type: "set_account", accountId: state.accountId });
    dispatch({ type: "session_starting" });
    try {
      const created = await createSession(state.mode);
      dispatch({ type: "session_started", sessionId: created.session_id });
      debugStop.current = openDebugSocket(created.ws_debug_url, {
        onEvent: (event) => {
          if (event.type === "transcript" && event.role === "assistant" && stateRef.current.mode === "text") {
            return;
          }
          dispatch({ type: "debug", event });
        },
        onStatus: (connected) => dispatch({ type: "debug_status", connected }),
      });
      if (created.ws_text_url) {
        const sock = openTextSocket(created.ws_text_url, {
          onAssistant: (text, final) => dispatch({ type: "assistant_text", text, final }),
          onRejected: (reason) => dispatch({ type: "toast", message: `rejected: ${reason}` }),
        });
        await sock.ready;
        textRef.current = sock;
      }
      if (state.mode === "voice") {
        const client = await startVoice(created.session_id);
        voiceRef.current = client;
        meterTimer.current = window.setInterval(() => {
          dispatch({ type: "set_input_level", level: client.getLevel() });
        }, 80);
      }
    } catch (err) {
      dispatch({ type: "toast", message: err instanceof Error ? err.message : "failed to start" });
      teardown();
    }
  };

  useEffect(() => {
    const v = voiceRef.current;
    if (!v) return;
    const allow = !state.voicePaused && !state.micMuted;
    v.setMicEnabled(allow);
  }, [state.voicePaused, state.micMuted]);

  useEffect(() => () => teardown(), [teardown]);

  const sendText = async (text: string) => {
    const before = stateRef.current.transcript.length;
    textRef.current?.send(text);
    await waitUntil(() => {
      const t = stateRef.current.transcript;
      const last = t[t.length - 1];
      return t.length > before && Boolean(last && last.role === "assistant" && last.final);
    }, 90_000);
  };

  const waitFor = async (kind: "payment_result" | "secure_capture", timeoutMs = 120_000) => {
    if (kind === "secure_capture") {
      return waitUntil(() => stateRef.current.gateState === "SECURE_CAPTURE" && Boolean(stateRef.current.captureUrl), timeoutMs);
    }
    return waitUntil(() => Boolean(stateRef.current.paymentResult), timeoutMs);
  };

  return (
    <div className="app">
      <header className="top">
        <h1>EBPP voice console</h1>
        <p>Local test harness. Card data stays in the payment iframe (port 8002).</p>
      </header>
      {state.disconnectWarned && <div className="banner warn">Debug stream disconnected — retrying.</div>}
      {state.toast && (
        <div className="banner toast" role="status">
          {state.toast}
          <button type="button" onClick={() => dispatch({ type: "toast", message: null })}>
            dismiss
          </button>
        </div>
      )}
      <div className="layout">
        <div className="col">
          <CallControls
            state={state}
            onMode={(mode: Mode) => dispatch({ type: "set_mode", mode })}
            onAccount={(accountId) => dispatch({ type: "set_account", accountId })}
            onStart={() => void start()}
            onEnd={teardown}
            onMute={() => dispatch({ type: "set_mic_muted", muted: !state.micMuted })}
            onHandoff={() => {
              if (state.sessionId) void endHandoff(state.sessionId);
            }}
          />
          <Transcript items={state.transcript} />
          <TextInput
            disabled={state.connection !== "connected"}
            captureActive={state.gateState === "SECURE_CAPTURE"}
            onSend={(t) => void sendText(t)}
          />
          {state.mode === "text" && (
            <ScenarioRunner
              disabled={state.connection !== "connected"}
              onAccount={(accountId) => dispatch({ type: "set_account", accountId })}
              send={sendText}
              waitFor={waitFor}
            />
          )}
        </div>
        <div className="col">
          <StateGatePanel state={state} />
          <SecurePaymentPanel
            captureUrl={state.captureUrl}
            expiresAt={state.captureExpiresAt}
            onStatus={() => {
              /* webhook drives state; postMessage is UI-only */
            }}
          />
          <ToolInspector tools={state.tools} router={state.router} />
          <LatencyPanel samples={state.latency} />
          <LeakCounters
            scrubberHits={state.scrubberHits}
            framesDroppedSecure={state.framesDroppedSecure}
            transcript={state.transcript}
          />
          <Outbox items={state.outbox} />
          <BillViewer bill={state.bill} />
        </div>
      </div>
    </div>
  );
}

function waitUntil(pred: () => boolean, timeoutMs: number): Promise<boolean> {
  const start = Date.now();
  return new Promise((resolve) => {
    const tick = () => {
      if (pred()) return resolve(true);
      if (Date.now() - start > timeoutMs) return resolve(false);
      window.setTimeout(tick, 120);
    };
    tick();
  });
}
