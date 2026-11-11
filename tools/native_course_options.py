"""Явный schema overlay Community fork; официальный upstream остаётся неизменным."""
from json_boundary import JSONObject, json_object


def integer_manual_points_schema(schema: JSONObject) -> JSONObject:
    overlay = json_object(schema)
    properties = overlay.get('properties')
    if not isinstance(properties, dict):
        raise ValueError('Native course schema properties missing')
    options = properties.get('options')
    if not isinstance(options, dict):
        raise ValueError('Native course options schema missing')
    fields = options.get('properties')
    if not isinstance(fields, dict):
        raise ValueError('Native course options properties missing')
    fields['integerManualPoints'] = {'type': 'boolean'}
    return overlay
