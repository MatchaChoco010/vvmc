import { useEffect, useRef } from "react";

export type DisplayChar = {
  id: number;
  text: string;
  /** 仮想再生時刻で、この文字の発声開始 (秒)。 */
  playAt: number;
};

type Props = {
  /** 表示対象の文字列(古いものから新しい順)。 */
  chars: DisplayChar[];
  /** 現在の仮想再生時刻 (秒) を返すアクセサ。毎フレーム呼ばれる。 */
  getPlayhead: () => number;
  /** 画面外に流れた文字を親に通知して DOM から落としてもらうコールバック。 */
  onPrune: (dropCount: number) => void;
};

/** 1 文字あたりの表示幅 (em)。CSS と合わせる。 */
const CHAR_EM = 2.0;
/** 現在位置より後ろに残す最大文字数。 */
const MAX_TRAIL_CHARS = 80;
/** prune は毎フレームではなくインターバルで走らせる。 */
const PRUNE_INTERVAL_MS = 500;

/**
 * スクロール字幕。
 *
 * DOM には props.chars しか置かない。画面外に流れた分は onPrune で親に落としてもらう。
 * transform の更新は毎フレーム (RAF) で直接 DOM を触って行う。
 */
export function Subtitle({ chars, getPlayhead, onPrune }: Props) {
  const outerRef = useRef<HTMLDivElement>(null);
  const innerRef = useRef<HTMLDivElement>(null);
  const charsRef = useRef<DisplayChar[]>(chars);
  const emPxRef = useRef(16);

  charsRef.current = chars;

  useEffect(() => {
    if (!outerRef.current) return;
    const fs = parseFloat(getComputedStyle(outerRef.current).fontSize);
    if (!Number.isNaN(fs)) emPxRef.current = fs;
  }, []);

  useEffect(() => {
    let raf = 0;
    let lastPruneAt = 0;

    const loop = () => {
      const t = getPlayhead();
      const xs = charsRef.current;
      const charWidth = CHAR_EM * emPxRef.current;

      let idx = 0;
      if (xs.length > 0) {
        let i = xs.length - 1;
        while (i > 0 && xs[i].playAt > t) i--;
        if (i + 1 < xs.length) {
          const a = xs[i].playAt;
          const b = xs[i + 1].playAt;
          const frac = b > a ? (t - a) / (b - a) : 0;
          idx = i + Math.max(0, Math.min(1, frac));
        } else {
          idx = i;
        }
      }

      const outer = outerRef.current;
      const inner = innerRef.current;
      if (outer && inner) {
        const centerX = outer.clientWidth / 2;
        const offsetPx = idx * charWidth - centerX + charWidth / 2;
        inner.style.transform = `translateX(${-offsetPx}px)`;
      }

      const now = performance.now();
      if (now - lastPruneAt > PRUNE_INTERVAL_MS) {
        lastPruneAt = now;
        const drop = Math.max(0, Math.floor(idx) - MAX_TRAIL_CHARS);
        if (drop > 0) onPrune(drop);
      }

      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [getPlayhead, onPrune]);

  return (
    <div className="subtitle" ref={outerRef}>
      <div className="subtitle-inner" ref={innerRef}>
        {chars.map((c) => (
          <span key={c.id} className="subtitle-char">
            {c.text}
          </span>
        ))}
      </div>
      <div className="subtitle-caret" aria-hidden="true" />
    </div>
  );
}
