from app.markov import MarkovModel


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
