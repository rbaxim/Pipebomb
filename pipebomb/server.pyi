"""
Pipebomb server
"""

from dataclasses import dataclass
import socket
import asyncio
from typing import Optional, Sequence, TypeAlias, Union, overload
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from pipebomb.impl import (
    DictFactory,
    FactoryDict,
    SocketAddress,
    SocketFactory,
    dict_factory,
    tcp_server_factory,
)
from pipebomb.utils import Request, Response
from _collections_abc import dict_keys, dict_values

class NewClientTicketMeta(type):
    def __dir__(cls):
        return ["addresses_owned", "uuid", "inbox", "outbox"]

@dataclass
class NewClientTicket(NewClientTicketMeta):
    uuid: str
    addresses_owned: list
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
    addresses_owned: list
    inbox: asyncio.Queue[Request]
    outbox: dict[bytes, Response]
    outbox_lock: asyncio.Lock
    uuid: str
    cipher: ChaCha20Poly1305
    rx_nonce: int
    tx_nonce: int

ClientDB: TypeAlias = FactoryDict[str, Client]
AddressBook: TypeAlias = FactoryDict[str, str]
DB: TypeAlias = FactoryDict[bytes, bytes]

class ServerMeta(type):
    def __dir__(cls):
        return ["__init__", "start", "__setitem__", "__getitem__"]

class Server(metaclass=ServerMeta):
    ERR_DISPATCH = {
        2: bytes([00, 69, 82, 82, 2]),  # invalid packet
        3: bytes([00, 69, 82, 82, 3]),  # invalid crc32
        4: bytes([00, 69, 82, 82, 4]),  # invalid command
        5: bytes([00, 69, 82, 82, 5]),  # key does not exist
        6: bytes([00, 69, 82, 82, 6]),  # invalid value
        7: bytes([00, 69, 82, 82, 7]),  # uuid does not exist
    }

    def __init__(
        self,
        address="localhost",
        port=9193,
        password=b"very_secure_password",
        sock: SocketFactory = tcp_server_factory,
        dictionary: DictFactory = dict_factory,
        keep_dead_sessions=False,
        multithreaded=False
    ) -> None:
        """
        Initialize a new Pipebomb Server instance.

        Args:
            address (str, optional): The address to bind to. Defaults to "localhost".
            port (int, optional): The port to bind to. Defaults to 9193.
            password (bytes, optional): The password for authentication. Defaults to b"very_secure_password".
            sock (SocketFactory, optional): The socket factory to use. Defaults to tcp_server_factory.
            dictionary (SocketFactory, optional): The dictionary factory to use. Defaults to dict_factory.
            keep_dead_sessions (bool, optional): Whether to keep dead sessions. Defaults to False.
            multithreaded (bool, optional): Whether to use gsyncio or not
        """
        ...

    async def start(self, client_accepters: Optional[int] = 1) -> None:
        """
        Starts the pipebomb server

        Args:
            client_accepters (int, optional): The number of client accepters to start. Defaults to 1.
        """
        ...

    def __getitem__(self, key: bytes) -> bytes:
        """
        Gets the value of a key from the pipebomb server DB
        """

    def __setitem__(self, key: bytes, value: bytes) -> None:
        """
        Sets the value of a key in the pipebomb server DB
        """

    def __delitem__(self, key: bytes) -> None:
        """
        Deletes a key from the pipebomb server DB
        """

    def __contains__(self, key: bytes) -> bool:
        """
        Checks if a key exists in the pipebomb server DB
        """

    def __len__(self) -> int:
        """
        Returns the number of keys in the pipebomb server DB
        """

    def keys(self) -> dict_keys:
        """
        Returns all the keys in the pipebomb server DB
        """

    def values(self) -> dict_values:
        """
        Returns all the values in the pipebomb server DB
        """

    async def stop(self) -> None:
        """
        Stops the server
        """

    async def accept_clients(self) -> None:
        """
        Internal handler for accepting new clients

        WARNING: IT IS NOT RECOMMENDED THAT YOU MANUALLY CALL THIS FUNCTION
        """

    async def handle_client(self, client: Client, uuid: str) -> None:
        """
        Internal handler for handling a client

        Args:
            client (Client): The client to handle
            uuid (str): The uuid of the client

        WARNING: IT IS NOT RECOMMENDED THAT YOU MANUALLY CALL THIS FUNCTION
        """

    async def add_client(self, client_ticket: NewClientTicket) -> None:
        """
        Adds a new client to the client db

        Args:
            client_ticket (NewClientTicket): The client ticket to add

        Raises:
            ValueError: If the uuid is not 36 characters long, if the client is already in the client db
        """

    async def get_client(self, uuid: str) -> Client:
        """
        Gets a client from the client db

        This will not give you the client's socket, cipher, or nonces

        Args:
            uuid (str): The uuid of the client to get

        Returns:
            Client: The client

        Raises:
            ValueError: If the uuid is not 36 characters long, if the client is not in the client db
        """

    async def check_client(self, uuid: str) -> bool:
        """
        Checks if a client exists in the client db

        Args:
            uuid (str): The uuid of the client to check

        Returns:
            bool: True if the client exists, False otherwise
        """

    async def remove_client(self, uuid: str) -> None:
        """
        Removes a client from the client db

        Side effects include removing the client's keys from the address book

        Args:
            uuid (str): The uuid of the client to remove

        Raises:
            ValueError: If the uuid is not 36 characters long, if the client is not in the client db
        """

    async def apply_client_state(
        self, client_ticket: NewClientTicket, strict=True
    ) -> None:
        """
        Applies a new client state

        Args:
            client_ticket (NewClientTicket): The client ticket to apply
            strict (bool, optional): Whether to raise an error if a key is not in the address book

        Raises:
            ValueError: If the uuid is not 36 characters long, if the client is not in the client db,
                If a key does not exist
        """

    async def add_key(self, key: str, uuid: str) -> None:
        """
        Adds a new key to the address book

        Args:
            key (str): The key to add
            uuid (str): The uuid of the client to add the key to

        Raises:
            ValueError: If the uuid is not 36 characters long, if the client is not in the client db
        """

    async def get_key(self, key: str) -> str:
        """
        Gets the value of a key from the address book

        Args:
            key (str): The key to get

        Returns:
            str: The uuid of the key

        Raises:
            ValueError: If the key is not in the address book
        """

    async def check_key(self, key: str, uuid: str) -> bool:
        """
        Checks if a key exists in the address book

        Args:
            key (str): The key to check
            uuid (str): The uuid of the client to check the key for

        Returns:
            bool: True if the key exists, False otherwise
        """

    async def remove_key(self, key: str, uuid: str) -> None:
        """
        Removes a key from the address book

        Args:
            key (str): The key to remove
            uuid (str): The uuid of the client to remove the key from

        Raises:
            ValueError: If the uuid is not 36 characters long, if the client is not in the client db
        """

    async def set_db(self, key: bytes, value: bytes) -> None:
        """
        Sets the value of a key in the pipebomb server DB

        Args:
            key (bytes): The key to set
            value (bytes): The value to set the key to
        """

    async def get_db(self, key: bytes) -> bytes:
        """
        Gets the value of a key from the pipebomb server DB

        Args:
            key (bytes): The key to get

        Returns:
            bytes: The value of the key
        """

    async def remove_db(self, key: bytes) -> None:
        """
        Removes a key from the pipebomb server DB

        Args:
            key (bytes): The key to remove
        """

    async def apply_state(
        self, db: dict[bytes, bytes], client_db: ClientDB, address_book: AddressBook
    ) -> None:
        """
        Applies a state to the server

        It is recommended you use this with the serialize/deserialize functions

        Args:
            db (dict): The db to apply
            client_db (dict): The client db to apply
            address_book (dict): The address book to apply
        """

    async def get_all_clients(self) -> list[str]:
        """
        Returns a list of all the clients's uuid in the client db

        Returns:
            list: A list of all the clients's uuid in the client db
        """
        ...

    async def get_all_keys(self) -> list[str]:
        """
        Returns a list of all keys in the address book

        Returns:
            list: A list of all keys in the address book
        """
        ...

