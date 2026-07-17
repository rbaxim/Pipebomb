import socket
import asyncio
from dataclasses import dataclass, replace
from uuid import uuid4
from typing import Any, TypeAlias, Union, cast, Sequence, Optional
import json
from zstandard import ZstdCompressor, ZstdDecompressor  # pyright: ignore[reportMissingImports]
from pipebomb.utils import (  # type: ignore
    verify_packet,  # pyright: ignore[reportAttributeAccessIssue]
    construct_packet,  # pyright: ignore[reportAttributeAccessIssue]
    extract_packet_frame,  # pyright: ignore[reportAttributeAccessIssue]
    err_to_human_readable,
    run_task_async,
    Request,
    Response,
    ACK,  # pyright: ignore[reportAttributeAccessIssue]
)
from pipebomb.impl import (
    FactoryDict,
    SocketAddress,
    SocketFactory,
    dict_factory,
    tcp_server_factory,
    parse_address,
    FactorySocket,
)  # type: ignore
import logging
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from hmac import compare_digest
import struct
import nest_asyncio  # type: ignore

logger = logging.getLogger(__name__)
logger.log(logging.INFO, "Applying nest_asyncio patches")
nest_asyncio.apply()


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


class NewClientTicketMeta(type):
    def __dir__(cls):
        return ["addresses_owned", "uuid", "inbox", "outbox"]


AddressBook: TypeAlias = FactoryDict[str, str]
DB: TypeAlias = FactoryDict[bytes, bytes]


@dataclass
class NewClientTicket(metaclass=NewClientTicketMeta):
    uuid: str
    addresses_owned: list[str]
    inbox: asyncio.Queue[Request]
    outbox: dict[bytes, Response]


class ClientMeta(type):
    def __dir__(cls):
        return [
            "socket",
            "address",
            "addresses_owned",
            "inbox",
            "outbox",
            "outbox_lock",
            "uuid",
            "cipher",
            "rx_nonce",
            "tx_nonce",
        ]


@dataclass
class Client(metaclass=ClientMeta):
    socket: socket.socket
    address: SocketAddress
    addresses_owned: list[str]
    inbox: asyncio.Queue[Request]
    outbox: dict[bytes, Response]
    outbox_lock: asyncio.Lock
    uuid: str
    cipher: Optional[ChaCha20Poly1305]
    rx_nonce: int
    tx_nonce: int
    active: bool


ClientDB: TypeAlias = FactoryDict[str, Client]


def factory_name(factory: Any) -> str:
    return getattr(factory, "__name__", type(factory).__name__)


class ServerMeta(type):
    def __dir__(cls):
        return ["__init__", "start", "__setitem__", "__getitem__"]


