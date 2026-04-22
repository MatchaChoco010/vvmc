from app.alignment import AlignInputMora, align_chars, pron_mora_count


def test_pron_mora_count_basic():
    assert pron_mora_count("") == 0
    assert pron_mora_count("ワガハイ") == 4
    assert pron_mora_count("ネコ") == 2


def test_pron_mora_count_youon():
    """拗音(小書きカナ)は直前に付いて 1 mora に含める。"""
    assert pron_mora_count("キャ") == 1
    assert pron_mora_count("キャベツ") == 3  # キャ + ベ + ツ
    assert pron_mora_count("シュワッチ") == 4  # シュ + ワ + ッ + チ


def test_pron_mora_count_sokuon_long():
    """促音 ッ / 撥音 ン / 長音 ー は独立 mora。"""
    assert pron_mora_count("ッ") == 1
    assert pron_mora_count("ン") == 1
    assert pron_mora_count("アー") == 2


def _mk(text: str, start: float, end: float, is_pause: bool = False) -> AlignInputMora:
    return AlignInputMora(text=text, start=start, end=end, is_pause=is_pause)


def test_align_simple_sentence():
    """「吾輩は猫である。」の各原文文字に時刻が割り当てられること。

    発音 mora: ワガハイ(4) + ワ(1) + ネコ(2) + デ(1) + アル(2) = 10 moras
    + 末尾 pause "。" で 1 pause_mora。
    """
    moras = [
        _mk("ワ", 0.0, 0.1),
        _mk("ガ", 0.1, 0.2),
        _mk("ハ", 0.2, 0.3),
        _mk("イ", 0.3, 0.4),
        _mk("ワ", 0.4, 0.5),
        _mk("ネ", 0.5, 0.6),
        _mk("コ", 0.6, 0.7),
        _mk("デ", 0.7, 0.8),
        _mk("ア", 0.8, 0.9),
        _mk("ル", 0.9, 1.0),
        _mk("。", 1.0, 1.2, is_pause=True),
    ]
    out = align_chars("吾輩は猫である。", moras)

    # 原文文字がそのまま順番に並ぶ
    assert [c.text for c in out] == list("吾輩は猫である。")

    # 「吾輩」(2 文字) に ワガハイ(4 mora) の区間 0.0〜0.4 が割り付けられ、
    # 2 文字に均等に割られているはず
    assert out[0].text == "吾"
    assert abs(out[0].start - 0.0) < 1e-9
    assert abs(out[0].end - 0.2) < 1e-9
    assert out[1].text == "輩"
    assert abs(out[1].start - 0.2) < 1e-9
    assert abs(out[1].end - 0.4) < 1e-9

    # 「は」(1 文字, 1 mora ワ) は 0.4〜0.5
    assert out[2].text == "は"
    assert abs(out[2].start - 0.4) < 1e-9
    assert abs(out[2].end - 0.5) < 1e-9

    # 「猫」(1 文字, 2 mora ネコ) は 0.5〜0.7
    assert out[3].text == "猫"
    assert abs(out[3].start - 0.5) < 1e-9
    assert abs(out[3].end - 0.7) < 1e-9

    # 「。」は pause_mora (1.0〜1.2) に割り付け
    assert out[-1].text == "。"
    assert abs(out[-1].start - 1.0) < 1e-9
    assert abs(out[-1].end - 1.2) < 1e-9


def test_align_monotonic():
    """連続する文字の時刻は単調非減少で、かつ前の文字の end = 次の文字の start
    (同じ token 内で均等割りなので連続、token 境界では mora 境界に一致)。
    """
    moras = [
        _mk("ネ", 0.0, 0.1),
        _mk("コ", 0.1, 0.2),
        _mk("ガ", 0.2, 0.3),
        _mk("イ", 0.3, 0.4),
        _mk("ル", 0.4, 0.5),
        _mk("。", 0.5, 0.7, is_pause=True),
    ]
    out = align_chars("猫がいる。", moras)
    for i in range(len(out) - 1):
        assert out[i].start <= out[i].end
        # 単調性
        assert out[i].end <= out[i + 1].start + 1e-9


def test_align_particle_wa_uses_pron():
    """助詞「は」の読み ワ / 助詞「を」の読み オ に VoiceVox の mora が合うこと。

    fugashi の pron を使っているので、「は」→「ワ」/「を」→「オ」で mora 数が合い、
    アラインメントのフォールバック分岐に落ちないはず。
    """
    # 「犬を見る。」: 犬(イヌ=2), を(オ=1), 見る(ミル=2), 。(0)
    moras = [
        _mk("イ", 0.0, 0.1),
        _mk("ヌ", 0.1, 0.2),
        _mk("オ", 0.2, 0.3),  # を → オ
        _mk("ミ", 0.3, 0.4),
        _mk("ル", 0.4, 0.5),
        _mk("。", 0.5, 0.6, is_pause=True),
    ]
    out = align_chars("犬を見る。", moras)
    assert [c.text for c in out] == list("犬を見る。")
    # 「犬」は 2 mora 分(イヌ = 0.0〜0.2)
    assert abs(out[0].start - 0.0) < 1e-9
    assert abs(out[0].end - 0.2) < 1e-9
    # 「を」は 1 mora 分(オ = 0.2〜0.3)
    assert abs(out[1].start - 0.2) < 1e-9
    assert abs(out[1].end - 0.3) < 1e-9


def test_align_fallback_on_mismatch():
    """fugashi と VoiceVox で mora 数が噛み合わない時は比例割りのフォールバック。

    適当に moras の数を少なく渡して、フォールバックが発動し、
    かつ原文文字が全て出力され、時間が単調増加すること。
    """
    moras = [
        _mk("ア", 0.0, 0.5),
        _mk("イ", 0.5, 1.0),
    ]
    out = align_chars("吾輩は猫である。", moras)
    assert [c.text for c in out] == list("吾輩は猫である。")
    assert abs(out[0].start - 0.0) < 1e-9
    assert abs(out[-1].end - 1.0) < 1e-9
    for i in range(len(out) - 1):
        assert out[i].end <= out[i + 1].start + 1e-9


def test_align_empty_inputs():
    assert align_chars("", []) == []
    assert align_chars("猫", []) == []
