"""Private, single-process inference for the local EmbeddingGemma 2 service."""

import io
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from mediamesh_ml.config import Settings
from mediamesh_ml.contracts import embedding_version
from mediamesh_ml.gemma_embeddings import GEMMA_ID, GEMMA_IMAGE_BYTES, GEMMA_IMAGE_EDGE


class TextInput(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


class DocumentInput(BaseModel):
    text: str = Field(min_length=1, max_length=10000)


def create_app():
    settings = Settings()
    inference_lock = threading.Lock()

    @asynccontextmanager
    async def lifespan(app):
        from sentence_transformers import SentenceTransformer

        app.state.model = SentenceTransformer(
            GEMMA_ID.name,
            revision=GEMMA_ID.revision,
            cache_folder=str(settings.model_cache),
            local_files_only=settings.model_offline,
            trust_remote_code=False,
            config_kwargs={"audio_config": None},
            model_kwargs={"dtype": "float32"},
            device=settings.device,
        )
        yield

    app = FastAPI(lifespan=lifespan)

    def embed(value, prompt_name="SearchQuery"):
        import torch

        with inference_lock:
            vector = app.state.model.encode(
                [value], convert_to_tensor=True, show_progress_bar=False,
                normalize_embeddings=True,
                **({"prompt_name": prompt_name} if isinstance(value, str) else {"prompt": ""}),
            )[0]
        return {"embedding": torch.nn.functional.normalize(vector.float(), dim=0).tolist()}

    @app.get("/ready")
    def ready():
        return {"modelVersion": embedding_version(GEMMA_ID)}

    @app.post("/text")
    def text(body: TextInput):
        return embed(body.text)

    @app.post("/document")
    def document(body: DocumentInput):
        return embed(body.text, "Document")

    def embed_image(payload):
        try:
            with Image.open(io.BytesIO(payload), formats=["PNG"]) as decoded:
                if max(decoded.size) > GEMMA_IMAGE_EDGE:
                    raise HTTPException(400, "Image exceeds the inference dimensions")
                with decoded.convert("RGB") as image:
                    return embed({"image": image})
        except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as error:
            raise HTTPException(400, "Invalid image") from error

    @app.post("/image")
    async def image(request: Request):
        data = bytearray()
        async for chunk in request.stream():
            if len(data) + len(chunk) > GEMMA_IMAGE_BYTES:
                raise HTTPException(413, "Image is too large")
            data.extend(chunk)
        return await run_in_threadpool(embed_image, data)

    return app
