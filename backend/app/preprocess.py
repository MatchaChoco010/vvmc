"""青空文庫テキストの前処理。

青空文庫の .txt は以下の記法を含む:
- ルビ: 漢字《かんじ》
- ルビ開始指定: ｜ (例: ｜漢字《かんじ》)
- 入力者注: ［＃ ... ］
- 外字注記 ※［＃...］
- ヘッダ (タイトル/著者) と ---- 区切り線
- 底本: 以降 の奥付

これらを剥がしてマルコフの学習に使える本文を返す。
"""

from __future__ import annotations

import re

# ルビ: 直前の漢字列 + 《...》 (｜があれば ｜ 以降が対象)
_RUBY_RE = re.compile(r"｜?([^｜《》\n]+?)《[^》]*》")
# 入力者注: ［＃...］(全角)
_EDITOR_NOTE_RE = re.compile(r"［＃[^］]*］")
# 外字注 ※［＃...］(上の注記ルールで拾える場合もあるが ※ が残ると嫌なので別途)
_GAIJI_NOTE_RE = re.compile(r"※?［＃[^］]*］")
# 全角 | (ルビ開始指定) が単体で残る場合に備えて
_RUBY_MARK = "｜"


def _strip_header(text: str) -> str:
    """冒頭のヘッダ(区切り線 ---- に挟まれた部分)を落とす。"""
    lines = text.splitlines()
    sep_indices = [i for i, ln in enumerate(lines) if re.fullmatch(r"[-‐―─-]{10,}", ln.strip())]
    if len(sep_indices) >= 2:
        # 2 本目の区切り線の後ろが本文
        return "\n".join(lines[sep_indices[1] + 1 :])
    return text


def _truncate_at_colophon(text: str) -> str:
    """底本: 以降の奥付を落とす。"""
    m = re.search(r"\n底本[:：]", text)
    if m:
        return text[: m.start()]
    return text


def clean_aozora(text: str) -> str:
    """青空文庫テキストを本文のみのプレーンテキストに整形する。"""
    # BOM / CRLF
    text = text.lstrip("﻿").replace("\r\n", "\n").replace("\r", "\n")

    text = _strip_header(text)
    text = _truncate_at_colophon(text)

    # ルビ除去: 《...》 と、その対象を表す ｜ を剥がす
    text = _RUBY_RE.sub(r"\1", text)
    # 残存する 《...》 (ルビ記法外) は単純除去
    text = re.sub(r"《[^》]*》", "", text)
    # 入力者注 / 外字注
    text = _GAIJI_NOTE_RE.sub("", text)
    text = _EDITOR_NOTE_RE.sub("", text)
    text = text.replace(_RUBY_MARK, "")

    # 空白行の畳み込み(過剰な空行を減らす)
    text = re.sub(r"\n{3,}", "\n\n", text)
    # 行頭の全角スペースは段落インデントなので落とす
    text = re.sub(r"^　+", "", text, flags=re.MULTILINE)

    return text.strip()
