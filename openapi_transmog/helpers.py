"""
Project-agnostic helper functions.
"""


from typing import Callable, TypeVar
import ast
import pathlib

T = TypeVar('T')


def split_by_predicate(
    data: list[T],
    pred: Callable[[T], bool] = bool
):
    yes: list[T] = []
    no: list[T] = []
    for x in data:
        (yes if pred(x) else no).append(x)
    return yes, no


def walk_dict(d: dict):
    """
    Walk a dict, yielding it and any dicts contained within it.
    """
    if not isinstance(d, dict):
        return
    yield d
    for v in d.values():
        yield from walk_dict(v)
        if isinstance(v, (list, tuple)):
            for v2 in v:
                yield from walk_dict(v)


def ast_syntax_error(node: ast.AST, message: str, file_path: pathlib.Path = None, _src: str = None) -> SyntaxError:
    """
    Raise a syntax error from an AST node.

    file_path may be None, though the result will miss ^^^ annotations.

    By default, _src = file_path.read_text(), but it can be provided if file_path is stdin or a socket or something.
    """

    file_path.is_fifo()
    err = SyntaxError(message)

    if not file_path:
        # rather unlikely a SyntaxError would be raised on a developer's own homebrewed AST,
        # so lack of ^^^^ annotations is not really an issue!
        err.filename = "<unknown>"
        err.text = ast.unparse(ast.fix_missing_locations(node))
        err.lineno = 1
        return err

    err.filename = file_path
    if _src is None:
        _src = pathlib.Path(file_path).read_text()

    if hasattr(node, 'lineno'):
        err.lineno = node.lineno
        err.text = _src.splitlines()[err.lineno - 1]

        if hasattr(node, 'end_lineno'):
            err.end_lineno = node.end_lineno
            # TODO: multiline err.text..?

    if hasattr(node, 'col_offset'):
        # TODO: check if +1 is just an error on my system or something
        err.offset = node.col_offset + 1
        if hasattr(node, 'end_col_offset'):
            err.end_offset = node.end_col_offset + 1

    return err


def argument_count(args: ast.arguments):
    "Number of arguments into a function."
    N = len(args.args + args.kwonlyargs + args.posonlyargs)
    if args.kwarg:
        N += 1
    if args.vararg:
        N += 1
    return N
