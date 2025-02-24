from ast import *
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from sys import stderr
from typing import Generator

from .helpers import ast_syntax_error, argument_count, split_by_predicate


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
    name: str

    @property
    def type(self):
        return self.fdef.args.args[0].annotation

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


CallMapping = tuple[str, str]


def get_call_annotators(
    fdef: FunctionDef, dcrtr: Call, fp: Path, src: str
) -> Generator[CallMapping, None, None]:
    """
    For a single decorator, list its function arg name -> API arg name mapping.

    For example, if a user used

    @+MyFunc(my_var='myVar', foo_bar='fooBar')
    def my_annotator(xyz: list[str]) -> str:
        return ','.join(xyz)

    they are saying that the generated MyFunc(my_var, foo_bar)
    will pass in those arguments as {'myVar': my_var, 'fooBar': foo_bar}
    when calling the API endpoint.

    Alternatively, as (potentially confusing?) shorthand, they may use

    @+MyFunc('myVar')
    def my_annotator(xyz: list[str]) -> str:
        return ','.join(xyz)

    in which the function's variable name is used, eg {'myVar': xyz}.

    This handles all the above and (hopefully?) passes sane SyntaxErrors.
    """

    if not isinstance(dcrtr.func, Name):
        raise ast_syntax_error(
            dcrtr.func,
            "Function annotators need a function name to annotate",
            fp, src)

    assert isinstance(dcrtr.func, Name), "Decorator should be the name of a function!"

    N = argument_count(fdef.args)

    if N == 0:
        raise ast_syntax_error(
            fdef,
            "Argument annotators cannot work on functions that take no input",
            # TODO: why not? We could delete the parameter,
            # hiding it from the encapsulation?
            fp, src)

    if N > 1 or fdef.args.kwarg or fdef.args.vararg:
        raise ast_syntax_error(
            fdef,
            f"Argument annotators can only modify one parameter."
            " For more complex transformations, consider a wrapper function"
            f" to encapsulate {dcrtr.func.id}.",
            fp, src)

    assert N == 1 and len(fdef.args.args) == 1, "incomprehensible function definition"
    default_dest = fdef.args.args[0].arg

    if len(dcrtr.args) == len(dcrtr.keywords) == 0:
        args = [f'{a.value}={a.value!r}' for a in dcrtr.args]
        more_explicit = f"@+{dcrtr.func.id}({default_dest!r})"
        raise ast_syntax_error(
            dcrtr,
            "Argument annotators requires at least one argument:"
            f" the key of the parameter to pass to {dcrtr.func.id}."
            "\n Check the OpenAPI schema or run without annotations"
            " to find which that might be."
            f"\nConsider: {more_explicit}",
            fp, src)

    def is_string_literal(node):
        return isinstance(node, Constant) and isinstance(node.value, str)
    if not all(map(is_string_literal, dcrtr.args)):
        raise ast_syntax_error(
            dcrtr,
            "Argument annotators should take only strings,"
            " representing the API parameter key",
            fp, src)

    if len(dcrtr.args) > 1:
        args = [f'{a.value}={a.value!r}' for a in dcrtr.args]
        more_explicit = f"@+{dcrtr.func.id}({', '.join(args)})"

        raise ast_syntax_error(
            dcrtr.args[1],
            "Cannot annotate an API call with multiple argument names in this way:"
            f" only one can be renamed {default_dest}."
            f"\nConsider: {more_explicit}",
            fp, src)

    if len(dcrtr.args) and len(dcrtr.keywords):
        args = [f'{a.value}={a.value!r}' for a in dcrtr.args]
        args += [f'{k.arg}={unparse(k.value)}' for k in dcrtr.keywords]
        more_explicit = f"@+{dcrtr.func.id}({', '.join(args)})"

        A0 = repr(dcrtr.args[0].value)
        mapping = '{%s: %s}' % (A0, default_dest)

        raise ast_syntax_error(
            dcrtr,
            "Argument annotators can only take either one name --"
            f" turning the API call into something like"
            f"\n    def {dcrtr.func.id}({A0}): get(params={mapping}) --"
            "\nor multiple arguments, which would provide explicit"
            "function argument names to embody each respective API parameter key."
            f"\nConsider: {more_explicit}",
            fp, src
        )

    # and that's syntaxerrors! wow, writing AST stuff is a pain.

    # yield func_arg_name, api_arg_name

    for arg in dcrtr.args:
        yield default_dest, arg.value

    for arg in dcrtr.keywords:
        yield arg.arg, arg.value.value


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

    src = fp.read_text()
    body = parse(src).body

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
                # -> applies to the argument to an API call
                for func_arg, api_arg in get_call_annotators(fdef, dcrtr, fp, src):
                    argdef = Argument(fdef, func_arg)
                    arguments.setdefault(dcrtr.func.id, {})[api_arg] = argdef

            elif isinstance(dcrtr, Subscript):
                # @value['prop_name', ...]
                # -> applies to the property of a TypedDict

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
