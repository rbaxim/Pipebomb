import pytest
current_port = 9193
from pipebomb.client import Client
from pipebomb.server import Server
from pipebomb.impl import tcp_server_factory, tcp_factory

@pytest.fixture
def server_client_tcp():
    global current_port
    server = Server(sock=tcp_server_factory, port=current_port)
    client = Client("127.0.0.1", current_port, sock=tcp_factory)
    current_port += 1
    return server, client