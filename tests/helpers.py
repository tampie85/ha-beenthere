"""Shared storage bindings and lightweight Home Assistant test harness."""

from copy import deepcopy
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch


COMPONENT_ROOT = Path(__file__).resolve().parent.parent

_storage_spec = importlib.util.spec_from_file_location(
    "beenthere_storage", COMPONENT_ROOT / "storage.py",
)
_storage = importlib.util.module_from_spec(_storage_spec)
assert _storage_spec.loader is not None
_storage_spec.loader.exec_module(_storage)

apply_change = _storage.apply_change
normalize_data = _storage.normalize_data
valid_country_code = _storage.valid_country_code
valid_name = _storage.valid_name


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
    path = COMPONENT_ROOT / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        "beenthere_backend_test", path, submodule_search_locations=[str(path.parent)],
    )
    integration = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {**modules, spec.name: integration}):
        spec.loader.exec_module(integration)
    return integration, websocket


class BackendTestCase(unittest.IsolatedAsyncioTestCase):
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