"""VoiceVox engine クライアント。

- /speakers パススルー
- /audio_query + /synthesis を 2 段で呼んで WAV と mora タイミングを得る
- mora は「文字ごとの経過時間(秒)」のリストに整形する(字幕同期用)
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx


@dataclass
class MoraTiming:
    """VoiceVox の 1 mora(カタカナ)とその再生区間 [start, end] 秒。

    pause_mora(句読点等のポーズ区間)は is_pause=True で区別する。
    """

    text: str
    start: float
    end: float
    is_pause: bool = False


@dataclass
class SynthesisResult:
    audio_wav: bytes
    # text と mora の整合: mora[i].text をつなげたものが text と一致(句読点含む)
    text: str
    moras: list[MoraTiming]


class VoiceVoxClient:
    def __init__(self, base_url: str, timeout: float = 60.0) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def close(self) -> None:
        await self._client.aclose()

    async def speakers(self) -> list[dict]:
        r = await self._client.get("/speakers")
        r.raise_for_status()
        return r.json()

    async def synthesize(self, text: str, speaker: int) -> SynthesisResult:
        # 1) audio_query
        q = await self._client.post("/audio_query", params={"text": text, "speaker": speaker})
        q.raise_for_status()
        query = q.json()

        # 2) synthesis
        s = await self._client.post(
            "/synthesis",
            params={"speaker": speaker},
            json=query,
            headers={"Content-Type": "application/json", "Accept": "audio/wav"},
        )
        s.raise_for_status()
        wav = s.content

        moras = _accent_phrases_to_moras(
            query.get("accent_phrases", []),
            pre_phoneme_length=float(query.get("prePhonemeLength", 0.0)),
            post_phoneme_length=float(query.get("postPhonemeLength", 0.0)),
            speed_scale=float(query.get("speedScale", 1.0)),
        )
        return SynthesisResult(audio_wav=wav, text=text, moras=moras)


def _accent_phrases_to_moras(
    accent_phrases: list[dict],
    pre_phoneme_length: float,
    post_phoneme_length: float,
    speed_scale: float,
) -> list[MoraTiming]:
    """audio_query の accent_phrases から MoraTiming のリストを作る。

    accent_phrases[].moras[] にはそれぞれ consonant_length / vowel_length が入っている。
    pause_mora が accent_phrase 末尾にある場合は句読点のポーズを表す。
    speedScale は全体の時間倍率(大きい=速い)なので 1/speedScale を掛ける。
    """
    scale = 1.0 / speed_scale if speed_scale > 0 else 1.0
    t = pre_phoneme_length * scale
    out: list[MoraTiming] = []

    for phrase in accent_phrases:
        for m in phrase.get("moras", []):
            c = float(m.get("consonant_length") or 0.0) * scale
            v = float(m.get("vowel_length") or 0.0) * scale
            dur = c + v
            # text は mora の「text」を使う(カタカナ 1 文字 or 拗音 2 文字)
            out.append(
                MoraTiming(text=m.get("text", ""), start=t, end=t + dur, is_pause=False)
            )
            t += dur
        pause = phrase.get("pause_mora")
        if pause is not None:
            v = float(pause.get("vowel_length") or 0.0) * scale
            # 句読点のポーズ。text は空 ("" または "、/。") になることが多い。
            out.append(
                MoraTiming(text=pause.get("text", "") or "", start=t, end=t + v, is_pause=True)
            )
            t += v

    # 末尾ポーズは時刻だけ進める(字幕には出さない)
    _ = post_phoneme_length  # 使わないが API 上の情報として残す
    return out
