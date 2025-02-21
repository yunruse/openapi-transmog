from argparse import ArgumentParser
from json import load as load_json
from yaml import safe_load as load_yaml
from pathlib import Path

from .schema import generate_code

parser = ArgumentParser('python -m openapi-transmog')
parser.add_argument(
    'schema', type=Path,
    help="the JSON or YAML file. Should be OpenAPI 3.")

parser.add_argument(
    '--annotations', type=Path, default=None,
    help="Path to annotations file (Python). See documentation for what that can do"
)

parser_interp = parser.add_argument_group(
    'HTTP interpolation',
    "You may reference a environmental variable such as '$TOKEN', which will be fetched at runtime. (Be careful not to hardcode the token!)"
)

parser_interp.add_argument(
    '--auth',
    nargs=2, metavar=('user', 'password'),
    help='HTTP basic authentication'
)
parser_interp.add_argument(
    '--cookie', '-C', default=[],
    nargs=2, metavar=('key', 'value'),
    action='append',
    help='Cookie (you may define multiple)'
)
parser_interp.add_argument(
    '--param', '-P', default=[],
    nargs=2, metavar=('key', 'value'),
    action='append',
    help='Parameter (you may define multiple; they will override)'
)
parser_interp.add_argument(
    '--header', '-H', default=[],
    nargs=2, metavar=('key', 'value'),
    action='append',
    help='HTTP header (you may define multiple)'
)

if __name__ == '__main__':
    args = parser.parse_args()
    match args.schema.suffix:
        case ".json":
            schema = load_json(args.schema.open())
        case ".yaml" | ".yml":
            schema = load_yaml(args.schema.open())

    print(generate_code(
        schema,
        params=dict(args.param) or None,
        headers=dict(args.header) or None,
        cookies=dict(args.cookie) or None,
        auth=args.auth,
        annotation_fp=args.annotations
    ))
