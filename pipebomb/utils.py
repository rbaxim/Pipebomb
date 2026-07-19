"""
Pipebomb Utils
"""

import asyncio
import os
from pathlib import Path
import struct
import sys
from typing import Sequence, TypeAlias, Callable, Any, Generic, TypeVar
from zlib import crc32
from dataclasses import dataclass
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
import logging
from zstandard import ZstdCompressor, ZstdDecompressor  # pyright: ignore[reportMissingImports]
import pipebomb.gsyncio as gsy
from hmac import compare_digest

logger = logging.getLogger(__name__)

HEADER = bytes([0x91, 0x93])
FOOTER = bytes([0x80, 0x38])
FRAME_HEADER_SIZE = 6

Primitives: TypeAlias = int | bytes | str


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


ACK = bytes([00, 69, 82, 82, 00])


def primitive(val: Primitives) -> bytes:
    if isinstance(val, int):
        return str(val).encode("latin1")
    elif isinstance(val, bytes):
        return val
    elif isinstance(val, str):
        return val.encode("latin1")
    else:
        raise TypeError(f"Invalid type {type(val)}")


def extract_packet_frame(buffer: bytes) -> tuple[bytes | None, bytes, int | None]:
    if len(buffer) < FRAME_HEADER_SIZE:
        return None, buffer, None

    if buffer[:2] != HEADER:
        logger.warning(
            f"Rejected packet stream: invalid header {buffer[:2]!r}, expected {HEADER!r}"
        )
        return None, bytes(), 2

    ciphertext_size = struct.unpack(">I", buffer[2:FRAME_HEADER_SIZE])[0]
    frame_size = FRAME_HEADER_SIZE + ciphertext_size

    if len(buffer) < frame_size:
        return None, buffer, None

    return buffer[:frame_size], buffer[frame_size:], None


def construct_packet(
    data: bytes,
    cipher: ChaCha20Poly1305,
    tx_nonce: int,
    compressor: ZstdCompressor,
):
    if not data:
        raise RuntimeError("Empty packet")

    compressed_payload = compressor.compress(data)

    use_compression = len(compressed_payload) < len(data)

    if use_compression:
        flags = 0b00000001
        body = compressed_payload
    else:
        flags = 0
        body = data

    checksum = crc32(data).to_bytes(4, "big")

    plaintext = bytes([flags]) + body + checksum + FOOTER

    nonce = tx_nonce.to_bytes(12, "little")

    ciphertext = cipher.encrypt(nonce, plaintext, None)

    return HEADER + struct.pack(">I", len(ciphertext)) + ciphertext


def verify_packet(
    packet: bytes,
    cipher: ChaCha20Poly1305,
    rx_nonce: int,
    decompressor: ZstdDecompressor,
):
    nonce = rx_nonce.to_bytes(12, "little")

    logger.debug(f"Verifying packet of length {len(packet)}")

    if len(packet) < 6:
        logger.warning(f"Rejected packet: packet too short ({len(packet)} bytes)")
        return 2, None

    if packet[:2] != HEADER:
        logger.warning(
            f"Rejected packet: invalid header {packet[:2]!r}, expected {HEADER!r}"
        )
        return 2, None

    ciphertext_size = struct.unpack(">I", packet[2:6])[0]

    logger.debug(f"Ciphertext size from header: {ciphertext_size}")

    if len(packet) < 6 + ciphertext_size:
        logger.warning(
            f"Rejected packet: incomplete packet "
            f"(got {len(packet) - 6} ciphertext bytes, expected {ciphertext_size})"
        )
        return 2, None

    ciphertext = packet[6 : 6 + ciphertext_size]
    remainder = packet[6 + ciphertext_size :] or None

    if remainder is not None:
        logger.debug(f"Packet has {len(remainder)} trailing bytes")

    try:
        plaintext = cipher.decrypt(nonce, ciphertext, None)
    except InvalidTag:
        logger.error(
            f"Packet authentication failed (InvalidTag) using nonce {rx_nonce}"
        )
        return 3, None

    logger.debug(f"Successfully decrypted packet, plaintext length = {len(plaintext)}")

    if len(plaintext) < 8:
        logger.warning(f"Rejected packet: plaintext too short ({len(plaintext)} bytes)")
        return 2, None

    if plaintext[-2:] != FOOTER:
        logger.warning(
            f"Rejected packet: invalid footer {plaintext[-2:]!r}, expected {FOOTER!r}"
        )
        return 2, None

    checksum = plaintext[-6:-2]
    flags = plaintext[0]
    body = plaintext[1:-6]

    logger.debug(f"Body length = {len(body)}, checksum = {checksum.hex()}")

    if not body:
        logger.warning("Rejected packet: empty payload")
        return 2, None

    is_compressed = (flags & 0b00000001) != 0

    logger.debug(f"Compression flag = {is_compressed}")

    if is_compressed:
        logger.debug(f"Attempting to decompress {len(body)} bytes")

        try:
            payload = decompressor.decompress(
                body,
                max_output_size=2**32 - 1,
            )

            logger.debug(f"Successfully decompressed body to {len(payload)} bytes")

        except Exception as e:
            logger.warning(f"Rejected packet: zstd decompression failed: {e!r}")
            logger.debug(f"Compressed body length = {len(body)}")
            logger.debug(f"Frame magic = {body[:4].hex()}")
            return 2, None
    else:
        payload = body

    calculated_checksum = crc32(payload).to_bytes(4, "big")

    if not compare_digest(calculated_checksum, checksum):
        logger.error(
            f"Checksum mismatch: received {checksum.hex()}, "
            f"calculated {calculated_checksum.hex()}"
        )
        return 3, None

    logger.debug(f"Packet verified successfully, payload length = {len(payload)}")

    return payload, remainder


