from collections import Counter

from app.markov import BOS, EOS, MarkovModel


def test_generate_after_train():
    m = MarkovModel(seed=42)
    m.train("吾輩は猫である。名前はまだ無い。")
    s = m.generate_sentence()
    assert isinstance(s, str)
    assert len(s) > 0
    # 終端に文末記号が付く
    assert s[-1] in "。！？!?…"


def test_empty_before_train():
    m = MarkovModel()
    assert m.generate_sentence() == ""
    assert m.is_trained is False


def test_trained_flag():
    m = MarkovModel()
    m.train("こんにちは。元気です。")
    assert m.is_trained is True


def test_next_token_probabilities_sum_to_one():
    m = MarkovModel()
    m.train("猫が鳴く。猫が走る。")
    probs = m.next_token_probabilities(BOS)
    assert probs, "BOS からの遷移が空"
    assert abs(sum(probs.values()) - 1.0) < 1e-9


def test_next_token_probabilities_reflects_frequencies():
    """a -> b が 3 回、a -> c が 1 回なら P(b|a)=0.75, P(c|a)=0.25。"""
    m = MarkovModel()
    # 「猫が鳴く。」を 3 回、「猫が走る。」を 1 回学習。
    # fugashi で分かち書きすると 猫/が/鳴く/。 系のトークンになり、
    # 「が」→「鳴く」が 3 回、「が」→「走る」が 1 回記録される想定。
    m.train("猫が鳴く。猫が鳴く。猫が鳴く。猫が走る。")
    probs = m.next_token_probabilities("が")
    assert probs.get("鳴く") == 0.75
    assert probs.get("走る") == 0.25


def test_sampling_matches_empirical_distribution():
    """確率的サンプリングが経験分布に収束することを検証。

    固定シードで 10000 サンプル取り、観測頻度と理論分布の誤差が
    許容範囲内に収まっていること。
    """
    m = MarkovModel(seed=12345)
    m.train("猫が鳴く。猫が鳴く。猫が鳴く。猫が走る。")
    expected = m.next_token_probabilities("が")
    assert "鳴く" in expected and "走る" in expected

    counts: Counter[str] = Counter()
    n = 10000
    for _ in range(n):
        nxt = m._sample_next("が")
        assert nxt is not None
        counts[nxt] += 1

    for tok, p_theory in expected.items():
        p_observed = counts[tok] / n
        # 二項分布の標準偏差 √(p(1-p)/n) に対して十分大きい許容を取る
        assert abs(p_observed - p_theory) < 0.02, (
            f"{tok}: observed={p_observed:.4f}, expected={p_theory:.4f}"
        )


def test_next_token_probabilities_unknown_prev():
    m = MarkovModel()
    m.train("こんにちは。")
    # 未知の前トークンは空 dict
    assert m.next_token_probabilities("存在しない") == {}


def test_eos_ends_generation():
    """EOS に遷移したら生成が止まる。"""
    m = MarkovModel(seed=0)
    m.train("終わり。")
    # 1 文分だけ学習 → 必ず BOS→...→EOS の鎖で止まる
    s = m.generate_sentence(max_tokens=500)
    assert s
    assert EOS not in s  # 特殊トークンは出力に混ざらない
