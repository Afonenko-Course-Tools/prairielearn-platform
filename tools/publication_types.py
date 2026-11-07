"""Типы опубликованных OCI-ссылок и runtime-профилей."""
from typing import NotRequired, TypedDict
from json_boundary import JSONObject

class ImageReferences(TypedDict):
    java: str
    fish: str
    community: str
    workspace: NotRequired[str]

class RuntimeImage(TypedDict):
    schemaVersion: int
    sourceCommit: str
    version: str
    images: ImageReferences
    deliverySchemaVersion: int
    resultsSchemaVersion: int


class PublishedRegistry(TypedDict):
    schemaVersion: int
    profiles: dict[str, JSONObject]
    workspaceImages: dict[str, dict[str, str]]


