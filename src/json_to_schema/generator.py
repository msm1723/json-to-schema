"""Pure, recursive inference from complete JSON observations."""

import math
from collections.abc import Sequence

type JSONValue = None | bool | int | float | str | list[JSONValue] | dict[str, JSONValue]
type Schema = dict[str, JSONValue]

SCHEMA_URI = 'https://json-schema.org/draft/2020-12/schema'


def _json_type(value: JSONValue) -> str:
    if value is None:
        return 'null'
    if isinstance(value, bool):
        return 'boolean'
    if isinstance(value, int):
        return 'integer'
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError('Non-finite numbers are not valid JSON')
        return 'number'
    if isinstance(value, str):
        return 'string'
    if isinstance(value, dict):
        return 'object'
    if isinstance(value, list):
        return 'array'
    raise ValueError(f'Unsupported JSON value: {type(value).__name__}')


def _validate_json(value: JSONValue) -> None:
    _json_type(value)
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise ValueError('JSON object keys must be strings')
            _validate_json(child)
    elif isinstance(value, list):
        for child in value:
            _validate_json(child)


def _json_equal(left: JSONValue, right: JSONValue) -> bool:
    """Compare JSON values without conflating booleans and numbers."""
    left_type, right_type = _json_type(left), _json_type(right)
    if left_type != right_type:
        return {left_type, right_type} == {'integer', 'number'} and left == right
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(
            _json_equal(value, right[key]) for key, value in left.items()
        )
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            _json_equal(a, b) for a, b in zip(left, right)
        )
    return left == right


def _infer(
    values: Sequence[JSONValue],
    *,
    number_sign: bool,
    required: bool,
    allow_additional_properties: bool,
) -> Schema:
    if not values:
        return {}

    groups: dict[str, list[JSONValue]] = {}
    for value in values:
        kind = _json_type(value)
        # Integers and floating-point numbers belong to one inference group.
        groups.setdefault('number' if kind == 'integer' else kind, []).append(value)

    types = [
        'integer' if kind == 'number' and all(isinstance(v, int) for v in group) else kind
        for kind, group in groups.items()
    ]
    schema: Schema = {'type': types[0] if len(types) == 1 else types}
    options = {
        'number_sign': number_sign,
        'required': required,
        'allow_additional_properties': allow_additional_properties,
    }

    if number_sign and (numbers := groups.get('number')):
        if all(value > 0 for value in numbers):
            schema['exclusiveMinimum'] = 0
        elif all(value < 0 for value in numbers):
            schema['exclusiveMaximum'] = 0

    if objects := groups.get('object'):
        properties: dict[str, list[JSONValue]] = {}
        for obj in objects:
            for name, value in obj.items():
                properties.setdefault(name, []).append(value)
        schema['properties'] = {
            name: _infer(observed, **options) for name, observed in properties.items()
        }
        common = [name for name, observed in properties.items() if len(observed) == len(objects)]
        if required and common:
            schema['required'] = common
        schema['additionalProperties'] = allow_additional_properties

    if arrays := groups.get('array'):
        schema['items'] = _infer([item for array in arrays for item in array], **options)

    # Type-specific keywords apply only to their corresponding instance types,
    # so even structural unions remain readable without anyOf wrappers.
    return schema


def generate_schema(
    examples: Sequence[JSONValue],
    *,
    title: str = 'Generated schema',
    schema_id: str | None = None,
    include_examples: bool = True,
    constant_fields: Sequence[str] = (),
    number_sign: bool = True,
    required: bool = True,
    allow_additional_properties: bool = False,
) -> Schema:
    """Infer one schema, preserving observation order and JSON equality.

    Root integer/number combinations are compatible; other mixed root types
    are rejected. ValueError reports invalid observations or constant fields.
    """
    if not examples:
        raise ValueError('At least one JSON example is required')
    for value in examples:
        _validate_json(value)
    root_types = list(dict.fromkeys(_json_type(value) for value in examples))
    if len(root_types) > 1 and not set(root_types) <= {'integer', 'number'}:
        raise ValueError(f'Incompatible root JSON types: {", ".join(root_types)}')

    constants: dict[str, JSONValue] = {}
    for field in constant_fields:
        for index, value in enumerate(examples, start=1):
            if not isinstance(value, dict) or field not in value:
                raise ValueError(f'Constant field {field!r} is missing from example {index}')
            if field in constants and not _json_equal(constants[field], value[field]):
                raise ValueError(f'Conflicting values for constant field {field!r} in example {index}')
            constants.setdefault(field, value[field])

    schema: Schema = {'$schema': SCHEMA_URI}
    if schema_id is not None:
        if schema_id.partition('#')[2]:
            raise ValueError('$id must not contain a non-empty fragment in Draft 2020-12')
        schema['$id'] = schema_id
    schema['title'] = title
    schema.update(_infer(
        examples,
        number_sign=number_sign,
        required=required,
        allow_additional_properties=allow_additional_properties,
    ))
    for field, value in constants.items():
        schema['properties'][field] = {'const': value}

    if include_examples:
        unique: list[JSONValue] = []
        for value in examples:
            if not any(_json_equal(value, previous) for previous in unique):
                unique.append(value)
        schema['examples'] = unique
    return schema