class Server(metaclass=ServerMeta):
    ERR_DISPATCH = {
        2: bytes([00, 69, 82, 82, 2]),  # invalid packet
        3: bytes([00, 69, 82, 82, 3]),  # invalid crc32
        4: bytes([00, 69, 82, 82, 4]),  # invalid command
        5: bytes([00, 69, 82, 82, 5]),  # Key does not exist or the key already exists
        6: bytes([00, 69, 82, 82, 6]),  # invalid value
        7: bytes([00, 69, 82, 82, 7]),  # uuid does not exist
    }

    __slots__ = (
        "address",
        "port",
        "socket",
        "db",
        "db_lock",
        "client_db",
        "address_book",
        "password",
        "compressor",
        "decompressor",
        "socket_factory",
        "tasks",
        "keep_dead_sessions",
    )

    def __init__(
        self,
        address="localhost",
        port=9193,
        password=b"very_secure_password",
        sock=tcp_server_factory,
        dictionary=dict_factory,
        keep_dead_sessions=False,
    ) -> None:
        logger.debug(f"Using socket factory: {factory_name(sock)}")
        logger.debug(f"Using dictionary factory: {dictionary.__name__}")
        self.address = address
        self.port = port
        self.socket_factory: SocketFactory = sock
        self.socket: FactorySocket = sock()
        self.db: DB = dictionary("db")  # pyright: ignore[reportCallIssue]
        self.db_lock = asyncio.Lock()
        self.client_db: ClientDB = dictionary("client_db")  # pyright: ignore[reportCallIssue]
        self.address_book: AddressBook = dictionary("address_book")  # pyright: ignore[reportCallIssue]
        self.password = password
        self.compressor = ZstdCompressor(level=9)
        self.decompressor = ZstdDecompressor()
        self.tasks: list[asyncio.Task] = []
        self.keep_dead_sessions = keep_dead_sessions

    async def start(self, client_accepters=1):
        bind_address = self.socket_factory.resolve_bind_address(
            self.socket, self.address, self.port
        )
        self.socket_factory.prepare_bind(self.socket, bind_address)
        self.socket.bind(bind_address)
        self.socket.listen()
        logger.info(f"Starting server on {self.socket.factory_address()}")
        for _ in range(client_accepters):
            self.tasks.append(run_task_async(self.accept_clients))

    def __getitem__(self, key):
        asyncio.get_event_loop().run_until_complete(self.db_lock.acquire())
        value = self.db[key]
        self.db_lock.release()
        return value

    def __setitem__(self, key, value):
        asyncio.get_event_loop().run_until_complete(self.db_lock.acquire())
        self.db[key] = value
        self.db_lock.release()

    def __delitem__(self, key):
        asyncio.get_event_loop().run_until_complete(self.db_lock.acquire())
        del self.db[key]
        self.db_lock.release()

    def __contains__(self, key):
        asyncio.get_event_loop().run_until_complete(self.db_lock.acquire())
        result = key in self.db
        self.db_lock.release()
        return result

    def __len__(self):
        asyncio.get_event_loop().run_until_complete(self.db_lock.acquire())
        length = len(self.db)
        self.db_lock.release()
        return length

    def keys(self):
        asyncio.get_event_loop().run_until_complete(self.db_lock.acquire())
        keys = self.db.keys()
        self.db_lock.release()
        return keys

    def values(self):
        asyncio.get_event_loop().run_until_complete(self.db_lock.acquire())
        values = self.db.values()
        self.db_lock.release()
        return values

    async def stop(self):
        logger.info("Shutting down server")
        logger.debug("Closing socket")
        self.socket.close()
        logger.debug("Clearing client db")
        self.client_db.clear()
        logger.debug("Clearing address book")
        self.address_book.clear()
        logger.debug("Clearing db")
        self.db.clear()
        logger.debug("Cleaning up tasks")
        for task in self.tasks:
            task.cancel()

    async def accept_clients(self):
        loop = asyncio.get_event_loop()
        while True:
            try:
                client_socket, client_address = await loop.sock_accept(self.socket)

                if client_address == "":
                    client_address = self.socket.factory_address() + " (Assumed)"
                client_address = parse_address(client_address)

                logger.info(f"Accepted connection from {client_address}")

                client_public_key_bytes = await read_exact(client_socket, 32)

                if len(client_public_key_bytes) != 32:
                    client_socket.close()
                    continue

                client_public_key = X25519PublicKey.from_public_bytes(
                    client_public_key_bytes
                )

                private_key = X25519PrivateKey.generate()

                public_key_bytes = private_key.public_key().public_bytes(
                    Encoding.Raw, PublicFormat.Raw
                )

                await loop.sock_sendall(client_socket, public_key_bytes)

                shared_secret = private_key.exchange(client_public_key)

                session_key = HKDF(
                    algorithm=SHA256(), length=32, salt=None, info=b"pipebomb"
                ).derive(shared_secret)

                cipher = ChaCha20Poly1305(session_key)

                tx_nonce = 0
                rx_nonce = 0

                password, _ = verify_packet(
                    await read_packet_frame(client_socket),
                    cipher,
                    rx_nonce,
                    self.decompressor,
                )

                if password == 3 or password == 2:
                    logger.warning(
                        f"Rejected {client_address} due to handshake failure. Error code {password}: {err_to_human_readable(password)}"  # pyright: ignore[reportArgumentType]
                    )
                    client_socket.close()
                    continue

                if not compare_digest(password, b"\x00" + self.password):
                    logger.warning(
                        f"Rejected {client_address} due to a invalid password"
                    )
                    client_socket.close()
                    continue

                rx_nonce += 1

                encrypted_ack = construct_packet(ACK, cipher, tx_nonce, self.compressor)

                tx_nonce += 1

                await loop.sock_sendall(client_socket, encrypted_ack)

                client_response, _ = verify_packet(
                    await read_packet_frame(client_socket),
                    cipher,
                    rx_nonce,
                    self.decompressor,
                )

                if isinstance(client_response, int):
                    logger.error(
                        f"Failed to receive client response from {client_address}: {err_to_human_readable(client_response)}"
                    )
                    continue

                rx_nonce += 1

                if client_response[0] == 0xC4:
                    logger.info("Client is relogging with same uuid")
                    uuid = cast(bytes, client_response[1:]).decode("latin1")
                    if uuid not in self.client_db:
                        logger.warning(f"Client with UUID {uuid} not found")
                        await loop.sock_sendall(
                            client_socket,
                            construct_packet(
                                self.ERR_DISPATCH[7], cipher, tx_nonce, self.compressor
                            ),
                        )
                        tx_nonce += 1

                        uuid = str(uuid4())

                        client = Client(
                            socket=client_socket,
                            address=cast(SocketAddress, client_address),
                            addresses_owned=[],
                            inbox=asyncio.Queue(),
                            outbox={},
                            outbox_lock=asyncio.Lock(),
                            uuid=uuid,
                            cipher=cipher,
                            tx_nonce=tx_nonce,
                            rx_nonce=rx_nonce,
                            active=True,
                        )

                        self.client_db[uuid] = client
                    else:
                        logger.info(f"Client with UUID {uuid} found")
                        client = self.client_db[uuid]
                        client.address = cast(SocketAddress, client_address)
                        client.socket = client_socket
                        client.cipher = cipher
                        await loop.sock_sendall(
                            client_socket,
                            construct_packet(ACK, cipher, tx_nonce, self.compressor),
                        )
                        tx_nonce += 1
                elif client_response[0] == 0xC5:
                    logger.info("Client is logging in for the first time")
                    uuid = str(uuid4())

                    client = Client(
                        socket=client_socket,
                        address=cast(SocketAddress, client_address),
                        addresses_owned=[],
                        inbox=asyncio.Queue(),
                        outbox={},
                        outbox_lock=asyncio.Lock(),
                        uuid=uuid,
                        cipher=cipher,
                        tx_nonce=tx_nonce,
                        rx_nonce=rx_nonce,
                        active=True,
                    )

                    self.client_db[uuid] = client

                    await loop.sock_sendall(
                        client_socket,
                        construct_packet(ACK, cipher, tx_nonce, self.compressor),
                    )

                    tx_nonce += 1
                else:
                    logger.warning(
                        f"Rejected {client_address} due to a invalid relog response"
                    )
                    client_socket.close()
                    continue

                client.tx_nonce = tx_nonce
                client.rx_nonce = rx_nonce

                logger.debug(f"Created client object. Client's UUID: {uuid}")
                logger.info(f"New client connected: {client_address}")

                self.tasks.append(
                    run_task_async(self.handle_client, client_socket, uuid)
                )

            except Exception as e:
                logger.exception(f"Error accepting client: {e}")

    async def handle_client(self, client_socket, uuid: str):
        event_loop = asyncio.get_event_loop()
        receive_buffer = bytes()
        peername = client_socket.getpeername()
        if peername == "":
            peername = self.socket.factory_address() + " (Assumed)"
        peername = parse_address(peername)
        clean_exit = False

        if self.client_db[uuid].cipher is None:
            raise RuntimeError(f"Client {uuid} has no cipher")

        while True:
            await asyncio.sleep(0)
            frame = None
            while frame is None:
                frame, receive_buffer, framing_error = extract_packet_frame(
                    receive_buffer
                )
                if framing_error is not None:
                    logger.error(
                        f"Error {framing_error} from {peername}: "
                        f"{err_to_human_readable(framing_error)}"
                    )
                    await event_loop.sock_sendall(
                        client_socket, self.ERR_DISPATCH[framing_error]
                    )
                    client_socket.close()
                    break
                if frame is None:
                    packet = await event_loop.sock_recv(client_socket, 1024)
                    if not packet:
                        break
                    receive_buffer += packet

            logger.info("Received packet from " + str(peername))

            data, remainder = verify_packet(
                frame,  # type: ignore
                self.client_db[uuid].cipher,  # type: ignore
                self.client_db[uuid].rx_nonce,
                self.decompressor,
            )

            if remainder is not None:
                logger.debug(
                    f"Received {len(remainder)} bytes after packet from {peername}"
                )

            self.client_db[uuid].rx_nonce += 1
            logger.debug(f"Verified packet from {peername}")

            if isinstance(data, int):
                logger.error(
                    f"Error {data} from {peername}: {err_to_human_readable(data)}"
                )
                await event_loop.sock_sendall(
                    client_socket,
                    construct_packet(
                        self.ERR_DISPATCH[data],
                        self.client_db[uuid].cipher,  # type: ignore
                        self.client_db[uuid].tx_nonce,
                        self.compressor,
                    ),
                )
                self.client_db[uuid].tx_nonce += 1
                client_socket.close()
                break

            type_, value = (cast(int, data[0]), cast(bytes, data[1:]))

            logger.debug(f"Header: 0x{type_:02X}")

            if bool(type_ & 0x80):  # Server request
                logger.info(f"Received server request from {peername}")
                opcode = (type_ & 0xF).to_bytes(1, "big")[0]
                if opcode == 1:  # SET
                    logger.info(f"Received SET command from {peername}")
                    async with self.db_lock:
                        key_length, value_length = struct.unpack(">2I", value[:8])
                        offset = 8
                        key = value[offset : offset + key_length]
                        offset += key_length
                        value = value[offset : offset + value_length]  # type: ignore
                        self.db[cast(bytes, key)] = value
                        await event_loop.sock_sendall(
                            client_socket,
                            construct_packet(
                                ACK,
                                self.client_db[uuid].cipher,  # type: ignore
                                self.client_db[uuid].tx_nonce,
                                self.compressor,
                            ),
                        )
                        self.client_db[uuid].tx_nonce += 1
                elif opcode == 2:  # GET
                    logger.info(f"Received GET command from {peername}")
                    async with self.db_lock:
                        command = value  # type: ignore
                        if command in self.db:
                            await event_loop.sock_sendall(
                                client_socket,
                                construct_packet(
                                    self.db[cast(bytes, command)],
                                    self.client_db[uuid].cipher,  # type: ignore
                                    self.client_db[uuid].tx_nonce,
                                    self.compressor,
                                ),
                            )
                            self.client_db[uuid].tx_nonce += 1
                        else:
                            await event_loop.sock_sendall(
                                client_socket,
                                construct_packet(
                                    self.ERR_DISPATCH[5],
                                    self.client_db[uuid].cipher,  # type: ignore
                                    self.client_db[uuid].tx_nonce,
                                    self.compressor,
                                ),
                            )
                            self.client_db[uuid].tx_nonce += 1
                elif opcode == 3:  # DELETE
                    logger.info(f"Received DELETE command from {peername}")
                    async with self.db_lock:
                        command = value  # type: ignore
                        if command in self.db:
                            del self.db[cast(bytes, command)]
                            await event_loop.sock_sendall(
                                client_socket,
                                construct_packet(
                                    ACK,
                                    self.client_db[uuid].cipher,  # type: ignore
                                    self.client_db[uuid].tx_nonce,
                                    self.compressor,
                                ),
                            )
                            self.client_db[uuid].tx_nonce += 1
                        else:
                            await event_loop.sock_sendall(
                                client_socket,
                                construct_packet(
                                    self.ERR_DISPATCH[5],
                                    self.client_db[uuid].cipher,  # type: ignore
                                    self.client_db[uuid].tx_nonce,
                                    self.compressor,
                                ),
                            )
                            self.client_db[uuid].tx_nonce += 1
                elif opcode == 4:  # LIST
                    logger.info(f"Received LIST command from {peername}")
                    async with self.db_lock:
                        await event_loop.sock_sendall(
                            client_socket,
                            construct_packet(
                                json.dumps(
                                    {
                                        key.decode("latin1"): value.decode("latin1")
                                        for key, value in self.db.items()
                                    }
                                ).encode("latin1"),
                                self.client_db[uuid].cipher,  # type: ignore
                                self.client_db[uuid].tx_nonce,
                                self.compressor,
                            ),
                        )
                        self.client_db[uuid].tx_nonce += 1
                elif opcode == 5:  # REGISTER
                    logger.info(f"Received REGISTER command from {peername}")
                    if value.decode("latin1") in self.address_book:
                        await event_loop.sock_sendall(
                            client_socket,
                            construct_packet(
                                self.ERR_DISPATCH[5],
                                self.client_db[uuid].cipher,  # type: ignore
                                self.client_db[uuid].tx_nonce,
                                self.compressor,
                            ),
                        )
                        self.client_db[uuid].tx_nonce += 1
                        continue
                    client = self.client_db[uuid]
                    client.addresses_owned.append(value.decode("latin1"))
                    self.address_book[value.decode("latin1")] = uuid
                    self.client_db[uuid] = client
                    await event_loop.sock_sendall(
                        client_socket,
                        construct_packet(
                            ACK,
                            self.client_db[uuid].cipher,  # type: ignore
                            self.client_db[uuid].tx_nonce,
                            self.compressor,
                        ),
                    )
                    self.client_db[uuid].tx_nonce += 1
                elif opcode == 6:  # UNREGISTER
                    logger.info(f"Received UNREGISTER command from {peername}")
                    client = self.client_db[uuid]
                    if value.decode("latin1") not in client.addresses_owned:
                        await event_loop.sock_sendall(
                            client_socket,
                            construct_packet(
                                self.ERR_DISPATCH[5],
                                self.client_db[uuid].cipher,  # type: ignore
                                self.client_db[uuid].tx_nonce,
                                self.compressor,
                            ),
                        )
                        self.client_db[uuid].tx_nonce += 1
                        continue
                    client.addresses_owned.remove(value.decode("latin1"))
                    self.address_book.pop(value.decode("latin1"))
                    self.client_db[uuid] = client
                    await event_loop.sock_sendall(
                        client_socket,
                        construct_packet(
                            ACK,
                            self.client_db[uuid].cipher,  # type: ignore
                            self.client_db[uuid].tx_nonce,
                            self.compressor,
                        ),
                    )
                    self.client_db[uuid].tx_nonce += 1
                elif opcode == 7:  # WHOAMI
                    logger.info(f"Received WHOAMI command from {peername}")
                    await event_loop.sock_sendall(
                        client_socket,
                        construct_packet(
                            uuid.encode("latin1"),
                            self.client_db[uuid].cipher,  # type: ignore
                            self.client_db[uuid].tx_nonce,
                            self.compressor,
                        ),
                    )
                    self.client_db[uuid].tx_nonce += 1
                elif opcode == 8:  # BYE
                    clean_exit = True
                    logger.info(f"Goodbye from {peername}")
                    break
                else:
                    logger.error(f"Received unknown command from {peername}")
                    await event_loop.sock_sendall(
                        client_socket,
                        construct_packet(
                            self.ERR_DISPATCH[4],
                            self.client_db[uuid].cipher,  # type: ignore
                            self.client_db[uuid].tx_nonce,
                            self.compressor,
                        ),
                    )
                    self.client_db[uuid].tx_nonce += 1
                continue
            else:  # Client request
                opcode = (type_ & 0xF).to_bytes(1, "big")[0]
                command: bytes = cast(bytes, value)  # type: ignore
                if opcode == 1:  # Ask for who has key
                    logger.info(f"Received WHOHAS command from {peername}")
                    if command.decode("latin1") in self.address_book:  # type: ignore
                        await event_loop.sock_sendall(
                            client_socket,
                            construct_packet(
                                self.address_book[command.decode("latin1")].encode(  # type: ignore
                                    "latin1"
                                ),
                                self.client_db[uuid].cipher,  # type: ignore
                                self.client_db[uuid].tx_nonce,
                                self.compressor,
                            ),
                        )
                        self.client_db[uuid].tx_nonce += 1
                    else:
                        await event_loop.sock_sendall(
                            client_socket,
                            construct_packet(
                                self.ERR_DISPATCH[5],
                                self.client_db[uuid].cipher,  # type: ignore
                                self.client_db[uuid].tx_nonce,
                                self.compressor,
                            ),
                        )
                        self.client_db[uuid].tx_nonce += 1
                elif opcode == 2:  # Put request in inbox
                    logger.info(f"Received PUT_INBOX command from {peername}")

                    target_length, req_length, key_length = struct.unpack(
                        ">3I", value[:12]
                    )
                    offset = 12
                    target = value[offset : offset + target_length]
                    offset += target_length
                    request = value[offset : offset + req_length]  # type: ignore
                    offset += req_length
                    key = value[offset : offset + key_length]  # type: ignore

                    operation_id = uuid4().bytes
                    await self.client_db[target.decode("latin1")].inbox.put(
                        Request(uuid.encode("latin1"), key, request, operation_id)  # type: ignore
                    )
                    await event_loop.sock_sendall(
                        client_socket,
                        construct_packet(
                            operation_id,
                            self.client_db[uuid].cipher,  # type: ignore
                            self.client_db[uuid].tx_nonce,
                            self.compressor,
                        ),
                    )
                    self.client_db[uuid].tx_nonce += 1
                elif opcode == 3:  # Get request from inbox
                    logger.info(f"Received GET_INBOX command from {peername}")
                    client = self.client_db[uuid]
                    request: Request = await client.inbox.get()  # type: ignore
                    retreq_length = len(request.return_uuid)  # type: ignore
                    req_length = len(request.request)  # type: ignore
                    key_length = len(request.key)  # type: ignore
                    req_uuid_length = len(request.request_uuid)  # type: ignore

                    await event_loop.sock_sendall(
                        client_socket,
                        construct_packet(
                            struct.pack(">I", retreq_length)
                            + struct.pack(">I", req_length)
                            + struct.pack(">I", key_length)
                            + struct.pack(">I", req_uuid_length)
                            + request.return_uuid  # type: ignore
                            + request.request  # type: ignore
                            + request.key  # type: ignore
                            + request.request_uuid,  # type: ignore
                            self.client_db[uuid].cipher,  # type: ignore
                            self.client_db[uuid].tx_nonce,
                            self.compressor,
                        ),
                    )
                    self.client_db[uuid].tx_nonce += 1
                elif opcode == 4:  # Write response to outbox
                    logger.info(f"Received PUT_OUTBOX command from {peername}")
                    target_length, res_length, key_length, req_uuid_length = (
                        struct.unpack(">4I", value[:16])
                    )
                    offset = 16
                    target = value[offset : offset + target_length]
                    offset += target_length
                    res = value[offset : offset + res_length]
                    offset += res_length
                    key = value[offset : offset + key_length]  # type: ignore
                    offset += key_length
                    req_uuid = value[offset : offset + req_uuid_length]
                    client = self.client_db[target.decode("latin1")]
                    async with client.outbox_lock:
                        client.outbox[req_uuid] = Response(key, res, req_uuid)  # type: ignore
                    await event_loop.sock_sendall(
                        client_socket,
                        construct_packet(
                            ACK,
                            self.client_db[uuid].cipher,  # type: ignore
                            self.client_db[uuid].tx_nonce,
                            self.compressor,
                        ),
                    )
                    self.client_db[uuid].tx_nonce += 1
                elif opcode == 5:
                    logger.info(f"Received GET_OUTBOX command from {peername}")
                    req_uuid = command  # type: ignore
                    client = self.client_db[uuid]
                    async with client.outbox_lock:
                        if req_uuid not in client.outbox:
                            await event_loop.sock_sendall(
                                client_socket,
                                construct_packet(
                                    self.ERR_DISPATCH[7],
                                    self.client_db[uuid].cipher,  # type: ignore
                                    self.client_db[uuid].tx_nonce,
                                    self.compressor,
                                ),
                            )
                            self.client_db[uuid].tx_nonce += 1
                        else:
                            response = client.outbox.pop(req_uuid)
                            key_length = len(response.key)
                            res_length = len(response.response)
                            await event_loop.sock_sendall(
                                client_socket,
                                construct_packet(
                                    struct.pack(">I", key_length)
                                    + struct.pack(">I", res_length)
                                    + response.key
                                    + response.response,
                                    self.client_db[uuid].cipher,  # type: ignore
                                    self.client_db[uuid].tx_nonce,
                                    self.compressor,
                                ),
                            )
                            self.client_db[uuid].tx_nonce += 1
                else:
                    logger.error(f"Received unknown command from {peername}")
                    await event_loop.sock_sendall(
                        client_socket,
                        construct_packet(
                            self.ERR_DISPATCH[4],
                            self.client_db[uuid].cipher,  # type: ignore
                            self.client_db[uuid].tx_nonce,
                            self.compressor,
                        ),
                    )
                    self.client_db[uuid].tx_nonce += 1

        if not clean_exit:
            logger.warning(f"{peername} abruptly disconnected. Bye {peername}")

        if not self.keep_dead_sessions:
            for key, client_uuid in self.address_book.items():  # type: ignore
                if client_uuid == uuid:
                    # No idea what the problem with fstrings and bytes is below
                    logger.debug(f"Removing '{key}' from address book")  # type: ignore
                    del self.address_book[key]  # type: ignore
                    break

            if uuid in self.client_db:
                logger.debug(f"Removing {uuid} from client db")
                del self.client_db[uuid]

            logger.debug(f"Closing connection to {peername}")
            try:
                client_socket.close()
            except Exception as e:
                logger.error(f"Error occurred while closing socket for {peername}: {e}")
        else:
            logger.info(f"Keeping dead session for {peername} alive")

    async def add_client(self, client_ticket: NewClientTicket):
        logger.info("Adding preset client to client db")

        if len(client_ticket.uuid) != 36:
            raise ValueError("UUID must be 36 characters long")

        if client_ticket.uuid in self.client_db:
            raise ValueError("Client already in client db")

        for response_uuid, response in client_ticket.outbox.items():
            if response_uuid != response.response_uuid:
                raise ValueError("Response UUIDs do not match")

        client = Client(
            FactorySocket(),
            ("unknown", 0),
            client_ticket.addresses_owned,
            client_ticket.inbox,
            client_ticket.outbox,
            asyncio.Lock(),
            client_ticket.uuid,
            None,
            0,
            0,
            active=False,
        )
        self.client_db[client_ticket.uuid] = client

    async def get_client(self, uuid: str) -> Client:
        logger.info("Getting client from client db")
        if len(uuid) != 36:
            raise ValueError("UUID must be 36 characters long")

        if uuid not in self.client_db:
            raise ValueError("Client not in client db")

        client_clone = replace(
            self.client_db[uuid],
            cipher=None,
            socket=FactorySocket(),
            tx_nonce=0,
            rx_nonce=0,
        )

        return client_clone

    async def check_client(self, uuid: str) -> bool:
        logger.info("Checking if client exists in client db")
        if len(uuid) != 36:
            raise ValueError("UUID must be 36 characters long")
        return uuid in self.client_db

    async def remove_client(self, uuid: str):
        logger.info("Removing client from client db")
        if len(uuid) != 36:
            raise ValueError("UUID must be 36 characters long")
        if uuid not in self.client_db:
            raise ValueError("Client not in client db")
        client = self.client_db[uuid]
        try:
            client.socket.close()  # Prevent future modifications
        except Exception:
            pass
        for key in client.addresses_owned:
            del self.address_book[key]
        del self.client_db[uuid]

    async def apply_client_state(self, client_ticket: NewClientTicket, strict=True):
        logger.info("Applying a new client state")
        uuid = client_ticket.uuid
        if len(uuid) != 36:
            raise ValueError("UUID must be 36 characters long")
        if uuid not in self.client_db:
            raise ValueError("Client not in client db. Use add_client first.")
        client = self.client_db[uuid]
        client.inbox = client_ticket.inbox
        async with client.outbox_lock:
            client.outbox = client_ticket.outbox

        for key in client_ticket.addresses_owned:
            if key not in self.address_book:
                if strict:
                    logger.error(f"Key {key} not in address book")
                    raise ValueError("Key not in address book")
                else:
                    logger.warning(f"Key {key} not in address book.")
                    self.address_book[key] = uuid

        client.addresses_owned = client_ticket.addresses_owned

    async def add_key(self, key: str, uuid: str):
        if len(uuid) != 36:
            raise ValueError("UUID must be 36 characters long")
        if key in self.address_book:
            raise ValueError("Key already exists")
        self.address_book[key] = uuid
        try:
            self.client_db[uuid].addresses_owned.append(key)
        except KeyError as e:
            raise ValueError("Client not in client db") from e

    async def get_key(self, key: str) -> str:
        if key not in self.address_book:
            raise ValueError("Key not in address book")
        return self.address_book[key]

    async def check_key(self, key: str, uuid: str) -> bool:
        if len(uuid) != 36:
            raise ValueError("UUID must be 36 characters long")
        return key in self.address_book and self.address_book[key] == uuid

    async def remove_key(self, key: str, uuid: str):
        if len(uuid) != 36:
            raise ValueError("UUID must be 36 characters long")
        try:
            del self.address_book[key]
        except KeyError as e:
            raise ValueError("Key not in address book") from e
        try:
            self.client_db[uuid].addresses_owned.remove(key)
        except KeyError as e:
            raise ValueError("Client not in client db") from e

    async def set_db(self, key: bytes, value: bytes):
        async with self.db_lock:
            self.db[key] = value

    async def get_db(self, key: bytes) -> bytes:
        async with self.db_lock:
            return self.db[key]

    async def remove_db(self, key: bytes) -> None:
        async with self.db_lock:
            del self.db[key]

    async def get_all_clients(self):
        return list(self.client_db.keys())

    async def get_all_keys(self):
        return list(self.address_book.keys())

    async def apply_state(self, db, client_db, address_book):
        self.db = db
        self.client_db = client_db
        self.address_book = address_book


