"""2-gram マルコフ連鎖による日本語文生成。

- fugashi + unidic-lite で分かち書き
- 文末記号 (。! ? …) で文を区切って学習
- 文頭/文末は特殊トークンで表現
- reset() で直近の状態(内部では持たないが API 整合性のため)をクリア
"""

from __future__ import annotations

import random
from collections import defaultdict
from collections.abc import Iterable

from fugashi import Tagger

# 文区切りに使う終端記号
_SENT_END_CHARS = "。！？!?…"
_SENT_END_SET = set(_SENT_END_CHARS)

# 特殊トークン
BOS = "<BOS>"
EOS = "<EOS>"


def _iter_sentences(text: str) -> Iterable[str]:
    """テキストを文(終端記号込み)に分割。"""
    buf: list[str] = []
    for ch in text:
        if ch == "\n":
            if buf:
                s = "".join(buf).strip()
                if s:
                    yield s
                buf = []
            continue
        buf.append(ch)
        if ch in _SENT_END_SET:
            s = "".join(buf).strip()
            if s:
                yield s
            buf = []
    if buf:
        s = "".join(buf).strip()
        if s:
            yield s


class MarkovModel:
    """2-gram (バイグラム) マルコフモデル。

    transitions[prev] = [next_token, ...] で重複込み。
    重複込みで持つのは確率サンプリング時に Counter 化しなくて良いため。
    """

    def __init__(self, seed: int | None = None) -> None:
        self._transitions: dict[str, list[str]] = defaultdict(list)
        self._tagger = Tagger()
        self._rng = random.Random(seed)

    # --- 学習 ---------------------------------------------------------

    def _tokenize(self, sentence: str) -> list[str]:
        # fugashi の Word.surface を使う。空白/改行はスキップ。
        return [w.surface for w in self._tagger(sentence) if w.surface.strip()]

    def train(self, text: str) -> None:
        for sent in _iter_sentences(text):
            tokens = self._tokenize(sent)
            if not tokens:
                continue
            seq = [BOS, *tokens, EOS]
            for a, b in zip(seq, seq[1:], strict=False):
                self._transitions[a].append(b)

    @property
    def is_trained(self) -> bool:
        return BOS in self._transitions

    # --- 生成 ---------------------------------------------------------

    def generate_sentence(self, max_tokens: int = 200) -> str:
        """1 文を生成して返す。学習されていなければ空文字を返す。"""
        if not self.is_trained:
            return ""
        out: list[str] = []
        cur = BOS
        for _ in range(max_tokens):
            candidates = self._transitions.get(cur)
            if not candidates:
                break
            nxt = self._rng.choice(candidates)
            if nxt == EOS:
                break
            out.append(nxt)
            cur = nxt
        text = "".join(out)
        # 終端記号がなければ付ける(VoiceVox の読み上げ的に据わりが良い)
        if text and text[-1] not in _SENT_END_SET:
            text += "。"
        return text

    # --- リセット -----------------------------------------------------

    def reset_state(self) -> None:
        """「状態」= 乱数シードの再初期化のみ。学習コーパスは保持。"""
        self._rng = random.Random()
