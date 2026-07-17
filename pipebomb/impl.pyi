import os
from typing import Any, Never, Protocol, Sequence, TypeAlias, TypeVar, Literal, Callable
import socket

DEFAULT_UNIX_SOCKET_PATH: str
SocketAddress: TypeAlias = tuple[str, int] | str
SocketT = TypeVar("SocketT", bound=socket.socket)
DictT_co = TypeVar("DictT_co", bound=dict)
DatabaseId: TypeAlias = Literal["db", "client_db", "address_book"]

class SocketFactory(Protocol[SocketT]):
    """
    The base protocol contract for Socket Factories
    """

    __name__: str
    def __call__(self, *args: Any, **kwargs: Any) -> SocketT: ...
    async def resolve_connect_address(
        self, sock: SocketT, address: str, port: int
    ) -> SocketAddress: ...
    def resolve_bind_address(
        self, sock: SocketT, address: str, port: int
    ) -> SocketAddress: ...
    def prepare_bind(self, sock: SocketT, bind_address: SocketAddress) -> None: ...

class FactorySocket(socket.socket):
    def factory_address(self) -> str: ...

class UnixSocket(FactorySocket):
    """
    The actual socket for Unix sockets.
    """

    path: str
    def factory_address(self) -> str: ...

class TcpSocket(FactorySocket):
    """
    The actual socket for TCP
    """
    def factory_address(self) -> str: ...

class TcpSocketFactory(SocketFactory[TcpSocket]):
    """
    The main protocol contract for TCP Socket Factories
    """

    nodelay: bool
    reuseaddr: bool
    __name__: str
    def __init__(
        self,
        nodelay: bool = False,
        reuseaddr: bool = False,
        name: str = "tcp_factory",
    ) -> None: ...
    def __call__(
        self, nodelay: bool | None = None, reuseaddr: bool | None = None
    ) -> TcpSocket: ...
    async def resolve_connect_address(
        self, sock: TcpSocket, address: str, port: int
    ) -> SocketAddress: ...
    def resolve_bind_address(
        self, sock: TcpSocket, address: str, port: int
    ) -> SocketAddress: ...
    def prepare_bind(self, sock: TcpSocket, bind_address: SocketAddress) -> None: ...

class UnixSocketFactory(SocketFactory[UnixSocket]):
    """
    The main protocol contract for Unix Socket Factories
    """

    path: str
    __name__: str
    def __init__(
        self, path: str = DEFAULT_UNIX_SOCKET_PATH, name: str = "unix_factory"
    ) -> None: ...
    def __call__(self, path: str | None = None) -> UnixSocket: ...
    async def resolve_connect_address(
        self, sock: UnixSocket, address: str, port: int
    ) -> SocketAddress: ...
    def resolve_bind_address(
        self, sock: UnixSocket, address: str, port: int
    ) -> SocketAddress: ...
    def prepare_bind(self, sock: UnixSocket, bind_address: SocketAddress) -> None: ...
    def resolve_path(self, address: str) -> str: ...

class DictFactory[DictT_co](Protocol):
    """
    The main protocol contract for dictionary factories

    Don't overthink it
    """

    __name__: str
    def __call__(self, db_id: DatabaseId) -> DictT_co: ...
    def __getitem__(self, key: Any) -> DictT_co: ...
    def __setitem__(self, key: Any, value: Any) -> None: ...
    def __delitem__(self, key: Any) -> None: ...
    def __contains__(self, key: Any) -> bool: ...
    def __len__(self) -> int: ...
    def clear(self) -> None: ...

class FactoryDict(dict):
    """
    Its literally just a dict.

    Don't overthink it

    Heres the real dict if you read the docstring above me
    """
    def __init__(self, db_id, *args, **kwargs): ...

# Consistancy got the best of me
class DictDictionaryFactory(DictFactory[dict]):
    """
    DictDictionaryFactory?

    yeah it just returns a dict

    Returns:
        dict
    """

    __name__ = "dict_factory"
    def __call__(self, db_id: DatabaseId) -> FactoryDict: ...

def parse_address(address: SocketAddress) -> str:
    """
    Converts a SocketAddress to a str

    Args:
        address (SocketAddress): The address to convert

    Returns:
        str
    """
    ...

tcp_factory: TcpSocketFactory()  # type: ignore
tcp_server_factory: TcpSocketFactory(reuseaddr=True, name="tcp_server_factory")  # type: ignore
if os.name == "posix":
    unix_factory: UnixSocketFactory()  # type: ignore
else:
    def unix_factory_not_supported(*args, **kwargs) -> Never:
        raise NotImplementedError("Unix sockets are not supported on this platform")
    unix_factory: Callable[..., Never] = unix_factory_not_supported
dict_factory = DictDictionaryFactory()  # type: ignore

__all__: Sequence[str] = [
    "SocketAddress",
    "SocketFactory",
    "TcpSocketFactory",
    "UnixSocketFactory",
    "DictFactory",
    "DictDictionaryFactory",
    "FactoryDict",
    "tcp_factory",
    "tcp_server_factory",
    "dict_factory",
    "unix_factory",
    "DEFAULT_UNIX_SOCKET_PATH",
]
