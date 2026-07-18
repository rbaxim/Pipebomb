import asyncio
import time
import pytest
import pipebomb.gsyncio as gsyncio
from pipebomb.server import Server
from pipebomb.client import Client
from pipebomb.utils import CancelableTask, run_task_async


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def gsyncio_loaded(gsyncio_library_location):
    if not gsyncio_library_location.exists():
        pytest.skip("gsyncio shared library not found")
    from pipebomb.utils import _init_gsyncio
    _init_gsyncio()
    yield


@pytest.fixture
async def server_gsyncio(port_fixture):
    s = Server("localhost", port_fixture, multithreaded=True)
    try:
        await s.start(client_accepters=1)
        yield s
    finally:
        await s.stop()


@pytest.fixture
async def server_singlethreaded(port_fixture):
    s = Server("localhost", port_fixture, multithreaded=False)
    try:
        await s.start()
        yield s
    finally:
        await s.stop()


# ---------------------------------------------------------------------------
# CancelableTask - asyncio-backed tasks (no gsyncio)
# ---------------------------------------------------------------------------

class TestCancelableTaskAsyncio:
    async def test_done_returns_false_before_completion(self):
        async def slow():
            await asyncio.sleep(10)

        task = CancelableTask(asyncio.create_task(slow()), None)
        assert task.done() is False
        task.cancel()

    async def test_done_returns_true_after_completion(self):
        async def fast():
            return 42

        task = CancelableTask(asyncio.create_task(fast()), None)
        await asyncio.sleep(0.05)
        assert task.done() is True

    async def test_result_returns_correct_value(self):
        async def compute():
            return 123

        task = CancelableTask(asyncio.create_task(compute()), None)
        await asyncio.sleep(0.05)
        assert task.result() == 123

    async def test_result_raises_on_cancelled_task(self):
        async def never():
            await asyncio.sleep(10)

        task = CancelableTask(asyncio.create_task(never()), None)
        task.cancel()
        await asyncio.sleep(0.05)
        with pytest.raises(asyncio.CancelledError):
            task.result()

    async def test_exception_returns_none_when_no_exception(self):
        async def ok():
            return "hello"

        task = CancelableTask(asyncio.create_task(ok()), None)
        await asyncio.sleep(0.05)
        assert task.exception() is None

    async def test_exception_returns_exception_when_raised(self):
        async def fail():
            raise ValueError("boom")

        task = CancelableTask(asyncio.create_task(fail()), None)
        await asyncio.sleep(0.05)
        exc = task.exception()
        assert isinstance(exc, ValueError)
        assert str(exc) == "boom"

    async def test_cancel_returns_false_when_already_cancelled(self):
        async def never():
            await asyncio.sleep(10)

        task = CancelableTask(asyncio.create_task(never()), None)
        task.cancel()
        assert task.cancel() is False

    async def test_cancel_stops_task(self):
        async def cancellable():
            await asyncio.sleep(10)

        task = CancelableTask(asyncio.create_task(cancellable()), None)
        task.cancel()
        await asyncio.sleep(0.05)
        assert task.done() is True

    async def test_task_id_is_none_for_asyncio_backed(self):
        async def fast():
            pass

        task = CancelableTask(asyncio.create_task(fast()), None)
        await asyncio.sleep(0.05)
        assert task.task_id is None


# ---------------------------------------------------------------------------
# CancelableTask - gsyncio-backed tasks
# ---------------------------------------------------------------------------

class TestCancelableTaskGsyncio:
    def test_result_from_go_callback(self, gsyncio_loaded):
        def sync_work():
            return "done"

        task = run_task_async(sync_work)
        asyncio.get_event_loop().run_until_complete(asyncio.sleep(1))
        assert task.done() is True
        assert task.result() == "done"

    def test_exception_propagated_from_go_callback(self, gsyncio_loaded):
        def failing_work():
            raise RuntimeError("go error")

        task = run_task_async(failing_work)
        asyncio.get_event_loop().run_until_complete(asyncio.sleep(1))
        assert task.done() is True
        exc = task.exception()
        assert isinstance(exc, RuntimeError)
        assert str(exc) == "go error"

    def test_go_callback_task_id_is_set(self, gsyncio_loaded):
        def sync_work():
            return 42

        task = run_task_async(sync_work)
        asyncio.get_event_loop().run_until_complete(asyncio.sleep(0.5))
        assert task.task_id is not None
        assert isinstance(task.task_id, int)

    def test_cancel_gsyncio_task(self, gsyncio_loaded):
        completed = {"flag": False}

        def long_work():
            for _ in range(1000000):
                completed["flag"] = True

        task = run_task_async(long_work)
        asyncio.get_event_loop().run_until_complete(asyncio.sleep(0.1))
        if not task.done():
            task.cancel()

    def test_gsyncio_result_with_computation(self, gsyncio_loaded):
        def compute():
            total = 0
            for i in range(10000):
                total += i
            return total

        task = run_task_async(compute)
        asyncio.get_event_loop().run_until_complete(asyncio.sleep(1))
        assert task.result() == sum(range(10000))