async def serialize(obj: Server) -> bytes:
    table_of_t: list[bytes] = []
    table_of_l: list[bytes] = []
    table_of_v: list[bytes] = []

    def add_field(field_type: int, value: bytes) -> None:
        table_of_t.append(bytes((field_type,)))
        table_of_l.append(struct.pack(">I", len(value)))
        table_of_v.append(value)

    for key, value in obj.db.items():
        add_field(0x10, key)
        add_field(0x11, value)

    for key, uuid in obj.address_book.items():
        if len(uuid) != 36:
            raise ValueError("UUID must be 36 characters long")
        add_field(
            0x20,
            struct.pack(">I", len(key)) + key.encode("latin1"),
        )
        add_field(
            0x21,
            uuid.encode("latin1"),
        )

    for client in obj.client_db.values():
        if len(client.uuid) != 36:
            raise ValueError("UUID must be 36 characters long")
        add_field(
            0x30,
            client.uuid.encode("latin1"),
        )

        addresses_owned: bytes = b"".join(
            struct.pack(">I", len(address.encode("latin1"))) + address.encode("latin1")
            for address in client.addresses_owned
        )

        add_field(
            0x31,
            client.uuid.encode("latin1") + addresses_owned,
        )

        inbox_items: list[bytes] = []

        while True:
            try:
                request: Request = client.inbox.get_nowait()
            except asyncio.QueueEmpty:
                break

            inbox_items.append(
                struct.pack(">I", len(request.return_uuid))
                + request.return_uuid
                + struct.pack(">I", len(request.key))
                + request.key
                + struct.pack(">I", len(request.request))
                + request.request
                + struct.pack(">I", len(request.request_uuid))
                + request.request_uuid
            )

        add_field(
            0x32,
            client.uuid.encode("latin1") + b"".join(inbox_items),
        )
        async with client.outbox_lock:
            outbox_items: list[bytes] = [
                struct.pack(">I", len(response.key))
                + response.key
                + struct.pack(">I", len(response.response))
                + response.response
                + struct.pack(">I", len(response.response_uuid))
                + response.response_uuid
                for response in client.outbox.values()
            ]

        add_field(
            0x33,
            client.uuid.encode("latin1") + b"".join(outbox_items),
        )

    type_table: bytes = b"".join(table_of_t)
    length_table: bytes = b"".join(table_of_l)
    value_table: bytes = b"".join(table_of_v)

    serialized_data: bytes = (
        struct.pack(">III", len(type_table), len(length_table), len(value_table))
        + type_table
        + length_table
        + value_table
    )

    compressed_data: bytes = ZstdCompressor(level=22).compress(serialized_data)

    return struct.pack(">I", 0x91938038) + compressed_data


