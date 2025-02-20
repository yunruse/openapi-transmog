# `pip install openapi-transmog`

[
![PyPI - Version](https://img.shields.io/pypi/v/openapi-transmog)
![Python - 3.8+](https://img.shields.io/badge/python-3.8%2B-blue)
![PyPI - Downloads](https://img.shields.io/pypi/dm/openapi-transmog)
![License - MIT](https://img.shields.io/pypi/l/openapi-transmog)
](https://pypi.org/project/openapi-transmog)



A simple development tool (not a dependency!) that transforms an [OpenAPI specification](https://spec.openapis.org/oas/latest.html) into a single `.py` file that encapsulates its function calls and return types (as `TypedDict`s).

The `.py` file outputted requires Python 3.8 or later, [`requests`](https://pypi.org/project/requests/), and [`python-dotenv`](https://pypi.org/project/python-dotenv/).

**Be aware** this tool is early in development: it will make a lot of assumptions that likely will not hold for your particular API spec!

## Usage

While the header must be passed along, it doesn't specify where you are getting certain variables. As such, you can pass various properties along. Make sure to wrap environmental variables in `''` so they are interpreted at runtime, rather than hardcoding a secret token into your code!

```sh
python -m openapi-transmog spec.json --header X-Api-Token '$token' > api.py
```