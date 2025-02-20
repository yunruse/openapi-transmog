from ast import *


def resolve_type(schema) -> type:
    if '$ref' in schema:
        return Constant(schema.get('$ref').removeprefix('#/components/schemas/'))

    if 'enum' in schema:
        return Subscript(
            Name('Literal'),
            Tuple([Constant(x) for x in schema['enum']])
        )

    match schema['type']:
        case "str" | "string": return Name('str')
        case "int" | "integer": return Name('int')
        case "float" | "number": return Name('float')
        case "boolean": return Name('bool')
        case "array":
            return Subscript(
                Name('list'),
                resolve_type(schema['items'])
            )
        case "object":
            return Name('dict')
            # TODO: handle anonymous types
            # TypedDict('anonymous', {
            #         k: resolve_type(v) for k, v in schema.get('properties', {}).items()
            #     })f
