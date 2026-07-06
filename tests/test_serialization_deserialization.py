import asyncio
from pipebomb.client import Client
from pipebomb.server import Server, deserialize, serialize
from pathlib import Path
from pipebomb.utils import Request, Response

async def test_serialization_deserialization(server_client_tcp: tuple[Server, Client]):
    server, client = server_client_tcp
    await server.start()
    await asyncio.sleep(0.1)
    await client.connect()
    uuid = await client.whoami()
    await client.set("foo", "bar")
    await client.set(1234, 5678)
    await client.set(bytes([0x36, 0x39]), bytes([0x34, 0x32, 0x30]))
    await client.register("test")
    req_uuid = await client.request(uuid, b"Test the serialization", "test")
    await client.respond(uuid, b"Hello World", "test", req_uuid)
    packed = await serialize(server)
    
    await client.close()
    
    res = await deserialize(packed)
    assert res[0][b"foo"] == b"bar" and res[0][b"1234"] == b"5678" and res[0][b"\x36\x39"] == b"\x34\x32\x30"
    assert uuid.decode("latin1") in res[2] and "test" in res[2][uuid.decode("latin1")].addresses_owned
    assert "test" in res[1] and res[1]["test"] == uuid.decode("latin1")
    
    
async def test_file_serialized():
    server = Server()
    await asyncio.sleep(0.1)
    with open(Path(__file__).parent / "test_serialized.bin", "rb") as f:
        serialized = f.read()
    await deserialize(serialized, server)
    client = await server.get_client("a" * 36)
    assert b"test" in server
    assert client.uuid == "a" * 36
    assert client.addresses_owned == ["test0", "test1", "test2", "test3"]
    assert client.inbox.get_nowait() == Request(b"a" * 36, b"test", b"test", b"a" * 36)
    assert client.outbox == {b"a" * 36: Response(b"test", b"test", b"a" * 36)}