from dataclasses import dataclass
from typing import Any

from .typing import resolve_type

from ast import *


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
            AnnAssign(Name(k), v, simple=1)
            for k, v in self.properties.items()
        ]

    def as_ast(self):
        return ClassDef(
            self.name,
            bases=[Name('TypedDict')],
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

    @classmethod
    def from_api_spec(cls, spec: dict):
        schema = spec.get('schema', {})
        return cls(
            name=spec.get('name'),
            in_path=spec.get('in') == 'path',
            description=spec.get('description'),
            required=spec.get('required', False),
            default=schema.get('default', None),
            type=resolve_type(schema)
        )

    def as_ast(self):
        return arg(self.name, self.type)

    def default_ast(self):
        if self.default == "null":
            return Constant(None)
        return Constant(self.default)


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
        return arguments(
            args=[p.as_ast() for p in self.parameters],
            defaults=[p.default_ast()
                      for p in self.parameters if not p.required],
            posonlyargs=[],
            kwonlyargs=[],
            kw_defaults=[]
        )

    @property
    def body(self) -> list[stmt]:
        url_args = [p.name for p in self.parameters if p.in_path]
        param_args = [p.name for p in self.parameters if not p.in_path]

        url = Call(
            Attribute(Constant(self.url), "format"),
            args=[],
            keywords=[keyword(n, Name(n)) for n in url_args]
        )
        params = Dict(
            [Constant(n) for n in param_args],
            [Name(n) for n in param_args],
        )

        return [
            Expr(Constant(self.description)),
            Return(Call(
                Name('api_call'),
                [Constant(self.method), url, params], []
            ))
        ]

    @property
    def returns(self) -> expr:
        "The return type."
        # TODO: handle errors!

        ok_resp = self.response_spec.get('200', {})
        if not ok_resp:
            return Constant('None')
        return_schema = ok_resp.get('content', {}).get(
            'application/json', {}).get('schema', {})
        if '$ref' not in return_schema:
            # TODO: handle anonymous return types which don't reference a schema
            raise NotImplementedError('anon types not yet ok')
        typ_name = return_schema['$ref'].removeprefix('#/components/schemas/')

        # TODO: output name
        return Name(typ_name)

    def as_ast(self):
        return FunctionDef(
            self.name,
            self.arguments,
            self.body,
            decorator_list=[],
            returns=self.returns,
            type_params=[],
        )
