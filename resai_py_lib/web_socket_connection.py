import asyncio
import json
import uuid
from asyncio import CancelledError

import jsonpickle
from abc import ABC
from dataclasses import dataclass
from typing import List, Dict

from traitlets import Callable
from websockets import connect, WebSocketClientProtocol
from websockets.exceptions import ConnectionClosedError
from resai_py_lib.utils import Serializable
from hcve_lib.utils import (
    convert_to_snake_case_keys,
    convert_to_snake_case,
    retry_async,
    find_key,
)


@dataclass
class Listener:
    obj: object
    prefix: str = ""


def print_dict(d, max_length=20, indent=0):
    """
    Print a nested dictionary, truncating long values.

    Args:
    - d (dict): The dictionary to print.
    - max_length (int): The maximum length for displayed values.
    - indent (int): Internal parameter for keeping track of indentation.
    """
    for key, value in d.items():
        if isinstance(value, dict):
            print(" " * indent + str(key) + ":")
            print_dict(value, max_length, indent + 2)
        else:
            display_value = value
            if isinstance(value, str) and len(value) > max_length:
                display_value = value[: max_length - 3] + "..."
            print(" " * indent + f"{key}: {display_value}")


class WebSocketConnection(Serializable, ABC):
    web_socket: WebSocketClientProtocol = None
    listeners: List[Listener]
    pending: dict[str, asyncio.Future] = {}
    on_connection_reconnects: Callable = None

    def __init__(self, web_socket: WebSocketClientProtocol = None):
        super().__init__()
        self.listeners = []
        self.exclude_serialization = (*self.exclude_serialization, "web_socket")
        if web_socket:
            self.set_websocket(web_socket)

    def set_websocket(
        self,
        web_socket: WebSocketClientProtocol,
    ):
        self.web_socket = web_socket
        asyncio.create_task(self.read_and_handle_messages())

    def listen(self, obj: object, prefix: str = ""):
        self.listeners.append(Listener(obj=obj, prefix=prefix))

    async def call(
        self,
        method,
        *args,
        **kwargs,
    ):
        return await self.send({"method": method, "args": args, "kwargs": kwargs})

    async def send(
        self,
        data: any,
        unpicklable: bool = True,
        additional_data: Dict = None,
    ):
        if additional_data is None:
            additional_data = {}

        if find_key(data, "py/object") or (
            "args" in data
            and any(find_key(arg, "py/object") for arg in data["args"])
            or ("kwargs" in data and find_key(data["kwargs"], "py/object"))
        ):
            encoded = json.dumps(data)
        else:
            encoded = jsonpickle.encode(data, unpicklable=unpicklable)

        if "message_id" not in data:
            message_id = str(uuid.uuid4())
            encoded = json.dumps(
                {**json.loads(encoded), "message_id": message_id, **additional_data}
            )
            future = asyncio.Future()
            self.pending[message_id] = future
        else:
            # already is a response
            future = None
            encoded = encoded

        if additional_data:
            encoded = json.dumps({**json.loads(encoded), **additional_data})

        await self.web_socket.send(encoded)
        print(" → ", str(encoded)[:200] + "\n")
        if future:
            return future

    async def read_and_handle_messages(self):
        try:
            async for message in self.web_socket:
                message_decoded = convert_to_snake_case_keys(jsonpickle.decode(message))
                print(" ← " + str(message_decoded)[:200] + "\n")
                for listener in self.listeners:
                    prefix = listener.prefix + "_" if listener.prefix else ""

                    message_id = message_decoded.get("message_id", None)

                    if message_id:
                        future = self.pending.pop(message_id, None)
                        if future:
                            future.set_result(message_decoded.get("result", None))

                    method = message_decoded.get("method", None)
                    if method:
                        result = await getattr(
                            listener.obj,
                            convert_to_snake_case(f"{prefix}{method}"),
                        )(
                            *message_decoded.get("args", []),
                            **message_decoded.get("kwargs", {}),
                        )
                        if result is not None:
                            await self.send(
                                dict(
                                    result=result,
                                    message_id=message_decoded["message_id"],
                                )
                            )
        except ConnectionClosedError as e:
            await self.connection_closed(e)
            pass

    async def connection_closed(self, e):
        print(f"Connection closed: {e}")

    def is_connected(self):
        return self.web_socket and self.web_socket.open


class WebSocketClientConnection(WebSocketConnection):
    port: int

    def __init__(self, port: int):
        super().__init__()
        self.port = port

    async def call(self, method, *args, **kwargs):
        if not self.is_connected():
            await self.connect()

        return await super().call(method, *args, **kwargs)

    @retry_async(max_retries=15, retry_delay=1, exception=ConnectionRefusedError)
    async def connect(self):
        web_socket = await connect(f"ws://localhost:{self.port}", max_size=None)
        self.set_websocket(web_socket)

    async def connection_closed(self, e):
        print("RECONNECTING")
        await self.connect()
        if self.on_connection_reconnects:
            await self.on_connection_reconnects()
