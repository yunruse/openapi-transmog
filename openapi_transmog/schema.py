import ast
from warnings import warn

from .api_call import def_api_call
from .schema_objects import TypedDictSpec, FuncArg, ApiCall


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

    base_url = schema.get('servers', [{}])[0].get('url')

    funcs: list[ApiCall] = []
    for path, m_spec in schema.get('paths', {}).items():
        if len(bu := m_spec.pop('servers', [])):
            base_url = bu[0].get('url')
            # HACK: this does NOT handle the case in which there are muliple servers...

        for method, path_spec in m_spec.items():
            desc = path_spec.get('description')
            func_params = [FuncArg.from_api_spec(s)
                           for s in path_spec.get('parameters', [])]

            # TODO: handle
            funcs.append(ApiCall(path, method, desc, func_params,
                         path_spec.get('responses')))

    if not base_url:
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
