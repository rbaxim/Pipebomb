from pipebomb.impl import tcp_factory, parse_address
from zstandard import ZstdCompressor, ZstdDecompressor  # pyright: ignore[reportMissingImports]
from pipebomb.utils import (  # type: ignore
    verify_packet,  # pyright: ignore[reportAttributeAccessIssue]
    construct_packet,  # pyright: ignore[reportAttributeAccessIssue]
    extract_packet_frame,  # pyright: ignore[reportAttributeAccessIssue]
    err_to_human_readable,
    Request,
    Response,
    ACK,  # pyright: ignore[reportAttributeAccessIssue]
    Primitives,  # pyright: ignore[reportAttributeAccessIssue]
    primitive,  # pyright: ignore[reportAttributeAccessIssue]
)
import asyncio
import socket
from typing import Any, Literal, TypedDict, cast, Sequence
import logging
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
import struct
import warnings
import json


def convert_to_length_format(*args):
    output = bytes([])
    for arg in args:
        output = output + struct.pack(">I", len(arg))

    return output


logger = logging.getLogger(__name__)


def factory_name(factory: Any) -> str:
    return getattr(factory, "__name__", type(factory).__name__)


async def read_exact(socket: socket.socket, size: int) -> bytes:
    loop = asyncio.get_event_loop()
    buffer = bytes()

    while len(buffer) < size:
        chunk = await loop.sock_recv(socket, size - len(buffer))
        if not chunk:
            break
        buffer += chunk

    return buffer


async def read_packet_frame(socket: socket.socket) -> bytes:
    loop = asyncio.get_event_loop()
    buffer = bytes()

    while True:
        frame, buffer, framing_error = extract_packet_frame(buffer)
        if framing_error is not None:
            raise RuntimeError(
                f"Invalid packet frame: {err_to_human_readable(framing_error)}"
            )
        if frame is not None:
            return frame

        chunk = await loop.sock_recv(socket, 1024)
        if not chunk:
            raise RuntimeError("Connection closed while waiting for packet frame")
        buffer += chunk


class Task(TypedDict):
    goal: Literal["send"]
    parameters: bytes


class RawClientMeta(type):
    def __dir__(cls):
        return ["__init__", "connect", "send", "receive"]


class InvalidRelogUUID(UserWarning):
    pass


