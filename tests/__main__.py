from pipebomb.server import NewClientTicket, Server, serialize
import asyncio
from pathlib import Path
from pipebomb.utils import Request, Response
import os
import sys

async def create_files():
    if not (Path(__file__).parent / "test_serialized.bin").exists():
        uuid = b"a" * 36
        server = Server()
        
        queue = asyncio.Queue()
        await queue.put(Request(uuid, b"test", b"test", uuid))
        
        res = Response(b"test", b"test", uuid)
        
        await server.add_client(NewClientTicket(uuid.decode("latin1"), ["test0"], queue, {uuid: res})) # pyright: ignore[reportArgumentType]
        
        await server.add_key("test1", uuid.decode("latin1"))
        await server.add_key("test2", uuid.decode("latin1"))
        await server.add_key("test3", uuid.decode("latin1"))
        
        server[b"test"] = b"test"
        
        serialized = await serialize(server)
        with open(Path(__file__).parent / "test_serialized.bin", "wb") as f:
            f.write(serialized)

if __name__ == "__main__":
    asyncio.run(create_files())
    os.system(f"{sys.executable} -m pytest {Path(__file__).parent} " + " ".join(sys.argv[1:]))