import asyncio
import json
import uuid

import jsonpickle
from abc import ABC
from dataclasses import dataclass
from typing import List, Dict
from websockets import connect, WebSocketClientProtocol

from resai_py_lib.utils import Serializable
from hcve_lib.utils import convert_to_snake_case_keys, convert_to_snake_case
from hcve_lib.service_locator import locator


@dataclass
class Listener:
    obj: object
    prefix: str = ""


class WebSocketConnection(Serializable, ABC):
    web_socket: WebSocketClientProtocol = None
    listeners: List[Listener]
    pending: dict[str, asyncio.Future] = {}

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

        # print(" → " + encoded)
        await self.web_socket.send(encoded)

        if future:
            return future

    async def read_and_handle_messages(self):
        async for message in self.web_socket:
            message_decoded = convert_to_snake_case_keys(jsonpickle.decode(message))
            # print(" ← " + str(message_decoded))
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
                                result=result, message_id=message_decoded["message_id"]
                            )
                        )


class WebSocketClientConnection(WebSocketConnection):
    port: int

    def __init__(self, port: int):
        super().__init__()
        self.port = port

    async def call(self, method, *args, **kwargs):
        if self.web_socket is None:
            await self.connect()

        return await super().call(method, *args, **kwargs)

    async def connect(self):
        web_socket = await connect(f"ws://localhost:{self.port}")
        self.set_websocket(web_socket)
