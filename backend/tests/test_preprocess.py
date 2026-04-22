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


def test_aozora_full_sample_akutagawa():
    """ユーザ提供の青空文庫サンプル(蜘蛛の糸 冒頭)に近い形で検証。

    2 本目の ---- 以降が本文。ルビ / 入力者注 / 外字注 が剥がれ、
    タイトル・著者・記号についての注意書きは残らないこと。
    """
    src = (
        "蜘蛛の糸\n"
        "芥川龍之介\n"
        "\n"
        "-------------------------------------------------------\n"
        "【テキスト中に現れる記号について】\n"
        "\n"
        "《》:ルビ\n"
        "(例)蓮池《はすいけ》のふち\n"
        "\n"
        "|:ルビの付く文字列の始まりを特定する記号\n"
        "(例)丁度|地獄《じごく》の底に\n"
        "\n"
        "［＃］:入力者注　主に外字の説明や、傍点の位置の指定\n"
        "　　　(数字は、JIS X 0213の面区点番号、または底本のページと行数)\n"
        "(例)※［＃「特のへん+廴+聿」、第3水準1-87-71］\n"
        "-------------------------------------------------------\n"
        "\n"
        "［＃8字下げ］一［＃「一」は中見出し］\n"
        "\n"
        "　ある日の事でございます。御釈迦様《おしゃかさま》は極楽の蓮池《はすいけ》のふちを、"
        "独りでぶらぶら御歩きになっていらっしゃいました。\n"
    )
    out = clean_aozora(src)

    # ヘッダ(タイトル・著者・記号についての注意書き)は消える
    assert "蜘蛛の糸" not in out
    assert "芥川龍之介" not in out
    assert "【テキスト中に現れる記号について】" not in out
    assert "ルビの付く文字列" not in out

    # 外字注・見出し注は消える
    assert "第3水準" not in out
    assert "中見出し" not in out
    assert "8字下げ" not in out

    # ルビは剥がれ、漢字側だけ残る
    assert "御釈迦様" in out
    assert "蓮池" in out
    assert "おしゃかさま" not in out
    assert "はすいけ" not in out

    # 本文の一部が含まれる
    assert "ある日の事でございます" in out
