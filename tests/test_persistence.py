"""Persistence guarantees and serialized writes."""

import asyncio
from unittest.mock import patch

from helpers import BackendTestCase


class PersistenceTests(BackendTestCase):
    async def test_store_uses_private_atomic_writes(self):
        with patch.object(self.integration, "Store") as store_type:
            self.make_store(self.hass, self.entry)
        store_type.assert_called_once_with(
            self.hass, 1, "beenthere.entry", private=True, atomic_writes=True,
        )

    async def test_failed_save_does_not_publish_candidate(self):
        self.store.async_save.side_effect = OSError("disk unavailable")
        with self.assertLogs(self.integration.__name__, level="ERROR"):
            connection = await self.request("change", action="add_traveller", name="Alice")
        self.assertEqual(connection.send_error.call_args.args[1], "storage_error")
        connection.send_result.assert_not_called()
        self.assertEqual((await self.current_data())["travellers"], {})
        self.hass.bus.async_fire.assert_not_called()

    async def test_concurrent_changes_are_serialized(self):
        started = asyncio.Event()
        release = asyncio.Event()

        async def slow_save(data):
            started.set()
            await release.wait()
            await self.store.save(data)

        self.store.async_save.side_effect = slow_save
        first = asyncio.create_task(self.request("change", action="add_traveller", name="One"))
        await started.wait()
        second = asyncio.create_task(self.request("change", action="add_traveller", name="Two"))
        await asyncio.sleep(0)
        self.assertEqual(self.store.async_save.await_count, 1)
        self.assertEqual((await self.current_data())["travellers"], {})
        release.set()
        await asyncio.gather(first, second)
        self.assertEqual(len(self.store.saved["travellers"]), 2)