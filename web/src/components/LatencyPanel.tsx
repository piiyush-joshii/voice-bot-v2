import type { LatencySample } from "../store/types";

const KEYS = ["asr_ms", "router_ms", "llm_ttft_ms", "tts_ttfb_ms", "e2e_ms"] as const;
const LABELS: Record<(typeof KEYS)[number], string> = {
  asr_ms: "ASR",
  router_ms: "Router",
  llm_ttft_ms: "LLM TTFT",
  tts_ttfb_ms: "TTS TTFB",
  e2e_ms: "E2E",
};

type Props = { samples: LatencySample[] };

export function LatencyPanel({ samples }: Props) {
  const last = samples[samples.length - 1];
  const avg = (k: (typeof KEYS)[number]) =>
    samples.length ? samples.reduce((s, x) => s + x[k], 0) / samples.length : 0;
  return (
    <section className="panel" aria-label="Latency">
      <h2>Latency</h2>
      {KEYS.map((k) => {
        const values = samples.map((s) => s[k]);
        return (
          <div key={k} className="lat-row">
            <span>{LABELS[k]}</span>
            <Spark values={values} />
            <span>{last ? `${last[k].toFixed(0)} / ${avg(k).toFixed(0)} ms` : "—"}</span>
          </div>
        );
      })}
    </section>
  );
}

function Spark({ values }: { values: number[] }) {
  const w = 80;
  const h = 18;
  if (values.length < 2) return <svg width={w} height={h} aria-hidden />;
  const max = Math.max(...values, 1);
  const pts = values
    .slice(-20)
    .map((v, i, arr) => `${(i / (arr.length - 1)) * w},${h - (v / max) * (h - 2) - 1}`)
    .join(" ");
  return (
    <svg width={w} height={h} aria-hidden>
      <polyline fill="none" stroke="currentColor" strokeWidth="1.5" points={pts} />
    </svg>
  );
}
