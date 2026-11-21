"""Original internal search contract; public metadata filters belong to Spring Boot."""

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=1000, strict=True)
    limit: int = Field(default=20, ge=1, le=100, strict=True)

    @field_validator("query", mode="before")
    @classmethod
    def strip_query(cls, value):
        return value.strip() if isinstance(value, str) else value


class SearchMatch(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    asset_id: UUID = Field(alias="assetId")
    score: float = Field(allow_inf_nan=False)
    frame_timestamp_seconds: float | None = Field(
        default=None, alias="frameTimestampSeconds", ge=0, allow_inf_nan=False
    )


class SearchResponse(BaseModel):
    matches: list[SearchMatch]


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
