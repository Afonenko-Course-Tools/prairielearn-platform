"""Проверяемая граница JSON для собственных операторских инструментов."""

from typing import TypeAlias, TypeGuard

JSONValue: TypeAlias = (
    "None | bool | int | float | str | list[JSONValue] | dict[str, JSONValue]"
)
JSONObject: TypeAlias = dict[str, JSONValue]


def is_object(value: object) -> TypeGuard[dict[object, object]]:
    return isinstance(value, dict)


def is_list(value: object) -> TypeGuard[list[object]]:
    return isinstance(value, list)


def json_value(value: object) -> JSONValue:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if is_list(value):
        return [json_value(item) for item in value]
    if is_object(value):
        result: JSONObject = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("JSON object keys must be strings")
            result[key] = json_value(item)
        return result
    raise ValueError("Expected a JSON value")


def json_object(value: object) -> JSONObject:
    result = json_value(value)
    if not isinstance(result, dict):
        raise ValueError("Expected a JSON object")
    return result