class RawClient(metaclass=RawClientMeta):
    __slots__ = (
        "socket",
        "address",
        "port",
        "tasks",
        "input_packets",
        "tx_nonce",
        "rx_nonce",
        "cipher",
        "password",
        "compressor",
        "decompressor",
        "socket_factory",
    )

    def __init__(
        self,
        address="localhost",
        port=9193,
        password=b"very_secure_password",
        sock=tcp_factory,
    ) -> None:
        logger.debug(f"Using socket factory: {factory_name(sock)}")
        self.socket_factory = sock
        self.socket = sock()
        self.address = address
        self.port = port
        self.tasks: asyncio.Queue[Task] = asyncio.Queue()
        self.input_packets: asyncio.Queue[bytes] = asyncio.Queue()
        self.tx_nonce = 0
        self.rx_nonce = 0
        self.cipher: None | ChaCha20Poly1305 = None
        self.password = password
        self.compressor: ZstdCompressor = ZstdCompressor(level=9)
        self.decompressor: ZstdDecompressor = ZstdDecompressor()

    async def connect(self, relog_uuid=None):
        loop = asyncio.get_event_loop()
        socket_address = await self.socket_factory.resolve_connect_address(
            self.socket, self.address, self.port
        )
        logger.info(f"Connecting to {parse_address(socket_address)}")

        await loop.sock_connect(self.socket, socket_address)

        private_key = X25519PrivateKey.generate()

        public_key_bytes = private_key.public_key().public_bytes(
            Encoding.Raw, PublicFormat.Raw
        )

        await loop.sock_sendall(self.socket, public_key_bytes)

        server_public_key_bytes = await read_exact(self.socket, 32)

        if len(server_public_key_bytes) != 32:
            raise RuntimeError("Failed to receive server public key")

        server_public_key = X25519PublicKey.from_public_bytes(server_public_key_bytes)

        shared_secret = private_key.exchange(server_public_key)

        session_key = HKDF(
            algorithm=SHA256(), length=32, salt=None, info=b"pipebomb"
        ).derive(shared_secret)

        self.cipher = ChaCha20Poly1305(session_key)

        await loop.sock_sendall(
            self.socket,
            construct_packet(
                b"\x00" + self.password, self.cipher, self.tx_nonce, self.compressor
            ),
        )

        self.tx_nonce += 1

        encrypted_ack = await read_packet_frame(self.socket)

        if not encrypted_ack:
            if encrypted_ack == b"":
                logger.error(
                    f"Unable to connect to {parse_address(socket_address)}. Handshake failure"
                )
                raise RuntimeError(
                    f"Unable to connect to {parse_address(socket_address)}. Handshake Failure"
                )
            else:
                logger.error(
                    f"Unable to connect to {parse_address(socket_address)}. ACK not received"
                )
            logger.debug(f"Recieved {repr(encrypted_ack)}")

            raise RuntimeError(
                f"Unable to connect to {parse_address(socket_address)}. ACK not received"
            )

        ack, _ = verify_packet(
            encrypted_ack, self.cipher, self.rx_nonce, self.decompressor
        )

        self.rx_nonce += 1

        if isinstance(ack, int):
            logger.error(
                f"Unable to connect to {parse_address(socket_address)}."
                f"ACK returned error: Error {ack}: {err_to_human_readable(ack)}"
            )

            raise RuntimeError(
                f"Unable to connect to {parse_address(socket_address)}."
                f"ACK returned error: Error {ack}: {err_to_human_readable(ack)}"
            )

        if ack != ACK:
            logger.debug(f"Recieved {repr(ack)} instead of {repr(ACK)}")
            raise RuntimeError("Invalid ACK")

        if relog_uuid is not None:
            await loop.sock_sendall(
                self.socket,
                construct_packet(
                    bytes([0xC4]) + relog_uuid,
                    self.cipher,
                    self.tx_nonce,
                    self.compressor,
                ),
            )
        else:
            await loop.sock_sendall(
                self.socket,
                construct_packet(
                    bytes([0xC5]), self.cipher, self.tx_nonce, self.compressor
                ),
            )

        self.tx_nonce += 1

        ack, _ = verify_packet(
            await read_packet_frame(self.socket),
            self.cipher,
            self.rx_nonce,
            self.decompressor,
        )

        self.rx_nonce += 1

        if ack != ACK:
            logger.warning("Invalid Relog UUID")
            warnings.warn("Invalid Relog UUID", InvalidRelogUUID)

        logger.info(f"Connected to {socket_address}")

        asyncio.create_task(self.handle_connection(self.socket))

    async def handle_connection(self, socket):
        event_loop = asyncio.get_event_loop()

        async def send_loop():
            while True:
                task = await self.tasks.get()
                if task["goal"] == "send":
                    logger.debug(
                        f"Sending packet to {parse_address(socket.getpeername())}"
                    )
                    await event_loop.sock_sendall(socket, task["parameters"])
                    self.tx_nonce += 1
                    self.tasks.task_done()

        async def recv_loop():
            receive_buffer = bytes()
            while True:
                try:
                    frame = None

                    while frame is None:
                        frame, receive_buffer, framing_error = extract_packet_frame(
                            receive_buffer
                        )
                        if framing_error is not None:
                            raise RuntimeError(
                                f"Error {framing_error} from {parse_address(socket.getpeername())}: "
                                f"{err_to_human_readable(framing_error)}"
                            )

                        if frame is None:
                            packet = await event_loop.sock_recv(socket, 1024)
                            if not packet:
                                return
                            receive_buffer += packet

                    logger.info(
                        f"Received packet from {parse_address(socket.getpeername())}"
                    )

                    packet, remainder = verify_packet(
                        frame,
                        self.cipher,  # pyright: ignore[reportArgumentType]
                        self.rx_nonce,
                        self.decompressor,  # pyright: ignore[reportArgumentType]
                    )

                    if remainder is not None:
                        logger.debug(
                            f"Received {len(remainder)} bytes after packet from {parse_address(socket.getpeername())}"
                        )

                    if packet == b"ERR\x00":
                        logger.info(
                            f"Received ACK from {parse_address(socket.getpeername())}"
                        )
                        if not self.tasks.empty():
                            self.tasks.task_done()

                    if isinstance(packet, int):
                        logger.error(
                            f"Error {packet} from {parse_address(socket.getpeername())}: {err_to_human_readable(packet)}"
                        )
                        raise RuntimeError(
                            f"Error {packet} from {parse_address(socket.getpeername())}: {err_to_human_readable(packet)}"
                        )

                    if not isinstance(packet, int):
                        self.rx_nonce += 1

                    packet = cast(bytes, packet)

                    if packet.startswith(b"ERR") and packet != b"ERR\x00":
                        logger.error(
                            f"Error {int.from_bytes(packet[3:], 'big')} from {parse_address(socket.getpeername())}: {err_to_human_readable(packet[3:])}"  # pyright: ignore[reportArgumentType]
                        )
                        raise RuntimeError(
                            f"Error {int.from_bytes(packet[3:], 'big')} from {parse_address(socket.getpeername())}: {err_to_human_readable(packet[3:][0])}"
                        )

                    await self.input_packets.put(packet)
                except Exception as e:
                    logger.error(
                        f"Error receiving packet from {parse_address(socket.getpeername())}: {e}"
                    )
                    raise RuntimeError(
                        f"Error receiving packet from {parse_address(socket.getpeername())}: {e}"
                    ) from e

        try:
            await asyncio.gather(send_loop(), recv_loop())
        except Exception as e:
            logger.error(
                f"Error handling connection to {parse_address(socket.getpeername())}: {e}"
            )
            raise RuntimeError(
                f"Error handling connection to {parse_address(socket.getpeername())}: {e}"
            ) from e
        finally:
            socket.close()

    async def send(self, data: bytes):
        packet = construct_packet(data, self.cipher, self.tx_nonce, self.compressor)  # type: ignore
        await self.tasks.put(Task(goal="send", parameters=packet))

    async def receive(self) -> bytes:
        try:
            packet = await asyncio.wait_for(self.input_packets.get(), 5)
        except asyncio.TimeoutError as e:
            raise RuntimeError("Timeout waiting for packet to arrive") from e
        return packet

    async def close(self) -> None:
        logger.info(f"Closing connection to {parse_address(self.socket.getpeername())}")
        if self.cipher is None:
            raise RuntimeError("Cipher is None")
        packet = construct_packet(
            bytes([0x88]),
            self.cipher,
            self.tx_nonce,
            self.compressor,  # type: ignore
        )  # type: ignore
        event_loop = asyncio.get_event_loop()
        await event_loop.sock_sendall(self.socket, packet)
        self.tx_nonce = 0
        self.rx_nonce = 0
        self.cipher = None
        try:
            self.socket.close()
        except Exception:
            pass


