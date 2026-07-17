from dataclasses import dataclass
from typing import Callable, Literal, TypeVar, Sequence, TypeAlias
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from zstandard import ZstdCompressor, ZstdDecompressor
import asyncio

T = TypeVar("T")

class RequestMeta(type):
    def __dir__(cls):
        return ["return_uuid", "key", "request", "request_uuid"]

Primitives: TypeAlias = int | bytes | str

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

def primitive(val: Primitives) -> bytes:
    """
    Converts a Primitive value to bytes

    Args:
        val (Primitives): The value to convert

    Returns:
        bytes

    Raises:
        TypeError: If the value is not a primitive
    """

def extract_packet_frame(buffer: bytes) -> tuple[bytes | None, bytes, int | None]:
    """
    Extracts a packet frame from a buffer

    Args:
        buffer (bytes): The buffer to extract the packet frame from

    Returns:
        tuple[bytes | None, bytes, int | None]
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
        data (bytes): The data to construct the packet from
        cipher (ChaCha20Poly1305): The cipher used to encrypt the packet
        tx_nonce (int): The nonce used to encrypt the packet
        compressor: ZstdCompressor

    Returns:
        bytes
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
        cipher (ChaCha20Poly1305): The cipher used to encrypt the packet
        rx_nonce (int): The nonce used to encrypt the packet
        decompressor (ZstdDecompressor): The decompressor used to decompress the packet

    Returns:
        tuple[Literal[2], None] | tuple[Literal[3], None] | tuple[bytes, bytes | None]
    """

def err_to_human_readable(err: int) -> str:
    """
    Converts an error code to a human readable string

    Args:
        err (int): The error code to convert

    Returns:
        str
    """

def run_task_async(
    callback: Callable[..., T], *args, task_id: int | None = None, **kwargs
) -> asyncio.Task[T]:
    """
    Runs a callback asynchronously. Uses Go gsyncio if available, otherwise falls back to asyncio.to_thread.

    Args:
        callback: The function to run in a background task
        *args: Positional arguments passed to the callback
        task_id: Optional task identifier for gsyncio tracking
        **kwargs: Keyword arguments passed to the callback

    Returns:
        An asyncio.Task that resolves when the callback completes
    """

__all__: Sequence[str] = [
    "err_to_human_readable",
    "Request",
    "Response",
    "run_task_async",
]
