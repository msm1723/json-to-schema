import copy
import math

import pytest
from jsonschema import Draft202012Validator

from json_to_schema import generate_schema
from json_to_schema.generator import SCHEMA_URI


def checked(examples, **options):
    schema = generate_schema(examples, **options)
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    for example in examples:
        validator.validate(example)
    return schema


@pytest.mark.parametrize(('value', 'kind'), [
    ('text', 'string'), (12, 'integer'), (1.5, 'number'),
    (True, 'boolean'), (False, 'boolean'), (None, 'null'),
    ({}, 'object'), ([], 'array'),
])
def test_all_json_types(value, kind):
    schema = checked([value])
    assert schema['type'] == kind
    assert schema['$schema'] == SCHEMA_URI
    assert schema['examples'] == [value]
    assert '$id' not in schema


@pytest.mark.parametrize(('values', 'constraint'), [
    ([1], 'exclusiveMinimum'), ([1.5], 'exclusiveMinimum'),
    ([-1], 'exclusiveMaximum'), ([-1.5], 'exclusiveMaximum'),
    ([0], None), ([0.0], None), ([-0.0], None),
    ([1, 2.5], 'exclusiveMinimum'), ([-1, -2.5], 'exclusiveMaximum'),
    ([-1, 2.5], None), ([0, 1], None), ([0, -1.5], None),
])
def test_number_signs(values, constraint):
    schema = checked(values)
    for keyword in ['exclusiveMinimum', 'exclusiveMaximum']:
        if keyword == constraint:
            assert schema[keyword] == 0
        else:
            assert keyword not in schema
    if constraint:
        validator = Draft202012Validator(schema)
        assert not validator.is_valid(0)
        assert not validator.is_valid(-1 if constraint == 'exclusiveMinimum' else 1)


def test_no_number_sign_recursively():
    schema = checked([{'n': -2, 'nested': {'n': 3}, 'items': [1.5, 4]}], number_sign=False)
    assert schema['properties']['n'] == {'type': 'integer'}
    assert schema['properties']['nested']['properties']['n'] == {'type': 'integer'}
    assert schema['properties']['items']['items'] == {'type': 'number'}
    Draft202012Validator(schema).validate({'n': 0, 'nested': {'n': -1}, 'items': [-2.5]})


def test_boolean_is_not_a_number():
    schema = checked([[True, 2, False]])
    assert schema['items'] == {'type': ['boolean', 'integer'], 'exclusiveMinimum': 0}
    assert not Draft202012Validator(schema).is_valid([0])
    assert checked([True])['type'] == 'boolean'
    assert 'exclusiveMinimum' not in checked([True])


def test_objects_merge_preserving_property_order():
    examples = [
        {'id': 1, 'name': 'Alice', 'email': 'alice@example.com'},
        {'id': 2, 'name': 'Bob', 'active': True},
    ]
    schema = checked(examples)
    assert list(schema['properties']) == ['id', 'name', 'email', 'active']
    assert schema['required'] == ['id', 'name']
    assert schema['properties']['email'] == {'type': 'string'}
    assert schema['additionalProperties'] is False
    assert checked([examples[0], examples[0]]) == checked([examples[0]])


def test_nested_optional_fields_and_arrays():
    examples = [
        {'user': {'id': 1, 'name': 'Alice'}, 'users': [{'id': 1, 'name': 'A'}, {'id': 2}]},
        {'user': {'id': 3, 'active': True}, 'users': [{'id': 3, 'active': True}]},
    ]
    schema = checked(examples)
    for sub in [schema['properties']['user'], schema['properties']['users']['items']]:
        assert sub['required'] == ['id']
        assert list(sub['properties']) == ['id', 'name', 'active']
        assert sub['additionalProperties'] is False


def test_empty_observations():
    assert checked([[], []])['items'] == {}
    assert checked([[], [2]])['items'] == {'type': 'integer', 'exclusiveMinimum': 0}
    assert 'required' not in checked([{}, {'id': 1}])
    assert 'required' not in checked([[{}, {'id': 1}]])['items']
    empty = checked([{}])
    assert empty['properties'] == {}
    assert empty['additionalProperties'] is False
    assert 'required' not in empty


def test_nested_empty_arrays_and_mixed_signs():
    schema = checked([{'a': [[], [1, 2]]}, {'a': [[0, -2.5]]}])
    assert schema['properties']['a']['items']['items'] == {'type': 'number'}


def test_nullable_and_heterogeneous_structural_unions():
    examples = [
        {'v': 10, 'items': [{'id': 1}, None, [1, 2], 'text']},
        {'v': None, 'items': [{'id': 2, 'name': 'B'}, [0.5], False]},
    ]
    schema = checked(examples)
    assert schema['properties']['v'] == {'type': ['integer', 'null'], 'exclusiveMinimum': 0}
    items = schema['properties']['items']['items']
    assert items['type'] == ['object', 'null', 'array', 'string', 'boolean']
    assert items['required'] == ['id']
    assert items['items'] == {'type': 'number', 'exclusiveMinimum': 0}
    validator = Draft202012Validator(schema)
    assert not validator.is_valid({'v': 0, 'items': []})
    assert not validator.is_valid({'v': None, 'items': [{'name': 'missing id'}]})
    assert not validator.is_valid({'v': None, 'items': [[-1]]})
    assert not validator.is_valid({'v': None, 'items': [1]})


