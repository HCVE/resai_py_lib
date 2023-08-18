import subprocess
from copy import copy

import json
from socket import socket, AF_INET, SOCK_STREAM
from typing import Dict, Any, Iterable, Callable, Optional

import jsonpickle
import psutil
from hcve_lib.service_locator import locator


def get_free_port():
    sock = socket()
    sock.bind(("", 0))
    return sock.getsockname()[1]


def encode(obj: Any) -> Dict:
    return json.loads(jsonpickle.encode(obj))


def is_port_up(port: int, host: str = "localhost") -> bool:
    s = socket(AF_INET, SOCK_STREAM)
    try:
        s.connect((host, port))
        return True
    except:
        return False
    finally:
        s.close()


class Serializable:
    exclude_serialization: Iterable[str]
    exclude_frontend_serialization: Iterable[str]

    def __init__(self):
        self.exclude_serialization = []
        self.exclude_frontend_serialization = []

    def __getstate__(self):
        state = copy(self.__dict__)

        exclude = getattr(self, "exclude_serialization", [])

        if hasattr(self, "exclude_frontend_serialization") and locator.get(
            "frontend_export"
        ):
            exclude_ = [*exclude, *self.exclude_frontend_serialization]
        else:
            exclude_ = exclude

        for name in exclude_:
            state.pop(name, None)

        return state


def kill_process_on_port(port: int) -> None:
    try:
        cmd_find = f"netstat -ano | findstr :{port}"
        output = subprocess.check_output(cmd_find, shell=True).decode("utf-8").strip()

        pid = None
        for line in output.split("\n"):
            parts = line.split()
            if len(parts) >= 5:
                pid = parts[-1]
                break

        if pid:
            subprocess.run(["taskkill", "/F", "/PID", pid])
            print(f"Process running on port {port} has been killed.")
        else:
            print(f"No process found running on port {port}.")
    except Exception as e:
        print(f"Error: {e}")
