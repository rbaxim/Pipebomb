import asyncio
from pipebomb.client import Client
from pipebomb.server import Server

async def test_opcodes(server_client_tcp: tuple[Server, Client]):
    server, client = server_client_tcp
    await server.start()
    await asyncio.sleep(0.1)
    await client.connect()
    await client.set("foo", "bar")
    await client.get("foo")
    await client.list()
    await client.delete("foo")
    uuid = await client.whoami()
    await client.register("test")
    await client.find("test")
    req_uuid = await client.request(uuid, b"Hello", b"test")
    await client.read_inbox()
    await client.respond(uuid, b"Hello World", b"test", req_uuid)
    await client.read_outbox(req_uuid)
    await client.unregister("test")
    await client.close()
    await asyncio.sleep(0.1)
    await server.stop()