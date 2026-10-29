"""Integration lifecycle and WebSocket API contracts."""

import asyncio

from helpers import BackendTestCase


class WebSocketTests(BackendTestCase):
    async def test_authenticated_non_admin_can_read(self):
        connection = await self.request("get", self.connection(admin=False))
        connection.send_result.assert_called_once_with(1, {"travellers": {}, "groups": {}})

    async def test_non_admin_cannot_mutate(self):
        connection = await self.request(
            "change", self.connection(admin=False), action="add_traveller", name="Alice",
        )
        connection.send_error.assert_called_once_with(
            1, "unauthorized", "Administrator access is required to change BeenThere data.",
        )
        self.store.async_save.assert_not_awaited()
        self.assertEqual((await self.current_data())["travellers"], {})

    async def test_missing_user_cannot_mutate(self):
        connection = self.connection()
        connection.user = None
        await self.request("change", connection, action="add_traveller", name="Alice")
        connection.send_error.assert_called_once()
        self.store.async_save.assert_not_awaited()

    async def test_admin_can_mutate_and_notify(self):
        connection = await self.request("change", action="add_traveller", name="Alice")
        data = connection.send_result.call_args.args[1]
        self.assertEqual(next(iter(data["travellers"].values()))["name"], "Alice")
        self.assertEqual(self.store.saved, data)
        self.hass.bus.async_fire.assert_called_once_with(
            "beenthere_updated", {"entry_id": "entry"},
        )

    async def test_invalid_change_never_saves_or_notifies(self):
        connection = await self.request("change", action="add_traveller", name=" ")
        self.assertEqual(connection.send_error.call_args.args[1], "invalid_request")
        self.store.async_save.assert_not_awaited()
        self.hass.bus.async_fire.assert_not_called()


class IntegrationSetupTests(BackendTestCase):
    async def test_failed_setup_does_not_activate_api(self):
        await self.integration.async_unload_entry(self.hass, self.entry)
        self.integration.panel_custom.async_register_panel.side_effect = RuntimeError("panel unavailable")
        with self.assertRaises(RuntimeError):
            await self.integration.async_setup_entry(self.hass, self.entry)
        connection = await self.request("get")
        self.assertEqual(connection.send_error.call_args.args[1], "not_loaded")

    async def test_unload_rejects_reads_and_writes(self):
        await self.integration.async_unload_entry(self.hass, self.entry)
        for command in ("get", "change"):
            connection = await self.request(command, action="add_traveller", name="Alice")
            self.assertEqual(connection.send_error.call_args.args[1], "not_loaded")
        self.store.async_save.assert_not_awaited()

    async def test_reload_uses_new_state_without_registering_more_commands(self):
        await self.integration.async_unload_entry(self.hass, self.entry)
        self.store.async_load.return_value = {
            "travellers": {"new": {"name": "New", "countries": ["GF"]}}, "groups": {},
        }
        await self.integration.async_setup(self.hass, {})
        await self.integration.async_setup_entry(self.hass, self.entry)
        self.assertEqual(self.websocket.async_register_command.call_count, 2)
        self.assertEqual((await self.current_data())["travellers"]["new"]["countries"], ["GF"])
        self.hass.http.async_register_static_paths.assert_awaited_once()

    async def test_unload_waits_for_save_and_rejects_queued_change(self):
        started = asyncio.Event()
        release = asyncio.Event()

        async def slow_save(data):
            started.set()
            await release.wait()
            await self.store.save(data)

        self.store.async_save.side_effect = slow_save
        first = asyncio.create_task(self.request("change", action="add_traveller", name="One"))
        await started.wait()
        queued = asyncio.create_task(self.request("change", action="add_traveller", name="Two"))
        unload = asyncio.create_task(self.integration.async_unload_entry(self.hass, self.entry))
        await asyncio.sleep(0)
        self.assertFalse(unload.done())
        release.set()
        _, rejected, _ = await asyncio.gather(first, queued, unload)
        self.assertEqual(rejected.send_error.call_args.args[1], "not_loaded")
        self.assertEqual(len(self.store.saved["travellers"]), 1)