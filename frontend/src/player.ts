import { base64ToArrayBuffer, fetchSentence, resetServer, type MoraJSON } from "./api";

/** 1 文が再生開始されたときに呼ばれるイベント。 */
export type SentenceStartEvent = {
  /** この文が始まる仮想時刻 (秒)。Player.getVirtualPlayhead() と同じ目盛り。 */
  baseline: number;
  /** この文の音声長 (秒)。 */
  duration: number;
  /** VoiceVox の mora タイミング。start/end は文内の相対秒。 */
  moras: MoraJSON[];
};

export type PlayerHandlers = {
  onSentenceStart?: (ev: SentenceStartEvent) => void;
  onReset?: () => void;
  onError?: (e: unknown) => void;
};

type BufferedSentence = {
  wavUrl: string; // Blob URL
  moras: MoraJSON[];
  duration: number;
};

/**
 * マルコフ連鎖で生成される文を連続再生するプレイヤー。
 *
 * Android Chrome ではタブがバックグラウンドに入ったり画面消灯すると
 * AudioContext が suspend されて音が止まる。これは PWA/Service Worker に
 * しても回避できない (SW からは音声を鳴らせない)。一方 <audio> 要素での
 * 再生はブラウザにメディア再生とみなされ、バックグラウンド/画面消灯でも
 * 継続する。このため Web Audio ではなく HTMLAudioElement を使う。
 *
 * クリップ間のギャップ対策として 2 つの <audio> 要素を ping-pong する。
 * さらに、ある文を再生開始した直後に buffer 先頭を反対側スロットに
 * preload しておき、ended → 次 play() の遅延を最小化する。
 */
export class Player {
  private static readonly SLOT_COUNT = 2;
  private readonly audios: HTMLAudioElement[];
  /**
   * タブを常時 audible に保つための微小信号ループ。
   *
   * ping-pong スロットだけでは、(1) ended → 次 play() の一瞬、および
   * (2) バッファ枯渇中 (maybePlay が shift 失敗で何もしないまま待機)
   * に「タブ non-audible」状態が発生する。Android Chrome は画面消灯中に
   * この状態になるとタブを throttle/freeze し、fetch まで止まるため
   * バッファの補充が効かず永久停止する (実機で再生 2〜3 文後に停止)。
   *
   * 対策として、-90 dBFS のほぼ無音な WAV を loop 再生する <audio> を
   * 常駐させ、再生セッション中は常にタブを audible 扱いに保つ。
   */
  private readonly keepalive: HTMLAudioElement;
  private slotIdx = 0; // 次に使うスロット

  private speakerId = -1;
  private corpusName: string | null = null;
  private buffer: BufferedSentence[] = [];
  private pending = 0;
  private readonly wantBuffered = 2;

  private playing = false;
  private currentAudio: HTMLAudioElement | null = null;
  private currentBaseline = 0;
  /** 再生中でないときに固定される仮想再生時刻。 */
  private virtualPlayhead = 0;

  private handlers: PlayerHandlers = {};
  private refillScheduled = false;

  constructor() {
    this.audios = [];
    // React StrictMode の double-invoke 等で複数回構築されても audio 要素が
    // DOM に増殖しないよう、既に挿入済みのものは再利用する。
    const existing = document.querySelectorAll<HTMLAudioElement>('audio[data-vvmc="1"]');
    for (let i = 0; i < existing.length && this.audios.length < Player.SLOT_COUNT; i++) {
      this.audios.push(existing[i]);
    }
    while (this.audios.length < Player.SLOT_COUNT) {
      const a = document.createElement("audio");
      a.dataset.vvmc = "1";
      a.preload = "auto";
      a.style.display = "none";
      document.body.appendChild(a);
      this.audios.push(a);
    }
    this.keepalive = this.ensureKeepaliveAudio();
    this.setupMediaSession();
  }

  private ensureKeepaliveAudio(): HTMLAudioElement {
    const existing = document.querySelector<HTMLAudioElement>(
      'audio[data-vvmc-keepalive="1"]',
    );
    if (existing) return existing;
    const a = document.createElement("audio");
    a.dataset.vvmcKeepalive = "1";
    a.loop = true;
    a.preload = "auto";
    a.style.display = "none";
    a.src = URL.createObjectURL(makeKeepaliveWav());
    document.body.appendChild(a);
    return a;
  }

  /**
   * OS の通知領域にメディアコントロールを出すための設定。
   * secure context 必須のため LAN + HTTP では navigator.mediaSession が
   * 無い。その場合でも <audio> 単体でバックグラウンド再生は維持される。
   */
  private setupMediaSession(): void {
    if (!("mediaSession" in navigator)) return;
    try {
      navigator.mediaSession.metadata = new MediaMetadata({ title: "vvmc" });
    } catch {
      /* ignore */
    }
    navigator.mediaSession.setActionHandler("play", () => {
      this.start().catch((e) => this.handlers.onError?.(e));
    });
    navigator.mediaSession.setActionHandler("pause", () => {
      this.pause();
    });
  }

