import { countPanLike } from "../luhn";
import type { TranscriptItem } from "../store/types";

type Props = {
  scrubberHits: number;
  framesDroppedSecure: number;
  transcript: TranscriptItem[];
};

export function LeakCounters({ scrubberHits, framesDroppedSecure, transcript }: Props) {
  const visible = transcript.map((t) => t.text).join("\n");
  const panLike = countPanLike(visible);
  return (
    <section className="panel" aria-label="Leak counters">
      <h2>Leak counters</h2>
      <ul>
        <li>scrubber_hits: {scrubberHits}</li>
        <li>frames_dropped_secure: {framesDroppedSecure}</li>
        <li>PAN-like strings in visible transcript: {panLike}</li>
      </ul>
    </section>
  );
}
