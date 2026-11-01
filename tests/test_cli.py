import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from jsonschema import Draft202012Validator

from json_to_schema import cli


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    return path


def read_schema(path):
    schema = json.loads(path.read_text(encoding='utf-8'))
    Draft202012Validator.check_schema(schema)
    for value in schema.get('examples', []):
        Draft202012Validator(schema).validate(value)
    return schema


def fail(args, capsys, message):
    with pytest.raises(SystemExit) as exc:
        cli.main([str(arg) for arg in args])
    assert exc.value.code == 2
    stderr = capsys.readouterr().err
    assert message in stderr
    assert 'Traceback' not in stderr
    return stderr


def test_single_input_naming_and_formatting(tmp_path):
    source = write_json(tmp_path / 'response.json', {'name': 'Алиса', 'id': 1})
    original = source.read_bytes()
    assert cli.main([str(source)]) == 0
    output = source.with_suffix('.schema.json')
    schema = read_schema(output)
    assert schema['title'] == 'response'
    assert schema['examples'] == [{'name': 'Алиса', 'id': 1}]
    assert source.read_bytes() == original
    text = output.read_text(encoding='utf-8')
    assert text == json.dumps(schema, indent=4, ensure_ascii=False) + '\n'
    assert 'Алиса' in text
    assert cli.main([str(source), '--force']) == 0
    assert output.read_text(encoding='utf-8') == text


def test_multiple_files_and_output_parents(tmp_path):
    first = write_json(tmp_path / 'z.json', {'id': 1, 'name': 'A'})
    second = write_json(tmp_path / 'a.json', {'id': 2, 'active': True})
    output = tmp_path / 'schemas' / 'nested' / 'merged.json'
    cli.main([str(first), str(second), '-o', str(output)])
    schema = read_schema(output)
    assert schema['title'] == 'z'
    assert schema['required'] == ['id']
    assert [value['id'] for value in schema['examples']] == [1, 2]


def test_directory_order_and_nonrecursive_filtering(tmp_path):
    inputs = tmp_path / 'inputs'
    inputs.mkdir()
    write_json(inputs / 'z.json', {'id': 2})
    write_json(inputs / 'a.json', {'id': 1})
    (inputs / 'ignore.txt').write_text('invalid')
    (inputs / 'ignore.JSON').write_text('invalid')
    nested = inputs / 'nested.json'
    nested.mkdir()
    (nested / 'bad.json').write_text('invalid')
    output = tmp_path / 'out.json'
    cli.main([str(inputs), '-o', str(output)])
    schema = read_schema(output)
    assert schema['title'] == 'a'
    assert schema['examples'] == [{'id': 1}, {'id': 2}]


def test_cli_options(tmp_path):
    source = write_json(tmp_path / 'request.json',
                        {'method': 'POST', 'url': '/', 'n': 1, 'nested': {'id': 2}})
    output = tmp_path / 'schema.json'
    cli.main([str(source), '-o', str(output), '--title', 'Custom', '--id', 'urn:test:request',
              '--const', 'method', 'url', '--no-examples', '--no-required',
              '--no-number-sign', '--allow-additional-properties'])
    schema = read_schema(output)
    assert schema['title'] == 'Custom'
    assert schema['$id'] == 'urn:test:request'
    assert schema['properties']['method'] == {'const': 'POST'}
    assert schema['properties']['url'] == {'const': '/'}
    assert schema['properties']['n'] == {'type': 'integer'}
    assert schema['properties']['nested']['properties']['id'] == {'type': 'integer'}
    assert 'required' not in schema
    assert 'required' not in schema['properties']['nested']
    assert 'examples' not in schema
    assert schema['additionalProperties'] is True
    assert schema['properties']['nested']['additionalProperties'] is True


def test_existing_output_protection_and_force(tmp_path, capsys):
    source = write_json(tmp_path / 'input.json', {'x': 1})
    output = tmp_path / 'input.schema.json'
    output.write_text('original contents')
    fail([source], capsys, '--force')
    assert output.read_text() == 'original contents'
    cli.main([str(source), '-f'])
    assert read_schema(output)['examples'] == [{'x': 1}]
    assert not list(tmp_path.glob('.*.tmp'))


@pytest.mark.parametrize('bad_json', ['{', '', 'NaN', 'Infinity', '-Infinity', '1e400', '{"a": NaN}'])
def test_invalid_json_preserves_output(tmp_path, capsys, bad_json):
    source = tmp_path / 'bad.json'
    source.write_text(bad_json)
    output = tmp_path / 'bad.schema.json'
    output.write_text('preserved')
    fail([source, '--force'], capsys, str(source))
    assert output.read_text() == 'preserved'


def test_invalid_utf8(tmp_path, capsys):
    source = tmp_path / 'bad.json'
    source.write_bytes(b'\xff')
    fail([source], capsys, str(source))


