"""Command-line interface and atomic UTF-8 file output."""

import argparse
import json
import math
import tempfile
from collections.abc import Sequence
from pathlib import Path

from .generator import JSONValue, generate_schema


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='json-to-schema',
        description='Generate readable JSON Schema Draft 2020-12 from JSON examples.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''Examples:
  json-to-schema response.json
  json-to-schema response.json -o schemas/response.schema.json
  json-to-schema response1.json response2.json -o response.schema.json
  json-to-schema examples/ -o response.schema.json
  json-to-schema request.json --const method url
  json-to-schema response.json --no-number-sign --no-required
  json-to-schema response.json --allow-additional-properties

Objects and array items merge recursively. A property is required only when
present in every observed object at that location. Unknown properties are
rejected by default; relax these rules with --no-required and
--allow-additional-properties.

Numbers observed only as positive use exclusiveMinimum: 0; only negative use
exclusiveMaximum: 0. Mixed signs or any zero remove sign constraints.
Use --no-number-sign to disable this inference.

--const selects literal top-level property names (no nested paths). Each must
exist with the same JSON value in every input. No constants are inferred.

One file defaults to NAME.schema.json beside NAME.json. Multiple files or a
directory require --output. Directories include only immediate .json files,
in alphabetical order. Directory and explicit file inputs cannot be mixed.
The title defaults to the first input filename stem. Original examples are
saved once each at the schema root unless --no-examples is supplied.''',
    )
    parser.add_argument('inputs', metavar='INPUT', nargs='+', type=Path,
                        help='JSON files, or one directory of JSON files')
    parser.add_argument('-o', '--output', metavar='PATH', type=Path, help='output schema path')
    parser.add_argument('--title', metavar='TEXT', help='override the filename-based title')
    parser.add_argument('--id', dest='schema_id', metavar='URI', help='include an explicit $id')
    parser.add_argument('--no-examples', action='store_true', help='omit original JSON examples')
    parser.add_argument('--const', dest='constant_fields', metavar='FIELD', nargs='+',
                        action='extend', default=[], help='require identical top-level field values')
    parser.add_argument('--no-number-sign', action='store_true', help='omit numeric sign constraints')
    parser.add_argument('--allow-additional-properties', action='store_true',
                        help='allow unknown properties in all objects')
    parser.add_argument('--no-required', action='store_true', help='omit all required constraints')
    parser.add_argument('-f', '--force', action='store_true', help='overwrite existing output')
    return parser


def _input_files(inputs: Sequence[Path], output: Path | None) -> list[Path]:
    for path in inputs:
        if not path.exists():
            raise ValueError(f'Input does not exist: {path}')
        if not path.is_file() and not path.is_dir():
            raise ValueError(f'Unsupported input path: {path}')
    directories = [path for path in inputs if path.is_dir()]
    if directories:
        if len(inputs) != 1:
            raise ValueError('Do not mix directory and file inputs or supply multiple directories')
        files = sorted(
            (path for path in directories[0].iterdir() if path.is_file() and path.suffix == '.json'),
            key=lambda path: path.name,
        )
        if not files:
            raise ValueError(f'No JSON files found in directory: {directories[0]}')
    else:
        files = list(inputs)
    if output is None and (directories or len(inputs) > 1):
        raise ValueError('--output is required for multiple files or directory input')
    return files


def _reject_constant(value: str) -> JSONValue:
    raise ValueError(f'{value} is not a valid JSON number')


def _parse_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f'JSON number is outside the supported finite range: {value}')
    if number == 0:
        # Distinguish an actual zero from a nonzero value lost to underflow.
        significand = value.lower().partition('e')[0]
        if any(digit in '123456789' for digit in significand):
            raise ValueError(f'JSON number underflows the supported floating-point range: {value}')
    return number


def _read_json(path: Path) -> JSONValue:
    try:
        return json.loads(path.read_text(encoding='utf-8'),
                          parse_constant=_reject_constant, parse_float=_parse_float)
    except (ValueError, OSError, RecursionError) as exc:
        raise ValueError(f'Cannot read JSON from {path}: {exc}') from exc


def _write_schema(path: Path, content: str, *, force: bool) -> None:
    """Stage the complete file, then publish without truncating existing output."""
    temporary: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode='w', encoding='utf-8', newline='\n', dir=path.parent,
            prefix=f'.{path.name}.', suffix='.tmp', delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        if force:
            temporary.replace(path)
        else:
            # Hard-link creation fails atomically if any output entry exists,
            # including a dangling symlink or a concurrently created file.
            try:
                path.hardlink_to(temporary)
            except FileExistsError as exc:
                raise ValueError(f'Output already exists: {path}; use --force to overwrite') from exc
    except OSError as exc:
        raise ValueError(f'Cannot write output {path}: {exc}') from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        files = _input_files(args.inputs, args.output)
        examples = [_read_json(path) for path in files]
        try:
            schema = generate_schema(
                examples,
                title=args.title if args.title is not None else files[0].stem,
                schema_id=args.schema_id,
                include_examples=not args.no_examples,
                constant_fields=args.constant_fields,
                number_sign=not args.no_number_sign,
                required=not args.no_required,
                allow_additional_properties=args.allow_additional_properties,
            )
        except ValueError as exc:
            raise ValueError(f'{exc} (inputs: {", ".join(str(path) for path in files)})') from exc
        content = json.dumps(schema, indent=4, ensure_ascii=False, allow_nan=False) + '\n'
        output = args.output if args.output is not None else files[0].with_suffix('.schema.json')
        _write_schema(output, content, force=args.force)
    except (ValueError, OSError, RecursionError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
