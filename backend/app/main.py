"""FastAPI エントリ。

- 起動時に corpus/<name>/*.txt をフォルダごとにまとめて MarkovModel を構築する。
  1 フォルダ = 1 コーパス = 1 マルコフチェイン。
- /api/corpora, /api/speakers, /api/sentence, /api/reset を提供
- frontend/dist が存在するときは / 配下で静的配信
"""

from __future__ import annotations

import base64
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.markov import MarkovModel
from app.preprocess import clean_aozora
from app.voicevox import VoiceVoxClient

log = logging.getLogger("vvmc")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

CORPUS_DIR = Path(os.environ.get("VVMC_CORPUS_DIR", "/corpus"))
VOICEVOX_URL = os.environ.get("VVMC_VOICEVOX_URL", "http://voicevox:50021")
FRONTEND_DIST = Path(os.environ.get("VVMC_FRONTEND_DIST", "/frontend_dist"))


def _read_text_any_encoding(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        # 青空文庫の .txt は Shift_JIS(CP932) 同梱もある
        return p.read_text(encoding="cp932", errors="replace")


def _load_corpora(corpus_dir: Path) -> dict[str, MarkovModel]:
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
            cleaned = clean_aozora(_read_text_any_encoding(txt))
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    corpora = _load_corpora(CORPUS_DIR)
    if not corpora:
        log.warning(
            "no corpora loaded — /api/corpora will return [] "
            "until a subdirectory with .txt files exists under %s",
            CORPUS_DIR,
        )
    vv = VoiceVoxClient(base_url=VOICEVOX_URL)

    app.state.corpora = corpora
    app.state.vv = vv
    try:
        yield
    finally:
        await vv.close()


app = FastAPI(title="vvmc", lifespan=lifespan)


class SentenceRequest(BaseModel):
    speaker_id: int
    corpus_name: str


class ResetRequest(BaseModel):
    # 省略した場合は全コーパスの乱数状態を初期化する
    corpus_name: str | None = None


class MoraJSON(BaseModel):
    text: str
    start: float
    end: float


class SentenceResponse(BaseModel):
    text: str
    audio: str  # base64-encoded WAV
    mora: list[MoraJSON]


def _get_model(corpus_name: str) -> MarkovModel:
    corpora: dict[str, MarkovModel] = app.state.corpora
    model = corpora.get(corpus_name)
    if model is None:
        raise HTTPException(status_code=404, detail=f"corpus not found: {corpus_name}")
    return model


@app.get("/api/corpora")
async def list_corpora() -> list[str]:
    corpora: dict[str, MarkovModel] = app.state.corpora
    return sorted(corpora.keys())


@app.get("/api/speakers")
async def get_speakers():
    vv: VoiceVoxClient = app.state.vv
    try:
        return await vv.speakers()
    except Exception as e:  # noqa: BLE001
        log.exception("speakers fetch failed")
        raise HTTPException(status_code=502, detail=f"voicevox unreachable: {e}") from e


@app.post("/api/sentence", response_model=SentenceResponse)
async def post_sentence(req: SentenceRequest) -> SentenceResponse:
    model = _get_model(req.corpus_name)
    vv: VoiceVoxClient = app.state.vv

    text = ""
    # 稀に空文字を引く可能性があるのでリトライ
    for _ in range(5):
        text = model.generate_sentence()
        if text:
            break
    if not text:
        raise HTTPException(status_code=500, detail="failed to generate a sentence")

    try:
        result = await vv.synthesize(text, speaker=req.speaker_id)
    except Exception as e:  # noqa: BLE001
        log.exception("synthesis failed")
        raise HTTPException(status_code=502, detail=f"voicevox synthesis failed: {e}") from e

    return SentenceResponse(
        text=result.text,
        audio=base64.b64encode(result.audio_wav).decode("ascii"),
        mora=[MoraJSON(text=m.text, start=m.start, end=m.end) for m in result.moras],
    )


@app.post("/api/reset")
async def post_reset(req: ResetRequest):
    corpora: dict[str, MarkovModel] = app.state.corpora
    if req.corpus_name is None:
        for m in corpora.values():
            m.reset_state()
    else:
        _get_model(req.corpus_name).reset_state()
    return JSONResponse({"ok": True})


@app.get("/api/health")
async def health():
    corpora: dict[str, MarkovModel] = app.state.corpora
    return {"ok": True, "corpora": sorted(corpora.keys())}


# --- 静的配信 (frontend/dist が存在するときだけ有効) ----------------------
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="static")
    log.info("serving frontend from %s", FRONTEND_DIST)
else:
    log.info("no frontend dist at %s — API only", FRONTEND_DIST)
