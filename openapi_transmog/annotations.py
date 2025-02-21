from ast import *
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from sys import stderr

from .helpers import split_by_predicate


def fdef_has_content(fdef: FunctionDef):
    """
    False iff a function AST node contains only `pass` or `...` in its body.
    """
    if len(fdef.body) == 1:
        if isinstance(fdef.body[0], Pass):
            return False
        if isinstance(fdef.body[0], Expr):
            if isinstance(fdef.body[0].value, Constant):
                return fdef.body[0].value.value is not ...
    return True


@dataclass
class Argument:
    fdef: FunctionDef

    def _first_arg(self):
        return self.fdef.args.args[0]

    @property
    def name(self):
        return self._first_arg().arg

    @property
    def type(self):
        return self._first_arg().annotation

    @property
    def default(self):
        return self.fdef.args.defaults[0] if self.fdef.args.defaults else None


@dataclass
class Property:
    fdef: FunctionDef

    # @property
    # def name(self):
    #     return self.fdef.name

    @property
    def type(self):
        return self.fdef.returns

    def value(self, name):
        return Applicator.apply(self, name)


class Applicator(NodeTransformer):
    "When inlining a function that is destined to work on a dict, turn its argument"

    @classmethod
    def apply(cls, ann: Argument | Property | None, name: str):
        expr = Name(name)
        argname = name

        if ann and fdef_has_content(ann.fdef):
            argname = ann.fdef.args.args[0].arg
            expr = Call(Name(ann.fdef.name), [Name(name)], [])
            returns = deepcopy(ann.fdef.body[0])
            if isinstance(returns, Return):
                expr = returns.value

        return cls(argname, name, isinstance(ann, Property)).visit(expr)

    def __init__(self, argname: str, key: str, is_dict: bool):
        self.argname = argname
        self.key = key
        self.is_dict = is_dict
        NodeTransformer.__init__(self)

    def visit_Name(self, node):
        if self.is_dict and node.id == self.argname:
            return Subscript(Name('dictionary'), Constant(self.key))
        return node


def get_annotations(fp: Path):
    """
    For a file path to a Python file, parse it, return its AST nodes, and also info on the argument and property 'annotators'.

    An 'annotator' is a function in the Python file which has a decorator of a certain form.
    It may be empty or it may modify a variable.

    As OpenAPI schemas only work with JSON types, this means, for example, that an API can be 'annotated'
    with, for example, datetime.time, or cleanup functions.

    If the decorator is of the form @+my_cls['a', 'b'], where my_cls is a class,
    that function is applied to my_cls.a and my_cls.b before returning

    If the decorator is of the form @+my_call('c', 'd'), where my_call is an API call,
    that function is applied to args c and d in my_call before being sent.

    The return/argument type of the annotator is used to carry forward typing annotations.

    @+ is used to ensure any other decorators are ignored.
    """

    body = parse(fp.read_text()).body

    # {func_name: {arg_name: arg}}
    arguments: dict[str, dict[str, Argument]] = {}
    # {{cls_name: {prop_name: prop}}
    properties: dict[str, dict[str, Property]] = {}

    for fdef in body:
        if not isinstance(fdef, FunctionDef):
            continue

        def is_at_plus(d): return isinstance(d, UnaryOp) and isinstance(d.op, UAdd)
        annotators, regular_decs = split_by_predicate(fdef.decorator_list, is_at_plus)

        fdef.decorator_list = regular_decs

        for dcrtr in annotators:
            dcrtr = dcrtr.operand

            if isinstance(dcrtr, Call):
                # @value(arg_name, ...)
                # -> applies to the argument to an API call; we want the annotator's argument type
                assert len(fdef.args.args) == 1, "Function must take only one parameter!"

                assert isinstance(dcrtr.func, Name)
                for arg in dcrtr.args:
                    assert isinstance(arg, Constant)

                    argdef = Argument(fdef)
                    arguments.setdefault(dcrtr.func.id, {})[arg.value] = argdef

            elif isinstance(dcrtr, Subscript):
                # @value['prop_name', ...]
                # -> applies to the property of a TypedDict; we want the annotator's return type

                continue
                # TODO: apply _from_api:
                # - inside api_call (selecting HTTP return code)
                # - inside generated _from_apis;
                #     recursively, even creating new ones
                #     if annotators are deep within an object

                assert isinstance(dcrtr.value, Name)
                for prop in dcrtr.slice.elts if isinstance(dcrtr.slice, Tuple) else [dcrtr.slice]:
                    assert isinstance(prop, Constant)

                    propdef = Property(fdef)
                    properties.setdefault(dcrtr.value.id, {})[prop.value] = propdef

    return body, arguments, properties