@pytest.mark.parametrize('number', ['1e-400', '-1E-400', '2e-324', '0.' + '0' * 330 + '1'])
@pytest.mark.parametrize('existing_output', [False, True])
def test_underflow_is_rejected_without_changing_output(tmp_path, capsys, number, existing_output):
    source = tmp_path / 'tiny.json'
    source.write_text('{"value": [' + number + ']}')
    original = source.read_bytes()
    output = tmp_path / 'tiny.schema.json'
    if existing_output:
        output.write_text('preserved')
    error = fail([source, '--const', 'value', '--force'], capsys, 'underflows')
    assert str(source) in error
    assert source.read_bytes() == original
    if existing_output:
        assert output.read_text() == 'preserved'
    else:
        assert not output.exists()
    assert not list(tmp_path.glob('.*.tmp'))


@pytest.mark.parametrize(('number', 'expected'), [
    ('0e-400', 0.0), ('-0.0E-400', -0.0), ('0e400', 0.0),
    ('5e-324', 5e-324), ('-5e-324', -5e-324),
])
def test_zero_and_representable_small_numbers_are_accepted(tmp_path, number, expected):
    source = tmp_path / 'small.json'
    source.write_text('{"value": ' + number + '}')
    assert cli.main([str(source), '--const', 'value']) == 0
    schema = read_schema(tmp_path / 'small.schema.json')
    assert schema['properties']['value'] == {'const': expected}
    assert schema['examples'] == [{'value': expected}]


def test_invalid_schema_id_preserves_output(tmp_path, capsys):
    source = write_json(tmp_path / 'input.json', {'id': 1})
    output = tmp_path / 'input.schema.json'
    output.write_text('preserved')
    fail([source, '--id', 'https://example.com/schema#section', '--force'],
         capsys, 'non-empty fragment')
    assert output.read_text() == 'preserved'


def test_missing_file(tmp_path, capsys):
    source = tmp_path / 'missing.json'
    fail([source], capsys, f'Input does not exist: {source}')


def test_empty_directory(tmp_path, capsys):
    fail([tmp_path, '-o', tmp_path / 'out.json'], capsys, 'No JSON files')


def test_missing_output_and_mixed_directory_inputs(tmp_path, capsys):
    first = write_json(tmp_path / 'a.json', {})
    second = write_json(tmp_path / 'b.json', {})
    fail([first, second], capsys, '--output is required')
    fail([tmp_path], capsys, '--output is required')
    fail([tmp_path, first, '-o', tmp_path / 'out.json'], capsys, 'Do not mix')
    fail([tmp_path, tmp_path, '-o', tmp_path / 'out.json'], capsys, 'Do not mix')


def test_unsupported_input_path(tmp_path, capsys):
    fifo = tmp_path / 'pipe.json'
    os.mkfifo(fifo)
    fail([fifo], capsys, 'Unsupported input path')


@pytest.mark.parametrize(('second_value', 'flags', 'message'), [
    ([], [], 'root JSON types'),
    ({}, ['--const', 'method'], 'missing from example 2'),
    ({'method': 'GET'}, ['--const', 'method'], 'Conflicting values'),
])
def test_merge_errors_include_filenames(tmp_path, capsys, second_value, flags, message):
    first = write_json(tmp_path / 'a.json', {'method': 'POST'})
    second = write_json(tmp_path / 'b.json', second_value)
    output = tmp_path / 'out.json'
    output.write_text('preserved')
    error = fail([first, second, '-o', output, '--force', *flags], capsys, message)
    assert str(first) in error and str(second) in error
    assert output.read_text() == 'preserved'


def test_output_write_failure(tmp_path, capsys):
    source = write_json(tmp_path / 'a.json', {})
    blocker = tmp_path / 'blocker'
    blocker.write_text('preserved')
    fail([source, '-o', blocker / 'out.json'], capsys, 'Cannot write output')
    assert blocker.read_text() == 'preserved'


def test_failed_atomic_replace_preserves_output(tmp_path, capsys, monkeypatch):
    source = write_json(tmp_path / 'a.json', {})
    output = tmp_path / 'out.json'
    output.write_text('preserved')

    def denied(*args):
        raise PermissionError('simulated replacement failure')

    monkeypatch.setattr(Path, 'replace', denied)
    fail([source, '-o', output, '--force'], capsys, 'Cannot write output')
    assert output.read_text() == 'preserved'
    assert not list(tmp_path.glob('.*.tmp'))


def test_dangling_output_symlink_is_protected(tmp_path, capsys):
    source = write_json(tmp_path / 'a.json', {})
    output = tmp_path / 'a.schema.json'
    target = tmp_path / 'absent.json'
    output.symlink_to(target)
    fail([source], capsys, '--force')
    assert output.is_symlink()
    assert not target.exists()


def test_help(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(['--help'])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    for text in ['--output', '--title', '--id', '--no-examples', '--const',
                 '--no-number-sign', '--allow-additional-properties', '--no-required',
                 '--force', '--help', 'Examples:', 'merge recursively',
                 'exclusiveMinimum', 'NAME.schema.json']:
        assert text in output


def test_installed_entrypoint_from_unrelated_directory(tmp_path):
    source = write_json(tmp_path / 'response.json', {'id': 1})
    executable = Path(sys.executable).parent / 'json-to-schema'
    environment = {key: value for key, value in os.environ.items() if key != 'PYTHONPATH'}
    result = subprocess.run([str(executable), source.name], cwd=tmp_path,
                            env=environment, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert read_schema(tmp_path / 'response.schema.json')['examples'] == [{'id': 1}]
