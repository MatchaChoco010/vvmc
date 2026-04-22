"""可変次数 N-gram マルコフ連鎖による日本語文生成。

- fugashi + unidic-lite で分かち書き
- 文末記号 (。! ? …) で文を区切って学習
- 文頭/文末は特殊トークン BOS / EOS で表現
- N-gram は 1-gram から max_n-gram まで全部を同時に学習して保持する
  (同じコーパスから n=1,2,3,... それぞれの遷移表を同時に作る)

生成ステップ:
  各ステップで n を [1, min(max_n, len(context))] から一様乱数で引く。
  引いた n について、直前 n トークンを context key として次トークンの分布を
  引き、その分布 P(next | last-n-tokens) に比例してサンプリングする。
  万一そのコンテキストが学習データに無ければ n を 1 ずつ小さくして back off。

  狙い: n を固定すると n が小さいとバラバラ、大きいと元文ほぼそのまま、に
  なりがち。n を毎回ランダムにすることで、その中間のゆらぎを出す。
"""

from __future__ import annotations

import random
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence

from fugashi import Tagger

# 文区切りに使う終端記号(半角 / 全角の両方を拾う)
_SENT_END_CHARS = "。！？!?…"
_SENT_END_SET = set(_SENT_END_CHARS)

# 特殊トークン
BOS = "<BOS>"
EOS = "<EOS>"

# 既定の最大 n-gram 次数
DEFAULT_MAX_N = 3


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
    """可変次数 N-gram マルコフモデル。

    _transitions[context_tuple] = Counter{next_token: count}。
    context_tuple は 1..max_n の長さの tuple (直前 n トークン列)。
    """

    def __init__(
        self,
        max_n: int = DEFAULT_MAX_N,
        seed: int | None = None,
    ) -> None:
        if max_n < 1:
            raise ValueError("max_n must be >= 1")
        self._max_n = max_n
        self._transitions: dict[tuple[str, ...], Counter[str]] = defaultdict(Counter)
        self._tagger = Tagger()
        self._rng = random.Random(seed)

    # --- 設定 ---------------------------------------------------------

    @property
    def max_n(self) -> int:
        return self._max_n

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
            # n = 1..max_n の全ての次数で n-gram を記録する。
            # context = seq[i : i+n], 次トークン = seq[i+n]
            for n in range(1, self._max_n + 1):
                for i in range(len(seq) - n):
                    context = tuple(seq[i : i + n])
                    nxt = seq[i + n]
                    self._transitions[context][nxt] += 1

    @property
    def is_trained(self) -> bool:
        # 1-gram の BOS 始点が無ければ生成できない
        return (BOS,) in self._transitions

    # --- 確率分布 / サンプリング -------------------------------------

    def next_token_probabilities(
        self,
        context: Sequence[str],
    ) -> dict[str, float]:
        """指定 context に続く次トークンの確率分布 P(next | context) を返す。

        context は長さ 1..max_n のトークン列(tuple / list どちらでも)。
        合計は 1.0。context が学習データに無ければ空 dict を返す。
        """
        key = tuple(context)
        counts = self._transitions.get(key)
        if not counts:
            return {}
        total = sum(counts.values())
        return {tok: cnt / total for tok, cnt in counts.items()}

    def _sample_from_counter(self, counts: Counter[str]) -> str:
        """Counter から頻度を重みにして 1 トークンサンプリング。"""
        tokens = list(counts.keys())
        weights = list(counts.values())
        return self._rng.choices(tokens, weights=weights, k=1)[0]

    def _sample_next(self, context: Sequence[str]) -> str | None:
        """現在のコンテキストから次トークンをサンプリング。

        手順:
          1. 利用可能な最大次数 = min(max_n, len(context))。
             これが 0 なら None (生成終了)。
          2. n を [1, 利用可能最大次数] から一様乱数で引く。
          3. context の末尾 n トークンを key として遷移表を引く。
             ヒットすれば頻度重みでサンプリングして返す。
          4. ヒットしなければ n を 1 ずつ減らして back off。
             n=1 まで試して全部ダメなら None。
        """
        max_n_here = min(self._max_n, len(context))
        if max_n_here < 1:
            return None

        picked_n = self._rng.randint(1, max_n_here)
        for n in range(picked_n, 0, -1):
            tail = tuple(context[-n:])
            counts = self._transitions.get(tail)
            if counts:
                return self._sample_from_counter(counts)
        return None

    # --- 生成 ---------------------------------------------------------

    def generate_sentence(self, max_tokens: int = 200) -> str:
        """1 文を生成して返す。学習されていなければ空文字を返す。"""
        if not self.is_trained:
            return ""
        out: list[str] = []
        context: list[str] = [BOS]
        for _ in range(max_tokens):
            nxt = self._sample_next(context)
            if nxt is None or nxt == EOS:
                break
            out.append(nxt)
            context.append(nxt)
            # context を max_n までで切り詰める(メモリを無駄に伸ばさない)
            if len(context) > self._max_n:
                context = context[-self._max_n :]
        text = "".join(out)
        # 終端記号がなければ付ける(VoiceVox の読み上げ的に据わりが良い)
        if text and text[-1] not in _SENT_END_SET:
            text += "。"
        return text

    # --- リセット -----------------------------------------------------

    def reset_state(self) -> None:
        """「状態」= 乱数シードの再初期化のみ。学習コーパスは保持。"""
        self._rng = random.Random()
