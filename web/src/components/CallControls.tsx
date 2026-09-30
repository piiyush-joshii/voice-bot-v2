import type { AppState, Mode } from "../store/types";
import { ACCOUNTS, OTP } from "../store/types";

type Props = {
  state: AppState;
  onMode: (mode: Mode) => void;
  onAccount: (id: string) => void;
  onStart: () => void;
  onEnd: () => void;
  onMute: () => void;
  onHandoff: () => void;
};

export function CallControls({ state, onMode, onAccount, onStart, onEnd, onMute, onHandoff }: Props) {
  const live = state.connection === "connected" || state.connection === "connecting";
  return (
    <section className="panel" aria-label="Call controls">
      <div className="row wrap">
        <fieldset className="segmented" role="radiogroup" aria-label="Mode">
          {(["text", "voice"] as const).map((m) => (
            <label key={m}>
              <input type="radio" name="mode" checked={state.mode === m} disabled={live} onChange={() => onMode(m)} />
              {m === "text" ? "Text" : "Voice"}
            </label>
          ))}
        </fieldset>
        <button type="button" className="primary" onClick={onStart} disabled={live}>
          Start session
        </button>
        <button type="button" onClick={onEnd} disabled={!live}>
          End
        </button>
        {state.mode === "voice" && (
          <button type="button" onClick={onMute} disabled={!live} aria-pressed={state.micMuted}>
            {state.micMuted || state.voicePaused ? "Mic muted" : "Mute mic"}
          </button>
        )}
        <button type="button" onClick={onHandoff} disabled={!live}>
          Handoff
        </button>
        <span className={`status ${state.connection}`} role="status">
          {state.connection}
        </span>
      </div>
      <div className="row wrap">
        <label>
          Account
          <select value={state.accountId} onChange={(e) => onAccount(e.target.value)} disabled={live}>
            {ACCOUNTS.map((a) => (
              <option key={a.id} value={a.id}>
                {a.id} — {a.note}
              </option>
            ))}
          </select>
        </label>
        <p className="hint">
          Verifier {ACCOUNTS.find((a) => a.id === state.accountId)?.verifier ?? "—"} · OTP {OTP}
        </p>
      </div>
      {state.mode === "voice" && (
        <div className="meter" aria-label="Input level">
          <div className={`meter-fill ${state.voicePaused ? "paused" : ""}`} style={{ width: `${Math.round(state.inputLevel * 100)}%` }} />
          {state.voicePaused && <span className="paused-flag">Voice paused for secure entry</span>}
        </div>
      )}
    </section>
  );
}