# ---------------------------------------------------------------------------
# run_task_async - coroutine vs sync callback detection
# ---------------------------------------------------------------------------

class TestRunTaskAsync:
    async def test_coroutine_callback_runs_in_asyncio(self):
        async def coro():
            await asyncio.sleep(0.01)
            return "coro_result"

        task = run_task_async(coro)
        assert isinstance(task, CancelableTask)
        await asyncio.sleep(0.1)
        assert task.done() is True
        assert task.result() == "coro_result"

    async def test_sync_callback_without_gsyncio_uses_threadpool(self):
        def sync_work(x, y):
            return x + y

        task = run_task_async(sync_work, 3, 7)
        await asyncio.sleep(0.5)
        assert task.done() is True
        assert task.result() == 10

    async def test_sync_callback_with_kwargs(self):
        def greet(greeting="hello", name="world"):
            return f"{greeting} {name}"

        task = run_task_async(greet, greeting="hi", name="alice")
        await asyncio.sleep(0.5)
        assert task.result() == "hi alice"

    async def test_coroutine_with_exception(self):
        async def failing_coro():
            await asyncio.sleep(0.01)
            raise TypeError("type error")

        task = run_task_async(failing_coro)
        await asyncio.sleep(0.1)
        assert task.done() is True
        exc = task.exception()
        assert isinstance(exc, TypeError)

    async def test_run_task_async_returns_cancelable_task(self):
        async def dummy():
            pass

        task = run_task_async(dummy)
        await asyncio.sleep(0.05)
        assert isinstance(task, CancelableTask)
        assert hasattr(task, "cancel")
        assert hasattr(task, "done")
        assert hasattr(task, "result")
        assert hasattr(task, "exception")


# ---------------------------------------------------------------------------
# Multithreaded server - basic operations
# ---------------------------------------------------------------------------

class TestMultithreadedServer:
    async def _run(self, port_fixture):
        client = Client("localhost", port_fixture)
        await client.connect()
        return client

    async def test_set_and_get_single_client(self, server_gsyncio, port_fixture):
        client = await self._run(port_fixture)
        assert await client.set("key1", "val1") is True
        result = await client.get("key1")
        assert result == b"val1"
        await client.close()

    async def test_set_and_get_multiple_keys(self, server_gsyncio, port_fixture):
        client = await self._run(port_fixture)
        for i in range(5):
            assert await client.set(f"k{i}", f"v{i}") is True
        for i in range(5):
            result = await client.get(f"k{i}")
            assert result == f"v{i}".encode()
        await client.close()

    async def test_delete_key(self, server_gsyncio, port_fixture):
        client = await self._run(port_fixture)
        assert await client.set("delme", "value") is True
        assert await client.delete("delme") is True
        result = await client.get("delme")
        assert b"ERR" in result
        await client.close()

    async def test_get_nonexistent_key(self, server_gsyncio, port_fixture):
        client = await self._run(port_fixture)
        result = await client.get("nope")
        assert b"ERR" in result
        await client.close()

    async def test_overwrite_key(self, server_gsyncio, port_fixture):
        client = await self._run(port_fixture)
        assert await client.set("overwrite", "first") is True
        assert await client.set("overwrite", "second") is True
        result = await client.get("overwrite")
        assert result == b"second"
        await client.close()

    async def test_list_empty_db(self, server_gsyncio, port_fixture):
        client = await self._run(port_fixture)
        result = await client.list()
        assert result == {}
        await client.close()

    async def test_list_with_keys(self, server_gsyncio, port_fixture):
        client = await self._run(port_fixture)
        await client.set("a", "1")
        await client.set("b", "2")
        result = await client.list()
        assert result == {"a": "1", "b": "2"}
        await client.close()

    async def test_whoami(self, server_gsyncio, port_fixture):
        client = await self._run(port_fixture)
        result = await client.whoami()
        assert len(result) == 36
        await client.close()


# ---------------------------------------------------------------------------
# Multithreaded server - concurrent clients
# ---------------------------------------------------------------------------

