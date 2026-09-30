import { postOffer } from "../api/sessions";

export type VoiceClient = {
  setMicEnabled: (enabled: boolean) => void;
  getLevel: () => number;
  close: () => void;
};

export async function startVoice(sessionId: string): Promise<VoiceClient> {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 },
    video: false,
  });
  const pc = new RTCPeerConnection({ iceServers: [] });
  const audioEl = document.createElement("audio");
  audioEl.autoplay = true;
  audioEl.setAttribute("playsinline", "true");
  document.body.appendChild(audioEl);

  stream.getTracks().forEach((t) => pc.addTrack(t, stream));
  pc.addTransceiver("audio", { direction: "recvonly" });

  pc.ontrack = (ev) => {
    audioEl.srcObject = ev.streams[0] ?? new MediaStream([ev.track]);
  };

  const ctx = new AudioContext();
  const source = ctx.createMediaStreamSource(stream);
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 512;
  source.connect(analyser);
  const bins = new Uint8Array(analyser.frequencyBinCount);
  const getLevel = () => {
    analyser.getByteTimeDomainData(bins);
    let sum = 0;
    for (const v of bins) {
      const n = (v - 128) / 128;
      sum += n * n;
    }
    return Math.min(1, Math.sqrt(sum / bins.length) * 4);
  };

  const offer = await pc.createOffer();
  await pc.setLocalDescription(offer);
  await waitForIce(pc);
  const local = pc.localDescription;
  if (!local?.sdp) throw new Error("no local SDP");
  const answer = await postOffer({ sdp: local.sdp, type: local.type, session_id: sessionId });
  await pc.setRemoteDescription({ type: answer.type as RTCSdpType, sdp: answer.sdp });

  return {
    setMicEnabled(enabled: boolean) {
      stream.getAudioTracks().forEach((t) => {
        t.enabled = enabled;
      });
    },
    getLevel,
    close() {
      pc.close();
      stream.getTracks().forEach((t) => t.stop());
      void ctx.close();
      audioEl.remove();
    },
  };
}

function waitForIce(pc: RTCPeerConnection): Promise<void> {
  if (pc.iceGatheringState === "complete") return Promise.resolve();
  return new Promise((resolve) => {
    const t = window.setTimeout(resolve, 2000);
    pc.onicegatheringstatechange = () => {
      if (pc.iceGatheringState === "complete") {
        window.clearTimeout(t);
        resolve();
      }
    };
  });
}
