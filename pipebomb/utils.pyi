from dataclasses import dataclass
from typing import Callable, Generic, Literal, Sequence, TypeAlias, TypeVar
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from zstandard import ZstdCompressor, ZstdDecompressor
import asyncio

class RequestMeta(type):
    def __dir__(cls):
        return ["return_uuid", "key", "request", "request_uuid"]
    
Primitives: TypeAlias = int | bytes | str

_gsyncio_available: bool

@dataclass
class Request(metaclass=RequestMeta):
    return_uuid: bytes
    key: bytes
    request: bytes
    request_uuid: bytes

class ResponseMeta(type):
    def __dir__(cls):
        return ["key", "response", "response_uuid"]
    
ACK: Literal[b"\x00\x45\x52\x52\x00"]

@dataclass
class Response(metaclass=ResponseMeta):
    key: bytes
    response: bytes
    response_uuid: bytes

T = TypeVar("T")

class CancelableTask(Generic[T]):
    task_id: int | None
    def __init__(self, asyncio_task: asyncio.Task[T], task_id: int | None): ...
    def cancel(self) -> bool: ...
    def done(self) -> bool: ...
    def result(self, timeout: float | None = None) -> T: ...
    def exception(self, timeout: float | None = None) -> BaseException | None: ...

def primitive(val: Primitives) -> bytes:
    """
    Converts a Primitive value to bytes
    
    Args:
        val (Primitives): The value to convert
        
    Returns:
        bytes: The Primitive in bytes
    """

def extract_packet_frame(buffer: bytes) -> tuple[bytes | None, bytes, int | None]:
    """
    Extracts a packet frame from a buffer
    
    Args:
        buffer (bytes): The buffer to extract the packet frame from
        
    Returns:
        tuple[bytes | None, bytes, int | None]: The packet frame, the remaining buffer, and the error code
    """

def construct_packet(
    data: bytes,
    cipher: ChaCha20Poly1305,
    tx_nonce: int,
    compressor: ZstdCompressor,
) -> bytes:
    """
    Constructs a packet for Pipebomb
    
    Args:
        data (bytes): The data to send
        cipher (ChaCha20Poly1305): The cipher to use
        tx_nonce (int): The nonce to use
        compressor (ZstdCompressor): The compressor to use
        
    Returns:
        bytes: The packet
    """

def verify_packet(
    packet: bytes,
    cipher: ChaCha20Poly1305,
    rx_nonce: int,
    decompressor: ZstdDecompressor,
) -> tuple[Literal[2], None] | tuple[Literal[3], None] | tuple[bytes, bytes | None]:
    """
    Verifies a packet for Pipebomb
    
    Args:
        packet (bytes): The packet to verify
        cipher (ChaCha20Poly1305): The cipher to use
        rx_nonce (int): The nonce to use
        decompressor (ZstdDecompressor): The decompressor to use
        
    Returns:
        tuple[Literal[2], None] | tuple[Literal[3], None] | tuple[bytes, bytes | None]: The data, the remaining buffer, and the error code
    """

def err_to_human_readable(err: int | bytes) -> str:
    """
    Converts an error code to a human readable string
    
    Args:
        err (int | bytes): The error code to convert
        
    Returns:
        str: The human readable string
    """
    
def _init_gsyncio() -> bool:
    """Initializes the Go gsyncio library"""

def run_task_async(
    callback: Callable[..., T], *args, **kwargs
) -> CancelableTask[T]:
    """
    Runs a callback asynchronously. Uses Go gsyncio if multithreaded mode is enabled, otherwise falls back to asyncio.
    
    Args:
        callback (Callable[..., T]): The callback to run
        *args: The arguments to pass to the callback
        **kwargs: The keyword arguments to pass to the callback
        
    Returns:
        CancelableTask[T]: The task
    """


__all__: Sequence[str] = [
    "err_to_human_readable",
    "Request",
    "Response",
    "run_task_async",
    "CancelableTask",
    "_gsyncio_available",
    "_init_gsyncio",
]
