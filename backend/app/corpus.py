"""コーパス (テキストファイル群) の読み込み。

エンコーディング判別と、corpus/<name>/*.txt を束ねて MarkovModel を
学習する処理をここに集約する。main.py から使う。
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.markov import MarkovModel
from app.preprocess import clean_aozora

log = logging.getLogger("vvmc")

_UTF8_BOM = b"\xef\xbb\xbf"


def read_text_auto(path: Path) -> str:
    """UTF-8 / UTF-8 with BOM / Shift_JIS(CP932) のどれでも読めるように
    自動判別して文字列を返す。

    - 先頭が UTF-8 BOM ならそれを剥がして UTF-8 で decode
    - 次に UTF-8 strict で decode 試行
    - 失敗したら CP932 strict で decode 試行
    - それも失敗したら CP932 で replace 付き decode し、警告を出す

    CP932 は Shift_JIS に Windows 拡張を足した上位互換。青空文庫の
    zip 配布は CP932 で入っていることが多いので、生の Shift_JIS ファイルも
    これで読める。

    errors='replace' を普段は使わないのは、UTF-8 の一部のバイト欠落
    (例: 末尾切り詰め) を CP932 で無理に読んで全編を壊れた文字列に
    すり替えてしまう事故を避けるため。
    """
    data = path.read_bytes()

    if data.startswith(_UTF8_BOM):
        return data[len(_UTF8_BOM) :].decode("utf-8")

    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        pass

    try:
        return data.decode("cp932")
    except UnicodeDecodeError:
        log.warning(
            "could not cleanly decode %s as UTF-8 or CP932; "
            "falling back to CP932 with replacement",
            path,
        )
        return data.decode("cp932", errors="replace")


def load_corpora(corpus_dir: Path) -> dict[str, MarkovModel]:
    """corpus_dir 配下の各サブディレクトリを 1 コーパスとして学習。

    例: corpus/akutagawa/*.txt → モデル名 "akutagawa"
        corpus/souseki/*.txt   → モデル名 "souseki"
    corpus_dir 直下の .txt ファイル(サブディレクトリ外)は無視する。
    """
    models: dict[str, MarkovModel] = {}
    if not corpus_dir.exists():
        log.warning("corpus dir %s does not exist", corpus_dir)
        return models

    loose_txts = list(corpus_dir.glob("*.txt"))
    if loose_txts:
        log.warning(
            "ignoring %d loose .txt file(s) directly under %s "
            "(place them in a subdirectory to form a corpus)",
            len(loose_txts),
            corpus_dir,
        )

    subdirs = sorted(p for p in corpus_dir.iterdir() if p.is_dir())
    for subdir in subdirs:
        parts: list[str] = []
        for txt in sorted(subdir.glob("*.txt")):
            raw = read_text_auto(txt)
            cleaned = clean_aozora(raw)
            log.info("corpus %s: +%s (%d chars)", subdir.name, txt.name, len(cleaned))
            if cleaned:
                parts.append(cleaned)
        if not parts:
            log.warning("corpus %s: no usable .txt; skipping", subdir.name)
            continue
        model = MarkovModel()
        model.train("\n".join(parts))
        models[subdir.name] = model
        log.info(
            "corpus %s: trained (%d head states)",
            subdir.name,
            len(model._transitions),
        )
    return models
