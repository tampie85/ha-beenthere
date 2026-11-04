"""Integration lifecycle and WebSocket API contracts."""

import asyncio

import voluptuous as vol

from helpers import BackendTestCase


class WebSocketTests(BackendTestCase):
    async def test_us_boundaries_have_a_local_static_route(self):
        configurations = self.integration.StaticPathConfig.call_args_list
        self.assertTrue(any(
            call.args[0] == "/beenthere/maps/US.geojson"
            and call.args[1].endswith("/beenthere/frontend/maps/US.geojson")
            and call.kwargs == {"cache_headers": False}
            for call in configurations
        ))

    async def test_admin_map_detail_change_notifies_all_readers(self):
        connection = await self.request("change", action="set_map_detail", country="US", enabled=True)
        connection.send_error.assert_not_called()
        data = connection.send_result.call_args.args[1]
        self.assertEqual(data["map_settings"], {"subdivision_countries": ["GB", "US"]})
        reader = await self.request("get", self.connection(admin=False))
        self.assertEqual(reader.send_result.call_args.args[1], data)
        self.hass.bus.async_fire.assert_called_once_with("beenthere_updated", {"entry_id": "entry"})

    async def test_map_detail_requires_admin_and_rejects_bad_payloads(self):
        denied = await self.request(
            "change", self.connection(admin=False), action="set_map_detail", country="US", enabled=True,
        )
        self.assertEqual(denied.send_error.call_args.args[1], "unauthorized")
        for overrides in ({"country": "RU"}, {"enabled": 1}, {"enabled": None},
                          {"target_id": "alice"}, {"members": []}, {"map_settings": {}}):
            with self.subTest(overrides=overrides):
                message = {"action": "set_map_detail", "country": "US", "enabled": True}
                connection = await self.request("change", **(message | overrides))
                self.assertEqual(connection.send_error.call_args.args[1], "invalid_request")
        self.store.async_save.assert_not_awaited()
        self.hass.bus.async_fire.assert_not_called()

    async def test_map_detail_schema_rejects_non_boolean_states(self):
        schema = vol.Schema(self.integration.CHANGE_COMMAND)
        message = {"type": "beenthere/change", "action": "set_map_detail", "country": "US", "enabled": True}
        self.assertEqual(schema(message), message)
        for enabled in (1, 0, "true", None, []):
            with self.subTest(enabled=enabled), self.assertRaises(vol.Invalid):
                schema(message | {"enabled": enabled})

    async def test_authenticated_non_admin_can_read(self):
        connection = await self.request("get", self.connection(admin=False))
        connection.send_result.assert_called_once_with(1, {
            "travellers": {}, "groups": {},
            "map_settings": {"subdivision_countries": ["GB"]},
        })

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

    async def test_set_visit_persists_exact_ids_and_preserves_children(self):
        await self.request("change", action="add_traveller", name="Alice")
        ident = next(iter((await self.current_data())["travellers"]))
        for location in ("US-CA", "US-FL", "US", "US"):
            connection = await self.request(
                "change", action="set_visit", target_id=ident, location=location, visited=True,
            )
            connection.send_error.assert_not_called()
        await self.request("change", action="set_visit", target_id=ident, location="US", visited=False)
        self.assertEqual(self.store.saved["travellers"][ident]["countries"], ["US-CA", "US-FL"])

    async def test_set_visit_invalid_inputs_never_save(self):
        await self.request("change", action="add_traveller", name="Alice")
        ident = next(iter((await self.current_data())["travellers"]))
        self.store.async_save.reset_mock()
        self.hass.bus.async_fire.reset_mock()
        for overrides in (
            {"location": "US-XX"}, {"location": "ZZ"}, {"location": "RU-MOW"},
            {"visited": "false"}, {"visited": 1}, {"visited": None},
            {"target_id": "missing"}, {"members": []},
        ):
            with self.subTest(overrides=overrides):
                message = {"action": "set_visit", "target_id": ident, "location": "US-CA", "visited": True}
                connection = await self.request("change", **(message | overrides))
                self.assertEqual(connection.send_error.call_args.args[1], "invalid_request")
        self.store.async_save.assert_not_awaited()
        self.hass.bus.async_fire.assert_not_called()

    async def test_set_visit_requires_admin_and_rejects_group_target(self):
        await self.request("change", action="add_traveller", name="Alice")
        await self.request("change", action="add_group", name="Family", members=[])
        data = await self.current_data()
        ident = next(iter(data["travellers"]))
        group_id = next(iter(data["groups"]))
        self.store.async_save.reset_mock()
        connection = await self.request(
            "change", self.connection(admin=False), action="set_visit",
            target_id=ident, location="US-CA", visited=True,
        )
        self.assertEqual(connection.send_error.call_args.args[1], "unauthorized")
        connection = await self.request(
            "change", action="set_visit", target_id=group_id, location="US-CA", visited=True,
        )
        self.assertEqual(connection.send_error.call_args.args[1], "invalid_request")
        self.store.async_save.assert_not_awaited()

    async def test_websocket_schema_rejects_bad_types_and_unknown_fields(self):
        schema = vol.Schema(self.integration.CHANGE_COMMAND)
        valid = {"type": "beenthere/change", "action": "set_visit", "target_id": "alice",
                 "location": "US-CA", "visited": True}
        self.assertEqual(schema(valid), valid)
        for overrides in ({"action": "unknown"}, {"visited": 1}, {"visited": "true"},
                          {"location": []}, {"target_id": 1}, {"unexpected": True}):
            with self.subTest(overrides=overrides), self.assertRaises(vol.Invalid):
                schema(valid | overrides)


class IntegrationSetupTests(BackendTestCase):
    async def test_geography_asset_has_own_static_file_route(self):
        configurations = self.integration.StaticPathConfig.call_args_list
        self.assertTrue(any(
            call.args[0] == "/beenthere/geography.json"
            and call.args[1].endswith("/beenthere/geography.json")
            and call.kwargs == {"cache_headers": False}
            for call in configurations
        ))

    async def test_geography_is_preloaded_outside_event_loop(self):
        self.hass.async_add_executor_job.assert_awaited_once_with(self.integration.get_geography)

    async def test_store_migration_hook_preserves_explicit_visits(self):
        store = self.integration.BeenThereStore(self.hass, 2, "beenthere.entry")
        original = {"travellers": {"alice": {"name": "Alice", "countries": ["US-CA"]}}, "groups": {}}
        migrated = await store._async_migrate_func(1, 1, original)
        self.assertEqual(migrated["travellers"], original["travellers"])
        self.assertEqual(migrated["map_settings"], {"subdivision_countries": ["GB"]})
        with self.assertRaises(NotImplementedError):
            await store._async_migrate_func(3, 1, original)

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