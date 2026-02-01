"""Auth schemas."""

from pydantic import BaseModel


class TokenRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    key: str


class SetupRequest(BaseModel):
    username: str
    password: str


class SetupStatusResponse(BaseModel):
    needs_setup: bool


class MeResponse(BaseModel):
    username: str
