"""原文(漢字かな混じり) ↔ VoiceVox の mora タイミングのアラインメント。

VoiceVox が返す mora のテキストは全てカタカナなので、字幕にそのまま使うと
「ワガハイハネコデアル」のように表示されてしまう。本モジュールは
fugashi で原文を分かち書きして各トークンの発音 mora 数を数え、VoiceVox の
speech-mora 列を token mora count で消費することで、各 token を「原文上の
start/end 秒」に対応づける。さらに token 区間を表層文字数で均等に割り付けて
「原文 1 文字 → [start, end]」の列に変換する。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from fugashi import Tagger

log = logging.getLogger("vvmc")

# 小書きカナ: 直前の mora に付いて独立 mora にならない(拗音)
# ッ(促音) と ン(撥音) と ー(長音) は独立 mora として数える(除外しない)
_SMALL_KANA = set("ャュョァィゥェォヮ")

_tagger_singleton: Tagger | None = None


def _tagger() -> Tagger:
    global _tagger_singleton
    if _tagger_singleton is None:
        _tagger_singleton = Tagger()
    return _tagger_singleton


def pron_mora_count(kana: str) -> int:
    """カタカナ列の mora 数。拗音(小書き ャュョ 等)は 1 mora に含める。

    例:
      "ワガハイ" → 4
      "キャベツ" → 3 (キャ + ベ + ツ)
      "ッ" → 1 (促音は独立 mora)
      "" → 0
    """
    if not kana:
        return 0
    return sum(1 for ch in kana if ch not in _SMALL_KANA)


def _token_pron(word) -> str:
    """fugashi の Word から発音カタカナを取る。

    unidic-lite は助詞「は」「を」「へ」を pron で "ワ" "オ" "エ" として返す
    (VoiceVox の実際の発音と一致)。kana フィールドだと表記カナ "ハ" "ヲ" "ヘ"
    になってしまい VoiceVox と噛み合わないので pron を優先。
    """
    f = word.feature
    return getattr(f, "pron", None) or getattr(f, "kana", None) or ""


@dataclass(frozen=True)
class AlignInputMora:
    """アラインメントの入力となる mora。

    VoiceVox の accent_phrases を flatten したもの。pause_mora は
    is_pause=True で区別する。
    """

    text: str
    start: float
    end: float
    is_pause: bool


@dataclass(frozen=True)
class CharTiming:
    """出力: 原文 1 文字とその再生時間(秒)。"""

    text: str
    start: float
    end: float


def align_chars(text: str, moras: Sequence[AlignInputMora]) -> list[CharTiming]:
    """原文 `text` の各文字に `moras` 由来の再生時刻を割り当てる。

    手順:
      1. fugashi で text を分かち書きし、各トークンの発音 mora 数を見積もる
      2. moras を speech / pause に分離
      3. トークンと speech-mora 列を順に歩き、各トークンが消費する
         mora 区間 [first_mora.start, last_mora.end] を算出
      4. 非 moraic トークン(句読点など)は直近の pause_mora に割り付ける
      5. トークン区間をその表層文字数で均等に割って CharTiming 列を返す

    fugashi と VoiceVox の mora 数が食い違った場合は、全文長を原文の
    文字数で均等割りにするフォールバックを使う(字幕が壊れないように)。
    """
    speech_moras = [m for m in moras if not m.is_pause]
    pause_moras = [m for m in moras if m.is_pause]

    tokens: list[tuple[str, int]] = []
    for w in _tagger()(text):
        surface = w.surface
        if not surface:
            continue
        tokens.append((surface, pron_mora_count(_token_pron(w))))

    expected_total = sum(c for _, c in tokens)
    if expected_total != len(speech_moras):
        log.debug(
            "mora alignment mismatch: fugashi=%d, voicevox=%d; "
            "falling back to proportional split over %r",
            expected_total,
            len(speech_moras),
            text,
        )
        return _proportional_split(text, moras)

    out: list[CharTiming] = []
    mi = 0  # speech mora index
    pi = 0  # pause mora index
    for surface, expected in tokens:
        if expected == 0:
            # 句読点などの非 moraic トークン。対応する pause_mora があれば
            # その区間を、無ければ「前 token の末尾時刻」で 0 秒区間として付ける。
            if pi < len(pause_moras):
                pm = pause_moras[pi]
                _spread(out, surface, pm.start, pm.end)
                pi += 1
            else:
                t_last = out[-1].end if out else (moras[0].start if moras else 0.0)
                _spread(out, surface, t_last, t_last)
            continue
        start = speech_moras[mi].start
        end = speech_moras[mi + expected - 1].end
        _spread(out, surface, start, end)
        mi += expected

    return out


def _spread(out: list[CharTiming], surface: str, start: float, end: float) -> None:
    """surface の各文字に [start, end] を均等割り付けして out に追加。"""
    cs = list(surface)
    if not cs:
        return
    dur = max(end - start, 0.0)
    per = dur / len(cs) if cs else 0.0
    for i, ch in enumerate(cs):
        out.append(CharTiming(text=ch, start=start + per * i, end=start + per * (i + 1)))


def _proportional_split(text: str, moras: Sequence[AlignInputMora]) -> list[CharTiming]:
    """フォールバック: 総再生時間を text の文字数で均等に分ける。"""
    if not moras or not text:
        return []
    t_start = moras[0].start
    t_end = moras[-1].end
    cs = list(text)
    if not cs:
        return []
    per = max(t_end - t_start, 0.0) / len(cs)
    return [
        CharTiming(text=c, start=t_start + per * i, end=t_start + per * (i + 1))
        for i, c in enumerate(cs)
    ]
