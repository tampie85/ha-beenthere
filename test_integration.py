"""Backend contract tests with lightweight Home Assistant boundary doubles."""

import asyncio
from copy import deepcopy
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch


class MemoryStore:
    def __init__(self, *args, **kwargs):
        self.saved = None
        self.async_load = AsyncMock(return_value=None)
        self.async_save = AsyncMock(side_effect=self.save)

    async def save(self, data):
        self.saved = deepcopy(data)


def load_integration():
    modules = {}
    for name in (
        "homeassistant", "homeassistant.components", "homeassistant.components.frontend",
        "homeassistant.components.panel_custom", "homeassistant.components.websocket_api",
        "homeassistant.components.http", "homeassistant.config_entries",
        "homeassistant.core", "homeassistant.helpers", "homeassistant.helpers.storage",
        "homeassistant.exceptions",
    ):
        modules[name] = ModuleType(name)
    modules["homeassistant.core"].HomeAssistant = object
    modules["homeassistant.config_entries"].ConfigEntry = object
    modules["homeassistant.helpers.storage"].Store = MemoryStore
    modules["homeassistant.exceptions"].HomeAssistantError = RuntimeError
    modules["homeassistant.components.http"].StaticPathConfig = Mock()
    frontend = modules["homeassistant.components.frontend"]
    frontend.async_remove_panel = Mock()
    panel = modules["homeassistant.components.panel_custom"]
    panel.async_register_panel = AsyncMock()
    websocket = modules["homeassistant.components.websocket_api"]
    websocket.async_response = lambda handler: handler

    def websocket_command(schema):
        def decorate(handler):
            handler.command = next(iter(schema.values()))
            return handler
        return decorate

    websocket.websocket_command = websocket_command
    websocket.async_register_command = Mock(
        side_effect=lambda hass, handler: hass.commands.update({handler.command: handler})
    )
    path = Path(__file__).with_name("__init__.py")
    spec = importlib.util.spec_from_file_location(
        "beenthere_backend_test", path, submodule_search_locations=[str(path.parent)],
    )
    integration = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {**modules, spec.name: integration}):
        spec.loader.exec_module(integration)
    return integration, websocket


class BackendTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.integration, self.websocket = load_integration()
        self.hass = SimpleNamespace(
            data={}, commands={},
            http=SimpleNamespace(async_register_static_paths=AsyncMock()),
            bus=SimpleNamespace(async_fire=Mock()),
        )
        self.entry = SimpleNamespace(entry_id="entry")
        self.store = MemoryStore()
        self.make_store = self.integration._store
        self.store_patch = patch.object(self.integration, "_store", return_value=self.store)
        self.store_patch.start()
        self.addCleanup(self.store_patch.stop)
        await self.integration.async_setup(self.hass, {})
        await self.integration.async_setup_entry(self.hass, self.entry)

    def connection(self, admin=True):
        return SimpleNamespace(
            user=SimpleNamespace(is_admin=admin),
            send_result=Mock(), send_error=Mock(),
        )

    async def request(self, command, connection=None, **message):
        connection = connection or self.connection()
        await self.hass.commands[f"beenthere/{command}"](
            self.hass, connection, {"id": 1, **message},
        )
        return connection

    async def current_data(self):
        connection = await self.request("get")
        return connection.send_result.call_args.args[1]

    async def test_authenticated_non_admin_can_read(self):
        connection = await self.request("get", self.connection(admin=False))
        connection.send_result.assert_called_once_with(1, {"travellers": {}, "groups": {}})

    async def test_store_uses_private_atomic_writes(self):
        with patch.object(self.integration, "Store") as store_type:
            self.make_store(self.hass, self.entry)
        store_type.assert_called_once_with(
            self.hass, 1, "beenthere.entry", private=True, atomic_writes=True,
        )

    async def test_failed_setup_does_not_activate_api(self):
        await self.integration.async_unload_entry(self.hass, self.entry)
        self.integration.panel_custom.async_register_panel.side_effect = RuntimeError("panel unavailable")
        with self.assertRaises(RuntimeError):
            await self.integration.async_setup_entry(self.hass, self.entry)
        connection = await self.request("get")
        self.assertEqual(connection.send_error.call_args.args[1], "not_loaded")

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

    async def test_failed_save_does_not_publish_candidate(self):
        self.store.async_save.side_effect = OSError("disk unavailable")
        with self.assertLogs(self.integration.__name__, level="ERROR"):
            connection = await self.request("change", action="add_traveller", name="Alice")
        self.assertEqual(connection.send_error.call_args.args[1], "storage_error")
        connection.send_result.assert_not_called()
        self.assertEqual((await self.current_data())["travellers"], {})
        self.hass.bus.async_fire.assert_not_called()

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


if __name__ == "__main__":
    unittest.main()