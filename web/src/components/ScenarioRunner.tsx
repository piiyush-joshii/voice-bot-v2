import { useState } from "react";
import { SCENARIOS, type Scenario } from "../scenarios";

type Result = { id: string; ok: boolean; detail: string };

type Props = {
  disabled: boolean;
  onAccount: (id: string) => void;
  send: (text: string) => Promise<void>;
  waitFor: (kind: "payment_result" | "secure_capture", timeoutMs?: number) => Promise<boolean>;
};

export function ScenarioRunner({ disabled, onAccount, send, waitFor }: Props) {
  const [running, setRunning] = useState<string | null>(null);
  const [results, setResults] = useState<Result[]>([]);

  const run = async (scenario: Scenario) => {
    setRunning(scenario.id);
    const out: Result[] = [];
    if (scenario.accountId) onAccount(scenario.accountId);
    for (const step of scenario.steps) {
      if (step.user) {
        await send(step.user);
        const gate = window.__ebppState ?? "";
        const reply = window.__ebppReply ?? "";
        const stateOk = !step.expectState || gate === step.expectState;
        const replyOk = !step.expectReply || reply.toLowerCase().includes(step.expectReply.toLowerCase());
        out.push({
          id: `${scenario.id}:${step.user.slice(0, 32)}`,
          ok: stateOk && replyOk,
          detail: `state=${gate}${step.expectReply ? ` reply=${reply.slice(0, 40)}` : ""}`,
        });
      } else if (step.waitFor) {
        const ok = await waitFor(step.waitFor, 120_000);
        const gate = window.__ebppState ?? "";
        const stateOk = !step.expectState || gate === step.expectState;
        out.push({
          id: `${scenario.id}:${step.waitFor}`,
          ok: ok && stateOk,
          detail: ok ? `state=${gate}` : "timed out — complete the iframe if it is showing",
        });
      }
    }
    setResults(out);
    setRunning(null);
  };

  return (
    <section className="panel" aria-label="Scenario runner">
      <h2>Scenarios</h2>
      <div className="row wrap">
        {SCENARIOS.map((s) => (
          <button key={s.id} type="button" disabled={disabled || running !== null} onClick={() => void run(s)}>
            {running === s.id ? "Running…" : s.name}
          </button>
        ))}
      </div>
      <ul className="results">
        {results.map((r) => (
          <li key={r.id} className={r.ok ? "pass" : "fail"}>
            {r.ok ? "PASS" : "FAIL"} {r.id} — {r.detail}
          </li>
        ))}
      </ul>
    </section>
  );
}

declare global {
  interface Window {
    __ebppState?: string;
    __ebppPay?: string;
    __ebppReply?: string;
  }
}
