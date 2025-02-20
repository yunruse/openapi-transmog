'''
Generate an api_call function, which is used by all API calls.
This allows the user to pass in environmental variables or constants.

If ran as __main__, will print:

def api_call(method, url, params): # type: (str, str, dict[str, str]) -> dict[str]
    """Handler for API calls."""
    params.update({'foo': expandvars('${BAR}')})
    response = request(method=method, url='https://example.org' + url, params=params, headers={'X-Api-Key': expandvars('$TOKEN'), 'User-Agent': 'Mozilla'}, auth=('user', expandvars('$password')))
    response.raise_for_status()
    return response.json()
'''

from sys import stderr
from ast import *


def entropy(string: str):
    """
    Approximate Kolmogorov complexity of a string (as Shannon isn't useful in testing).

    Should help highlight secret tokens. A UUID will be about 40; a decent limit is 35.

    """
    from zlib import compress
    return len(compress(string.encode('utf-8')))


def string(s: str, context=None):
    "os.path.expandvars(string), if applicable"
    warn = "Warning: Did you type (e.g.) \"$token\" instead of '$token'?"
    if s.strip() == '' or entropy(s) > 35:
        print(f"{warn} The {context} will be hardcoded, not fetched!", file=stderr)

    if '$' in s or '%' in s:
        return Call(Name('expandvars'), [Constant(s)], [])
    return Constant(s)


def dicts(d: dict[str, str], context=None):
    return Dict([Constant(k) for k in d.keys()], [string(v, context=context) for v in d.values()])


def def_api_call(
    base_url,
    params: dict[str, str] = None,
    headers: dict[str, str] = None,
    auth: tuple[str, str] = None,
    cookies: dict[str, str] = None,
):

    # assume:
    # from requests import request
    # from os.path import expandvars

    body = [Expr(Constant('Handler for API calls.'))]
    if params is not None:
        body += [Expr(Call(Attribute(Name('params'), 'update'), [dicts(params, 'params')], []))]

    request_keywords = [
        keyword('method', Name('method')),
        keyword('url', BinOp(Constant(base_url), Add(), Name('url'))),
        keyword('params', Name('params')),
    ]
    if headers is not None:
        request_keywords += [keyword('headers', dicts(headers, 'headers'))]
    if cookies is not None:
        request_keywords += [keyword('cookies', dicts(cookies, 'cookies'))]
    if auth is not None:
        user, pw = auth
        request_keywords += [keyword('auth', Tuple([string(user, 'username'), string(pw, 'password')]))]

    body += [
        Assign([Name('response', Store())], Call(Name('request'), [], request_keywords)),
        Expr(Call(Attribute(Name('response'), 'raise_for_status'), [], [])),
        Return(Call(Attribute(Name('response'), 'json'), [], []))
    ]

    return FunctionDef(
        'api_call',
        arguments([], args=[arg('method'), arg('url'), arg('params')],
                  kwonlyargs=[], kw_defaults=[], defaults=[]),
        body, [], type_comment='(str, str, dict[str, str]) -> dict[str]')


if __name__ == '__main__':
    node = def_api_call(
        'https://example.org',
        params={'foo': '${BAR}'}, headers={'X-Api-Key': '$TOKEN', 'User-Agent': 'Mozilla'},
        auth=('user', '$password')
    )
    print(unparse(fix_missing_locations(node)))
