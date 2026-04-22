from app.preprocess import clean_aozora


def test_strip_ruby():
    src = "吾輩《わがはい》は猫《ねこ》である。"
    assert clean_aozora(src) == "吾輩は猫である。"


def test_strip_ruby_with_pipe():
    src = "｜朝日新聞《あさひしんぶん》を読む。"
    assert clean_aozora(src) == "朝日新聞を読む。"


def test_strip_editor_note():
    src = "これは［＃「これ」に傍点］本文です。"
    assert clean_aozora(src) == "これは本文です。"


def test_truncate_at_colophon():
    src = "本文だ。\n底本:なんとか全集\n著者なんとか\n"
    out = clean_aozora(src)
    assert out == "本文だ。"


def test_strip_header_between_separators():
    src = (
        "タイトル\n"
        "著者名\n"
        "-------------------------------------------------------\n"
        "【テキスト中に現れる記号について】\n"
        "凡例色々\n"
        "-------------------------------------------------------\n"
        "\n本文一行目。\n本文二行目。\n"
    )
    out = clean_aozora(src)
    assert "凡例" not in out
    assert "本文一行目。" in out
