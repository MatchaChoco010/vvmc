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
  audio: AudioBuffer;
  moras: MoraJSON[];
  duration: number;
};

/**
 * マルコフ連鎖で生成される文を連続再生するプレイヤー。
 *
 * 設計:
 * - バッファは 1〜2 文。不足したら非同期に先読み。
 * - 一時停止中は新規取得も行わず、再生中の音声も停止(現在文は破棄)。
 * - 仮想タイムライン (virtualPlayhead) は再生中だけ進む。字幕の scroll はこれを使う。
 */
export class Player {
  private readonly ctx: AudioContext;
  private speakerId = -1;
  private corpusName: string | null = null;
  private buffer: BufferedSentence[] = [];
  private pending = 0;
  private readonly wantBuffered = 2;

  private playing = false;
  private currentSrc: AudioBufferSourceNode | null = null;
  private currentCtxStart = 0;
  private currentBaseline = 0;
  /** 再生中でないときに固定される仮想再生時刻。 */
  private virtualPlayhead = 0;

  private handlers: PlayerHandlers = {};
  private refillScheduled = false;

  constructor() {
    this.ctx = new AudioContext();
  }

  setHandlers(h: PlayerHandlers): void {
    this.handlers = h;
  }

  setSpeaker(id: number): void {
    this.speakerId = id;
    // 話者を切り替えたら、合成済みバッファは前の話者の声なので捨てる。
    this.buffer = [];
  }

  setCorpus(name: string): void {
    this.corpusName = name;
    // コーパスが変わればバッファの文章も古いので捨てる。
    this.buffer = [];
  }

  isPlaying(): boolean {
    return this.playing;
  }

  async start(): Promise<void> {
    if (this.playing) return;
    this.playing = true;
    await this.ctx.resume();
    this.scheduleRefill();
    this.maybePlay();
  }

  pause(): void {
    if (!this.playing) return;
    // 仮想時刻をフリーズ
    this.virtualPlayhead = this.getVirtualPlayhead();
    this.playing = false;
    if (this.currentSrc) {
      this.currentSrc.onended = null;
      try {
        this.currentSrc.stop();
      } catch {
        /* already stopped */
      }
      this.currentSrc = null;
    }
  }

  async reset(): Promise<void> {
    this.pause();
    this.buffer = [];
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
    if (this.playing && this.currentSrc) {
      return this.currentBaseline + (this.ctx.currentTime - this.currentCtxStart);
    }
    return this.virtualPlayhead;
  }

  // --- 内部 -----------------------------------------------------------

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
            this.scheduleRefill();
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
    const wav = base64ToArrayBuffer(resp.audio);
    const audio = await this.ctx.decodeAudioData(wav);
    return { audio, moras: resp.mora, duration: audio.duration };
  }

  private maybePlay(): void {
    if (!this.playing || this.currentSrc) return;
    const next = this.buffer.shift();
    if (!next) return;

    const src = this.ctx.createBufferSource();
    src.buffer = next.audio;
    src.connect(this.ctx.destination);

    this.currentCtxStart = this.ctx.currentTime;
    this.currentBaseline = this.virtualPlayhead;
    src.start(this.currentCtxStart);
    this.currentSrc = src;

    this.handlers.onSentenceStart?.({
      baseline: this.currentBaseline,
      duration: next.duration,
      moras: next.moras,
    });

    src.onended = () => {
      if (this.currentSrc !== src) return; // stale (pause/reset 後)
      this.virtualPlayhead = this.currentBaseline + next.duration;
      this.currentSrc = null;
      this.scheduleRefill();
      this.maybePlay();
    };
  }
}
