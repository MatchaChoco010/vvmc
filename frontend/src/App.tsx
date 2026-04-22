import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fetchSpeakers, type Speaker, type SpeakerStyle } from "./api";
import { Player, type SentenceStartEvent } from "./player";
import { Subtitle, type DisplayChar } from "./Subtitle";

type FlatStyle = {
  speakerName: string;
  style: SpeakerStyle;
};

function flattenSpeakers(speakers: Speaker[]): FlatStyle[] {
  const flat: FlatStyle[] = [];
  for (const sp of speakers) {
    for (const st of sp.styles) {
      flat.push({ speakerName: sp.name, style: st });
    }
  }
  return flat;
}

let _charId = 0;

function morasToDisplayChars(ev: SentenceStartEvent): DisplayChar[] {
  const out: DisplayChar[] = [];
  for (const m of ev.moras) {
    if (!m.text) continue; // 無音ポーズは字幕に出さない
    const cs = Array.from(m.text); // 拗音("キャ"など)は 2 文字 = 2 moras 表示
    const dur = Math.max(m.end - m.start, 0);
    const per = cs.length > 0 ? dur / cs.length : 0;
    for (let i = 0; i < cs.length; i++) {
      out.push({
        id: _charId++,
        text: cs[i],
        playAt: ev.baseline + m.start + per * i,
      });
    }
  }
  return out;
}

export function App() {
  const player = useMemo(() => new Player(), []);
  const [speakers, setSpeakers] = useState<FlatStyle[] | null>(null);
  const [speakerId, setSpeakerId] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [chars, setChars] = useState<DisplayChar[]>([]);

  const playerRef = useRef(player);

  // 話者一覧取得
  useEffect(() => {
    fetchSpeakers()
      .then((data) => {
        const flat = flattenSpeakers(data);
        setSpeakers(flat);
        if (flat.length > 0) setSpeakerId(flat[0].style.id);
      })
      .catch((e) => setError(String(e)));
  }, []);

  // 話者変更 → Player に反映
  useEffect(() => {
    if (speakerId !== null) player.setSpeaker(speakerId);
  }, [speakerId, player]);

  // Player のハンドラを App に集約
  useEffect(() => {
    player.setHandlers({
      onSentenceStart: (ev) => {
        setChars((prev) => [...prev, ...morasToDisplayChars(ev)]);
      },
      onReset: () => setChars([]),
      onError: (e) => setError(String(e)),
    });
  }, [player]);

  const getPlayhead = useCallback(() => playerRef.current.getVirtualPlayhead(), []);
  const onPrune = useCallback((drop: number) => {
    setChars((prev) => (prev.length > drop ? prev.slice(drop) : prev));
  }, []);

  const toggle = async () => {
    setError(null);
    try {
      if (playing) {
        player.pause();
        setPlaying(false);
      } else {
        await player.start();
        setPlaying(true);
      }
    } catch (e) {
      setError(String(e));
    }
  };

  const reset = async () => {
    setError(null);
    await player.reset();
    setPlaying(false);
  };

  return (
    <div className="app">
      <header className="app-header">
        <h1>vvmc</h1>
        <div className="controls">
          <label className="speaker-picker">
            <span>話者</span>
            <select
              value={speakerId ?? ""}
              onChange={(e) => setSpeakerId(Number(e.target.value))}
              disabled={!speakers || playing}
            >
              {speakers === null && <option>読み込み中…</option>}
              {speakers?.map((fs) => (
                <option key={fs.style.id} value={fs.style.id}>
                  {fs.speakerName} / {fs.style.name}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className={playing ? "btn btn-pause" : "btn btn-play"}
            onClick={toggle}
            disabled={speakerId === null}
          >
            {playing ? "一時停止" : "再生開始"}
          </button>
          <button type="button" className="btn btn-reset" onClick={reset}>
            リセット
          </button>
        </div>
      </header>
      {error && <div className="error">{error}</div>}
      <main className="app-main">
        <Subtitle chars={chars} getPlayhead={getPlayhead} onPrune={onPrune} />
      </main>
    </div>
  );
}
