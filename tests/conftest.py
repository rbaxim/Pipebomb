import os
import pytest
from pipebomb.client import Client
from pipebomb.server import Server
from pipebomb.impl import tcp_server_factory, tcp_factory
from pathlib import Path
import sys

current_port = 9193 + int(os.environ.get("TEST_PORT_OFFSET", "0"))


@pytest.fixture
def port_fixture():
    global current_port
    p = current_port
    current_port += 1
    return p


@pytest.fixture
def server_client_tcp(port_fixture):
    server = Server(sock=tcp_server_factory, port=port_fixture)
    client = Client("127.0.0.1", port_fixture, sock=tcp_factory)
    return server, client


@pytest.fixture
def pipebomb_folder():
    tests_folder = Path(__file__).parent.parent.resolve()
    return (tests_folder / "pipebomb").resolve()


@pytest.fixture
def gsyncio_library_location():
    tests_folder = Path(__file__).parent.parent.resolve()
    dist_folder = tests_folder / "dist"
    if sys.platform.startswith("win"):
        return (dist_folder / "gsyncio.pyd").resolve()
    else:
        return (dist_folder / "gsyncio.so").resolve()