async def deserialize(
    data: bytes,
    server: Optional[Server] = None,
) -> Union[tuple[DB, AddressBook, ClientDB], Server]:
    magic: int = struct.unpack_from(">I", data, 0)[0]

    if magic != 0x91938038:
        raise ValueError(f"Invalid magic 0x{magic:08X}, expected 0x91938038.")

    compressed_data: bytes = data[4:]
    serialized_data: bytes = ZstdDecompressor().decompress(compressed_data)

    (
        type_table_length,
        length_table_length,
        value_table_length,
    ) = struct.unpack_from(">III", serialized_data, 0)

    offset: int = 12

    table_of_t: bytes = serialized_data[offset : offset + type_table_length]
    offset += type_table_length

    table_of_l_data: bytes = serialized_data[offset : offset + length_table_length]
    offset += length_table_length

    table_of_v_data: bytes = serialized_data[offset : offset + value_table_length]

    table_of_l: list[int] = [
        struct.unpack_from(">I", table_of_l_data, i)[0]
        for i in range(0, length_table_length, 4)
    ]

    table_of_v: list[bytes] = []

    offset = 0
    for length in table_of_l:
        table_of_v.append(table_of_v_data[offset : offset + length])
        offset += length

    db: DB = FactoryDict("db")
    address_book: AddressBook = FactoryDict("address_book")
    client_db: ClientDB = FactoryDict("client_db")

    pending_db_key: bytes | None = None
    pending_address: str | None = None

    for field_type, value in zip(table_of_t, table_of_v, strict=True):
        if field_type == 0x10:
            pending_db_key = value

        elif field_type == 0x11:
            if pending_db_key is None:
                raise ValueError("Encountered DB value without a preceding DB key.")

            db[pending_db_key] = value
            pending_db_key = None

        elif field_type == 0x20:
            key_length: int = struct.unpack_from(">I", value, 0)[0]

            pending_address = value[4 : 4 + key_length].decode("latin1")

        elif field_type == 0x21:
            if pending_address is None:
                raise ValueError(
                    "Encountered address UUID without a preceding address."
                )

            address_book[pending_address] = value.decode("latin1")
            pending_address = None

        elif field_type == 0x30:
            client_uuid: str = value.decode("latin1")

            client_db[client_uuid] = Client(
                socket=FactorySocket(),
                address=("unknown", 0),
                addresses_owned=[],
                inbox=asyncio.Queue(),
                outbox={},
                outbox_lock=asyncio.Lock(),
                uuid=client_uuid,
                cipher=None,
                rx_nonce=0,
                tx_nonce=0,
                active=False,
            )

        elif field_type == 0x31:
            client_uuid: str = value[:36].decode("latin1")
            try:
                client: Client = client_db[client_uuid]
            except KeyError as e:
                raise ValueError(
                    "Client not found in client db. This likely means a malformed UUID"
                ) from e
            cursor: int = 36

            while cursor < len(value):
                address_length: int = struct.unpack_from(">I", value, cursor)[0]
                cursor += 4

                client.addresses_owned.append(
                    value[cursor : cursor + address_length].decode("latin1")
                )

                cursor += address_length

        elif field_type == 0x32:
            client_uuid: str = value[:36].decode("latin1")
            client: Client = client_db[client_uuid]

            cursor: int = 36

            while cursor < len(value):
                return_uuid_length: int = struct.unpack_from(">I", value, cursor)[0]
                cursor += 4

                return_uuid: bytes = value[cursor : cursor + return_uuid_length]
                cursor += return_uuid_length

                key_length: int = struct.unpack_from(">I", value, cursor)[0]
                cursor += 4

                key: bytes = value[cursor : cursor + key_length]
                cursor += key_length

                request_length: int = struct.unpack_from(">I", value, cursor)[0]
                cursor += 4

                request: bytes = value[cursor : cursor + request_length]
                cursor += request_length

                request_uuid_length: int = struct.unpack_from(">I", value, cursor)[0]
                cursor += 4

                request_uuid: bytes = value[cursor : cursor + request_uuid_length]
                cursor += request_uuid_length

                client.inbox.put_nowait(
                    Request(
                        return_uuid=return_uuid,
                        key=key,
                        request=request,
                        request_uuid=request_uuid,
                    )
                )

        elif field_type == 0x33:
            client_uuid: str = value[:36].decode("latin1")
            client: Client = client_db[client_uuid]

            cursor: int = 36

            while cursor < len(value):
                key_length: int = struct.unpack_from(">I", value, cursor)[0]
                cursor += 4

                key: bytes = value[cursor : cursor + key_length]
                cursor += key_length

                response_length: int = struct.unpack_from(">I", value, cursor)[0]
                cursor += 4

                response: bytes = value[cursor : cursor + response_length]
                cursor += response_length

                response_uuid_length: int = struct.unpack_from(">I", value, cursor)[0]
                cursor += 4

                response_uuid: bytes = value[cursor : cursor + response_uuid_length]
                cursor += response_uuid_length

                client.outbox[response_uuid] = Response(
                    key=key,
                    response=response,
                    response_uuid=response_uuid,
                )

    if server is not None:
        await server.apply_state(db, client_db, address_book)
        return server
    else:
        return db, address_book, client_db


__all__: Sequence[str] = ["Server", "serialize", "deserialize"]
