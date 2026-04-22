export type SpeakerStyle = { id: number; name: string; type?: string };
export type Speaker = {
  name: string;
  speaker_uuid: string;
  styles: SpeakerStyle[];
};

export type MoraJSON = { text: string; start: number; end: number };

export type SentenceResponse = {
  text: string;
  audio: string; // base64 WAV
  mora: MoraJSON[];
};

export async function fetchSpeakers(): Promise<Speaker[]> {
  const r = await fetch("/api/speakers");
  if (!r.ok) throw new Error(`speakers HTTP ${r.status}`);
  return r.json();
}

export async function fetchCorpora(): Promise<string[]> {
  const r = await fetch("/api/corpora");
  if (!r.ok) throw new Error(`corpora HTTP ${r.status}`);
  return r.json();
}

export async function fetchSentence(
  speakerId: number,
  corpusName: string,
): Promise<SentenceResponse> {
  const r = await fetch("/api/sentence", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ speaker_id: speakerId, corpus_name: corpusName }),
  });
  if (!r.ok) throw new Error(`sentence HTTP ${r.status}`);
  return r.json();
}

export async function resetServer(corpusName?: string | null): Promise<void> {
  const r = await fetch("/api/reset", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ corpus_name: corpusName ?? null }),
  });
  if (!r.ok) throw new Error(`reset HTTP ${r.status}`);
}

export function base64ToArrayBuffer(b64: string): ArrayBuffer {
  const bin = atob(b64);
  const buf = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i);
  return buf.buffer;
}
