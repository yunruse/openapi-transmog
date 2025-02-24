from dataclasses import dataclass
from functools import reduce
from sys import stderr
from typing import Any

from .helpers import split_by_predicate

from .typing import resolve_type
from .annotations import Argument, Property, Applicator

from ast import *


@dataclass
class TypedDictSpec:
    "A typeddict defined by a schema; typically that returned by an API call."
    name: str
    description: str
    properties: dict[str, type]
    prop_anns: dict[str, Property]

    @classmethod
    def from_api_spec(
        cls,
        name: str,
        prop_spec: dict,
        prop_anns: dict[str, Property],
    ):
        assert prop_spec['type'] == 'object'
        properties = {
            k: prop_anns[k].type or resolve_type(v) if k in prop_anns else resolve_type(v)
            for k, v in prop_spec.get('properties').items()}

        return cls(name, prop_spec.get('description'), properties, prop_anns)

    @property
    def body(self):
        body = []
        if self.description:
            body.append(Expr(Constant(self.description)))
        body += [
            AnnAssign(Name(k), v, simple=1)
            for k, v in self.properties.items()
        ]
        if self.prop_anns:
            body.append(FunctionDef(
                "_from_api",
                arguments([], [arg('dictionary', Name('dict'))], None, [], [], None, []),
                [Return(Dict(
                    [None, *(Constant(k) for k in self.prop_anns.keys())],
                    [Name('dictionary'), *(p.value(k) for k, p in self.prop_anns.items())]
                ))],
                [Name('staticmethod')], Constant(self.name), None, []
            ))

        return body

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
    dest_name: str
    in_path: bool
    description: str
    required: bool
    type: type
    default: expr
    arg_ann: Argument | None

    @classmethod
    def from_api_spec(cls, spec: dict, arg_ann: Argument | None):
        schema: dict = spec.get('schema', {})
        return cls(
            name=arg_ann.name if arg_ann else spec.get('name'),
            dest_name=spec.get('name'),
            in_path=spec.get('in') == 'path',
            description=spec.get('description'),
            required=spec.get('required', False),
            default=arg_ann.default if arg_ann else schema.get('default', None),
            type=arg_ann.type if arg_ann else resolve_type(schema),
            arg_ann=arg_ann,
        )

    def include_in_fdef(self):
        if self.arg_ann:
            return not self.arg_ann.hides_argument
        return True

    def as_ast(self):
        return arg(self.name, self.type)

    def default_ast(self):
        if isinstance(self.default, Constant):
            return self.default
        if self.default == "null":
            return Constant(None)
        return Constant(self.default)

    def has_value(self):
        if self.arg_ann:
            return self.arg_ann.has_return_value
        return True

    def value(self):
        return Applicator.apply(self.arg_ann, self.name)


@dataclass
class ApiCall:
    "An API at some URL."
    name: str
    url: str
    method: str
    description: str
    parameters: list[FuncArg]
    responses: list[expr]
    obj_extras: dict[str, dict]
    arg_anns: dict[str, Argument]

    @staticmethod
    def response_type(cls_name, code: int, resp_spec: dict):
        return_schema: dict = resp_spec.get('content', {}).get(
            'application/json', {}).get('schema', {})
        typ_name = return_schema.pop('$ref', "").removeprefix('#/components/schemas/')

        if not typ_name:
            return f'{cls_name}_{code}', return_schema

        return typ_name, return_schema

    @classmethod
    def from_api_spec(
        cls,
        name: str,
        path: str,
        method: str,
        api_call_spec: dict,
        arg_anns: dict[str, Argument],
    ):
        func_params = [
            FuncArg.from_api_spec(s, arg_anns.get(s.get('name')))
            for s in api_call_spec.get('parameters', [])
        ]
        required, optional = split_by_predicate(func_params, lambda f: f.required)

        obj_extras = dict(
            cls.response_type(name, k, v)
            for k, v in api_call_spec.get('responses', {}).items()
        )

        return cls(
            name,
            path,
            method,
            api_call_spec.get('description'),
            required + optional,
            [Name(k) for k in obj_extras.keys()],
            obj_extras,
            arg_anns,
        )

    @property
    def arguments(self):
        # TODO: This dictates if the FuncArg can have a default.
        # For now, 'mandatory' FuncArgs remain mandatory,
        # as they could be provided a default anywhere.
        # However, this shouldn't be the case:
        # any 'mandatory' FuncArgs should have a default
        # if they don't leave any gaps.
        defaults = [
            p.default_ast() for p in self.parameters
            if p.include_in_fdef() and not p.required
        ]

        return arguments(
            args=[p.as_ast() for p in self.parameters if p.include_in_fdef()],
            defaults=defaults,
            posonlyargs=[],
            kwonlyargs=[],
            kw_defaults=[]
        )

    @property
    def body(self) -> list[stmt]:
        url_args, param_args = split_by_predicate(self.parameters, lambda p: p.in_path)

        url = Call(
            Attribute(Constant(self.url), "format"),
            args=[],
            keywords=[keyword(a.dest_name, a.value()) for a in url_args]
        )
        # print(param_args)
        params = {
            Constant(a.dest_name): a.value()
            for a in param_args if a.has_value()
        }
        params = Dict(params.keys(), params.values())
        # print(unparse(fix_missing_locations(params)))

        # TODO: fetch annotators by HTTP status code
        # and imbue with any ._from_api
        annotators = Dict([], [])

        body = []
        if self.description:
            body.append(Expr(Constant(self.description)))
        body.append(Return(Call(Name('api_call'), [
            Constant(self.method),
            url,
            params,
            annotators,
        ], [])))
        return body

    @property
    def returns(self) -> expr:
        "The return type."
        if len(self.responses) == 0:
            return None
        if len(self.responses) == 1:
            return self.responses[0]

        # chain with |
        return reduce(lambda x, y: BinOp(x, BitOr(), y), self.responses[1:], self.responses[0])

    def as_ast(self):
        return FunctionDef(
            self.name,
            self.arguments,
            self.body,
            decorator_list=[],
            returns=self.returns,
            type_params=[],
        )
