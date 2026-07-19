import sys
import asyncio
from pathlib import Path
import os

rc = os.system("uv build --wheel")
if rc != 0:
    print("Failed to build package")

rc = os.system("uv pip install --group tests")
if rc != 0:
    print(f"Failed to install required test packages. Return Code: {rc}")


async def create_files():
    if not (Path(__file__).parent / "test_serialized.bin").exists():
        uuid = b"a" * 36
        from pipebomb.server import Server
        server = Server()

        queue = asyncio.Queue()
        await queue.put(
            __import__("pipebomb.utils", fromlist=["Request"]).Request(
                uuid, b"test", b"test", uuid
            )
        )

        res = __import__("pipebomb.utils", fromlist=["Response"]).Response(b"test", b"test", uuid)

        await server.add_client(
            __import__("pipebomb.server", fromlist=["NewClientTicket"]).NewClientTicket(
                uuid.decode("latin1"), ["test0"], queue, {uuid: res}
            )
        )

        await server.add_key("test1", uuid.decode("latin1"))
        await server.add_key("test2", uuid.decode("latin1"))
        await server.add_key("test3", uuid.decode("latin1"))

        server[b"test"] = b"test"

        serialized = await __import__("pipebomb.server", fromlist=["serialize"]).serialize(server)
        with open(Path(__file__).parent / "test_serialized.bin", "wb") as f:
            f.write(serialized)


if __name__ == "__main__":
    asyncio.run(create_files())
    sys.exit(
        os.system(
            f"{sys.executable} -m pytest {Path(__file__).parent} "
            + " ".join(sys.argv[1:])
        )
    )
