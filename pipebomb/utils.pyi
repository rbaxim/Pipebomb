from dataclasses import dataclass
from typing import Sequence

class RequestMeta(type):
    def __dir__(cls):
        return ["return_uuid", "key", "request", "request_uuid"]

@dataclass
class Request(metaclass=RequestMeta):
    return_uuid: bytes
    key: bytes
    request: bytes
    request_uuid: bytes

class ResponseMeta(type):
    def __dir__(cls):
        return ["key", "response", "response_uuid"]

@dataclass
class Response(metaclass=ResponseMeta):
    key: bytes
    response: bytes
    response_uuid: bytes

def err_to_human_readable(err: int) -> str:
    """
    Converts an error code to a human readable string

    Args:
        err (int): The error code to convert

    Returns:
        str
    """

__all__: Sequence[str] = ["err_to_human_readable", "Request", "Response"]
