"""
Pipebomb Client
"""

from typing import TypeAlias, Sequence
import socket
from pipebomb.impl import SocketFactory, tcp_factory
from pipebomb.utils import Request, Response

Primitives: TypeAlias = int | bytes | str

class RawClient:
    """
    Raw TCP client for pipebomb protocol

    Args:
        address (str): The address of the pipebomb server. Defaults to "localhost"
        port (int): The port of the pipebomb server. Defaults to 9193
        password (bytes): The password of the pipebomb server. Defaults to b"very_secure_password"'
        sock (SocketFactory, optional): The socket factory to use. Defaults to tcp_factory
    """
    def __init__(
        self,
        address: str = "localhost",
        port: int = 9193,
        password: bytes = b"very_secure_password",
        sock: SocketFactory = tcp_factory,
    ) -> None: ...
    async def connect(self, relog_uuid: bytes | None = None) -> None:
        """
        Connects to the pipebomb server

        Args:
            relog_uuid (bytes, optional): The uuid to relogin as

        Raises:
            RuntimeError: If the client failed to receive the server's public key, If the client fails the handshake,
                If the client did not receive a ACK, If the client received a error instead of a ACK,
                If the client recieved a invalid ACK
        """
        ...

    async def handle_connection(self, socket: socket.socket) -> None:
        """
        Internal handler for the connection.

        WARNING: IT IS NOT RECOMMENDED THAT YOU MANUALLY CALL THIS FUNCTION

        Args:
            socket (socket.socket): The TCP socket connected to the pipebomb server

        Raises:
            RuntimeError: If the client receives a error packet from the server, If the client fails to receive a packet from the server,
                If the client has an error while handling the connection to the server
        """

    async def send(self, data: bytes) -> None:
        """
        Sends data over the TCP socket to the server

        This function automatically converts the bytes into a proper packet

        Args:
            data (bytes): The bytes to send over TCP socket to the server
        """
        ...

    async def receive(self) -> bytes:
        """
        Gets the bytes from the TCP socket (blocking).

        This function automatically converts the input packet back into a payload

        Returns:
            A bytes object containing the payload

        Raises:
            RuntimeError: If the timeout of 5 seconds exceeds
        """

    async def close(self) -> None:
        """
        Closes the connection to the pipebomb server
        """

class Client:
    """
    The standard Client for the pipebomb protocol

    Args:
        address (str, optional): The address of the pipebomb server. Defaults to "localhost"
        port (int, optional): The port of the pipebomb server. Defaults to 9193
        password (bytes, optional): The password of the pipebomb server. Defaults to b"very_secure_password"
        sock (SocketFactory, optional): The socket factory to use. Defaults to tcp_factory
    """
    def __init__(
        self,
        address="localhost",
        port=9193,
        password=b"very_secure_password",
        sock: SocketFactory = tcp_factory,
    ) -> None: ...
    async def connect(self, relog_uuid: bytes | None = None):
        """
        Connects to the pipebomb server

        Calls RawClient.connect to connect

        Args:
            relog_uuid (bytes, optional): The uuid to relogin as

        Raises:
            RuntimeError: If the client failed to receive the server's public key, If the client fails the handshake,
                If the client did not receive a ACK, If the client received a error instead of a ACK,
                If the client recieved a invalid ACK
        """
        ...

    async def set(self, key: Primitives, value: Primitives) -> bool:
        """
        Sets a key in the pipebomb server DB

        Sends the packet:
            0x81 + key_length (>I) + value_length (>I) + key + value

        Args:
            key (Primitives): The key to set
            value (Primitives): The value to assign to the key

        Returns:
            A bool object stating whether the operation succeeded or not
        """
        ...

    async def get(self, key: Primitives) -> bytes:
        """
        Gets the value of a key from the pipebomb server DB

        Sends the packet:
            0x82 + key

        Args:
            key (Primitives): The key to lookup

        Returns:
            A bytes object containing the response
        """
        ...

    async def delete(self, key: Primitives) -> bool:
        """
        Deletes the entry of a key from the pipebomb server DB

        Sends the packet:
            0x83 + key

        Args:
            key (Primitives): The key to delete

        Returns:
            A bool object stating whether the operation succeeded or not
        """
        ...

    async def list(self) -> dict[str, str]:
        """
        Returns all the keys and values in the pipebomb server DB

        Sends the packet:
            0x84

        Returns:
            A dict object containing the response
        """
        ...

    async def register(self, key: Primitives) -> bool:
        """
        Registers a key in the pipebomb server DB

        Sends the packet:
            0x85 + key

        Args:
            key (Primitives): The key to register

        Returns:
            A bool object stating whether the operation succeeded or not
        """
        ...

    async def unregister(self, key: Primitives) -> bool:
        """
        Unregisters a key in the pipebomb server DB

        Sends the packet:
            0x86 + key

        Args:
            key (Primitives): The key to unregister

        Returns:
            A bool object stating whether the operation succeeded or not
        """
        ...

    async def whoami(self) -> bytes:
        """
        Tells you your uuid

        Sends the packet:
            0x87

        Returns:
            A bytes object containing the response
        """
        ...

    async def find(self, key: Primitives) -> bytes:
        """
        Tells you the owner uuid of a key

        Sends the packet:
            0x1 + key

        Args:
            key (Primitives): The key to lookup

        Returns:
            A bytes object containing the response
        """
        ...

    async def request(self, uuid: bytes, request: Primitives, key: Primitives) -> bytes:
        """
        Sends a request to a specific client with a key

        Sends the packet:
            0x2 + uuid + request_length (>I) + request + key_length (>I) + key

        Args:
            uuid (bytes): The uuid to send the request to
            request (Primitives): The request to send
            key (Primitives): The key to send with the request

        Returns:
            A bytes object containing the response
        """
        ...

    async def read_inbox(self) -> Request:
        """
        Read a request from your inbox

        Sends the packet:
            0x3

        Returns:
            A Request object containing the response
        """
        ...

    async def respond(
        self,
        target_uuid: bytes,
        response: Primitives,
        key: Primitives,
        request_uuid: bytes,
    ) -> bool:
        """
        Writes a response to the callee

        Sends the packet:
            0x4 + target_length (>I) + response_length (>I) + key_length (>I) + request_uuid_length (>I) + target_uuid + response + key + request_uuid

        Returns:
            A bool object stating whether the operation succeeded or not
        """
        ...

    async def read_outbox(self, request_uuid: bytes) -> Response:
        """
        Read a response from your outbox

        Sends the packet:
            0x5 + request_uuid

        Returns:
            A Response object containing the response
        """
        ...

    async def close(self) -> None:
        """
        Closes the connection to the pipebomb server

        Sends the packet:
            0x88

        Returns:
            None
        """

__all__: Sequence[str] = ["RawClient", "Client"]
