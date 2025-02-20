import ast
from dataclasses import dataclass
from typing import Any, Literal
from warnings import warn

from .api_call import def_api_call

def resolve_type(schema) -> type:
    if '$ref' in schema:
        return ast.Constant(schema.get('$ref').removeprefix('#/components/schemas/'))

    if 'enum' in schema:
        return ast.Subscript(
            ast.Name('Literal'),
            ast.Tuple([ast.Constant(x) for x in schema['enum']])
        )

    match schema['type']:
        case "string":
            return ast.Name('str')
        case "integer":
            return ast.Name('int')
        case "boolean":
            return ast.Name('bool')
        case "array":
            return ast.Subscript(
                ast.Name('list'),
                resolve_type(schema['items'])
            )
        case "object":
            return ast.Name('dict')
            # TODO: handle anonymous types
            # TypedDict('anonymous', {
            #         k: resolve_type(v) for k, v in schema.get('properties', {}).items()
            #     })

# @dataclass
# class Property:
#     "An object type held in a TypedDictSpec."
#     pass


@dataclass
class TypedDictSpec:
    "A typeddict defined by a schema; typically that returned by an API call."
    name: str
    properties: dict[str, type]

    @classmethod
    def from_api_spec(cls, name: str, prop_spec: dict):
        assert prop_spec['type'] == 'object'
        properties = {k: resolve_type(v)
                      for k, v in prop_spec.get('properties').items()}
        return cls(name, properties)

    @property
    def body(self):
        return [
            ast.AnnAssign(ast.Name(k), v, simple=1)
            for k, v in self.properties.items()
        ]

    def as_ast(self):
        return ast.ClassDef(
            self.name,
            bases=[ast.Name('TypedDict')],
            keywords=[],
            body=self.body,
            decorator_list=[],
            type_params=[],
        )


@dataclass
class FuncArg:
    "An argument to the API call, whether it is part of the path or a parameter."
    name: str
    in_path: bool
    description: str
    required: bool
    type: type
    default: Any

    @staticmethod
    def _get_type(schema: dict):
        if enum := schema.get('enum'):
            return Literal[*enum]

        match schema.get('type'):
            case "string":
                return str
            case "integer":
                return int

        return NotImplemented

    @classmethod
    def from_api_spec(cls, spec: dict):
        schema = spec.get('schema', {})
        return cls(
            name=spec.get('name'),
            in_path=spec.get('in') == 'path',
            description=spec.get('description'),
            required=spec.get('required', False),
            default=schema.get('default', None),
            type=cls._get_type(schema)
        )

    def as_ast(self):
        return ast.arg(self.name)

    def default_ast(self):
        if self.default == "null":
            return ast.Constant(None)
        return ast.Constant(self.default)


@dataclass
class ApiCall:
    "An API at some URL."
    url: str
    method: str
    description: str
    parameters: list[FuncArg]
    response_spec: dict

    @property
    def name(self):
        url = self.url.removeprefix('/').removesuffix('/')
        # TODO: fancier wrangling
        return '_'.join([
            seg for seg in url.split('/') if not seg.startswith('{')
        ])

    @property
    def arguments(self):
        # NOTE: This assumes required params come first!
        return ast.arguments(
            args=[p.as_ast() for p in self.parameters],
            defaults=[p.default_ast()
                      for p in self.parameters if not p.required],
            posonlyargs=[],
            kwonlyargs=[],
            kw_defaults=[]
        )

    @property
    def body(self) -> list[ast.stmt]:
        url_args = [p.name for p in self.parameters if p.in_path]
        param_args = [p.name for p in self.parameters if not p.in_path]

        url = ast.Call(
            ast.Attribute(ast.Constant(self.url), "format"),
            args=[],
            keywords=[ast.keyword(n, ast.Name(n)) for n in url_args]
        )
        params = ast.Dict(
            [ast.Constant(n) for n in param_args],
            [ast.Name(n) for n in param_args],
        )

        return [
            ast.Expr(ast.Constant(self.description)),
            ast.Return(ast.Call(
                ast.Name('api_call'),
                [ast.Constant(self.method), url, params], []
            ))
        ]

    @property
    def returns(self) -> ast.expr:
        "The return type."
        # TODO: handle errors!

        ok_resp = self.response_spec.get('200', {})
        if not ok_resp:
            return ast.Constant('None')
        return_schema = ok_resp.get('content', {}).get(
            'application/json', {}).get('schema', {})
        if '$ref' not in return_schema:
            # TODO: handle anonymous return types which don't reference a schema
            raise NotImplementedError('anon types not yet ok')
        typ_name = return_schema['$ref'].removeprefix('#/components/schemas/')

        # TODO: output name
        return ast.Name(typ_name)

    def as_ast(self):
        return ast.FunctionDef(
            self.name,
            self.arguments,
            self.body,
            decorator_list=[],
            returns=self.returns,
            type_params=[],
        )


def generate_code(
    schema: dict,
    params: dict[str, str] = None,
    headers: dict[str, str] = None,
    cookies: dict[str, str] = None,
    auth: tuple[str, str] = None,
):
    objs: list[TypedDictSpec] = []
    obj_specs = schema.get('components', {}).get('schemas', {})
    for name, obj_spec in obj_specs.items():
        objs.append(TypedDictSpec.from_api_spec(name, obj_spec))

    funcs: list[ApiCall] = []
    for path, m_spec in schema.get('paths', {}).items():
        for method, path_spec in m_spec.items():
            desc = path_spec.get('description')
            func_params = [FuncArg.from_api_spec(s)
                      for s in path_spec.get('parameters', [])]
            funcs.append(ApiCall(path, method, desc, func_params,
                         path_spec.get('responses')))

    base_url = schema.get('servers', [{}])[0].get('url')
    if not base_url:
        # TODO: use a default and r UserWarning instead, perhaps?
        base_url = 'https://example.org'
        warn(f'The schema does not define a base URL! The code will use {base_url}')

    body = [def_api_call(
        base_url,
        params=params,
        headers=headers,
        cookies=cookies,
        auth=auth,
    )]
    body.append(ast.Assign(
        [ast.Name('__all__')],
        ast.List([ast.Constant(f.name) for f in funcs])
    ))
    for obj in objs:
        body.append(obj.as_ast())
    for func in funcs:
        body.append(func.as_ast())

    return ast.unparse(ast.fix_missing_locations(ast.Module(body, [])))