class ClientMeta(type):
    def __dir__(cls):
        return [
            "__init__",
            "connect",
            "set",
            "get",
            "delete",
            "list",
            "register",
            "unregister",
            "whoami",
            "find",
            "request",
            "read_inbox",
            "respond",
            "read_outbox",
        ]


class Client(metaclass=ClientMeta):
    __slots__ = ["client"]

    def __init__(
        self,
        address="localhost",
        port=9193,
        password=b"very_secure_password",
        sock=tcp_factory,
    ):
        self.client = RawClient(address, port, password, sock)

    async def connect(self, relog_uuid=None):
        await self.client.connect(relog_uuid)

    async def set(self, key: Primitives, value: Primitives) -> bool:
        await self.client.send(
            bytes([0x81])
            + convert_to_length_format(primitive(key), primitive(value))
            + primitive(key)
            + primitive(value)
        )
        return await self.client.receive() == ACK

    async def get(self, key: Primitives) -> bytes:
        await self.client.send(bytes([0x82]) + primitive(key))
        return await self.client.receive()

    async def delete(self, key: Primitives) -> bool:
        await self.client.send(bytes([0x83]) + primitive(key))
        return await self.client.receive() == ACK

    async def list(self) -> dict[str, str]:
        await self.client.send(bytes([0x84]))
        return json.loads(await self.client.receive())

    async def register(self, key: Primitives) -> bool:
        await self.client.send(bytes([0x85]) + primitive(key))
        return await self.client.receive() == ACK

    async def unregister(self, key: Primitives) -> bool:
        await self.client.send(bytes([0x86]) + primitive(key))
        return await self.client.receive() == ACK

    async def whoami(self):
        await self.client.send(bytes([0x87]))
        return await self.client.receive()

    async def find(self, key: Primitives) -> bytes:
        await self.client.send(bytes([0x1]) + primitive(key))
        return await self.client.receive()

    async def request(self, uuid: bytes, request: Primitives, key: Primitives) -> bytes:
        p_request = primitive(request)
        p_key = primitive(key)
        await self.client.send(
            bytes([0x2])
            + convert_to_length_format(uuid, p_request, p_key)
            + uuid
            + p_request
            + p_key
        )
        res = await self.client.receive()

        return res

    async def read_inbox(self) -> Request:
        await self.client.send(bytes([0x3]))
        res = await self.client.receive()

        uuid_length, req_length, key_length, req_uuid_length = struct.unpack(
            ">4I", res[:16]
        )
        offset = 16
        uuid = res[offset : offset + uuid_length]
        offset += uuid_length
        req = res[offset : offset + req_length]
        offset += req_length
        key = res[offset : offset + key_length]
        offset += key_length
        req_uuid = res[offset : offset + req_uuid_length]

        return Request(uuid, key, req, req_uuid)

    async def respond(
        self,
        target_uuid: bytes,
        response: Primitives,
        key: Primitives,
        request_uuid: bytes,
    ) -> bool:
        response = primitive(response)
        key = primitive(key)
        await self.client.send(
            bytes([0x4])
            + convert_to_length_format(target_uuid, response, key, request_uuid)
            + target_uuid
            + response
            + key
            + request_uuid
        )
        res = await self.client.receive()

        return res == ACK

    async def read_outbox(self, request_uuid: bytes) -> Response:
        await self.client.send(bytes([0x5]) + request_uuid)
        res = await self.client.receive()

        if len(res) < 9:
            raise RuntimeError(f"Invalid response. Too short: {len(res)} bytes")

        key_length, res_length = struct.unpack(">2I", res[:8])
        offset = 8
        key = res[offset : offset + key_length]
        offset += key_length
        response = res[offset : offset + res_length]

        return Response(key, response, request_uuid)

    async def close(self):
        await self.client.close()


__all__: Sequence[str] = ["RawClient", "Client"]
