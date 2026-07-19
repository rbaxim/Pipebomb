# Pipebomb

![Python Version](https://img.shields.io/badge/python-3.12%20%7C%203.13-blue)
![License](https://img.shields.io/badge/license-Apache%202.0-green)
![GitHub repo size](https://img.shields.io/github/repo-size/rbaxim/Pipebomb?label=Repo%20Size)

A high-performance encrypted IPC microframework based of the post office model for Python.

## Highlights

- **End-to-end encryption** - X25519 key exchange + HKDF session derivation + ChaCha20-Poly1305 AEAD with perfect forward secrecy
- **Async-first design** - built on `asyncio` with a producer/consumer message pattern for zero-copy transport
- **Built-in key-value store** - distributed `dict[bytes, bytes]` accessible over the network from any connected client
- **Address book & name resolution** - register human-readable keys to discover and address other clients
- **Inter-client async RPC** - inbox/outbox messaging with request/response correlation via opaque UUIDs
- **Full state serialization** - compressible binary checkpointing of the entire server state (DB, address book, client sessions) for persistence, hot standby, or crash recovery
- **Duck-typed factories** - swap transports (TCP <-> Unix sockets) or storage backends (in-memory dict -> Redis, SQLite, etc.) by implementing a single `Protocol`
- **Go-powered multithreaded execution** - optional `gsyncio` backend spawns native Go goroutines for blocking callbacks, bypassing the GIL and scaling to thousands of concurrent clients without Python threading overhead

## Installation

```bash
uv add pipebomb
```

Or from source:

```bash
git clone https://github.com/rbaxim/Pipebomb.git
cd Pipebomb
uv sync
```

**Note for `multithreaded=True`:** if you plan to use the Go-powered gsyncio backend, ensure `go` is installed and in PATH before running `uv sync`. The hatch build hook compiles the gsyncio shared library automatically during installation.

## Quick Start

### Basic TCP Messaging

This example spins up a server, connects two clients, and sends an async request/response between them.

```python
import pipebomb.client as client
import pipebomb.server as server
import pipebomb.impl as impl
import asyncio

pipebomb_server = server.Server(sock=impl.tcp_server_factory)

async def main():
    # Start the server in the background
    asyncio.create_task(pipebomb_server.start())
    await asyncio.sleep(0)

    # Connect two clients
    client_a = client.Client("localhost", 9193, sock=impl.tcp_factory)
    client_b = client.Client("localhost", 9193, sock=impl.tcp_factory)
    await client_a.connect()
    await client_b.connect()

    # Client A registers the key "test" so Client B can find it
    await client_a.register("test")
    client_a_uuid = await client_b.find("test")

    # Client B sends an async request to Client A
    req_uuid = await client_b.request(client_a_uuid, b"Hello", b"test")

    # Client A reads the request from its inbox and responds
    request = await client_a.read_inbox()
    if request.request == b"Hello":
        await client_a.respond(
            request.return_uuid, b"Hello World", b"test", request.request_uuid
        )

    # Client B reads the response from its outbox
    response = await client_b.read_outbox(req_uuid)
    print(response.response.decode("latin1"))  # -> Hello World

    await client_a.close()
    await client_b.close()
    await pipebomb_server.stop()

asyncio.run(main())
```

### Using Unix Sockets

Pipebomb ships with a built-in `UnixSocketFactory`. Swap the transport in one line:

```python
import pipebomb.client as client
import pipebomb.server as server
from pipebomb.impl import unix_factory

srv = server.Server(sock=unix_factory)  # binds to /tmp/pipebomb.sock by default
cli = client.Client("localhost", 9193, sock=unix_factory)

# ... rest of your code stays the same
```

### Writing a Custom Storage Factory

The `DictFactory` protocol lets you plug in any storage backend - Redis, SQLite, LMDB, whatever. You just need a callable that returns dict-like objects implementing `__getitem__`, `__setitem__`, `__delitem__`, `__contains__`, `__len__`, and `clear`.

```python
from typing import Any
from pipebomb.impl import DictFactory, FactoryDict, DatabaseId


class RedisDict(FactoryDict):
    """A dict-like wrapper around a Redis connection."""

    def __init__(self, db_id: str, *args, **kwargs):
        super().__init__(db_id, *args, **kwargs)
        self._client = redis.Redis()  # your setup here

    def __getitem__(self, key: Any) -> Any:
        return self._client.hget(self.db_id, key)

    def __setitem__(self, key: Any, value: Any) -> None:
        self._client.hset(self.db_id, key, value)

    def __delitem__(self, key: Any) -> None:
        self._client.hdel(self.db_id, key)

    def __contains__(self, key: Any) -> bool:
        return self._client.hexists(self.db_id, key)

    def __len__(self) -> int:
        return self._client.hlen(self.db_id)

    def clear(self) -> None:
        self._client.delete(self.db_id)


class RedisDictFactory(DictFactory[RedisDict]):
    """Returns Redis-backed dict instances for each db_id."""

    __name__ = "redis_factory"

    def __call__(self, db_id: DatabaseId) -> RedisDict:
        return RedisDict(db_id)

    def __getitem__(self, key: Any) -> RedisDict:
        return self(key)

    def __setitem__(self, key: Any, value: Any) -> None:
        raise NotImplementedError("Use factory(db_id)[key] = value")

    def __delitem__(self, key: Any) -> None:
        raise NotImplementedError("Use del factory(db_id)[key]")

    def __contains__(self, key: Any) -> bool:
        return False  # not applicable at factory level

    def __len__(self) -> int:
        return 0  # not applicable at factory level

    def clear(self) -> None:
        raise NotImplementedError("Use factory(db_id).clear()")


# Use it when constructing the server
srv = server.Server(dict_factory=RedisDictFactory())
```

## Usage

### Client API

| Method | Description |
| --- | --- |
| `await client.connect(relog_uuid=None)` | Connect to server. Pass `relog_uuid` to reattach an existing session. |
| `await client.set(key, value)` | Store a key-value pair in the server's DB. |
| `value = await client.get(key)` | Retrieve a value from the server's DB. |
| `await client.delete(key)` | Remove a key from the server's DB. |
| `data = await client.list()` | Return all DB entries as JSON. |
| `await client.register(key)` | Register a named address for this client. |
| `await client.unregister(key)` | Remove a registered address. |
| `uuid = await client.whoami()` | Get this client's UUID. |
| `target_uuid = await client.find(key)` | Look up which client owns a registered key. |
| `req_uuid = await client.request(target_uuid, payload, key)` | Send an async RPC request to another client. |
| `request = await client.read_inbox()` | Pop the next request from your inbox (blocking). |
| `await client.respond(target_uuid, payload, key, request_uuid)` | Write a response to another client's outbox. |
| `response = await client.read_outbox(request_uuid)` | Read and consume a response from your outbox. |
| `await client.close()` | Graceful disconnect (sends BYE frame). |

### Server API

Create a server with the `multithreaded` flag to enable Go-powered goroutine execution:

```python
import pipebomb.server as server

# Default: pure asyncio (single-threaded event loop)
srv = server.Server()

# Multithreaded: uses gsyncio Go goroutines for client handling
srv = server.Server(multithreaded=True)
await srv.start(client_accepters=4)
```

The server exposes dict-style access for synchronous and simple use:

```python
server["foo"] = b"bar"
value = server["foo"]
del server["foo"]
size = len(server)
keys = server.keys()
values = server.values()
```

Async methods are also available:

| Method | Description |
| --- | --- |
| `await server.start(client_accepters=1)` | Bind and accept connections. Set `client_accepters` to spawn multiple concurrent acceptor tasks for handling connection bursts. |
| `await server.stop()` | Close socket, clear all data. |
| `await server.set_db(key, value)` | Async DB write. |
| `value = await server.get_db(key)` | Async DB read. |
| `await server.remove_db(key)` | Async DB delete. |
| `uuids = await server.get_all_clients()` | List all connected (or preserved) client UUIDs. |
| `keys = await server.get_all_keys()` | List all registered address book keys. |

### Persistence & Checkpointing

```python
from pipebomb.server import serialize, deserialize

# Serialize the entire server state to bytes
data = await serialize(server)

# Deserialize into a fresh server instance
new_server = await deserialize(data)

# Or deserialize and get the raw tables back
db, address_book, client_db = await deserialize(data, server=None)
```

The serialized format uses a `0x91938038` magic header, Zstandard compression (level 22), and encodes all three internal tables (DB, address book, client state with inboxes/outboxes). Deserialization is lossless.

## Server Modes

Pipebomb runs in two concurrency modes depending on your workload:

**Single-threaded (asyncio mode)** - `multithreaded=False` (default). All client handling runs cooperatively on a single asyncio event loop thread. This is the simplest setup: no Go compiler needed, zero build complexity. Each client connection is handled as an async coroutine that yields control back to the event loop during I/O waits.

**Multithreaded mode** - `multithreaded=True`. Client handling runs in native Go goroutines via gsyncio (see below). Each `accept_clients()` call and each `handle_client()` invocation spawns a separate goroutine that calls back into Python with proper GIL management. This bypasses the GIL entirely for blocking callbacks, allowing true parallel execution of client handlers across all available CPU cores.

### Scaling Connection Acceptance

When starting the server, you can set `client_accepters=N` to spawn N concurrent acceptor tasks:

```python
server = Server(multithreaded=True)
await server.start(client_accepters=4)
```

Each acceptor independently calls `socket.accept()`, so with `N=4` the server can queue up connections across 4 acceptors simultaneously rather than having a single bottleneck at `accept()`. This is useful for handling connection bursts (e.g., when many clients reconnect after a restart). In asyncio mode, `client_accepters` spawns multiple async coroutines on the event loop; in multithreaded mode, each acceptor runs as its own Go goroutine.

### Choosing a Mode

| Server Tier  | Cores | Clients | Recommendation                                                                     |
| ------------ | ----- | ------- | ---------------------------------------------------------------------------------- |
| Small / Edge | 4-6   | 8       | Use **asyncio** unless you expect 12+ simultaneous clients                         |
| Mid-range    | 8     | 16      | **Asyncio** for <16 clients, switch to **gsyncio** above that                      |
| Production   | 16+   | 32+     | Use **gsyncio** by default - at this scale Go goroutines are worth it from day one |

Rule of thumb: if your server has 16+ cores and you expect more than a handful of clients, just use gsyncio. The overhead of the Go library is negligible compared to the concurrency gains.

## gsyncio: Go-Powered Concurrency

gsyncio is a hybrid Python-Go async execution system that allows blocking callbacks to run concurrently alongside an asyncio event loop **without using Python's `threading` module or `asyncio.to_thread`**. Instead, it spawns native Go goroutines that call back into Python via cffi (API mode) with proper GIL management.

### Architecture

```text
Python Event Loop                                  Go Runtime
     |                                                  |
     |-- run_task_async(sync_callback) ---------------> |
     |   (creates asyncio.Event + result_holder)        |
     |   (spawns Go goroutine) -----------------------> |
     |                                                  |-- calls Python callback via cffi FFI
     |                                                  | -- GIL acquired/released automatically
     |                                                  |
     |   <---- loop.call_soon_threadsafe(event.set) ----|
     |   (result stored in result_holder)               |
     |   <-- asyncio.Event.wait() returns ------------- |
     |   (result/exception delivered to event loop)     |
```

The system has three layers:

1. **Go native library** - CGo shared library (`gsyncio.go`) exports functions for spawning cancellable goroutines, canceling by task ID, and atomic task ID generation. Each goroutine holds a function pointer to the Python callback and checks a shared cancellation flag each loop iteration.

2. **Python cffi wrapper** - loads the compiled shared library (`.so` on Linux, `.pyd` on Windows) via `ffi.dlopen()`, resolves C function signatures automatically from the cffi `cdef` declarations, and provides `StartGoTaskWithResult()`, `CancelGoTask()`, and `get_next_task_id()` as Python-callable functions. Live cffi callback objects are kept in a list to prevent garbage collection. GIL acquire/release function pointers are resolved at runtime via ctypes against the running interpreter, then passed to Go goroutines so each callback enters Python with the GIL held. The compiled cffi extension (`gsyncio_cffi`) links against both libpython and the Go shared library at build time, and is distributed alongside `gsyncio.{so|pyd}`.

3. **Higher-level orchestration** - `run_task_async()` (in `utils.py`) routes callbacks through three paths:
   - **Coroutine callback** -> pure asyncio `create_task()` (no Go involved)
   - **gsyncio available** -> spawns Go goroutine with result capture via `asyncio.Event` + `call_soon_threadsafe()` bridge
   - **gsyncio unavailable, sync callback** -> falls back to `asyncio.to_thread()` (ThreadPoolExecutor)

Even in the gsyncio path, callbacks are wrapped in an asyncio `Task` and returned as a `CancelableTask`, providing a uniform interface. The `CancelableTask` tracks both the asyncio task (for `done()`, `result()`, `exception()`) and a Go-assigned task ID (for Go-level cancellation via `cancel()`).

### When to Use gsyncio

- **High concurrent client counts** (>2x your CPU core count, or 16+ clients on any machine)
- **Blocking I/O in callbacks** - database queries, file operations, or any synchronous call that would block the event loop
- **CPU-bound work** competing for the GIL across many simultaneous handlers
- **Connection burst handling** - when many clients connect simultaneously and `client_accepters` alone isn't enough

### When NOT to Use gsyncio

- **Low client counts** (a handful of clients) - asyncio is simpler and has zero build dependency
- **Simple scripts or single-client tools** - the Go compilation step adds unnecessary complexity
- **Environments without Go installed** - while Pipebomb gracefully falls back to `asyncio.to_thread()`, you lose the Go goroutine advantages

### Build Requirements

When building from source (not via pip/uv index), gsyncio requires:

- **Go 1.21+** installed and in PATH
- **CGo enabled** (`CGO_ENABLED=1`) - the Go compiler must be able to call into Python's C API

The hatch build hook (`hatch_build.py`) handles compilation automatically during `uv sync` or `uv build`. If Go is not found, it skips gsyncio compilation and packages a pure-Python fallback (using `asyncio.to_thread()` instead). The compiled shared library is bundled into the wheel at `pipebomb/gsyncio/gsyncio.{so|pyd}`.

## Protocol Reference

### Packet Framing

Every packet on the wire follows this structure:

```text
[HEADER: 2 bytes] [CIPHERTEXT_LENGTH: 4 bytes BE] [CIPHERTEXT: variable]
   0x91 0x93        <ciphertext_size>                <encrypted payload>
```

The decrypted plaintext inside has the layout:

```text
[FLAGS: 1 byte] [BODY: variable] [CRC32: 4 bytes BE] [FOOTER: 2 bytes]
                 (compressed or    integrity check      0x80 0x38
                  plain)
```

- **Flags**: bit 0 = compression enabled. Zstandard is used only when it reduces size (level 9 for live traffic).
- **CRC32**: computed over the decompressed body as a second integrity layer after AEAD decryption.
- **Nonce**: per-direction monotonically increasing ChaCha20 counter prevents replay attacks within a session.

### Connection Lifecycle

1. **TCP connect** - Client establishes a socket to the server.
2. **X25519 key exchange** - Both sides generate ephemeral keypairs and exchange public keys. ECDH produces a shared secret.
3. **Session key derivation** - `HKDF(SHA-256)` derives a 32-byte ChaCha20 session key from the shared secret with info string `b"pipebomb"`.
4. **Password auth** - Client sends its password encrypted; server verifies via constant-time `compare_digest`.
5. **Login** - Client sends `LOGIN` (0xC5) for a new session or `RELOGIN` (0xC4 + uuid) to reattach. Server assigns or restores the client UUID.
6. **Message exchange** - Bidirectional opcode dispatch begins.
7. **Disconnect** - Client sends `BYE` (0x88); server tears down the session.

### Opcodes

**Server requests** (opcode bit 7 set):

| Opcode | Name | Description |
| --- | --- | --- |
| `0x81` | SET | Store key-value in server DB |
| `0x82` | GET | Retrieve value from server DB |
| `0x83` | DELETE | Remove key from server DB |
| `0x84` | LIST | Return all DB entries as JSON |
| `0x85` | REGISTER | Register a named address for this client |
| `0x86` | UNREGISTER | Remove a registered address |
| `0x87` | WHOAMI | Get your own UUID |
| `0x88` | BYE | Graceful disconnect |

**Client requests** (opcode bit 7 clear):

| Opcode | Name | Description |
| --- | --- | --- |
| `0x01` | WHOHAS | Find which client owns a registered key |
| `0x02` | PUT_INBOX | Push a request into another client's inbox |
| `0x03` | GET_INBOX | Pop the next request from your own inbox |
| `0x04` | PUT_OUTBOX | Write a response to another client's outbox |
| `0x05` | GET_OUTBOX | Read and consume a response from your outbox |

## Architecture

```text
Client A                          Server                           Client B
  |                                 |                                 |
  |-- X25519 + auth + login ------> |                                 |
  |<-- UUID assigned -------------- |                                 |
  |                                 |                                 |
  |-- FIND("mykey") --------------> |                                 |
  |<-- UUID_of_B -----------------  |                                 |
  |                                 |                                 |
  |-- REQUEST(B_uuid, payload) -->  |                                 |
  |                                 | PUT_INBOX -> queue[B].inbox --> |
  |<-- request_id ----------------- |                                 |
  |                                 |     GET_INBOX -> A -----------> |
  |                                 | <-- Request (from inbox) ------ |
  |                                 |                                 |
  |                                 |     RESPOND(A_uuid, resp) ----> |
  |                                 | - PUT_OUTBOX -> outbox[req_id]  |
  |                                 |     GET_OUTBOX -> A ----------> |
  | <-- Response ------------------ |                                 |
```

### Security Model

- **Per-session X25519** - each connection gets fresh ephemeral keys (perfect forward secrecy).
- **ChaCha20-Poly1305 AEAD** - authenticated encryption with per-packet unique nonces.
- **Constant-time password verify** - `hmac.compare_digest` prevents timing side-channels.
- **CRC32 after decryption** - second integrity check catches corruption the AEAD tag might miss (e.g., memory tampering).

### Factory System

Pipebomb uses duck-typed factories via Python `Protocol` for all pluggable components:

| Factory | Purpose | Built-in | Customizable |
| --- | --- | --- | --- |
| `SocketFactory` | Creates and configures transport sockets | TCP, Unix socket | Yes - implement the protocol for any transport |
| `DictFactory` | Creates dict-like storage backends | In-memory dict | Yes - use Redis, SQLite, LMDB, etc. |

Both factories follow simple protocols: a callable returning instances plus helper methods for address resolution (`SocketFactory`) or standard mapping methods (`DictFactory`).

## Attribution

If you redistribute Pipebomb or substantial portions of it, you must preserve the LICENSE and NOTICE files as required by Apache 2.0. Visible credit in documentation or UI is appreciated but not required.

- See [NOTICE](NOTICE).

## License

- [LICENSE](LICENSE)
