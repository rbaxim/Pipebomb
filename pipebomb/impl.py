from typing import Any, Generic, Protocol, Sequence, TypeVar, Literal, TypeAlias
import socket
import os

SocketT = TypeVar("SocketT", bound=socket.socket)
DictT_co = TypeVar("DictT_co", bound=dict)

DEFAULT_UNIX_SOCKET_PATH = "/tmp/pipebomb.sock"  # nosec B108
SocketAddress = tuple[str, int] | str
DatabaseId: TypeAlias = Literal["db", "client_db", "address_book"]


class SocketFactory(Protocol[SocketT]):
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
    def factory_address(self) -> str:
        return "Unknown"


class UnixSocket(FactorySocket):
    path: str

    def factory_address(self) -> str:
        return self.path


class TcpSocket(FactorySocket):
    def factory_address(self) -> str:
        addr, port = self.getsockname()
        return f"{addr}:{port}"


class TcpSocketFactory(SocketFactory[TcpSocket]):
    def __init__(
        self,
        nodelay: bool = False,
        reuseaddr: bool = False,
        name: str = "tcp_factory",
    ) -> None:
        self.nodelay = nodelay
        self.reuseaddr = reuseaddr
        self.__name__ = name

    def __call__(
        self, nodelay: bool | None = None, reuseaddr: bool | None = None
    ) -> TcpSocket:
        sock = TcpSocket(socket.AF_INET, socket.SOCK_STREAM)
        if reuseaddr if reuseaddr is not None else self.reuseaddr:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setblocking(False)
        if nodelay if nodelay is not None else self.nodelay:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        return sock

    async def resolve_connect_address(  # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        sock: TcpSocket,
        address: str,
        port: int,  # type: ignore
    ) -> SocketAddress:
        addrinfos = await asyncio_loop_getaddrinfo(sock, address, port)
        if not addrinfos:
            raise RuntimeError(f"Unable to resolve {address}:{port}")
        return addrinfos[0][4]

    def resolve_bind_address(  # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        sock: TcpSocket,
        address: str,
        port: int,  # type: ignore
    ) -> SocketAddress:
        return address, port

    def prepare_bind(self, sock: TcpSocket, bind_address: SocketAddress) -> None:  # type: ignore
        return


class UnixSocketFactory(SocketFactory[UnixSocket]):
    def __init__(
        self, path: str = DEFAULT_UNIX_SOCKET_PATH, name: str = "unix_factory"
    ) -> None:
        if os.name != "posix":
            raise NotImplementedError("Unix sockets are not supported on this platform")
        self.path = path
        self.__name__ = name

    def __call__(self, path: str | None = None) -> UnixSocket:
        if os.name != "posix":
            raise NotImplementedError("Unix sockets are not supported on this platform")

        sock = UnixSocket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.path = path if path is not None else self.path
        sock.setblocking(False)
        return sock

    async def resolve_connect_address(  # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        sock: UnixSocket,
        address: str,
        port: int,  # type: ignore
    ) -> SocketAddress:
        return self.resolve_path(address)

    def resolve_bind_address(  # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        sock: UnixSocket,
        address: str,
        port: int,  # type: ignore
    ) -> SocketAddress:
        return self.resolve_path(address)

    def prepare_bind(self, sock: UnixSocket, bind_address: SocketAddress) -> None:  # type: ignore
        try:
            os.unlink(str(bind_address))
        except FileNotFoundError:
            pass

    def resolve_path(self, address: str) -> str:
        if address != "localhost":
            return address
        return self.path

# Factories for a simple builtin is crazy
class DictFactory[DictT_co](Protocol):
    __name__: str

    def __call__(self, db_id: DatabaseId) -> DictT_co: ...
    def __getitem__(self, key: Any) -> DictT_co: ...
    def __setitem__(self, key: Any, value: Any) -> None: ...
    def __delitem__(self, key: Any) -> None: ...
    def __contains__(self, key: Any) -> bool: ...
    def __len__(self) -> int: ...
    def clear(self) -> None: ...
    
KT = TypeVar("KT")
VT = TypeVar("VT")

class FactoryDict(dict[KT, VT], Generic[KT, VT]):
    def __init__(self, db_id, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.db_id = db_id


# Consistency got the best of me
class DictDictionaryFactory(DictFactory[dict]):
    __name__ = "dict_factory"

    def __call__(self, db_id: DatabaseId) -> FactoryDict:
        return FactoryDict(db_id)


def parse_address(address: SocketAddress) -> str:
    if isinstance(address, tuple):
        return f"{address[0]}:{address[1]}"
    return address


async def asyncio_loop_getaddrinfo(
    sock: socket.socket, address: str, port: int
) -> Sequence[tuple]:
    import asyncio

    loop = asyncio.get_event_loop()
    return await loop.getaddrinfo(
        address,
        port,
        family=sock.family,
        type=socket.SOCK_STREAM,
    )


tcp_factory = TcpSocketFactory()
tcp_server_factory = TcpSocketFactory(reuseaddr=True, name="tcp_server_factory")
if os.name == "posix":
    unix_factory = UnixSocketFactory()
else:

    def unix_factory_not_supported(*args, **kwargs):
        raise NotImplementedError("Unix sockets are not supported on this platform")

    unix_factory = unix_factory_not_supported  # type: ignore
dict_factory = DictDictionaryFactory()  # type: ignore


__all__: Sequence[str] = [
    "SocketAddress",
    "SocketFactory",
    "TcpSocketFactory",
    "UnixSocketFactory",
    "tcp_factory",
    "tcp_server_factory",
    "dict_factory",
    "unix_factory",
    "DEFAULT_UNIX_SOCKET_PATH",
]