  setHandlers(h: PlayerHandlers): void {
    this.handlers = h;
  }

  setSpeaker(id: number): void {
    this.speakerId = id;
    // 話者を切り替えたら、合成済みバッファは前の話者の声なので捨てる。
    this.clearBuffer();
  }

  setCorpus(name: string): void {
    this.corpusName = name;
    // コーパスが変わればバッファの文章も古いので捨てる。
    this.clearBuffer();
    if ("mediaSession" in navigator) {
      try {
        navigator.mediaSession.metadata = new MediaMetadata({ title: "vvmc", artist: name });
      } catch {
        /* ignore */
      }
    }
  }

  isPlaying(): boolean {
    return this.playing;
  }

  async start(): Promise<void> {
    if (this.playing) return;
    this.playing = true;
    // バッファ枯渇や clip 間ギャップでタブが non-audible 判定されないよう
    // 先に keepalive を回す。ユーザ操作 (再生ボタン) 直後に play() が
    // 呼ばれる前提なので autoplay policy も通る。
    try {
      const p = this.keepalive.play();
      if (p && typeof p.catch === "function") await p.catch(() => undefined);
    } catch {
      /* ignore — keepalive が動かなくても本筋の再生自体は始める */
    }
    if ("mediaSession" in navigator) navigator.mediaSession.playbackState = "playing";
    this.scheduleRefill();
    this.maybePlay();
  }

  pause(): void {
    if (!this.playing) return;
    // 仮想時刻をフリーズ
    this.virtualPlayhead = this.getVirtualPlayhead();
    this.playing = false;
    if (this.currentAudio) {
      const a = this.currentAudio;
      a.onended = null;
      try {
        a.pause();
      } catch {
        /* already stopped */
      }
      this.currentAudio = null;
    }
    try {
      this.keepalive.pause();
    } catch {
      /* ignore */
    }
    if ("mediaSession" in navigator) navigator.mediaSession.playbackState = "paused";
  }

  async reset(): Promise<void> {
    this.pause();
    this.clearBuffer();
    this.virtualPlayhead = 0;
    try {
      // 現在選択中のコーパスのみ状態を初期化する。他のコーパスには触らない。
      await resetServer(this.corpusName);
    } catch (e) {
      this.handlers.onError?.(e);
    }
    this.handlers.onReset?.();
  }

  /**
   * 仮想再生時刻(秒)。ポーズ中はフリーズ、再生中は単調増加。
   * 字幕の scroll 計算に使う。
   */
  getVirtualPlayhead(): number {
    if (this.playing && this.currentAudio) {
      return this.currentBaseline + this.currentAudio.currentTime;
    }
    return this.virtualPlayhead;
  }

  // --- 内部 -----------------------------------------------------------

  private clearBuffer(): void {
    for (const s of this.buffer) URL.revokeObjectURL(s.wavUrl);
    this.buffer = [];
  }

  private scheduleRefill(): void {
    if (this.refillScheduled) return;
    this.refillScheduled = true;
    queueMicrotask(() => {
      this.refillScheduled = false;
      this.refill();
    });
  }

  private refill(): void {
    if (!this.playing) return;
    if (this.speakerId < 0 || this.corpusName === null) return;
    while (this.buffer.length + this.pending < this.wantBuffered) {
      this.pending++;
      this.fetchOne(this.speakerId, this.corpusName)
        .then((sentence) => {
          this.pending--;
          if (this.playing) {
            this.buffer.push(sentence);
            this.maybePlay();
            this.preloadNext();
            this.scheduleRefill();
          } else {
            // もう再生していないので blob を捨てる。
            URL.revokeObjectURL(sentence.wavUrl);
          }
        })
        .catch((e) => {
          this.pending--;
          this.handlers.onError?.(e);
          // バックオフ
          setTimeout(() => this.scheduleRefill(), 1000);
        });
    }
  }

  private async fetchOne(speakerId: number, corpusName: string): Promise<BufferedSentence> {
    const resp = await fetchSentence(speakerId, corpusName);
    const buf = base64ToArrayBuffer(resp.audio);
    const blob = new Blob([buf], { type: "audio/wav" });
    const wavUrl = URL.createObjectURL(blob);
    const duration = await probeDuration(wavUrl);
    return { wavUrl, moras: resp.mora, duration };
  }

