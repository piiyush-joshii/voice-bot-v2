import type { AppState } from "../store/types";

const COLORS: Record<string, string> = {
  IDLE: "var(--muted)",
  UNAUTHENTICATED: "#8a6d3b",
  AUTHENTICATED: "#2e7d32",
  PAYMENT_PENDING: "#1565c0",
  SECURE_CAPTURE: "#c62828",
  PAYMENT_RESULT: "#6a1b9a",
  HANDOFF: "#455a64",
};

type Props = { state: AppState };

export function StateGatePanel({ state }: Props) {
  return (
    <section className="panel" aria-label="State and gate">
      <div className="state-badge" style={{ background: COLORS[state.gateState] ?? "#333" }}>
        {state.gateState}
      </div>
      <ul className="indicators">
        <li>
          Audio to model:{" "}
          <strong className={state.audioToModel}>{state.audioToModel.toUpperCase()}</strong>
        </li>
        <li>
          Recording: <strong>{state.recording.toUpperCase()}</strong>
        </li>
      </ul>
      <ol className="timeline">
        {state.transitions.slice(-8).map((t) => (
          <li key={t.id}>
            {t.from} → {t.to}
            {t.reason ? ` (${t.reason})` : ""}
          </li>
        ))}
      </ol>
    </section>
  );
}
