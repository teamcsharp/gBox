"""JSON answers of plain ``def`` endpoints are encoded in the threadpool, never on the event loop.

FastAPI runs a ``def`` endpoint in its threadpool, then encodes the dict or list it returns on the event loop
(``jsonable_encoder`` + ``json.dumps``). The control plane has one event loop, and it also carries every live game
picture: the worker's frame upload (POST /api/sessions/{sid}/stream), each MJPEG view of the app and the broadcast
feeds Pine Box reads. While a big answer was encoded, all of them stood still. GET /api/workers (1.9 MB: 21 stale
worker rows with their source hashes), which the app, the web view and the session observers each poll every 5 s,
held the loop about 90 ms per poll on a desktop CPU and longer on the loaded Spark (operator 2026-10-26: "the app
itself has a stutter every 5 seconds ... it also has a slight stutter with the pine box").

ThreadJSONRoute encodes that answer in the threadpool thread that ran the endpoint, with the same encoder and the
same response class, so status, headers and bytes are unchanged. Routes whose answer FastAPI shapes itself keep
FastAPI's path: async endpoints, generators, a response model, an explicit status code or response class, and
endpoints that take the injected Response to set headers. route.endpoint stays the undecorated function.
"""
from __future__ import annotations

import functools
import inspect
import json

from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.responses import Response


def _dumps(value) -> bytes:
    # JSONResponse.render's exact settings
    return json.dumps(value, ensure_ascii=False, allow_nan=False, indent=None, separators=(",", ":")).encode("utf-8")


def _array(items) -> bytes:
    return b"[" + b",".join(_dumps(x) for x in items) + b"]"


def json_bytes(content) -> bytes:
    """JSONResponse(content).body, byte for byte, encoded in pieces. json.dumps of a whole answer is one C call that holds
    the GIL from its start to its end: the 47 MB inbox list took 275 ms of an idle Spark core and 577 ms of the loaded
    one (2026-10-27), and the event loop, the frame uploads and every MJPEG view stood still meanwhile. A list is
    encoded item by item, a dict with string keys value by value (a list value item by item), so other threads get
    the GIL between pieces. Anything else, or a dict with other keys (json.dumps converts those), is one call."""
    if isinstance(content, list):
        return _array(content)
    if isinstance(content, dict) and all(type(k) is str for k in content):
        return b"{" + b",".join(_dumps(k) + b":" + (_array(v) if isinstance(v, list) else _dumps(v))
                                for k, v in content.items()) + b"}"
    return _dumps(content)


class PiecewiseJSONResponse(JSONResponse):
    """A JSONResponse whose body is rendered by json_bytes: the same bytes and headers, never one long GIL hold."""

    def render(self, content) -> bytes:
        return json_bytes(content)


def encode_in_thread(call):
    """`call`, answering with a JSONResponse built where it runs (a threadpool thread) instead of a bare dict/list."""
    @functools.wraps(call)
    def answer(*args, **kwargs):
        result = call(*args, **kwargs)
        return result if isinstance(result, Response) else PiecewiseJSONResponse(jsonable_encoder(result))
    answer.gbox_thread_json = True
    return answer


def _sets_response(dependant) -> bool:
    """The endpoint or one of its dependencies takes the injected Response (headers, cookies, status code): FastAPI
    copies those onto an answer it builds itself, never onto one the endpoint returns."""
    return bool(getattr(dependant, "response_param_name", None)) or any(
        _sets_response(d) for d in getattr(dependant, "dependencies", None) or ())


def thread_encodable(route: APIRoute) -> bool:
    """Whether FastAPI would answer this route with JSONResponse(jsonable_encoder(result)) encoded on the loop."""
    call = getattr(getattr(route, "dependant", None), "call", None)
    if not inspect.isfunction(call) or getattr(call, "gbox_thread_json", False):
        return False
    if inspect.iscoroutinefunction(call) or inspect.isgeneratorfunction(call) or inspect.isasyncgenfunction(call):
        return False
    if getattr(route, "response_field", None) is not None or getattr(route, "status_code", None) is not None:
        return False
    if _sets_response(route.dependant):
        return False
    response_class = getattr(route, "response_class", JSONResponse)
    return getattr(response_class, "value", response_class) is JSONResponse   # DefaultPlaceholder or the class


class ThreadJSONRoute(APIRoute):
    """app.router.route_class for the control plane (gbox/server.py): see the module docstring."""

    def __init__(self, path, endpoint, **kwargs):
        super().__init__(path, endpoint, **kwargs)
        if thread_encodable(self):
            # The request handler reads dependant.call per request; FastAPI already analysed the real endpoint.
            self.dependant.call = encode_in_thread(self.dependant.call)