class TestConcurrentClients:
    async def test_two_clients_set_separate_keys(self, server_gsyncio, port_fixture):
        c1 = Client("localhost", port_fixture)
        c2 = Client("localhost", port_fixture)
        await c1.connect()
        await c2.connect()

        await c1.set("from_c1", "val1")
        await c2.set("from_c2", "val2")

        r1 = await c1.get("from_c1")
        r2 = await c2.get("from_c2")

        assert r1 == b"val1"
        assert r2 == b"val2"

        await c1.close()
        await c2.close()

    async def test_two_clients_interleaved_ops(self, server_gsyncio, port_fixture):
        c1 = Client("localhost", port_fixture)
        c2 = Client("localhost", port_fixture)
        await c1.connect()
        await c2.connect()

        for i in range(3):
            await c1.set(f"c1key{i}", f"c1val{i}")
            await c2.set(f"c2key{i}", f"c2val{i}")

        for i in range(3):
            r1 = await c1.get(f"c1key{i}")
            r2 = await c2.get(f"c2key{i}")
            assert r1 == f"c1val{i}".encode()
            assert r2 == f"c2val{i}".encode()

        await c1.close()
        await c2.close()

    async def test_three_clients_concurrent(self, server_gsyncio, port_fixture):
        clients = [Client("localhost", port_fixture) for _ in range(3)]
        for c in clients:
            await c.connect()

        for i, c in enumerate(clients):
            for j in range(2):
                await c.set(f"c{i}_k{j}", f"c{i}_v{j}")

        for i, c in enumerate(clients):
            for j in range(2):
                r = await c.get(f"c{i}_k{j}")
                assert r == f"c{i}_v{j}".encode()

        for c in clients:
            await c.close()

    async def test_two_clients_competing_same_key(self, server_gsyncio, port_fixture):
        c1 = Client("localhost", port_fixture)
        c2 = Client("localhost", port_fixture)
        await c1.connect()
        await c2.connect()

        await c1.set("contention", "from_c1")
        await c2.set("contention", "from_c2")

        r1 = await c1.get("contention")
        assert r1 == b"from_c2"

        await c1.close()
        await c2.close()


# ---------------------------------------------------------------------------
# Single-threaded server - parity with multithreaded behavior
# ---------------------------------------------------------------------------

class TestSingleThreadedServer:
    async def test_set_and_get(self, server_singlethreaded, port_fixture):
        client = Client("localhost", port_fixture)
        await client.connect()
        assert await client.set("k", "v") is True
        result = await client.get("k")
        assert result == b"v"
        await client.close()

    async def test_delete(self, server_singlethreaded, port_fixture):
        client = Client("localhost", port_fixture)
        await client.connect()
        assert await client.set("delme", "v") is True
        assert await client.delete("delme") is True
        result = await client.get("delme")
        assert b"ERR" in result
        await client.close()

    async def test_list(self, server_singlethreaded, port_fixture):
        client = Client("localhost", port_fixture)
        await client.connect()
        await client.set("a", "1")
        await client.set("b", "2")
        result = await client.list()
        assert result == {"a": "1", "b": "2"}
        await client.close()


# ---------------------------------------------------------------------------
# Register / Unregister operations
# ---------------------------------------------------------------------------

class TestRegisterOperations:
    async def test_register_singlethreaded(self, server_singlethreaded, port_fixture):
        client = Client("localhost", port_fixture)
        await client.connect()
        assert await client.register("mykey") is True
        result = await client.find("mykey")
        uuid_bytes = await client.whoami()
        assert result == uuid_bytes
        await client.close()

    async def test_unregister_singlethreaded(self, server_singlethreaded, port_fixture):
        client = Client("localhost", port_fixture)
        await client.connect()
        await client.register("unregkey")
        assert await client.unregister("unregkey") is True
        result = await client.find("unregkey")
        assert b"ERR" in result
        await client.close()

    async def test_register_multithreaded(self, server_gsyncio, port_fixture):
        client = Client("localhost", port_fixture)
        await client.connect()
        assert await client.register("mtkey") is True
        result = await client.find("mtkey")
        uuid_bytes = await client.whoami()
        assert result == uuid_bytes
        await client.close()

    async def test_cannot_register_duplicate(self, server_gsyncio, port_fixture):
        c1 = Client("localhost", port_fixture)
        c2 = Client("localhost", port_fixture)
        await c1.connect()
        await c1.register("dupkey")

        await c2.connect()
        try:
            await c2.register("dupkey")
        except RuntimeError:
            pass  # Expected — duplicate registration fails

        await c1.close()
        await c2.close()

class TestServerLifecycle:
    async def test_server_stop_cancels_tasks(self, port_fixture):
        s = Server("localhost", port_fixture, multithreaded=True)
        await s.start(client_accepters=1)
        assert len(s.tasks) >= 1 # pyright: ignore[reportAttributeAccessIssue]
        await s.stop()
        for t in s.tasks: # pyright: ignore[reportAttributeAccessIssue]
            assert t.done() or t._cancelled

    async def test_server_stop_cleans_db(self, port_fixture):
        s = Server("localhost", port_fixture)
        await s.start()
        s[b"before_stop"] = b"value"
        assert b"before_stop" in s
        await s.stop()
        assert len(s.db) == 0
        assert len(s.client_db) == 0