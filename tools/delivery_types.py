"""Типы существующих delivery bindings после закрытой проверки полей."""

from typing import Literal, NotRequired, TypeAlias, TypedDict

GradingMethod: TypeAlias = Literal["manual", "mixed", "external"]
NativeControl: TypeAlias = tuple[str, dict[str, str | None]]


class MatchingOption(TypedDict):
    anchor: str
    ordinal: int | float


class ResponseSlot(TypedDict):
    name: str
    type: Literal["manual", "numeric", "single-choice", "matching"]
    anchor: str
    labelAnchor: NotRequired[str]
    ordinal: NotRequired[int]
    options: NotRequired[list[MatchingOption]]


class SeedDeclaration(TypedDict):
    schema: str
    archive: str
    manifest: str


class SeedProof(TypedDict):
    initialCommit: str
