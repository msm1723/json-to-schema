# json-to-schema

Generate readable JSON Schema Draft 2020-12 documents from one or more JSON
examples, particularly for automated API tests. Python 3.14+ is required;
the installed tool has no runtime dependencies.

## Install and update

From this repository, install with [uv](https://docs.astral.sh/uv/):

```bash
uv tool install .
```

The `json-to-schema` command then works from any directory. If uv's tool bin
directory is not on your shell's PATH, run `uv tool update-shell` and restart
your shell. No `PYTHONPATH` or shell wrapper is needed.

To update after changing or pulling the source:

```bash
uv tool install --force .
```

## Usage

```bash
json-to-schema response.json
json-to-schema response.json -o schemas/response.schema.json
json-to-schema response1.json response2.json -o response.schema.json
json-to-schema examples/ -o response.schema.json
json-to-schema request.json --const method url
json-to-schema response.json --title 'API response' --id https://example.com/response.schema.json
json-to-schema response.json --no-number-sign --no-required --allow-additional-properties
json-to-schema response.json --no-examples --force
json-to-schema --help
```

A single file defaults to `response.schema.json` beside `response.json`.
Multiple files and directories require `--output`. Directories contribute only
immediate files ending in `.json`, sorted alphabetically; they cannot be mixed
with explicit file inputs. Explicit files retain command-line order. The title
defaults to the first input filename's stem, or can be set with `--title`.
Missing output directories are created automatically. Existing files require
`--force`; output is staged before publishing so failures do not truncate an
existing schema. Input documents are read completely before output is written.

Given `response.json` containing `{"id": 1, "name": "Alice"}`:

```json
{
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "response",
    "type": "object",
    "properties": {
        "id": {
            "type": "integer",
            "exclusiveMinimum": 0
        },
        "name": {
            "type": "string"
        }
    },
    "required": [
        "id",
        "name"
    ],
    "additionalProperties": false,
    "examples": [
        {
            "id": 1,
            "name": "Alice"
        }
    ]
}
```

## Inference rules

- Objects merge recursively in first-seen property order. A property is required
  only if it appears in every observed object at that location. Empty objects
  count as observations. `--no-required` omits required constraints everywhere.
- Unknown properties are rejected in all inferred objects. Use
  `--allow-additional-properties` to allow them recursively.
- Arrays merge every item from every example into one `items` schema. Empty
  arrays supply no item information; arrays that are all empty use `items: {}`.
- Nested types use type unions. Integers and numbers merge to `number`.
  Type-specific keywords constrain only the relevant type, including unions
  containing objects and arrays. All roots must have the same JSON type, except
  compatible integer/number combinations.
- All-positive numbers infer `exclusiveMinimum: 0`; all-negative numbers infer
  `exclusiveMaximum: 0`. Mixed signs or any zero omit sign constraints.
  `--no-number-sign` disables this inference recursively.
- `--const FIELD [FIELD ...]` replaces selected top-level property schemas with
  `const`. Every example must contain the field with the same JSON value.
  Constants can be strings, numbers, booleans, null, objects, or arrays. Field
  names are literal: a dot is part of a name, not a nested path. Put positional
  inputs before `--const` so they are not consumed as field names.
- Complete examples are included only at the root, with duplicates removed in
  first-seen order. Equality ignores object key order and treats equal numeric
  values such as `1` and `1.0` alike; booleans are distinct from numbers.
  `--no-examples` omits them.
- `$id` appears only with `--id`; nonempty URI fragments are rejected.
  No formats, regexes, string lengths, concrete numeric ranges, tuple schemas,
  `$defs`, or `$ref` are inferred.

Schemas intentionally allow unobserved combinations of merged properties; they
do not model distinct success/error variants. Output uses four-space indentation,
UTF-8 characters, and a final newline. Invalid JSON, non-finite or overflowing
floating-point numbers, nonzero numbers that underflow to zero, and ordinary
file errors produce concise errors with a nonzero exit status.

## Python API

```python
from json_to_schema import generate_schema

schema = generate_schema(
    [{'id': 1, 'name': 'Alice'}, {'id': 2, 'active': True}],
    title='Users',
    include_examples=False,
)
```

The API accepts a nonempty sequence of decoded JSON documents and raises
`ValueError` for invalid examples or conflicting constants. It does not modify
the supplied data.

## Development

Development uses the configuration in [`.devcontainer/`](.devcontainer/).
Install and start Docker, install the
[VS Code Dev Containers extension](https://code.visualstudio.com/docs/devcontainers/containers),
then open this repository in VS Code and run **Dev Containers: Reopen in Container**.

The container provides Python 3.14, uv 0.13.1, Git, and the Python editor
extensions. On creation, `uv sync --locked --group dev` installs the package
in editable mode and its test dependencies from `uv.lock`.
The Python environment lives at `/home/vscode/.local/share/json-to-schema/venv`
inside the container; development does not require a host `.venv`.
An existing host `.venv` is ignored by the container and can be removed once
you have switched over.

Run these commands in the container terminal:

```bash
uv run --locked pytest
uv run --locked json-to-schema --help
uv build
```

After pulling dependency changes, run `uv sync --locked --group dev` again.
After changing the Dockerfile, use **Dev Containers: Rebuild Container**.
The container uses [uv's Docker integration](https://docs.astral.sh/uv/guides/integration/docker/)
to keep the Python environment separate from the mounted source tree.

`pytest` and `jsonschema` are development dependencies only. Tests check schemas
against Draft 2020-12, validate their source examples, exercise rejected values,
and cover CLI errors and output protection.
