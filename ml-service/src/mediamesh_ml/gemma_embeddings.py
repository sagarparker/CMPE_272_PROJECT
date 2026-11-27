"""Gemma client for the API and worker. Inference uses one shared local model."""

import io
import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from mediamesh_ml.contracts import InvalidQuery, ModelIdentity
from mediamesh_ml.embeddings import ClipEngine

GEMMA_ID = ModelIdentity(
    "google/embeddinggemma-2",
    "f9972ac22e696a105c482202646979e33e4b5a1e",
    768,
    "gemma2-rgb768-searchquery-l2-v1",
)
GEMMA_IMAGE_EDGE = 768
GEMMA_IMAGE_BYTES = 4 * 1024 * 1024


class GemmaEngine(ClipEngine):
    @property
    def identity(self) -> ModelIdentity:
        return GEMMA_ID

    def _request(self, path, body=None, content_type="application/json"):
        url = self.settings.gemma_embedding_url.rstrip("/") + path
        request = Request(url, data=body, headers={"Content-Type": content_type})
        with urlopen(request, timeout=60) as response:
            return json.load(response)

    def load(self):
        if self._request("/ready").get("modelVersion") != self.model_version:
            raise OSError("Gemma inference model does not match the configured vector version")

    def encode_text(self, text):
        if not text.strip():
            raise InvalidQuery("Query must not be blank")
        try:
            result = self._request("/text", json.dumps({"text": text}).encode())
        except HTTPError as error:
            if error.code in {400, 422}:
                raise InvalidQuery("Gemma query exceeds the input limits") from None
            raise
        return self._validated_vectors([result["embedding"]], 1)[0]

    def encode_document(self, text):
        result = self._request("/document", json.dumps({"text": text}).encode())
        return self._validated_vectors([result["embedding"]], 1)[0]

    def _encode(self, inputs):
        vectors = []
        for image in inputs:
            image.thumbnail((GEMMA_IMAGE_EDGE, GEMMA_IMAGE_EDGE))
            with io.BytesIO() as buffer:
                image.save(buffer, format="PNG")
                result = self._request("/image", buffer.getvalue(), "image/png")
            vectors.append(result["embedding"])
        return self._validated_vectors(vectors, len(inputs))
