"""FastAPI エントリ。

- 起動時に corpus/*.txt を読んで MarkovModel を構築
- /api/speakers, /api/sentence, /api/reset を提供
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


def _load_corpus(corpus_dir: Path) -> str:
    if not corpus_dir.exists():
        log.warning("corpus dir %s does not exist", corpus_dir)
        return ""
    chunks: list[str] = []
    for p in sorted(corpus_dir.glob("*.txt")):
        try:
            raw = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            # 青空文庫の .txt は Shift_JIS 同梱もある
            raw = p.read_text(encoding="cp932", errors="replace")
        cleaned = clean_aozora(raw)
        log.info("loaded corpus %s (%d chars)", p.name, len(cleaned))
        chunks.append(cleaned)
    return "\n".join(chunks)


@asynccontextmanager
async def lifespan(app: FastAPI):
    model = MarkovModel()
    corpus = _load_corpus(CORPUS_DIR)
    if corpus:
        model.train(corpus)
        log.info("markov model trained: %d head states", len(model._transitions))
    else:
        log.warning("no corpus found — /api/sentence will 503 until text is placed in %s", CORPUS_DIR)
    vv = VoiceVoxClient(base_url=VOICEVOX_URL)

    app.state.model = model
    app.state.vv = vv
    try:
        yield
    finally:
        await vv.close()


app = FastAPI(title="vvmc", lifespan=lifespan)


class SentenceRequest(BaseModel):
    speaker_id: int


class MoraJSON(BaseModel):
    text: str
    start: float
    end: float


class SentenceResponse(BaseModel):
    text: str
    audio: str  # base64-encoded WAV
    mora: list[MoraJSON]


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
    model: MarkovModel = app.state.model
    vv: VoiceVoxClient = app.state.vv
    if not model.is_trained:
        raise HTTPException(status_code=503, detail="markov model not trained (corpus is empty)")

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
async def post_reset():
    model: MarkovModel = app.state.model
    model.reset_state()
    return JSONResponse({"ok": True})


@app.get("/api/health")
async def health():
    model: MarkovModel = app.state.model
    return {"ok": True, "markov_trained": model.is_trained}


# --- 静的配信 (frontend/dist が存在するときだけ有効) ----------------------
if FRONTEND_DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIST), html=True), name="static")
    log.info("serving frontend from %s", FRONTEND_DIST)
else:
    log.info("no frontend dist at %s — API only", FRONTEND_DIST)