  private maybePlay(): void {
    if (!this.playing || this.currentAudio) return;
    const next = this.buffer.shift();
    if (!next) return;

    const slot = this.audios[this.slotIdx];
    this.slotIdx = (this.slotIdx + 1) % Player.SLOT_COUNT;

    // 既に preload で src セット済みなら load し直さない。
    if (slot.src !== next.wavUrl) {
      this.revokeSlotBlob(slot);
      slot.src = next.wavUrl;
    }
    slot.onended = null;
    try {
      slot.currentTime = 0;
    } catch {
      /* ignore (一部ブラウザで src セット直後に触ると throw) */
    }

    this.currentBaseline = this.virtualPlayhead;
    this.currentAudio = slot;
    const duration = next.duration;
    const moras = next.moras;
    const wavUrl = next.wavUrl;

    slot.onended = () => {
      if (this.currentAudio !== slot) return; // stale (pause/reset 後)
      this.virtualPlayhead = this.currentBaseline + duration;
      this.currentAudio = null;
      // 再生が終わったスロットの blob はもう不要。
      if (slot.src === wavUrl) {
        // 次の maybePlay で上書きされるときに revoke される。ここでは残す。
      }
      this.scheduleRefill();
      this.maybePlay();
    };

    const p = slot.play();
    if (p && typeof p.catch === "function") {
      p.catch((e) => this.handlers.onError?.(e));
    }

    this.handlers.onSentenceStart?.({ baseline: this.currentBaseline, duration, moras });

    // 次の文があれば反対側スロットに src をセットして先読みさせる。
    this.preloadNext();
  }

  /**
   * 次回 maybePlay で使う予定のスロットに buffer 先頭を事前 src 設定する。
   * ended → 次 play() の間でデコードを待たないための最適化。
   */
  private preloadNext(): void {
    const upcoming = this.buffer[0];
    if (!upcoming) return;
    const slot = this.audios[this.slotIdx];
    if (slot === this.currentAudio) return;
    if (slot.src === upcoming.wavUrl) return;
    this.revokeSlotBlob(slot);
    slot.src = upcoming.wavUrl;
    // load() は src セット時に自動で走るので明示呼び出しは不要。
  }

  private revokeSlotBlob(slot: HTMLAudioElement): void {
    const prev = slot.src;
    if (prev && prev.startsWith("blob:")) {
      URL.revokeObjectURL(prev);
    }
  }
}

/**
 * WAV Blob URL の再生時間を <audio> 要素の metadata load で計測する。
 * VoiceVox が返す mora の end と実 WAV 長は厳密には一致しない可能性が
 * あるので、実ファイルから取った値を baseline 更新の基準にする。
 */
function probeDuration(url: string): Promise<number> {
  return new Promise((resolve, reject) => {
    const probe = document.createElement("audio");
    probe.preload = "metadata";
    const cleanup = () => {
      probe.onloadedmetadata = null;
      probe.onerror = null;
      probe.src = "";
    };
    probe.onloadedmetadata = () => {
      const d = probe.duration;
      cleanup();
      resolve(Number.isFinite(d) && d > 0 ? d : 0);
    };
    probe.onerror = () => {
      cleanup();
      reject(new Error("audio metadata load failed"));
    };
    probe.src = url;
  });
}

/**
 * 振幅 1 (16bit PCM、約 -90 dBFS、人間の耳には完全に無音) の 1 秒 WAV。
 * タブを常時 audible 扱いに保ち、Android Chrome のバックグラウンド
 * throttle からセッション全体を守るために loop 再生する。
 *
 * 振幅 0 を避けているのは、ブラウザによっては完全無音を "silent" と
 * 判定して audible タブ扱いから外す可能性があるため (保険)。
 */
function makeKeepaliveWav(): Blob {
  const sampleRate = 8000;
  const numSamples = sampleRate; // 1 秒
  const dataSize = numSamples * 2; // 16bit mono
  const buf = new ArrayBuffer(44 + dataSize);
  const view = new DataView(buf);
  let p = 0;
  const writeStr = (s: string) => {
    for (let i = 0; i < s.length; i++) view.setUint8(p++, s.charCodeAt(i));
  };
  const writeU32 = (n: number) => {
    view.setUint32(p, n, true);
    p += 4;
  };
  const writeU16 = (n: number) => {
    view.setUint16(p, n, true);
    p += 2;
  };
  writeStr("RIFF");
  writeU32(36 + dataSize);
  writeStr("WAVE");
  writeStr("fmt ");
  writeU32(16);
  writeU16(1); // PCM
  writeU16(1); // mono
  writeU32(sampleRate);
  writeU32(sampleRate * 2); // byte rate
  writeU16(2); // block align
  writeU16(16); // bits per sample
  writeStr("data");
  writeU32(dataSize);
  for (let i = 0; i < numSamples; i++) {
    view.setInt16(44 + i * 2, 1, true);
  }
  return new Blob([buf], { type: "audio/wav" });
}
