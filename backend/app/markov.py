"""2-gram マルコフ連鎖による日本語文生成。

- fugashi + unidic-lite で分かち書き
- 文末記号 (。! ? …) で文を区切って学習
- 文頭/文末は特殊トークンで表現
- 遷移先は頻度カウンタで持ち、次トークンは確率に比例した重み付き
  サンプリング(random.choices の weights 引数)で選ぶ

確率的サンプリングの意味:
  ある前トークン a について、学習データ中で a -> b が 3 回、a -> c が 1 回
  観測されていれば、次トークンは b が 75%、c が 25% の確率で選ばれる。
  next_token_probabilities() で分布そのものを取り出せるので、外部から
  確率を確認・検証することもできる。
"""

from __future__ import annotations

import random
from collections import Counter, defaultdict
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

    _transitions[prev] は Counter{next_token: count}。
    学習データ中の a -> b の出現回数をそのまま数え、次トークン選択時に
    頻度を重みとする重み付きサンプリングを行う(= 経験分布 P(b|a) に従う)。
    """

    def __init__(self, seed: int | None = None) -> None:
        self._transitions: dict[str, Counter[str]] = defaultdict(Counter)
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
                self._transitions[a][b] += 1

    @property
    def is_trained(self) -> bool:
        return BOS in self._transitions

    # --- 確率分布 / サンプリング -------------------------------------

    def next_token_probabilities(self, prev: str) -> dict[str, float]:
        """前トークン prev に続く各トークンの確率分布を返す。

        合計は 1.0 (prev が未知なら空 dict)。
        """
        counts = self._transitions.get(prev)
        if not counts:
            return {}
        total = sum(counts.values())
        return {tok: cnt / total for tok, cnt in counts.items()}

    def _sample_next(self, prev: str) -> str | None:
        """P(next|prev) に従って 1 トークンをサンプリング。"""
        counts = self._transitions.get(prev)
        if not counts:
            return None
        # 頻度をそのまま weights に渡す(確率に比例して選ばれる)。
        # 正規化(合計 1 への換算)は random.choices の内部で行われる。
        tokens = list(counts.keys())
        weights = list(counts.values())
        return self._rng.choices(tokens, weights=weights, k=1)[0]

    # --- 生成 ---------------------------------------------------------

    def generate_sentence(self, max_tokens: int = 200) -> str:
        """1 文を生成して返す。学習されていなければ空文字を返す。"""
        if not self.is_trained:
            return ""
        out: list[str] = []
        cur = BOS
        for _ in range(max_tokens):
            nxt = self._sample_next(cur)
            if nxt is None or nxt == EOS:
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
