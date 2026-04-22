from collections import Counter

from app.markov import BOS, EOS, MarkovModel


def test_generate_after_train():
    m = MarkovModel(seed=42)
    m.train("吾輩は猫である。名前はまだ無い。")
    s = m.generate_sentence()
    assert isinstance(s, str)
    assert len(s) > 0
    # 終端に文末記号が付く
    assert s[-1] in "。!?…！？"


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
    probs = m.next_token_probabilities((BOS,))
    assert probs, "BOS からの遷移が空"
    assert abs(sum(probs.values()) - 1.0) < 1e-9


def test_unigram_probabilities_reflects_frequencies():
    """n=1: a -> b が 3 回、a -> c が 1 回なら P(b|a)=0.75, P(c|a)=0.25。"""
    m = MarkovModel(max_n=3)
    m.train("猫が鳴く。猫が鳴く。猫が鳴く。猫が走る。")
    probs = m.next_token_probabilities(("が",))
    assert probs.get("鳴く") == 0.75
    assert probs.get("走る") == 0.25


def test_bigram_and_trigram_stored():
    """可変次数: n=1..max_n の全ての遷移が学習時に記録される。"""
    m = MarkovModel(max_n=3)
    m.train("猫が鳴く。猫が鳴く。猫が走る。")
    # n=2 の context
    bigram_probs = m.next_token_probabilities(("猫", "が"))
    assert bigram_probs, "(猫, が) からの遷移が記録されていない"
    assert abs(sum(bigram_probs.values()) - 1.0) < 1e-9
    assert bigram_probs.get("鳴く") == 2 / 3
    assert bigram_probs.get("走る") == 1 / 3
    # n=3 の context
    trigram_probs = m.next_token_probabilities((BOS, "猫", "が"))
    assert trigram_probs, "(BOS, 猫, が) からの遷移が記録されていない"
    assert abs(sum(trigram_probs.values()) - 1.0) < 1e-9


def test_max_n_limits_stored_order():
    """max_n=2 なら 3-gram は記録されない。"""
    m = MarkovModel(max_n=2)
    m.train("猫が鳴く。猫が走る。")
    # 3-gram の key は入っていない
    assert m.next_token_probabilities((BOS, "猫", "が")) == {}
    # 1-gram と 2-gram は入っている
    assert m.next_token_probabilities(("が",)) != {}
    assert m.next_token_probabilities(("猫", "が")) != {}


def test_sampling_matches_empirical_distribution_fixed_n():
    """固定 n=1 でのサンプリングが経験分布に収束することを検証。"""
    m = MarkovModel(max_n=1, seed=12345)
    m.train("猫が鳴く。猫が鳴く。猫が鳴く。猫が走る。")
    expected = m.next_token_probabilities(("が",))
    assert "鳴く" in expected and "走る" in expected

    counts: Counter[str] = Counter()
    n = 10000
    for _ in range(n):
        # max_n=1 なので _sample_next は必ず 1-gram を使う
        nxt = m._sample_next(["が"])
        assert nxt is not None
        counts[nxt] += 1

    for tok, p_theory in expected.items():
        p_observed = counts[tok] / n
        assert abs(p_observed - p_theory) < 0.02


def test_random_n_selection_uses_all_orders():
    """max_n=3 でサンプリングを繰り返すと、全ての n が使われる。

    判定の仕方: 決定的に分岐が変わる最小コンテキストを作る。
    - 1-gram での (が,) の次は {鳴く:3, 走る:1, 跳ぶ:1}
    - 2-gram での (猫,が) の次は {鳴く:3, 走る:1}(跳ぶは絶対に来ない)
    - 3-gram での (BOS,猫,が) の次は {鳴く:3, 走る:1}(跳ぶは絶対に来ない)
    「跳ぶ」が 1 回でもサンプルされれば n=1 が使われた証拠。
    「跳ぶ」が出ない場合もあるので 5000 回程度回して統計的に確認。
    """
    m = MarkovModel(max_n=3, seed=7)
    # 1-gram でのみ「跳ぶ」が後続しうる分布を作る
    # 「が」単独なら {鳴く, 走る, 跳ぶ} が来るが、(猫, が) だと「跳ぶ」は来ない
    m.train(
        "猫が鳴く。猫が鳴く。猫が鳴く。猫が走る。"
        # 「猫」以外の文脈で「が鳴く」が出るパターン
        "犬が跳ぶ。"
    )
    # 注: fugashi のトークナイズ結果次第で語が変わる可能性があるが、
    # 「跳ぶ」「走る」「鳴く」は表層形で保持されるはず。

    # 1-gram の分布に「跳ぶ」があることを確認
    p1 = m.next_token_probabilities(("が",))
    assert "跳ぶ" in p1
    # 2-gram の分布には「跳ぶ」は無い(猫の後の「が」からは出ない)
    p2 = m.next_token_probabilities(("猫", "が"))
    assert "跳ぶ" not in p2

    # 「猫」で始めて「が」まで進んだ状態でサンプリング。
    # max_n=3 で back off が効くので、n がランダムに選ばれれば
    # 一定確率で 1-gram が選ばれ、「跳ぶ」にも遷移しうる。
    seen_jump = False
    for _ in range(5000):
        nxt = m._sample_next([BOS, "猫", "が"])
        if nxt == "跳ぶ":
            seen_jump = True
            break
    assert seen_jump, "n がランダムに選ばれているなら、n=1 経由で「跳ぶ」が出るはず"


def test_backoff_when_context_unknown():
    """未知の n-gram コンテキストが選ばれても、back off して小さい n で生成が続く。"""
    m = MarkovModel(max_n=3, seed=1)
    m.train("猫が鳴く。猫が走る。")
    # 3-gram key (X, Y, が) は未知でも、最終的に (が,) か何かが引けるはず。
    # 内部的に back off して鳴く/走る のどちらかを返す。
    nxt = m._sample_next(["X", "Y", "が"])
    assert nxt in {"鳴く", "走る"}


def test_next_token_probabilities_unknown_context():
    m = MarkovModel()
    m.train("こんにちは。")
    assert m.next_token_probabilities(("存在しない",)) == {}
    assert m.next_token_probabilities(("a", "b", "c")) == {}


def test_eos_ends_generation():
    """EOS に遷移したら生成が止まる。"""
    m = MarkovModel(seed=0)
    m.train("終わり。")
    s = m.generate_sentence(max_tokens=500)
    assert s
    assert EOS not in s  # 特殊トークンは出力に混ざらない


def test_invalid_max_n():
    import pytest

    with pytest.raises(ValueError):
        MarkovModel(max_n=0)