def err_to_human_readable(err: int | bytes) -> str:
    if isinstance(err, bytes):
        err = int.from_bytes(err, "big")
    match err:
        case 0:
            return "Success"  # Task failed successfully
        case 1:
            return "Unknown error"
        case 2:
            return "Invalid packet"
        case 3:
            return "Invalid crc32 or MAC"
        case 4:
            return "Invalid command"
        case 5:
            return "Key does not exist or the key already exists"
        case 6:
            return "Invalid value"
        case 7:
            return "UUID does not exist"
        case 8:
            return "Empty outbox"
        case _:
            return "Unknown error"

T = TypeVar("T")

class CancelableTask(Generic[T]):
    __slots__ = ("_asyncio_task", "_task_id", "_cancelled")

    def __init__(self, asyncio_task: asyncio.Task[T], task_id: int | None):
        self._asyncio_task = asyncio_task
        self._task_id = task_id
        self._cancelled = False

    @property
    def task_id(self) -> int | None:
        return self._task_id

    def cancel(self) -> bool:
        if self._cancelled:
            return False
        self._cancelled = True
        if self._task_id is not None:
            try:
                gsy.CancelGoTask(self._task_id)
            except (ImportError, RuntimeError):
                pass
        return self._asyncio_task.cancel()

    def done(self) -> bool:
        return self._asyncio_task.done()

    def result(self, timeout: float | None = None) -> T:
        if timeout is not None:
            return asyncio.get_event_loop().run_until_complete(
                asyncio.wait_for(self._asyncio_task, timeout=timeout)
            )
        return self._asyncio_task.result()

    def exception(self, timeout: float | None = None) -> BaseException | None:
        if timeout is not None:
            asyncio.get_event_loop().run_until_complete(
                asyncio.wait_for(self._asyncio_task, timeout=timeout)
            )
        return self._asyncio_task.exception()


_gsyncio_available: bool = False


def _init_gsyncio():
    global _gsyncio_available
    if gsy.NO_GSYNCIO_CFFI:
        logger.warning("gsyncio not available")
        return False

    go_ext = ""
    if sys.platform.startswith("win"):
        go_ext = ".pyd"
    elif sys.platform.startswith("darwin"):
        go_ext = ".dylib"
    else:
        go_ext = ".so"
    found_lib = None

    env_path = os.environ.get("GSYNCIO_PATH")
    if env_path:
        candidate = Path(env_path).resolve() / f"gsyncio{go_ext}"
        if candidate.exists():
            logger.debug(f"Using gsyncio from {candidate}")
            found_lib = str(candidate)

    if not found_lib:
        base = Path(__file__).resolve().parent.parent / "dist"
        candidate = base / f"gsyncio{go_ext}"
        if candidate.exists():
            logger.debug(f"Using gsyncio from {candidate}")
            found_lib = str(candidate)

    if not found_lib:
        local_candidate = Path(os.path.dirname(__file__), "gsyncio", f"gsyncio{go_ext}")
        if local_candidate.exists():
            logger.debug(f"Using gsyncio from {local_candidate}")
            found_lib = str(local_candidate)

    if found_lib:
        logger.info("Found gsyncio")
        gsy.load_go_library(found_lib)
        _gsyncio_available = True
    else:
        logger.warning("gsyncio not found")
        _gsyncio_available = False

    logger.debug(f"gsyncio available: {_gsyncio_available}")
    return _gsyncio_available



def run_task_async(
    callback: Callable[..., T], *args: Any, **kwargs: Any
) -> CancelableTask[T]:
    import inspect

    if inspect.iscoroutinefunction(callback):
        task = asyncio.create_task(callback(*args, **kwargs))
        return CancelableTask(task, None)

    global _gsyncio_available

    if _gsyncio_available:
        event = asyncio.Event()
        result_holder: list[T | Exception] = [None]  # type: ignore

        def wrapped():
            try:
                result_holder[0] = callback(*args, **kwargs)
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.call_soon_threadsafe(event.set)
                else:
                    event.set()
            except Exception as e:
                result_holder[0] = e
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.call_soon_threadsafe(event.set)
                else:
                    event.set()

        async def _await_wrapper() -> T:
            await event.wait()
            if isinstance(result_holder[0], Exception):
                raise result_holder[0]  # type: ignore
            return result_holder[0]  # type: ignore

        tid = gsy.get_next_task_id()
        gsy.StartGoTaskWithResult(wrapped, tid)

        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio_task = loop.create_task(_await_wrapper())
            return CancelableTask(asyncio_task, tid)
        else:
            deferred_result: list[asyncio.Task[T]] = [None]  # type: ignore

            def _deferred_create():
                t = loop.create_task(_await_wrapper())
                deferred_result[0] = t

            loop.call_soon(_deferred_create)
            while deferred_result[0] is None:
                loop.run_until_complete(asyncio.sleep(0))
            return CancelableTask(deferred_result[0], tid)
    else:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            task = loop.create_task(asyncio.to_thread(callback, *args, **kwargs))
        else:
            result_holder2: list[asyncio.Task] = [None]  # type: ignore

            def _deferred_create2():
                t = loop.create_task(asyncio.to_thread(callback, *args, **kwargs))
                result_holder2[0] = t

            loop.call_soon(_deferred_create2)
            while result_holder2[0] is None:
                loop.run_until_complete(asyncio.sleep(0))
            task = result_holder2[0]
        return CancelableTask(task, -1)


__all__: Sequence[str] = [
    "err_to_human_readable",
    "Request",
    "Response",
    "run_task_async",
    "CancelableTask",
    "_gsyncio_available",
    "_init_gsyncio",
]
