from pathlib import Path

from app.corpus import load_corpora, read_text_auto


def test_read_utf8(tmp_path: Path) -> None:
    p = tmp_path / "a.txt"
    p.write_bytes("吾輩は猫である。".encode("utf-8"))
    assert read_text_auto(p) == "吾輩は猫である。"


def test_read_utf8_with_bom(tmp_path: Path) -> None:
    p = tmp_path / "a.txt"
    p.write_bytes(b"\xef\xbb\xbf" + "吾輩は猫である。".encode("utf-8"))
    assert read_text_auto(p) == "吾輩は猫である。"


def test_read_cp932(tmp_path: Path) -> None:
    """青空文庫の zip に入っている Shift_JIS(CP932) ファイルが読めること。"""
    p = tmp_path / "a.txt"
    src = "吾輩は猫である。名前はまだ無い。"
    p.write_bytes(src.encode("cp932"))
    assert read_text_auto(p) == src


def test_read_cp932_with_windows_extensions(tmp_path: Path) -> None:
    """CP932 固有の記号(ローマ数字 Ⅰ, ① など)も壊れないこと。"""
    p = tmp_path / "a.txt"
    src = "第Ⅰ章 ①項目"
    p.write_bytes(src.encode("cp932"))
    assert read_text_auto(p) == src


def test_read_pure_ascii_is_utf8(tmp_path: Path) -> None:
    """純 ASCII は UTF-8 としてそのまま読める(CP932 fallback を誤爆しない)。"""
    p = tmp_path / "a.txt"
    p.write_bytes(b"hello, world.\n")
    assert read_text_auto(p) == "hello, world.\n"


def test_load_corpora_mixed_encodings(tmp_path: Path) -> None:
    """UTF-8 と Shift_JIS のファイルが同じフォルダに混在していても、
    両方とも正しくデコードされて 1 コーパスとして学習される。
    """
    corpus_root = tmp_path / "corpus"
    sub = corpus_root / "neko"
    sub.mkdir(parents=True)

    utf8_text = "吾輩は猫である。名前はまだ無い。"
    sjis_text = "どこで生まれたかとんと見当がつかぬ。"
    (sub / "01_utf8.txt").write_bytes(utf8_text.encode("utf-8"))
    (sub / "02_sjis.txt").write_bytes(sjis_text.encode("cp932"))

    corpora = load_corpora(corpus_root)
    assert set(corpora.keys()) == {"neko"}

    model = corpora["neko"]
    assert model.is_trained
    # 学習後の生成結果は乱数依存なので、両方のファイルの語彙が
    # 遷移表に乗っているかで検証する。可変次数モデルのキーは tuple なので
    # 全長の tuple を平らに展開したトークン集合で見る。
    trans = model._transitions  # internal access: テスト目的なので許容
    vocab = {tok for key in trans.keys() for tok in key}
    # UTF-8 側の語彙
    assert "吾輩" in vocab or "猫" in vocab
    # CP932 側の語彙
    assert "どこ" in vocab or "生まれ" in vocab


def test_load_corpora_missing_dir(tmp_path: Path) -> None:
    # 存在しないディレクトリは空 dict を返す(例外を投げない)
    assert load_corpora(tmp_path / "does-not-exist") == {}


def test_load_corpora_ignores_loose_txt(tmp_path: Path) -> None:
    corpus_root = tmp_path / "corpus"
    corpus_root.mkdir()
    (corpus_root / "loose.txt").write_text("無視される。", encoding="utf-8")
    sub = corpus_root / "real"
    sub.mkdir()
    (sub / "a.txt").write_text("これは学習される。", encoding="utf-8")

    corpora = load_corpora(corpus_root)
    assert set(corpora.keys()) == {"real"}