def test_number_merging():
    assert checked([1, 2.5])['type'] == 'number'
    assert checked([1.0, 2])['type'] == 'number'
    schema = checked([[1, 2.5, 'x', None]])
    assert schema['items']['type'] == ['number', 'string', 'null']


@pytest.mark.parametrize('examples', [[{}, []], [True, 1], [None, 'x'], [1, '1']])
def test_incompatible_roots(examples):
    with pytest.raises(ValueError, match='root JSON types'):
        generate_schema(examples)


def test_recursive_strictness_options():
    example = {'nested': {'id': 1}, 'items': [{'name': 'A'}]}
    strict = checked([example])
    validator = Draft202012Validator(strict)
    for invalid in [{}, {**example, 'extra': 1}, {**example, 'nested': {}},
                    {**example, 'items': [{'name': 'A', 'extra': 1}]}]:
        assert not validator.is_valid(invalid)
    relaxed = checked([example], required=False, allow_additional_properties=True)
    for obj in [relaxed, relaxed['properties']['nested'], relaxed['properties']['items']['items']]:
        assert 'required' not in obj
        assert obj['additionalProperties'] is True
    validator = Draft202012Validator(relaxed)
    validator.validate({})
    validator.validate({'nested': {'extra': 1}, 'items': [{}], 'extra': True})


@pytest.mark.parametrize('value', ['POST', 3, 1.5, True, None, {'a': [False, None]}, [1, 'x']])
def test_constants_of_all_types(value):
    schema = checked([{'field': value}, {'field': copy.deepcopy(value)}], constant_fields=['field'])
    assert schema['properties']['field'] == {'const': value}
    assert not Draft202012Validator(schema).is_valid({'field': 'different'})


def test_constants_use_json_equality():
    checked([{'v': {'a': 1, 'b': 2}}, {'v': {'b': 2, 'a': 1.0}}], constant_fields=['v'])
    for values in [[True, 1], [False, 0], [[True], [1]], [{'a': True}, {'a': 1}]]:
        with pytest.raises(ValueError, match='Conflicting values'):
            generate_schema([{'v': value} for value in values], constant_fields=['v'])


@pytest.mark.parametrize('examples', [[{}, {'v': 1}], [{'v': 1}, {}], [1], [None]])
def test_missing_constants(examples):
    with pytest.raises(ValueError, match="Constant field 'v' is missing"):
        generate_schema(examples, constant_fields=['v'])


def test_constants_are_explicit_and_top_level_only():
    example = {'method': 'POST', 'url': '/', 'type': 'x', 'scheme': 'https',
               'query_string': '', 'nested': {'method': 'GET'}, 'a.b': 3}
    schema = checked([example], constant_fields=['method', 'a.b'])
    assert schema['properties']['method'] == {'const': 'POST'}
    assert schema['properties']['a.b'] == {'const': 3}
    assert schema['properties']['nested']['properties']['method'] == {'type': 'string'}
    for key in ['url', 'type', 'scheme', 'query_string']:
        assert schema['properties'][key] == {'type': 'string'}
    with pytest.raises(ValueError, match='missing'):
        generate_schema([example], constant_fields=['nested.method'])


def test_examples_deduplicate_without_mutating_sources():
    examples = [{'a': 1, 'b': [True]}, {'b': [True], 'a': 1},
                {'a': True, 'b': [True]}, {'a': 1, 'b': [1]}]
    original = copy.deepcopy(examples)
    schema = checked(examples)
    assert schema['examples'] == [examples[0], examples[2], examples[3]]
    assert examples == original
    assert 'examples' not in schema['properties']['a']
    assert 'examples' not in checked(examples, include_examples=False)


def test_metadata_and_no_unwanted_inference():
    schema = checked([{'email': 'a@example.com', 'date': '2026-11-01'}],
                     title='A title', schema_id='https://example.com/schema')
    assert list(schema)[:3] == ['$schema', '$id', 'title']
    assert schema['title'] == 'A title'
    assert schema['$id'] == 'https://example.com/schema'
    assert schema['properties'] == {'email': {'type': 'string'}, 'date': {'type': 'string'}}


@pytest.mark.parametrize('schema_id', [
    'https://example.com/schema#section',
    'https://example.com/schema#/properties/id',
    'https://example.com/schema##',
])
def test_schema_id_rejects_nonempty_fragments(schema_id):
    with pytest.raises(ValueError, match='non-empty fragment'):
        generate_schema([{}], schema_id=schema_id)


@pytest.mark.parametrize('schema_id', [
    'https://example.com/schema#', 'https://example.com/schema%23section', 'urn:test:example',
])
def test_schema_id_preserves_allowed_identifiers(schema_id):
    assert checked([{}], schema_id=schema_id)['$id'] == schema_id


@pytest.mark.parametrize('examples', [[], [math.nan], [math.inf], [{'x': -math.inf}],
                                     [{'x': (1, 2)}], [{1: 'value'}]])
def test_invalid_python_api_inputs(examples):
    with pytest.raises(ValueError):
        generate_schema(examples)


def test_every_nested_type_combination_accepts_sources():
    # Exercise all pairs and triples, including empty structural observations.
    from itertools import combinations_with_replacement

    values = [None, True, False, 0, 1, -2, 0.5, 'x', {}, {'a': 1}, [], [1, None]]
    for size in [2, 3]:
        for combination in combinations_with_replacement(values, size):
            checked([{'value': value} for value in combination])
