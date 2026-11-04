"""Persistence guarantees and serialized writes."""

import asyncio
from unittest.mock import patch

from helpers import BackendTestCase


class PersistenceTests(BackendTestCase):
    async def test_map_detail_survives_reload_without_changing_traveller_history(self):
        await self.request("change", action="add_traveller", name="Alice")
        ident = next(iter((await self.current_data())["travellers"]))
        await self.request("change", action="set_visit", target_id=ident, location="US-CA", visited=True)
        for enabled in (True, False, True):
            await self.request("change", action="set_map_detail", country="US", enabled=enabled)
        before = self.store.saved
        await self.integration.async_unload_entry(self.hass, self.entry)
        self.store.async_load.return_value = before
        await self.integration.async_setup_entry(self.hass, self.entry)
        self.assertEqual(await self.current_data(), before)
        self.assertEqual(before["travellers"][ident]["countries"], ["US-CA"])

    async def test_map_detail_save_failure_does_not_publish_or_notify(self):
        self.store.async_save.side_effect = OSError("disk unavailable")
        with self.assertLogs(self.integration.__name__, level="ERROR"):
            connection = await self.request("change", action="set_map_detail", country="US", enabled=True)
        self.assertEqual(connection.send_error.call_args.args[1], "storage_error")
        self.assertEqual((await self.current_data())["map_settings"], {"subdivision_countries": ["GB"]})
        self.hass.bus.async_fire.assert_not_called()

    async def test_concurrent_settings_and_visit_updates_are_serialized(self):
        await self.request("change", action="add_traveller", name="Alice")
        ident = next(iter((await self.current_data())["travellers"]))
        await asyncio.gather(
            self.request("change", action="set_map_detail", country="US", enabled=True),
            self.request("change", action="set_visit", target_id=ident, location="US-CA", visited=True),
            self.request("change", action="set_map_detail", country="CA", enabled=True),
        )
        self.assertEqual(self.store.saved["map_settings"], {"subdivision_countries": ["CA", "GB", "US"]})
        self.assertEqual(self.store.saved["travellers"][ident]["countries"], ["US-CA"])

    async def test_store_uses_private_atomic_writes(self):
        with patch.object(self.integration, "BeenThereStore") as store_type:
            self.make_store(self.hass, self.entry)
        store_type.assert_called_once_with(
            self.hass, 2, "beenthere.entry", private=True, atomic_writes=True,
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

    async def test_failed_visit_save_preserves_published_history_and_can_retry(self):
        await self.request("change", action="add_traveller", name="Alice")
        ident = next(iter((await self.current_data())["travellers"]))
        self.store.async_save.side_effect = OSError("disk unavailable")
        self.hass.bus.async_fire.reset_mock()
        with self.assertLogs(self.integration.__name__, level="ERROR"):
            connection = await self.request(
                "change", action="set_visit", target_id=ident, location="US-CA", visited=True,
            )
        self.assertEqual(connection.send_error.call_args.args[1], "storage_error")
        self.assertEqual((await self.current_data())["travellers"][ident]["countries"], [])
        self.hass.bus.async_fire.assert_not_called()
        self.store.async_save.side_effect = self.store.save
        for repeat in range(2):
            connection = await self.request(
                "change", action="set_visit", target_id=ident, location="US-CA", visited=True,
            )
            connection.send_error.assert_not_called()
        self.assertEqual(self.store.saved["travellers"][ident]["countries"], ["US-CA"])

    async def test_concurrent_subdivision_visits_do_not_overwrite_each_other(self):
        await self.request("change", action="add_traveller", name="Alice")
        ident = next(iter((await self.current_data())["travellers"]))
        await asyncio.gather(*(
            self.request("change", action="set_visit", target_id=ident, location=code, visited=True)
            for code in ("US-CA", "US-FL", "US-CA")
        ))
        self.assertEqual(self.store.saved["travellers"][ident]["countries"], ["US-CA", "US-FL"])