async def serialize(server: Server) -> bytes:
    """
    Serializes the server into a bytes object

    This is meant to be used with the deserialize function to restore the server

    Args:
        server (Server): The server to serialize

    """
    ...

@overload
async def deserialize(
    serialized: bytes, server: None = None
) -> tuple[DB, AddressBook, ClientDB]:
    """
    Deserializes a bytes object into a server

    Args:
        serialized (bytes): The bytes to deserialize
        server (Optional[Server], optional): The server to deserialize into. Defaults to None.

    If server is None, a tuple of (db, address_book, client_db) will be returned
    If server is Server, the server will be updated with Server.apply_state
    """
    ...

@overload
async def deserialize(serialized: bytes, server: Server) -> Server:
    """
    Deserializes a bytes object into a server

    Args:
        serialized (bytes): The bytes to deserialize
        server (Optional[Server], optional): The server to deserialize into. Defaults to None.

    If server is None, a tuple of (db, address_book, client_db) will be returned
    If server is Server, the server will be updated with Server.apply_state
    """
    ...

@overload
async def deserialize(
    serialized: bytes, server: Optional[Server] = None
) -> Union[tuple[DB, AddressBook, ClientDB], Server]:
    """
    Deserializes a bytes object into a server

    Args:
        serialized (bytes): The bytes to deserialize
        server (Optional[Server], optional): The server to deserialize into. Defaults to None.

    If server is None, a tuple of (db, address_book, client_db) will be returned
    If server is Server, the server will be updated with Server.apply_state
    """
    ...

__all__: Sequence[str] = ["Server", "serialize", "deserialize"]
