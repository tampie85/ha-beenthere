"""Optional real-browser panel contracts with synthetic Home Assistant boundaries."""

import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import urlparse

from helpers import COMPONENT_ROOT

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None


@unittest.skipIf(sync_playwright is None, "Optional browser runtime: playwright with Chromium")
class PanelBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        try:
            cls.browser = cls.playwright.chromium.launch()
        except Exception:
            cls.playwright.stop()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.context = self.browser.new_context(viewport={"width": 1440, "height": 1000})
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.errors = []
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.context.route("**/*", self.route)

    def route(self, route):
        url = urlparse(route.request.url)
        if url.hostname == "beenthere.test":
            if url.path == "/":
                route.fulfill(content_type="text/html", body="""
                    <!doctype html><html><head><meta charset="utf-8"/>
                    <style>body{margin:0;font:14px sans-serif}</style></head><body>
                    <script type="module">
                    import '/beenthere/beenthere-panel.js';
                    const clone=value=>JSON.parse(JSON.stringify(value));
                    window.snapshot={travellers:{alice:{name:'Alice',countries:['US-CA','FR']}},
                        groups:{family:{name:'Family',members:['alice']}},
                        map_settings:{subdivision_countries:['GB']}};
                    window.originalHistory=JSON.stringify(snapshot.travellers);
                    window.wsMessages=[];
                    window.callbacks=new Set();
                    window.failNextSave=false;
                    window.addPanel=admin=>{
                        const panel=document.createElement('beenthere-panel');
                        document.body.append(panel);
                        const listeners=new Map();
                        panel.hass={user:{is_admin:admin},connection:{connected:true,
                            addEventListener:(type,handler)=>listeners.set(type,handler),
                            removeEventListener:(type,handler)=>listeners.delete(type),
                            subscribeEvents:async handler=>{callbacks.add(handler);return ()=>callbacks.delete(handler);}},
                            callWS:async message=>{
                                wsMessages.push(message);
                                if(message.type==='beenthere/get')return clone(snapshot);
                                if(!admin)throw new Error('Administrator access is required');
                                if(failNextSave){failNextSave=false;throw new Error('Storage unavailable');}
                                if(message.action==='set_map_detail'){
                                    const enabled=new Set(snapshot.map_settings.subdivision_countries);
                                    if(message.enabled)enabled.add(message.country);else enabled.delete(message.country);
                                    snapshot.map_settings.subdivision_countries=[...enabled].sort();
                                } else if(message.action==='set_visit'){
                                    const traveller=snapshot.travellers[message.target_id];
                                    const countries=new Set(traveller.countries);
                                    if(message.visited)countries.add(message.location);else countries.delete(message.location);
                                    traveller.countries=[...countries].sort();
                                } else {
                                    throw new Error('Unexpected mutation');
                                }
                                callbacks.forEach(handler=>handler({event_type:'beenthere_updated'}));
                                return clone(snapshot);
                            }};
                        return panel;
                    };
                    window.renderer=index=>document.querySelectorAll('beenthere-panel')[index]
                        .shadowRoot.querySelector('beenthere-card');
                    </script></body></html>
                """)
                return
            files = {
                "/beenthere/beenthere-panel.js": COMPONENT_ROOT / "frontend" / "beenthere-panel.js",
                "/beenthere/beenthere-card.js": COMPONENT_ROOT / "frontend" / "beenthere-card.js",
                "/beenthere/geography.json": COMPONENT_ROOT / "geography.json",
            }
            files.update({
                f"/beenthere/maps/{code}.geojson":
                    COMPONENT_ROOT / "frontend" / "maps" / f"{code}.geojson"
                for code in ("AU", "CA", "DE", "GB", "US")
            })
            if url.path in files:
                route.fulfill(
                    content_type="application/json" if url.path.endswith((".json", ".geojson")) else "text/javascript",
                    body=files[url.path].read_text(),
                )
                return
        if url.hostname == "raw.githubusercontent.com":
            features = [
                {"type": "Feature", "properties": {"ISO_A2_EH": code, "ADMIN": name,
                                                   "CONTINENT": continent},
                 "geometry": {"type": "Polygon", "coordinates": [coordinates]}}
                for code, name, continent, coordinates in (
                    ("US", "United States", "North America", [[-120, 25], [-70, 25], [-70, 50], [-120, 50], [-120, 25]]),
                    ("FR", "France", "Europe", [[-5, 42], [8, 42], [8, 51], [-5, 51], [-5, 42]]),
                    ("AU", "Australia", "Oceania", [[112, -44], [154, -44], [154, -10], [112, -10], [112, -44]]),
                )
            ]
            route.fulfill(content_type="application/json", body=json.dumps({"type": "FeatureCollection", "features": features}))
            return
        route.abort()

    def open_panels(self, count=1, admin=True):
        self.page.goto("http://beenthere.test/")
        self.page.wait_for_function("typeof window.addPanel==='function'")
        self.page.evaluate("options=>{for(let index=0;index<options.count;index++)addPanel(options.admin);}",
                           {"count": count, "admin": admin})
        self.page.wait_for_function("count=>callbacks.size===count && [...document.querySelectorAll('beenthere-panel')].every((panel,index)=>renderer(index).catalogue && renderer(index).data && renderer(index).geo)", arg=count)

    def show_settings(self, index=0):
        panel = self.page.locator("beenthere-panel").nth(index)
        panel.get_by_role("button", name="Settings", exact=True).click()
        return panel

    def wait_for_detail(self, index, enabled):
        self.page.wait_for_function(
            "options=>renderer(options.index).data.map_settings.subdivision_countries.includes('US')===options.enabled && !renderer(options.index)._pendingChanges",
            arg={"index": index, "enabled": enabled},
        )

    def test_global_controls_defaults_and_history_preservation(self):
        self.open_panels()
        panel = self.show_settings()
        self.assertEqual(panel.locator("#vc-settings").get_by_role("checkbox").count(), 5)
        self.assertTrue(panel.get_by_role("checkbox", name="Subdivision tracking for United Kingdom", exact=True).is_checked())
        united_states = panel.get_by_role("checkbox", name="Subdivision tracking for United States", exact=True)
        self.assertFalse(united_states.is_checked())
        united_states.check()
        self.wait_for_detail(0, True)
        self.assertTrue(self.page.evaluate("JSON.stringify(snapshot.travellers)===originalHistory"))
        changes = self.page.evaluate("wsMessages.filter(message=>message.type==='beenthere/change')")
        self.assertEqual(changes, [{"type": "beenthere/change", "action": "set_map_detail", "country": "US", "enabled": True}])
        self.assertEqual(self.errors, [])

    def open_us_map(self, selection="t:alice"):
        self.page.evaluate("""selection=>{
            snapshot.map_settings.subdivision_countries.push('US');
            renderer(0).data=JSON.parse(JSON.stringify(snapshot));
            renderer(0).selection=selection;
            renderer(0).continent='North America';
            renderer(0).render();
        }""", selection)
        panel = self.page.locator("beenthere-panel").first
        self.page.wait_for_function("!!renderer(0).regionalMaps?.US")
        return panel

    def test_map_selection_persists_exact_subdivision_and_survives_reload(self):
        self.open_panels()
        panel = self.open_us_map()
        self.assertEqual(panel.locator(".region-shape").count(), 51)
        florida = panel.locator('[data-location="US-FL"]')
        florida.focus()
        florida.press("Enter")
        self.page.wait_for_function("!renderer(0)._pendingChanges && snapshot.travellers.alice.countries.includes('US-FL')")
        self.assertEqual(self.page.evaluate("snapshot.travellers.alice.countries"), ["FR", "US-CA", "US-FL"])
        self.assertIn("active", florida.get_attribute("class"))
        self.assertNotIn("active", panel.locator('[data-location="US-AK"]').get_attribute("class"))
        self.assertEqual(panel.locator("#details").count(), 0)
        self.page.evaluate("renderer(0).data=null; renderer(0).refreshData();")
        self.page.wait_for_function("renderer(0).data?.travellers.alice.countries.includes('US-FL')")
        self.assertEqual(florida.get_attribute('aria-pressed'), 'true')
        self.assertEqual(self.page.evaluate("renderer(0).selection"), "t:alice")
        self.assertEqual(self.page.evaluate("renderer(0).continent"), "North America")
        self.assertNotIn("partial", panel.locator('.country[data-idx="0"]').get_attribute("class"))
        self.assertEqual(self.errors, [])

    def test_unvisited_region_outlines_match_country_outlines_until_a_region_is_visited(self):
        self.open_panels()
        self.page.evaluate("snapshot.travellers.alice.countries=['FR']")
        panel = self.open_us_map()
        alaska = panel.locator('[data-location="US-AK"]')
        country = panel.locator('.country[data-idx="0"]')
        self.assertEqual(country.evaluate("element=>getComputedStyle(element).stroke"), "rgb(57, 92, 116)")
        self.assertEqual(alaska.evaluate("element=>getComputedStyle(element).stroke"), "rgb(57, 92, 116)")

        panel.locator('[data-location="US-FL"]').dispatch_event("click")
        self.page.wait_for_function(
            "!renderer(0)._pendingChanges && snapshot.travellers.alice.countries.includes('US-FL')"
        )
        self.assertEqual(alaska.evaluate("element=>getComputedStyle(element).stroke"), "rgb(57, 92, 116)")
        self.assertEqual(self.errors, [])

    def test_unvisited_australian_region_outlines_match_country_outline(self):
        self.open_panels()
        self.page.evaluate("""
            snapshot.travellers.alice.countries=[];
            snapshot.map_settings.subdivision_countries=['AU'];
            renderer(0).data=JSON.parse(JSON.stringify(snapshot));
            renderer(0).render();
        """)
        panel = self.page.locator("beenthere-panel").first
        self.page.wait_for_function("!!renderer(0).regionalMaps?.AU")
        country = panel.locator('.country[aria-label="Australia"]')
        region = panel.locator('.region-shape').first
        self.assertGreater(panel.locator('.region-shape').count(), 0)
        expected = "rgb(57, 92, 116)"
        self.assertEqual(country.evaluate("element=>getComputedStyle(element).stroke"), expected)
        self.assertEqual(region.evaluate("element=>getComputedStyle(element).stroke"), expected)
        self.assertEqual(self.errors, [])

    def test_unvisited_regions_do_not_inherit_the_country_visit_fill(self):
        self.open_panels()
        panel = self.open_us_map()
        country = panel.locator('.country[aria-label="United States"]')
        california = panel.locator('[data-location="US-CA"]')
        alaska = panel.locator('[data-location="US-AK"]')
        self.assertEqual(country.evaluate("element=>getComputedStyle(element).fill"), "rgb(36, 65, 89)")
        self.assertEqual(country.evaluate("element=>getComputedStyle(element).strokeDasharray"), "none")
        self.assertEqual(california.evaluate("element=>getComputedStyle(element).fill"), "rgb(35, 217, 207)")
        self.assertEqual(alaska.evaluate("element=>getComputedStyle(element).fill"), "rgb(36, 65, 89)")
        self.assertEqual(self.errors, [])

    def test_country_and_region_side_controls_manage_explicit_records_separately(self):
        self.open_panels()
        panel = self.open_us_map()
        country = panel.locator('[data-country-item="US"]')
        self.assertEqual(country.locator('[data-region]').count(), 51)
        self.assertFalse(country.locator('[data-country-visit="US"]').is_checked())
        self.assertTrue(country.locator('[data-region="US-CA"]').is_checked())
        country.locator('[data-country-visit="US"]').check()
        self.page.wait_for_function(
            "!renderer(0)._pendingChanges && snapshot.travellers.alice.countries.includes('US')"
        )
        self.assertIn("US-CA", self.page.evaluate("snapshot.travellers.alice.countries"))
        country.locator('[data-country-visit="US"]').uncheck()
        self.page.wait_for_function(
            "!renderer(0)._pendingChanges && !snapshot.travellers.alice.countries.includes('US')"
        )
        self.assertIn("US-CA", self.page.evaluate("snapshot.travellers.alice.countries"))
        self.assertEqual(self.errors, [])

    def test_map_and_menu_selection_identify_exact_group_visitors(self):
        self.open_panels()
        self.page.evaluate("""
            snapshot.travellers.bob={name:'Bob',countries:['US-FL']};
            snapshot.groups.family.members=['alice','bob'];
        """)
        panel = self.open_us_map("g:family")
        panel.locator('[data-location="US-FL"]').dispatch_event("click")
        florida = panel.locator('[data-location="US-FL"]')
        self.page.wait_for_function(
            "renderer(0).selectedLocation==='US-FL' && renderer(0).visitors('US-FL').length===1"
        )
        self.assertEqual(florida.get_attribute("aria-current"), "true")
        self.assertIn("Bob", panel.locator(".location-visitors").inner_text())
        self.assertNotIn("Alice", panel.locator(".location-visitors").inner_text())
        panel.locator('[data-location-select="US-CA"]').click()
        self.page.wait_for_function("renderer(0).selectedLocation==='US-CA'")
        self.assertEqual(panel.locator('[data-location="US-CA"]').get_attribute("aria-current"), "true")
        self.assertEqual(panel.locator('[data-location-select="US-CA"]').get_attribute("aria-current"), "true")
        self.assertIn("Alice", panel.locator(".location-visitors").inner_text())
        self.assertNotIn("Bob", panel.locator(".location-visitors").inner_text())
        self.assertEqual(self.errors, [])

    def test_hidden_region_visits_cannot_be_cleared_from_country_map(self):
        self.open_panels()
        panel = self.open_us_map()
        self.page.evaluate("""
            snapshot.travellers.alice.countries=['US-CA'];
            snapshot.map_settings.subdivision_countries=[];
            renderer(0).data=JSON.parse(JSON.stringify(snapshot));
            renderer(0).render();
        """)
        panel.locator('.country[aria-label="United States"]').click()
        self.page.wait_for_function(
            "renderer(0).error.includes('hidden region visits')"
        )
        self.assertEqual(self.page.evaluate("snapshot.travellers.alice.countries"), ["US-CA"])
        self.assertEqual(self.page.evaluate(
            "wsMessages.filter(message=>message.type==='beenthere/change').length"
        ), 0)
        self.assertEqual(self.errors, [])

    def test_country_click_toggles_visit_for_selected_traveller(self):
        self.open_panels()
        panel = self.page.locator("beenthere-panel").first
        panel.locator('#view').select_option('t:alice')
        panel.locator('#continent').select_option('Europe')
        france = panel.locator('.country[aria-label="France"]')
        france.click()
        self.page.wait_for_function("!renderer(0)._pendingChanges && !snapshot.travellers.alice.countries.includes('FR')")
        self.assertNotIn("active", france.get_attribute("class"))
        france.focus()
        france.press("Enter")
        self.page.wait_for_function("!renderer(0)._pendingChanges && snapshot.travellers.alice.countries.includes('FR')")
        self.assertIn("active", france.get_attribute("class"))
        self.assertEqual(self.page.evaluate("renderer(0).selection"), "t:alice")
        self.assertEqual(self.errors, [])

    def test_map_focus_uses_geographic_border_without_square_outline(self):
        self.open_panels()
        panel = self.open_us_map()
        self.page.keyboard.press("Tab")
        state = panel.locator('[data-location="US-FL"]')
        state.focus()
        self.assertEqual(state.evaluate("element=>getComputedStyle(element).outlineStyle"), "none")
        self.assertEqual(state.evaluate("element=>getComputedStyle(element).stroke"), "rgb(255, 255, 255)")
        country = panel.locator('.country[data-idx="0"]')
        country.focus()
        self.assertEqual(country.evaluate("element=>getComputedStyle(element).outlineStyle"), "none")
        self.assertEqual(country.evaluate("element=>getComputedStyle(element).stroke"), "rgb(255, 255, 255)")
        self.assertEqual(self.errors, [])

    def test_state_click_keeps_focus_and_scroll_on_map(self):
        self.page.set_viewport_size({"width": 1440, "height": 700})
        self.open_panels()
        panel = self.open_us_map()
        florida = panel.locator('[data-location="US-FL"]')
        florida.focus()
        before = self.page.evaluate("({x:scrollX,y:scrollY})")
        florida.dispatch_event("click")
        self.page.wait_for_function("!renderer(0)._pendingChanges && snapshot.travellers.alice.countries.includes('US-FL')")
        self.page.wait_for_function("renderer(0).getRootNode().activeElement?.dataset.location==='US-FL'")
        self.assertEqual(self.page.evaluate("({x:scrollX,y:scrollY})"), before)
        self.assertEqual(florida.get_attribute('aria-pressed'), 'true')
        self.assertIn("active", florida.get_attribute("class"))
        self.assertEqual(self.errors, [])

    def test_group_union_and_region_controls_are_read_only(self):
        self.open_panels()
        self.page.evaluate("""
            snapshot.travellers.bob={name:'Bob',countries:['US-FL']};
            snapshot.travellers.outsider={name:'Outsider',countries:['US-AK']};
            snapshot.groups.family.members=['alice','bob'];
        """)
        panel = self.open_us_map("g:family")
        before = self.page.evaluate("JSON.stringify(snapshot.travellers)")
        for code in ("US-CA", "US-FL"):
            self.assertIn("active", panel.locator(f'[data-location="{code}"]').get_attribute("class"))
        self.assertNotIn("active", panel.locator('[data-location="US-AK"]').get_attribute("class"))
        self.assertTrue(panel.get_by_role('button', name='Collapse regions').is_visible())
        self.assertEqual(panel.locator("#details").count(), 0)
        self.assertEqual(panel.locator('[data-region]').count(), 51)
        self.assertEqual(panel.locator('[data-region]:not(:disabled)').count(), 0)
        self.assertEqual(self.page.evaluate("JSON.stringify(snapshot.travellers)"), before)
        self.assertEqual(self.page.evaluate("wsMessages.filter(message=>message.type==='beenthere/change').length"), 0)
        self.assertNotIn("partial", panel.locator('.country[data-idx="0"]').get_attribute("class"))
        self.assertEqual(self.errors, [])

    def test_explicit_country_visit_does_not_infer_states_or_get_removed_with_state(self):
        self.open_panels()
        panel = self.open_us_map()
        self.page.evaluate("renderer(0).setLocationVisit('US', true)")
        self.page.wait_for_function("!renderer(0)._pendingChanges && snapshot.travellers.alice.countries.includes('US')")
        self.assertEqual(panel.locator('[data-location="US-FL"]').get_attribute('aria-pressed'), 'false')
        panel.locator('[data-location="US-CA"]').dispatch_event('click')
        self.page.wait_for_function("!renderer(0)._pendingChanges && !snapshot.travellers.alice.countries.includes('US-CA')")
        self.assertIn("US", self.page.evaluate("snapshot.travellers.alice.countries"))
        shape = panel.locator('.country[data-idx="0"]')
        self.assertIn("active", shape.get_attribute("class"))
        self.assertNotIn("partial", shape.get_attribute("class"))
        self.assertEqual(shape.evaluate("element=>getComputedStyle(element).stroke"), "rgb(57, 92, 116)")
        self.assertEqual(self.errors, [])

    def test_failed_region_save_restores_control_and_can_retry(self):
        self.open_panels()
        panel = self.open_us_map()
        self.page.evaluate("failNextSave=true;")
        state = panel.locator('[data-location="US-CA"]')
        state.focus()
        state.press("Space")
        self.page.wait_for_function("renderer(0).error==='Storage unavailable' && !renderer(0)._pendingChanges")
        self.assertEqual(state.get_attribute('aria-pressed'), 'true')
        self.assertIn("active", panel.locator('[data-location="US-CA"]').get_attribute("class"))
        self.assertTrue(state.evaluate("element=>element===element.getRootNode().activeElement"))
        state.press('Space')
        self.page.wait_for_function("!renderer(0)._pendingChanges && !snapshot.travellers.alice.countries.includes('US-CA')")
        self.assertNotIn("active", panel.locator('[data-location="US-CA"]').get_attribute("class"))
        self.assertEqual(self.errors, [])

    def test_disabling_detail_returns_to_world_without_deleting_visits(self):
        self.open_panels(count=2)
        panel = self.open_us_map()
        second = self.show_settings(1)
        self.page.evaluate("callbacks.forEach(handler=>handler({}));")
        self.wait_for_detail(1, True)
        second.get_by_role("checkbox", name="Subdivision tracking for United States", exact=True).uncheck()
        self.wait_for_detail(0, False)
        self.assertEqual(panel.locator('[data-location="US-CA"]').count(), 0)
        self.assertEqual(self.page.evaluate("snapshot.travellers.alice.countries"), ["US-CA", "FR"])
        self.assertNotIn("partial", panel.locator('.country[data-idx="0"]').get_attribute("class"))
        self.assertEqual(
            panel.locator('.country[aria-label="United States"]').evaluate(
                "element=>getComputedStyle(element).fill"
            ),
            "rgb(35, 217, 207)",
        )
        self.assertEqual(self.errors, [])

    def test_region_controls_in_read_only_individual_view(self):
        self.open_panels(admin=False)
        panel = self.open_us_map()
        before = self.page.evaluate("JSON.stringify(snapshot.travellers)")
        panel.locator('[data-location="US-DC"]').focus()
        panel.locator('[data-location="US-DC"]').press("Enter")
        self.assertEqual(panel.locator("#details").count(), 0)
        self.assertEqual(self.page.evaluate("JSON.stringify(snapshot.travellers)"), before)
        self.assertEqual(self.page.evaluate("wsMessages.filter(message=>message.type==='beenthere/change').length"), 0)
        self.assertEqual(self.errors, [])

    def test_pending_region_write_blocks_duplicate_mutations(self):
        self.open_panels()
        panel = self.open_us_map()
        self.page.evaluate("""()=>{
            const hass=renderer(0)._hass, original=hass.callWS;
            hass.callWS=async message=>{
                if(message.action==='set_visit')await new Promise(resolve=>{window.finishSave=resolve;});
                return original(message);
            };
        }""")
        state = panel.locator('[data-location="US-FL"]')
        state.focus()
        state.press("Space")
        self.page.wait_for_function("typeof finishSave==='function'")
        self.assertTrue(self.page.evaluate('!!renderer(0)._pendingChanges'))
        self.page.evaluate("renderer(0).selectRegion('US-AK',true); finishSave();")
        self.page.wait_for_function("!renderer(0)._pendingChanges && snapshot.travellers.alice.countries.includes('US-FL')")
        self.assertNotIn("US-AK", self.page.evaluate("snapshot.travellers.alice.countries"))
        self.assertEqual(self.page.evaluate("wsMessages.filter(message=>message.action==='set_visit').length"), 1)
        self.assertEqual(self.errors, [])

    def test_regional_map_and_controls_fit_mobile_layout(self):
        self.open_panels()
        panel = self.open_us_map()
        for width in (1440, 390, 320):
            with self.subTest(width=width):
                self.page.set_viewport_size({"width": width, "height": 1000})
                self.assertTrue(self.page.evaluate("document.documentElement.scrollWidth<=window.innerWidth"))
                self.assertTrue(panel.locator(".map").is_visible())
                self.assertEqual(panel.locator('[data-location="US-CA"]').get_attribute('aria-pressed'), 'true')
        self.assertEqual(self.errors, [])

    def test_two_panels_share_settings_without_losing_selection(self):
        self.open_panels(count=2)
        self.page.evaluate("renderer(0).selection='t:alice'; renderer(1).selection='g:family'; renderer(1).continent='Europe'; renderer(0).render(); renderer(1).render();")
        first = self.show_settings(0)
        second = self.show_settings(1)
        first.get_by_role("checkbox", name="Subdivision tracking for United States", exact=True).check()
        self.wait_for_detail(1, True)
        self.assertTrue(second.get_by_role("checkbox", name="Subdivision tracking for United States", exact=True).is_checked())
        self.assertEqual(self.page.evaluate("renderer(0).selection"), "t:alice")
        self.assertEqual(self.page.evaluate("renderer(1).selection"), "g:family")
        self.assertEqual(self.page.evaluate("renderer(1).continent"), "Europe")
        self.assertEqual(self.errors, [])

    def test_failed_save_restores_control_and_keyboard_focus(self):
        self.open_panels()
        panel = self.show_settings()
        self.page.evaluate("failNextSave=true;")
        checkbox = panel.get_by_role("checkbox", name="Subdivision tracking for United States", exact=True)
        checkbox.focus()
        checkbox.press("Space")
        self.page.wait_for_function("renderer(0).error==='Storage unavailable' && !renderer(0)._pendingChanges")
        self.assertFalse(checkbox.is_checked())
        self.assertTrue(checkbox.evaluate("element=>element===element.getRootNode().activeElement"))
        self.assertTrue(self.page.evaluate("JSON.stringify(snapshot.travellers)===originalHistory"))
        self.assertEqual(self.errors, [])

    def test_non_admin_has_no_settings_controls(self):
        self.open_panels(admin=False)
        panel = self.page.locator("beenthere-panel")
        self.assertFalse(panel.get_by_role("button", name="Settings", exact=True).is_visible())
        self.assertEqual(panel.locator("#vc-settings").get_by_role("checkbox").count(), 0)
        self.assertEqual(self.errors, [])

    def test_settings_fit_desktop_and_mobile(self):
        self.open_panels()
        self.show_settings()
        for width in (1440, 390, 320):
            with self.subTest(width=width):
                self.page.set_viewport_size({"width": width, "height": 1000})
                self.assertTrue(self.page.evaluate("document.documentElement.scrollWidth<=window.innerWidth"))
                self.assertTrue(self.page.locator(".map-detail-option").evaluate_all("labels=>labels.every(label=>label.querySelector('span').getBoundingClientRect().right<=label.querySelector('input').getBoundingClientRect().left)"))
                self.page.screenshot(path=str(Path(tempfile.gettempdir()) / f"beenthere-settings-{width}.png"), full_page=True)
        self.assertEqual(self.errors, [])

    def test_visited_country_focus_expands_all_regions_with_visited_checked(self):
        self.open_panels()
        panel = self.open_us_map()
        self.assertEqual(panel.locator('.regional-checklists, .regional-checklist').count(), 0)
        self.assertEqual(panel.get_by_role("button", name="Regions", exact=True).count(), 0)
        country = panel.locator('.visited-country-item', has_text='United States')
        self.assertIn('1 of 51 regions visited', country.inner_text())
        country.get_by_role('button', name='United States', exact=True).click()
        self.assertEqual(panel.locator('.visited-country-list > li').first.get_attribute('data-country-item'), 'US')
        self.assertEqual(country.locator('.visited-subdivision-list li').count(), 51)
        self.assertIn('California', country.locator('.visited-subdivision-list').inner_text())
        self.assertTrue(country.get_by_role('checkbox', name='California in United States', exact=True).is_checked())
        self.assertFalse(country.get_by_role('checkbox', name='Alabama in United States', exact=True).is_checked())
        california = panel.locator('[data-location="US-CA"]')
        california.focus()
        california.press('Space')
        self.page.wait_for_function(
            "!renderer(0)._pendingChanges && !snapshot.travellers.alice.countries.includes('US-CA')",
        )
        self.assertEqual(california.get_attribute('aria-pressed'), 'false')
        changes = self.page.evaluate("wsMessages.filter(message=>message.type==='beenthere/change' && message.action==='set_visit')")
        self.assertEqual(changes, [{
            "type": "beenthere/change", "action": "set_visit",
            "target_id": "alice", "location": "US-CA", "visited": False,
        }])
        country = panel.locator('.visited-country-item[data-country-item="US"]')
        self.assertEqual(country.count(), 1)
        self.assertFalse(country.locator('[data-country-visit="US"]').is_checked())
        self.assertIn('Not visited', country.inner_text())
        self.assertEqual(self.errors, [])