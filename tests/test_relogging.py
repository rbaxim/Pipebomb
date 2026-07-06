import asyncio
from pipebomb.server import NewClientTicket, Server, deserialize
from pipebomb.client import Client
from pipebomb.utils import Request, Response
from pathlib import Path
    
async def test_relogging_into_preset(server_client_tcp: tuple[Server, Client]):
    sample_uuid = b"a" * 36
    server, client = server_client_tcp
    await server.start()
    queue: asyncio.Queue = asyncio.Queue()
    await queue.put(Request(sample_uuid, b"key", b"pls write to fd", b"isdjfsdhifusdfh"))
    await server.add_client(NewClientTicket(sample_uuid.decode("latin1"), ["test"], queue, {b"isdjfsdhifusdfh": Response(b"key", b"okie dokie", b"isdjfsdhifusdfh")})) # pyright: ignore[reportArgumentType]
    await asyncio.sleep(0.1)
    await client.connect(relog_uuid=sample_uuid)
    uuid = await client.whoami()
    assert uuid == sample_uuid
    await client.close()
    await asyncio.sleep(0.1)
    await server.stop()
    
async def test_relogging_into_serialized_server(server_client_tcp: tuple[Server, Client]):
    server, client = server_client_tcp
    await server.start()
    await asyncio.sleep(0.1)
    with open(Path(__file__).parent / "test_serialized.bin", "rb") as f:
        serialized = f.read()
    await deserialize(serialized, server)
    await client.connect(relog_uuid=b"a" * 36)
    server_client = await server.get_client("a" * 36)
    await asyncio.sleep(0.1)
    assert b"test" in server
    assert await client.whoami() == b"a" * 36
    assert server_client.addresses_owned == ["test0", "test1", "test2", "test3"]
    inbox = await client.read_inbox()
    assert inbox == Request(b"a" * 36, b"test", b"test", b"a" * 36)
    outbox = await client.read_outbox(b"a" * 36)
    assert outbox == Response(b"test", b"test", b"a" * 36)