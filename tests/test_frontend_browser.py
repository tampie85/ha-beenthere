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
                                } else if(message.action==='add_traveller'){
                                    snapshot.travellers.bob={name:message.name,countries:[]};
                                } else if(message.action==='rename_traveller'){
                                    snapshot.travellers[message.target_id].name=message.name;
                                } else if(message.action==='delete_traveller'){
                                    delete snapshot.travellers[message.target_id];
                                    Object.values(snapshot.groups).forEach(group=>{
                                        group.members=group.members.filter(member=>member!==message.target_id);
                                    });
                                } else if(message.action==='add_group'||message.action==='update_group'){
                                    const id=message.target_id||'trip';
                                    snapshot.groups[id]={name:message.name,members:message.members};
                                } else if(message.action==='delete_group'){
                                    delete snapshot.groups[message.target_id];
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
        self.assertTrue(panel.get_by_role("checkbox", name="Show regional detail for United Kingdom", exact=True).is_checked())
        united_states = panel.get_by_role("checkbox", name="Show regional detail for United States", exact=True)
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

    def test_sidebar_removes_only_explicit_country_visit_with_confirmation(self):
        self.open_panels()
        panel = self.open_us_map()
        country = panel.locator('[data-country-item="US"]')
        self.assertEqual(country.locator('.visited-subdivision-list li').count(), 0)
        self.assertTrue(country.get_by_role('button', name='Remove country-only visit to United States').count() == 0)
        self.assertEqual(country.get_by_role('button', name='Expand visited regions in United States').get_attribute('aria-expanded'), 'false')
        country.get_by_role('button', name='Expand visited regions in United States').click()
        self.assertEqual(country.locator('.visited-subdivision-list li').count(), 1)
        self.page.evaluate("renderer(0).setLocationVisit('US',true)")
        self.page.wait_for_function(
            "!renderer(0)._pendingChanges && snapshot.travellers.alice.countries.includes('US')"
        )
        country = panel.locator('[data-country-item="US"]')
        self.assertEqual(country.locator('.visited-subdivision-list li').count(), 1)
        messages = []
        self.page.on("dialog", lambda dialog: (messages.append(dialog.message), dialog.accept()))
        remove = country.get_by_role('button', name='Remove country-only visit to United States')
        target = remove.bounding_box()
        self.assertGreaterEqual(target["width"], 44)
        self.assertGreaterEqual(target["height"], 44)
        remove.focus()
        remove.press('Enter')
        self.page.wait_for_function(
            "!renderer(0)._pendingChanges && !snapshot.travellers.alice.countries.includes('US')"
        )
        self.assertIn("US-CA", self.page.evaluate("snapshot.travellers.alice.countries"))
        self.assertEqual(country.locator('.visited-subdivision-list li').count(), 1)
        self.assertEqual(country.get_by_role('button', name='Remove country-only visit to United States').count(), 0)
        self.assertEqual(len(messages), 1)
        self.assertIn("Regional visits, if any, will be preserved.", messages[0])
        self.assertEqual(self.errors, [])

    def test_sidebar_remove_cancel_and_failure_preserve_country_visit(self):
        self.open_panels()
        panel = self.open_us_map()
        self.page.evaluate("""
            snapshot.travellers.alice.countries=['US'];
            renderer(0).data=JSON.parse(JSON.stringify(snapshot));
            renderer(0).render();
        """)
        remove = panel.get_by_role('button', name='Remove country-only visit to United States')
        self.page.once("dialog", lambda dialog: dialog.dismiss())
        remove.click()
        self.assertIn("US", self.page.evaluate("snapshot.travellers.alice.countries"))
        self.assertEqual(self.page.evaluate("wsMessages.filter(message=>message.action==='set_visit').length"), 0)

        self.page.evaluate("failNextSave=true;")
        self.page.once("dialog", lambda dialog: dialog.accept())
        panel.get_by_role('button', name='Remove country-only visit to United States').click()
        self.page.wait_for_function(
            "renderer(0).error==='Storage unavailable' && !renderer(0)._pendingChanges"
        )
        self.assertIn("US", self.page.evaluate("snapshot.travellers.alice.countries"))
        self.assertEqual(panel.locator('[data-remove-country="US"]').count(), 1)
        self.assertEqual(self.errors, [])

    def test_empty_individual_and_group_views_show_zero_and_empty_message(self):
        self.open_panels()
        panel = self.page.locator("beenthere-panel").first
        self.page.evaluate("""
            snapshot.travellers.alice.countries=[];
            snapshot.groups.empty={name:'Empty',members:[]};
            renderer(0).data=JSON.parse(JSON.stringify(snapshot));
            renderer(0).selection='t:alice';
            renderer(0).render();
        """)
        self.assertEqual(panel.locator('.country-count').inner_text(), '(0)')
        self.assertEqual(panel.get_by_text('No countries visited yet.', exact=True).count(), 1)
        self.assertEqual(panel.locator('.visited-country-item').count(), 0)
        self.page.evaluate("renderer(0).selection='g:empty'; renderer(0).render();")
        self.assertEqual(panel.locator('.country-count').inner_text(), '(0)')
        self.assertEqual(panel.get_by_text('No countries visited yet.', exact=True).count(), 1)
        self.assertEqual(panel.locator('[data-remove-country]').count(), 0)
        self.assertEqual(self.errors, [])

    def test_view_card_controls_and_editability(self):
        self.open_panels()
        panel = self.page.locator('beenthere-panel')
        card = panel.get_by_role('region', name='Map Filters', exact=True)
        traveller = card.get_by_role('combobox', name='Travellers / Groups')
        continent = card.get_by_role('combobox', name='Continent')
        for control in (traveller, continent):
            self.assertEqual(control.evaluate("element=>getComputedStyle(element).appearance"), 'none')
            arrow = control.locator('..').evaluate("""element=>{
                const style=getComputedStyle(element,'::after');
                return [style.content,style.right,style.pointerEvents];
            }""")
            self.assertEqual(arrow, ['""', '13px', 'none'])
        self.assertEqual(continent.locator('option:checked').inner_text(), 'All continents')
        self.assertEqual(card.get_by_text('Editable', exact=True).count(), 0)
        traveller.select_option('t:alice')
        card.get_by_text('Editable', exact=True).wait_for(state='visible')
        for width in (1440, 390, 320):
            with self.subTest(width=width):
                self.page.set_viewport_size({'width': width, 'height': 700})
                bounds = card.bounding_box()
                for control in (traveller, continent, card.get_by_text('Editable', exact=True)):
                    box = control.bounding_box()
                    self.assertGreaterEqual(box['x'], bounds['x'])
                    self.assertLessEqual(box['x'] + box['width'], bounds['x'] + bounds['width'])
                self.assertLess(traveller.bounding_box()['y'], continent.bounding_box()['y'])
                self.assertFalse(self.page.evaluate('document.documentElement.scrollWidth>innerWidth'))
        continent.select_option('Europe')
        self.page.wait_for_function("renderer(0).continent==='Europe'")
        traveller.select_option('g:family')
        self.page.wait_for_function("renderer(0).selection==='g:family' && !renderer(0).querySelector('.view-editable')")
        self.assertEqual(self.errors, [])

        self.open_panels(admin=False)
        panel = self.page.locator('beenthere-panel')
        panel.get_by_role('combobox', name='Travellers / Groups').select_option('t:alice')
        self.page.wait_for_function("renderer(0).selection==='t:alice'")
        self.assertEqual(panel.locator('.view-editable').count(), 0)
        self.assertEqual(self.errors, [])

    def test_many_visited_countries_scroll_inside_sidebar(self):
        self.page.set_viewport_size({"width": 1440, "height": 700})
        self.open_panels()
        panel = self.page.locator("beenthere-panel").first
        self.page.evaluate("""
            const card=renderer(0);
            snapshot.travellers.alice.countries=Object.values(card.catalogue.countries)
                .flatMap(Object.keys).slice(0,40).concat(['US-CA','GB-ENG']);
            snapshot.map_settings.subdivision_countries=['GB','US'];
            card.data=JSON.parse(JSON.stringify(snapshot));
            card.render();
        """)
        sidebar = panel.locator('.region-panel')
        country_card = sidebar.locator('.visited-country-section')
        country_list = sidebar.locator('.visited-country-list')
        style = country_card.evaluate(
            "element=>({background:getComputedStyle(element).backgroundColor,"
            "borderRadius:getComputedStyle(element).borderRadius,"
            "borderStyle:getComputedStyle(element).borderTopStyle})"
        )
        self.assertEqual(style["background"], "rgb(17, 43, 63)")
        self.assertEqual(style["borderRadius"], "11px")
        self.assertEqual(style["borderStyle"], "solid")
        self.assertFalse(sidebar.locator("#continent").evaluate("element=>!!element.closest('.visited-country-section')"))
        self.assertFalse(sidebar.locator("#view").evaluate("element=>!!element.closest('.visited-country-section')"))
        heading = country_card.locator(".sidebar-heading")
        typography = heading.evaluate("""element=>{
            const style=getComputedStyle(element);
            return [style.fontSize,style.fontWeight,style.color,style.lineHeight];
        }""")
        self.assertEqual(typography[:3], ["13px", "400", "rgb(182, 232, 241)"])
        self.assertEqual(country_card.locator(".country-count").evaluate("""element=>{
            const style=getComputedStyle(element);
            return [style.fontSize,style.fontWeight,style.color,style.lineHeight];
        }"""), typography)
        divider = country_card.locator(".visited-country-divider")
        self.assertEqual(country_list.locator(".sidebar-heading, .visited-country-divider").count(), 0)
        self.assertEqual(panel.locator(".visited-subdivision-list").count(), 0)
        panel.get_by_role('button', name='Expand visited regions in United Kingdom').click()
        panel.get_by_role('button', name='Collapse visited regions in United Kingdom').wait_for()
        panel.get_by_role('button', name='Expand visited regions in United States').click()
        panel.get_by_role('button', name='Collapse visited regions in United States').wait_for()
        before = self.page.evaluate("scrollY")
        heading_before = heading.bounding_box()
        divider_before = divider.bounding_box()
        country_list.evaluate("element=>element.scrollTop=element.scrollHeight")
        self.assertGreater(country_list.evaluate("element=>element.scrollTop"), 0)
        self.assertEqual(heading.bounding_box(), heading_before)
        self.assertEqual(divider.bounding_box(), divider_before)
        self.assertEqual(sidebar.evaluate("element=>element.scrollTop"), 0)
        self.assertEqual(self.page.evaluate("scrollY"), before)
        for width, height in ((1440, 700), (1440, 900), (390, 700)):
            self.page.set_viewport_size({"width": width, "height": height})
            dimensions = country_list.evaluate(
                "element=>({height:element.clientHeight,scrollHeight:element.scrollHeight})"
            )
            self.assertGreater(dimensions["scrollHeight"], dimensions["height"])
            self.assertEqual(sidebar.evaluate("element=>element.scrollHeight"), sidebar.evaluate("element=>element.clientHeight"))
            map_bounds = panel.locator(".map").bounding_box()
            card_bounds = country_card.bounding_box()
            sidebar_bounds = sidebar.bounding_box()
            list_bounds = country_list.bounding_box()
            divider_bounds = divider.bounding_box()
            self.assertGreater(list_bounds["y"], divider_bounds["y"] + divider_bounds["height"])
            self.assertAlmostEqual(list_bounds["y"] + list_bounds["height"],
                                   card_bounds["y"] + card_bounds["height"] - 13)
            self.assertGreater(card_bounds["y"], map_bounds["y"])
            self.assertAlmostEqual(card_bounds["y"] + card_bounds["height"], map_bounds["y"] + map_bounds["height"])
            self.assertAlmostEqual(sidebar_bounds["y"] + sidebar_bounds["height"], map_bounds["y"] + map_bounds["height"])
            self.assertTrue(self.page.evaluate("document.documentElement.scrollWidth<=window.innerWidth"))
        self.assertEqual(self.errors, [])

    def test_sidebar_selection_focuses_country_and_region_without_mutation(self):
        self.open_panels()
        self.page.evaluate("""
            snapshot.travellers.bob={name:'Bob',countries:['US-FL']};
            snapshot.groups.family.members=['alice','bob'];
        """)
        panel = self.open_us_map("g:family")
        before = self.page.evaluate("JSON.stringify(snapshot.travellers)")
        self.page.evaluate("renderer(0).continent='Europe'; renderer(0).render();")
        country = panel.locator('[data-country-item="US"] [data-location-select="US"]')
        country.focus()
        country.press('Enter')
        self.page.wait_for_function("renderer(0).selectedLocation==='US'")
        self.assertEqual(self.page.evaluate("renderer(0).continent"), "World")
        self.assertEqual(panel.locator('.country[aria-label="United States"]').get_attribute("aria-current"), "true")
        visitors = panel.locator('.search-result-visitors')
        regions = panel.locator('.search-result-regions')
        self.assertEqual(visitors.evaluate("element=>getComputedStyle(element).borderLeftWidth"), "0px")
        self.assertEqual(regions.evaluate("element=>getComputedStyle(element).borderLeftWidth"), "1px")
        self.assertEqual(panel.locator('[data-country-item="US"] .visited-subdivision-list').count(), 0)
        panel.get_by_role('button', name='Expand visited regions in United States').click()
        panel.locator('[data-location-select="US-CA"]').click()
        self.page.wait_for_function("renderer(0).querySelector('[data-location=\"US-CA\"]')?.getAttribute('aria-current')==='true'")
        self.assertEqual(panel.locator('[data-location="US-CA"]').get_attribute("aria-current"), "true")
        self.assertEqual(panel.locator('[data-location-select="US-CA"]').get_attribute("aria-current"), "true")
        self.assertEqual(panel.locator('[data-location="US-CA"]').evaluate("element=>getComputedStyle(element).fill"), "rgb(139, 114, 154)")
        self.assertIn("rgb(139, 114, 154)", panel.locator('[data-location-select="US-CA"]').locator('..').evaluate("element=>getComputedStyle(element).boxShadow"))
        self.assertEqual(self.page.evaluate("JSON.stringify(snapshot.travellers)"), before)
        self.assertEqual(self.page.evaluate("wsMessages.filter(message=>message.type==='beenthere/change').length"), 0)
        self.assertEqual(self.errors, [])

    def test_country_banner_toggle_preserves_hidden_region_visits(self):
        self.open_panels()
        panel = self.open_us_map()
        self.page.evaluate("""
            snapshot.travellers.alice.countries=['US','US-CA'];
            snapshot.map_settings.subdivision_countries=[];
            renderer(0).data=JSON.parse(JSON.stringify(snapshot));
            renderer(0).render();
        """)
        panel.locator('.country[aria-label="United States"]').click()
        self.page.wait_for_function("renderer(0).querySelector('.search-result-name')?.textContent==='United States'")
        self.assertEqual(self.page.evaluate("snapshot.travellers.alice.countries"), ["US", "US-CA"])
        self.assertEqual(self.page.evaluate("wsMessages.filter(message=>message.type==='beenthere/change').length"), 0)
        self.assertTrue(panel.get_by_role('button', name='Mark unvisited', exact=True).is_visible())
        messages = []
        self.page.on('dialog', lambda dialog: (messages.append(dialog.message), dialog.dismiss()))
        panel.get_by_role('button', name='Mark unvisited', exact=True).click()
        self.page.wait_for_function("renderer(0).querySelector('.search-result-status')?.textContent==='Visited via regions'")
        self.assertEqual(self.page.evaluate("snapshot.travellers.alice.countries"), ["US-CA"])
        self.assertEqual(panel.locator('.search-result-visit-status').count(), 0)
        self.assertEqual(panel.locator('#toggle-search-result').count(), 0)
        self.assertTrue(panel.locator('[data-country-item="US"]').is_visible())
        self.assertEqual(panel.locator('.country[aria-label="United States"]').get_attribute('aria-pressed'), 'true')
        self.assertEqual(panel.locator('.search-result-name').inner_text(), 'United States')
        self.page.evaluate("""
            snapshot.map_settings.subdivision_countries=['US'];
            renderer(0).data=JSON.parse(JSON.stringify(snapshot));
            renderer(0).render();
        """)
        panel.locator('[data-location="US-CA"]').dispatch_event('click')
        self.page.wait_for_function("renderer(0).querySelector('#toggle-search-result')?.textContent.trim()==='Mark visited'")
        self.assertEqual(panel.locator('[data-country-item="US"]').count(), 0)
        panel.get_by_role('button', name='Mark visited', exact=True).click()
        self.page.wait_for_function("renderer(0).querySelector('#toggle-search-result')?.textContent.trim()==='Mark unvisited'")
        self.assertEqual(self.page.evaluate("snapshot.travellers.alice.countries"), ['US'])
        self.assertEqual(panel.locator('.search-result-regions').inner_text(), '0 of 51 regions visited')
        self.assertEqual(messages, [])
        self.assertEqual(self.page.evaluate(
            "wsMessages.filter(message=>message.type==='beenthere/change').length"
        ), 3)
        self.assertEqual(self.errors, [])

    def test_country_selection_requires_the_banner_mark_action(self):
        self.open_panels()
        panel = self.page.locator("beenthere-panel").first
        panel.locator('#view').select_option('t:alice')
        panel.locator('#continent').select_option('Europe')
        france = panel.locator('.country[aria-label="France"]')
        before = self.page.evaluate("JSON.stringify(snapshot.travellers)")
        france.click()
        self.page.wait_for_function("renderer(0).querySelector('.search-result-name')?.textContent==='France'")
        self.assertEqual(self.page.evaluate("JSON.stringify(snapshot.travellers)"), before)
        self.assertEqual(self.page.evaluate("wsMessages.filter(message=>message.type==='beenthere/change').length"), 0)
        toggle = panel.get_by_role('button', name='Mark unvisited', exact=True)
        self.assertEqual(toggle.inner_text(), 'Mark unvisited')
        self.assertIn('secondary', toggle.get_attribute('class'))
        self.assertEqual(toggle.locator('ha-icon').get_attribute('icon'), 'mdi:minus-circle-outline')
        secondary_size = toggle.bounding_box()
        self.assertEqual(panel.locator('.search-result-visit-status').count(), 0)
        self.assertEqual(panel.locator('#edit-country, #country-edit').count(), 0)
        messages = []
        self.page.on("dialog", lambda dialog: (messages.append(dialog.message), dialog.dismiss()))
        toggle.click()
        self.page.wait_for_function("!renderer(0)._pendingChanges && !snapshot.travellers.alice.countries.includes('FR')")
        self.page.wait_for_function("renderer(0).querySelector('.country[aria-label=\"France\"]')?.getAttribute('aria-pressed')==='false'")
        self.assertEqual(messages, [])
        self.assertTrue(panel.get_by_role('button', name='Mark visited', exact=True).is_visible())
        self.assertEqual(panel.locator('.search-result-name').inner_text(), 'France')
        self.assertEqual(panel.locator('[data-country-item="FR"]').count(), 0)
        self.assertNotIn("active", france.get_attribute("class"))
        france.focus()
        france.press("Enter")
        self.page.wait_for_function("!renderer(0)._renderScheduled")
        self.assertNotIn('FR', self.page.evaluate('snapshot.travellers.alice.countries'))
        mark = panel.get_by_role('button', name='Mark visited', exact=True)
        self.assertIn('primary', mark.get_attribute('class'))
        self.assertEqual(mark.locator('ha-icon').get_attribute('icon'), 'mdi:check-circle-outline')
        primary_size = mark.bounding_box()
        self.assertEqual(primary_size['width'], secondary_size['width'])
        self.assertEqual(primary_size['height'], secondary_size['height'])
        mark.focus()
        mark.press('Space')
        self.page.wait_for_function("!renderer(0)._pendingChanges && snapshot.travellers.alice.countries.includes('FR')")
        self.page.wait_for_function("renderer(0).querySelector('.country[aria-label=\"France\"]')?.getAttribute('aria-pressed')==='true'")
        self.page.wait_for_function("renderer(0).querySelector('#toggle-search-result')===renderer(0).getRootNode().activeElement")
        self.assertIn("active", france.get_attribute("class"))
        self.assertTrue(panel.get_by_role('button', name='Mark unvisited', exact=True).is_visible())
        self.assertTrue(panel.locator('[data-country-item="FR"]').is_visible())
        self.assertEqual(self.page.evaluate("wsMessages.filter(message=>message.type==='beenthere/change').length"), 2)
        before_search = self.page.evaluate("JSON.stringify(snapshot.travellers)")
        panel.locator('#search').fill('Australia')
        panel.get_by_role('option', name='Australia', exact=True).click()
        self.page.wait_for_function("renderer(0).querySelector('.search-result-name')?.textContent==='Australia'")
        self.assertEqual(self.page.evaluate("JSON.stringify(snapshot.travellers)"), before_search)
        self.assertTrue(panel.get_by_role('button', name='Mark visited', exact=True).is_visible())
        self.assertEqual(self.page.evaluate("renderer(0).selection"), "t:alice")
        self.assertEqual(self.errors, [])

    def test_country_map_click_is_read_only_without_an_editable_traveller(self):
        for admin, selection in ((True, ''), (True, 'g:family'), (False, 't:alice')):
            with self.subTest(admin=admin, selection=selection):
                self.open_panels(admin=admin)
                panel = self.page.locator('beenthere-panel')
                panel.locator('#view').select_option(selection)
                before = self.page.evaluate('JSON.stringify(snapshot.travellers)')
                panel.locator('.country[aria-label="France"]').click()
                self.page.wait_for_function("renderer(0).querySelector('.search-result-name')?.textContent==='France'")
                self.assertEqual(self.page.evaluate('JSON.stringify(snapshot.travellers)'), before)
                self.assertEqual(self.page.evaluate("wsMessages.filter(message=>message.type==='beenthere/change').length"), 0)
                self.assertEqual(panel.locator('#edit-country').count(), 0)
                self.assertEqual(panel.locator('#toggle-search-result').count(), 0)
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
        self.assertEqual(panel.locator('.country-count').inner_text(), '(2)')
        before = self.page.evaluate("JSON.stringify(snapshot.travellers)")
        for code in ("US-CA", "US-FL"):
            self.assertIn("active", panel.locator(f'[data-location="{code}"]').get_attribute("class"))
        self.assertNotIn("active", panel.locator('[data-location="US-AK"]').get_attribute("class"))
        self.assertTrue(panel.get_by_role('button', name='Expand visited regions in United States').is_visible())
        panel.get_by_role('button', name='Expand visited regions in United States').click()
        self.assertTrue(panel.get_by_role('button', name='Collapse visited regions in United States').is_visible())
        self.assertEqual(panel.locator("#details").count(), 0)
        self.assertEqual(panel.locator('.visited-subdivision-list li').count(), 2)
        self.assertEqual(panel.locator('.visited-subdivision-list input').count(), 0)
        self.assertEqual(panel.locator('[data-remove-country]').count(), 0)
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
        second.get_by_role("checkbox", name="Show regional detail for United States", exact=True).uncheck()
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

    def test_country_details_are_contextual_without_displacing_the_map(self):
        self.open_panels()
        panel = self.page.locator("beenthere-panel")
        panel.locator("#view").select_option("t:alice")
        self.page.wait_for_function("renderer(0).querySelector('#view').value==='t:alice'")
        for width in (1440, 320, 375, 430):
            with self.subTest(width=width):
                self.page.set_viewport_size({"width": width, "height": 1000})
                self.page.evaluate("renderer(0).searchResult=null; renderer(0).render()")
                panel.locator(".search-row").wait_for(state="visible")
                self.assertEqual(panel.locator(".search-result").count(), 0)
                search = panel.locator(".search-row").bounding_box()
                self.assertEqual(search["height"], 56)
                before = panel.locator(".map").bounding_box()
                panel.locator("#search").fill("France")
                self.assertEqual(panel.locator(".map").bounding_box(), before)
                panel.get_by_role("option", name="France", exact=True).click()
                self.page.wait_for_function("renderer(0).querySelector('.search-result-name')?.textContent==='France'")
                details = panel.locator(".search-result")
                self.assertEqual(details.locator(".search-result-name").inner_text(), "France")
                after = panel.locator(".map").bounding_box()
                box = details.bounding_box()
                input_box = panel.locator("#search").bounding_box()
                self.assertLessEqual(box["y"] + box["height"], after["y"])
                if width > 760:
                    self.assertEqual(after, before)
                    self.assertEqual(box["y"], input_box["y"])
                    self.assertEqual(box["height"], 56)
                    self.assertEqual(input_box["height"], box["height"])
                    self.assertGreater(box["x"], input_box["x"] + input_box["width"])
                    self.assertGreaterEqual(input_box["width"], 300)
                    self.assertLessEqual(input_box["width"], 360)
                else:
                    self.assertEqual(input_box["width"], search["width"])
                    self.assertGreaterEqual(box["y"], input_box["y"] + input_box["height"])
                self.assertGreaterEqual(box["x"], 0)
                self.assertLessEqual(box["x"] + box["width"], width)
                self.assertLessEqual(box["height"], 144)
                action = details.get_by_role('button', name='Mark unvisited', exact=True).bounding_box()
                close = details.get_by_role('button', name='Deselect country', exact=True).bounding_box()
                self.assertGreaterEqual(action['height'], 44)
                self.assertGreaterEqual(action['x'], box['x'])
                self.assertLessEqual(action['x'] + action['width'], close['x'])
                self.assertLessEqual(close['x'] + close['width'], box['x'] + box['width'])
                self.assertTrue(self.page.evaluate("document.documentElement.scrollWidth<=innerWidth"))
                secondary = details.get_by_role('button', name='Mark unvisited', exact=True)
                secondary.hover()
                self.assertEqual(secondary.bounding_box(), action)
                self.assertTrue(secondary.locator('span').evaluate('element=>element.scrollWidth<=element.clientWidth'))
                self.page.screenshot(path=str(Path(tempfile.gettempdir()) / f"beenthere-country-details-{width}.png"), full_page=True, animations='disabled')
                panel.locator('#search').fill('Australia')
                panel.get_by_role('option', name='Australia', exact=True).click()
                self.page.wait_for_function("renderer(0).querySelector('.search-result-name')?.textContent==='Australia'")
                primary = details.get_by_role('button', name='Mark visited', exact=True)
                primary_box = primary.bounding_box()
                self.assertEqual(primary_box['width'], action['width'])
                self.assertEqual(primary_box['height'], action['height'])
                primary.hover()
                self.assertEqual(primary.bounding_box(), primary_box)
                self.assertTrue(primary.locator('span').evaluate('element=>element.scrollWidth<=element.clientWidth'))
                self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
                self.page.screenshot(path=str(Path(tempfile.gettempdir()) / f"beenthere-country-mark-visited-{width}.png"), full_page=True, animations='disabled')
            panel.locator('#search').fill('France')
            panel.get_by_role('option', name='France', exact=True).click()
            self.page.wait_for_function("renderer(0).querySelector('.search-result-name')?.textContent==='France'")
        panel.get_by_role("button", name="Mark unvisited", exact=True).click()
        self.page.wait_for_function("!renderer(0)._pendingChanges && !snapshot.travellers.alice.countries.includes('FR')")
        panel.get_by_role("button", name="Mark visited", exact=True).click()
        self.page.wait_for_function("!renderer(0)._pendingChanges && snapshot.travellers.alice.countries.includes('FR')")
        panel.locator("#view").select_option("g:family")
        self.page.wait_for_function("renderer(0).querySelector('#view').value==='g:family'")
        panel.locator('.country[aria-label="Australia"]').dispatch_event("click")
        self.page.wait_for_function("renderer(0).querySelector('.search-result-name')?.textContent==='Australia'")
        self.assertEqual(panel.locator(".search-result-name").inner_text(), "Australia")
        self.assertEqual(panel.locator("#toggle-search-result").count(), 0)
        panel.locator('[data-location-select="FR"]').click()
        self.page.wait_for_function("renderer(0).querySelector('.search-result-name')?.textContent==='France'")
        self.assertEqual(panel.locator(".search-result-name").inner_text(), "France")
        panel.locator("#search").fill("No such country")
        self.assertEqual(panel.locator("#country-search-status").inner_text(), "No matching countries")
        self.assertEqual(panel.locator(".search-result-name").inner_text(), "France")
        panel.locator("#search").press("Escape")
        self.assertFalse(panel.locator("#country-suggestions").is_visible())
        self.assertEqual(self.errors, [])

    def test_country_banner_close_does_not_select_unidentified_map_areas(self):
        self.open_panels()
        panel = self.page.locator("beenthere-panel")
        before = self.page.evaluate("JSON.stringify(snapshot.travellers)")
        self.page.evaluate("""
            const card=renderer(0);
            const template=card.geo.features.find(feature=>card.iso(feature)==='FR');
            ['Somaliland','Siachen Glacier','Northern Cyprus'].forEach((name,index)=>{
                card.geo.features.push({...template,properties:{ADMIN:name,
                    ISO_A2_EH:[null,'-99',undefined][index],CONTINENT:'Europe'}});
            });
            card.render();
        """)
        self.assertEqual(panel.locator('.country[data-country-shape=""]').count(), 3)
        panel.locator('[data-location-select="FR"]').click()
        self.page.wait_for_function("renderer(0).querySelector('.search-result-name')?.textContent==='France'")
        self.assertEqual(panel.locator('.country.selected').count(), 1)
        panel.get_by_role("button", name="Deselect country", exact=True).click()
        self.page.wait_for_function("!renderer(0).querySelector('.search-result')")
        self.assertEqual(panel.locator('.country.selected, .region-shape.selected').count(), 0)
        self.assertEqual(panel.locator('.country[aria-current="true"]').count(), 0)
        self.assertEqual(self.page.evaluate("JSON.stringify(snapshot.travellers)"), before)
        self.assertEqual(self.page.evaluate("wsMessages.filter(message=>message.type==='beenthere/change').length"), 0)
        self.assertEqual(self.errors, [])

    def test_country_search_keyboard_and_dismissal_in_combined_views(self):
        self.open_panels()
        panel = self.page.locator("beenthere-panel")
        before = self.page.evaluate("JSON.stringify(snapshot.travellers)")
        search = panel.get_by_role("combobox", name="Search countries", exact=True)
        self.assertEqual(panel.locator("#find").count(), 0)
        self.assertEqual(panel.locator(".search-result").count(), 0)
        search.fill("a")
        self.assertEqual(panel.locator("#country-suggestions").get_by_role("option").count(), 3)
        self.assertEqual(panel.locator("#country-suggestions").get_by_role("option").first.locator("img").count(), 1)
        self.assertEqual(search.get_attribute("aria-activedescendant"), "country-option-0")
        search.press("ArrowUp")
        self.assertEqual(search.get_attribute("aria-activedescendant"), "country-option-2")
        search.press("ArrowDown")
        self.assertEqual(search.get_attribute("aria-activedescendant"), "country-option-0")
        search.press("ArrowDown")
        self.assertEqual(panel.locator('[role="option"][aria-selected="true"]').inner_text(), "France")
        search.press("Enter")
        self.page.wait_for_function("renderer(0).selectedLocation==='FR' && renderer(0).querySelector('.search-result-name')?.textContent==='France'")
        self.assertEqual(panel.locator(".search-result-name").inner_text(), "France")
        self.assertEqual(panel.locator('.country[aria-label="France"]').get_attribute("aria-current"), "true")
        self.assertEqual(panel.locator("#edit-country").count(), 0)
        self.assertEqual(panel.locator("#toggle-search-result").count(), 0)
        search.fill("FrA")
        self.assertEqual(panel.locator("#country-suggestions").get_by_role("option").inner_text(), "France")
        search.press("Escape")
        self.assertEqual(search.get_attribute("aria-expanded"), "false")
        search.press("Enter")
        self.assertEqual(panel.locator(".search-result-name").inner_text(), "France")
        search.fill("aus")
        panel.locator(".view-heading").click()
        self.assertEqual(search.get_attribute("aria-expanded"), "false")
        panel.locator("#view").select_option("g:family")
        panel.locator("#continent").select_option("Europe")
        search.fill("aUs")
        panel.get_by_role("option", name="Australia", exact=True).click()
        self.page.wait_for_function("renderer(0).selectedLocation==='AU' && renderer(0).continent==='World' && renderer(0).querySelector('.search-result-name')?.textContent==='Australia'")
        self.assertEqual(panel.locator(".search-result-name").inner_text(), "Australia")
        self.assertEqual(panel.locator("#edit-country").count(), 0)
        panel.get_by_role("button", name="Deselect country", exact=True).click()
        self.assertEqual(panel.locator(".search-result").count(), 0)
        self.assertEqual(self.page.evaluate("renderer(0).selectedLocation"), None)
        self.assertEqual(self.page.evaluate("JSON.stringify(snapshot.travellers)"), before)
        self.assertEqual(self.page.evaluate("wsMessages.filter(message=>message.type==='beenthere/change').length"), 0)
        self.assertEqual(self.errors, [])

    def test_country_banner_uses_compact_search_and_clear_identity(self):
        self.open_panels()
        panel = self.page.locator('beenthere-panel')
        panel.locator('#search').fill('France')
        panel.get_by_role('option', name='France', exact=True).click()
        self.page.wait_for_function("renderer(0).querySelector('.search-result-name')?.textContent==='France'")
        banner = panel.locator('.search-result')
        self.assertEqual(banner.get_by_text('Visited', exact=True).count(), 0)
        self.assertEqual(banner.locator('.search-result-visit-status').count(), 0)
        self.assertTrue(banner.get_by_role('img', name='Alice', exact=True).is_visible())
        for width in (1280, 1920):
            with self.subTest(width=width):
                self.page.set_viewport_size({'width': width, 'height': 1000})
                search = panel.locator('#search').bounding_box()
                box = banner.bounding_box()
                self.assertGreaterEqual(search['width'], 300)
                self.assertLessEqual(search['width'], 360)
                self.assertEqual(search['height'], box['height'])
                self.assertEqual(search['y'], box['y'])
                self.assertEqual(banner.locator('img').bounding_box()['width'], 24)
                self.assertEqual(banner.locator('.search-result-name').evaluate('element=>getComputedStyle(element).fontSize'), '16px')
                self.assertEqual(banner.locator('.search-result-visitors').evaluate('element=>getComputedStyle(element).fontSize'), '13px')
                border = banner.evaluate('element=>{const style=getComputedStyle(element);return [style.borderLeftWidth,style.borderTopWidth,style.borderLeftColor,style.borderTopColor];}')
                self.assertEqual(border[0:2], ['1px', '1px'])
                self.assertEqual(border[2], border[3])
                self.assertEqual(border[2], 'rgb(139, 114, 154)')
                self.assertEqual(banner.locator('.search-result-visitors').evaluate("element=>getComputedStyle(element).borderLeftWidth"), '0px')
                identity = banner.locator('.search-result-identity').bounding_box()
                visitors = banner.locator('.search-result-visitors').bounding_box()
                self.assertGreaterEqual(visitors['x'], identity['x'] + identity['width'])
                self.assertEqual(visitors['x'] - identity['x'] - identity['width'], 12)
                self.assertEqual(banner.locator('.search-result-visitors').evaluate("element=>getComputedStyle(element).paddingLeft"), '16px')
                close = banner.locator('#close-country').bounding_box()
                self.assertLessEqual(box['x'] + box['width'] - close['x'] - close['width'], 12)
                sidebar_selection = panel.locator('[data-country-item="FR"]')
                self.assertIn('selected', sidebar_selection.get_attribute('class'))
                self.assertIn('rgb(139, 114, 154)', sidebar_selection.evaluate('element=>getComputedStyle(element).boxShadow'))
                country = panel.locator('.country[aria-label="France"]')
                self.assertEqual(country.evaluate('element=>getComputedStyle(element).fill'), 'rgb(139, 114, 154)')
                self.assertEqual(country.evaluate('element=>getComputedStyle(element).stroke'), 'rgb(139, 114, 154)')
                self.assertEqual(country.evaluate('element=>getComputedStyle(element).strokeWidth'), '0.7px')
        close_button = banner.locator('#close-country')
        search_input = panel.locator('#search')
        search_input.focus()
        focus_style = search_input.evaluate("""element=>{
            const style=getComputedStyle(element);
            return [style.outlineStyle,style.outlineWidth,style.outlineColor];
        }""")
        self.assertEqual(focus_style, ['solid', '2px', 'rgb(99, 243, 229)'])
        self.assertNotEqual(focus_style[2], banner.evaluate('element=>getComputedStyle(element).borderColor'))
        self.assertEqual(close_button.get_attribute('title'), 'Deselect country')
        self.assertEqual(close_button.get_attribute('aria-label'), 'Deselect country')
        self.assertEqual(close_button.bounding_box()['width'], 44)
        self.page.mouse.move(0, 0)
        self.assertEqual(close_button.evaluate('element=>getComputedStyle(element).color'), 'rgb(159, 179, 195)')
        self.assertEqual(close_button.evaluate('element=>getComputedStyle(element).backgroundColor'), 'rgba(0, 0, 0, 0)')
        close_button.hover()
        self.assertEqual(close_button.evaluate('element=>getComputedStyle(element).color'), 'rgb(230, 248, 255)')
        self.assertEqual(close_button.evaluate('element=>getComputedStyle(element).backgroundColor'), 'rgb(32, 58, 81)')
        panel.locator('#view').select_option('t:alice')
        panel.get_by_role('button', name='Mark unvisited', exact=True).wait_for(state='visible')
        self.assertEqual(banner.get_by_text('Visited', exact=True).count(), 0)
        self.assertEqual(banner.locator('.search-result-status').count(), 0)
        self.assertEqual(self.page.evaluate("wsMessages.filter(message=>message.type==='beenthere/change').length"), 0)
        self.assertEqual(self.errors, [])

    def test_country_banner_combined_views_show_one_unvisited_status(self):
        self.open_panels()
        panel = self.page.locator('beenthere-panel')
        before = self.page.evaluate('JSON.stringify(snapshot.travellers)')
        for width in (1440, 375):
            for selection in ('', 'g:family'):
                with self.subTest(width=width, selection=selection):
                    self.page.set_viewport_size({'width': width, 'height': 1000})
                    panel.locator('#view').select_option(selection)
                    panel.locator('#search').fill('Australia')
                    panel.get_by_role('option', name='Australia', exact=True).click()
                    self.page.wait_for_function("renderer(0).querySelector('.search-result-name')?.textContent==='Australia'")
                    banner = panel.locator('.search-result')
                    self.assertEqual(banner.get_by_text('Not visited', exact=True).count(), 1)
                    self.assertEqual(banner.locator('.search-result-status').inner_text(), 'Not visited')
                    self.assertEqual(banner.locator('#toggle-search-result').count(), 0)
                    self.assertTrue(banner.get_by_role('button', name='Deselect country', exact=True).is_visible())
                    self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
                    panel.locator('#search').fill('France')
                    panel.get_by_role('option', name='France', exact=True).click()
                    self.page.wait_for_function("renderer(0).querySelector('.search-result-name')?.textContent==='France'")
                    self.assertEqual(banner.get_by_text('Visited', exact=True).count(), 0)
                    visitors = banner.get_by_role('group', name='Visited by', exact=True)
                    self.assertEqual(visitors.get_by_role('img', name='Alice', exact=True).inner_text(), 'A')
                    self.assertEqual(visitors.locator('.traveller-bubble').count(), 1)
        self.assertEqual(self.page.evaluate('JSON.stringify(snapshot.travellers)'), before)
        self.assertEqual(self.page.evaluate("wsMessages.filter(message=>message.type==='beenthere/change').length"), 0)
        self.assertEqual(self.errors, [])

    def test_map_selection_highlight_does_not_change_visit_colors(self):
        self.open_panels()
        panel = self.page.locator('beenthere-panel')
        panel.locator('#search').fill('Australia')
        panel.get_by_role('option', name='Australia', exact=True).click()
        self.page.wait_for_function("renderer(0).querySelector('.country[aria-label=\"Australia\"]')?.getAttribute('aria-current')==='true'")
        country = panel.locator('.country[aria-label="Australia"]')
        self.assertEqual(country.evaluate('element=>getComputedStyle(element).fill'), 'rgb(139, 114, 154)')
        self.assertEqual(country.get_attribute('aria-pressed'), 'false')
        self.page.keyboard.press('Tab')
        country.focus()
        self.assertEqual(country.evaluate('element=>getComputedStyle(element).stroke'), 'rgb(226, 212, 235)')
        panel.locator('#close-country').dispatch_event('click')
        self.page.wait_for_function("!renderer(0).querySelector('.country.selected')")
        self.assertEqual(country.evaluate('element=>getComputedStyle(element).fill'), 'rgb(36, 65, 89)')
        self.assertEqual(panel.locator('.country[aria-label="France"]').evaluate('element=>getComputedStyle(element).fill'), 'rgb(35, 217, 207)')
        self.assertEqual(self.errors, [])

    def test_country_banner_visitor_bubbles_fit_desktop_and_mobile(self):
        self.open_panels()
        panel = self.page.locator('beenthere-panel')
        names = ['Taylor Woods', 'Beth Walker', 'Riley West']
        self.page.evaluate("""names=>{
            snapshot.travellers=Object.fromEntries(names.map((name,index)=>[
                `visitor-${index}`,{name,countries:['FR']}
            ]));
            snapshot.groups.family.members=Object.keys(snapshot.travellers);
            renderer(0).data=JSON.parse(JSON.stringify(snapshot));
            renderer(0).render();
        }""", names)
        panel.locator('#search').fill('France')
        panel.get_by_role('option', name='France', exact=True).click()
        self.page.wait_for_function("renderer(0).querySelectorAll('.traveller-bubble').length===3")
        for width in (1440, 375, 320):
            with self.subTest(width=width):
                self.page.set_viewport_size({'width': width, 'height': 1000})
                banner = panel.locator('.search-result')
                bubbles = banner.locator('.traveller-bubble')
                self.assertEqual(bubbles.all_inner_texts(), ['TW', 'BW', 'RW'])
                box = banner.bounding_box()
                for index, name in enumerate(names):
                    bubble = bubbles.nth(index)
                    self.assertEqual(bubble.get_attribute('title'), name)
                    self.assertEqual(bubble.get_attribute('aria-label'), name)
                    size = bubble.bounding_box()
                    self.assertEqual(size['width'], 32)
                    self.assertEqual(size['height'], 32)
                    self.assertEqual(bubble.evaluate('element=>getComputedStyle(element).borderRadius'), '50%')
                    self.assertGreaterEqual(size['x'], box['x'])
                    self.assertLessEqual(size['x'] + size['width'], box['x'] + box['width'])
                    self.assertTrue(bubble.evaluate('element=>element.scrollWidth<=element.clientWidth'))
                self.assertEqual(banner.locator('#toggle-search-result').count(), 0)
                self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
                self.page.screenshot(path=str(Path(tempfile.gettempdir()) / f'beenthere-visitor-bubbles-{width}.png'), full_page=True)
        self.assertEqual(self.page.evaluate("wsMessages.filter(message=>message.type==='beenthere/change').length"), 0)
        self.assertEqual(self.errors, [])

    def test_country_banner_visitor_names_support_touch_keyboard_and_overflow(self):
        self.context.close()
        self.context = self.browser.new_context(viewport={'width': 375, 'height': 1000}, has_touch=True)
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.page.on('pageerror', lambda error: self.errors.append(str(error)))
        self.context.route('**/*', self.route)
        self.open_panels(admin=False)
        panel = self.page.locator('beenthere-panel')
        panel.locator('#view').select_option('g:family')
        panel.locator('#search').fill('United States')
        panel.get_by_role('option', name='United States', exact=True).tap()
        self.page.wait_for_function("renderer(0).querySelector('.search-result-name')?.textContent==='United States'")
        names = [
            'Alexandria-Catherine Montgomery-Smythe', 'Taylor Alexandra Woods',
            'Bethany Charlotte Walker', 'Riley Morgan West',
            'Jean-Baptiste de La Rochefoucauld', 'Christopher Theodore North',
            'Michaela Stephanie South',
            'AnExceptionallyLongUnbrokenTravellerNameForWrapping East',
        ]
        for width in (1440, 320):
            for count in (0, 1, 4, 5, 8):
                with self.subTest(width=width, count=count):
                    self.page.set_viewport_size({'width': width, 'height': 1000})
                    selected_names = names[:count]
                    self.page.evaluate("""names=>{
                        snapshot.travellers=Object.fromEntries(names.map((name,index)=>[
                            `visitor-${index}`,{name,countries:index===names.length-1?['US-CA']:['US']}
                        ]));
                        snapshot.groups.family.members=Object.keys(snapshot.travellers);
                        snapshot.map_settings.subdivision_countries=['US'];
                        renderer(0).data=JSON.parse(JSON.stringify(snapshot));
                        renderer(0).render();
                    }""", selected_names)
                    self.page.wait_for_function("!!renderer(0).regionalMaps?.US && !renderer(0)._renderScheduled")
                    before = self.page.evaluate('JSON.stringify(snapshot.travellers)')
                    banner = panel.locator('.search-result')
                    expected_names = selected_names[:3] if count > 4 else selected_names
                    bubbles = banner.locator('.traveller-bubble')
                    self.assertEqual(bubbles.evaluate_all("elements=>elements.map(element=>element.getAttribute('aria-label'))"), expected_names)
                    self.assertEqual(banner.locator('.visitor-overflow').count(), int(count > 4))
                    self.assertEqual(banner.locator('#toggle-search-result').count(), 0)
                    self.assertEqual(banner.locator('.search-result-regions').inner_text(), f'{int(count > 0)} of 51 regions visited')
                    if not count:
                        self.assertEqual(banner.get_by_text('Not visited', exact=True).count(), 1)
                        continue
                    box = banner.bounding_box()
                    map_box = panel.locator('.map').bounding_box()
                    first = banner.get_by_role('button', name=f'Show full name: {names[0]}', exact=True)
                    first.tap()
                    popup = banner.locator('.visitor-disclosure[open] .visitor-popover')
                    popup.wait_for(state='visible')
                    self.assertEqual(popup.inner_text(), names[0])
                    self.assertEqual(banner.bounding_box(), box)
                    self.assertEqual(panel.locator('.map').bounding_box(), map_box)
                    first.press('Escape')
                    self.assertEqual(banner.locator('.visitor-disclosure[open]').count(), 0)
                    first.focus()
                    first.press('Enter')
                    popup.wait_for(state='visible')
                    if count > 4:
                        overflow = banner.get_by_role('button', name=f'Show {count - 3} more travellers who visited', exact=True)
                        self.assertEqual(overflow.inner_text(), f'+{count - 3}')
                        overflow.tap()
                        popup = banner.locator('.visitor-overflow[open] .visitor-popover')
                        popup.wait_for(state='visible')
                        self.assertEqual(popup.locator('li').all_inner_texts(), selected_names[3:])
                        self.assertEqual(banner.locator('.visitor-disclosure[open]').count(), 1)
                        self.assertEqual(banner.bounding_box(), box)
                        self.assertEqual(panel.locator('.map').bounding_box(), map_box)
                    popup_box = popup.bounding_box()
                    self.assertGreaterEqual(popup_box['x'], 0)
                    self.assertLessEqual(popup_box['x'] + popup_box['width'], width)
                    self.assertTrue(popup.evaluate('element=>element.scrollWidth<=element.clientWidth'))
                    self.assertTrue(self.page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
                    self.page.screenshot(path=str(Path(tempfile.gettempdir()) / f'beenthere-visitor-names-{width}-{count}.png'), full_page=True)
                    banner.locator('.search-result-name').tap()
                    self.assertEqual(banner.locator('.visitor-disclosure[open]').count(), 0)
                    self.assertEqual(self.page.evaluate('JSON.stringify(snapshot.travellers)'), before)
        self.assertEqual(self.page.evaluate("wsMessages.filter(message=>message.type==='beenthere/change').length"), 0)
        self.assertEqual(self.errors, [])

    def test_country_banner_reflects_stored_visits_and_view_switches(self):
        self.open_panels()
        self.page.evaluate("""
            snapshot.travellers.bob={name:'Bob',countries:['US','US-FL']};
            snapshot.travellers.outsider={name:'Outsider',countries:['US-AK']};
            snapshot.groups.family.members=['alice','bob'];
        """)
        panel = self.open_us_map("g:family")
        panel.locator('[data-location-select="US"]').click()
        self.page.wait_for_function("renderer(0).searchResult==='US' && renderer(0).querySelectorAll('.traveller-bubble').length===2")
        bubbles = panel.locator('.traveller-bubble')
        self.assertEqual(bubbles.evaluate_all("elements=>elements.map(element=>element.getAttribute('aria-label'))"), ['Alice', 'Bob'])
        self.assertEqual(bubbles.all_inner_texts(), ['A', 'B'])
        alice_colour = panel.get_by_role('img', name='Alice', exact=True).evaluate('element=>getComputedStyle(element).backgroundColor')
        self.assertEqual(panel.locator(".search-result-regions").inner_text(), "2 of 51 regions visited")
        self.assertIn("/us.png", panel.locator(".search-result img").get_attribute("src"))
        self.assertEqual(panel.locator("#edit-country").count(), 0)
        panel.locator("#view").select_option("")
        self.page.wait_for_function("!!renderer(0).querySelector('.traveller-bubble[aria-label=\"Outsider\"]')")
        self.assertEqual(bubbles.evaluate_all("elements=>elements.map(element=>element.getAttribute('aria-label'))"), ['Alice', 'Bob', 'Outsider'])
        self.assertEqual(panel.get_by_role('img', name='Alice', exact=True).evaluate('element=>getComputedStyle(element).backgroundColor'), alice_colour)
        self.assertEqual(panel.locator(".search-result-regions").inner_text(), "3 of 51 regions visited")
        panel.locator("#view").select_option("t:bob")
        self.page.wait_for_function("renderer(0).querySelector('#view')?.value==='t:bob' && !!renderer(0).querySelector('#toggle-search-result')")
        self.assertTrue(panel.get_by_role("button", name="Mark unvisited", exact=True).is_visible())
        self.assertEqual(panel.locator(".search-result-regions").inner_text(), "1 of 51 regions visited")
        panel.locator('[data-location="US-FL"]').dispatch_event("click")
        self.page.wait_for_function("renderer(0).querySelector('.search-result-regions')?.textContent==='0 of 51 regions visited'")
        self.assertTrue(panel.get_by_role('button', name='Mark unvisited', exact=True).is_visible())
        panel.get_by_role("button", name="Mark unvisited", exact=True).click()
        self.page.wait_for_function("renderer(0).querySelector('#toggle-search-result')?.textContent.trim()==='Mark visited'")
        self.page.evaluate("renderer(0).data.map_settings.subdivision_countries=[]; renderer(0).render()")
        self.assertEqual(panel.locator(".search-result-regions").count(), 0)
        panel.locator("#continent").select_option("Europe")
        self.page.wait_for_function("!renderer(0).querySelector('.search-result')")
        self.assertEqual(self.errors, [])

    def test_country_search_touch_and_non_admin_banner(self):
        self.context.close()
        self.context = self.browser.new_context(viewport={"width": 375, "height": 850}, has_touch=True)
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.page.on("pageerror", lambda error: self.errors.append(str(error)))
        self.context.route("**/*", self.route)
        self.open_panels(admin=False)
        panel = self.page.locator("beenthere-panel")
        panel.locator("#view").select_option("t:alice")
        search = panel.get_by_role("combobox", name="Search countries", exact=True)
        search.fill("fra")
        panel.get_by_role("option", name="France", exact=True).tap()
        self.page.wait_for_function("renderer(0).querySelector('.search-result-name')?.textContent==='France'")
        self.assertEqual(panel.locator('.country[aria-label="France"]').get_attribute('aria-pressed'), 'true')
        self.assertEqual(panel.locator('.search-result-visit-status').count(), 0)
        self.assertEqual(panel.locator("#edit-country").count(), 0)
        self.assertEqual(panel.locator("#toggle-search-result").count(), 0)
        panel.get_by_role("button", name="Deselect country", exact=True).tap()
        self.assertEqual(panel.locator(".search-result").count(), 0)
        self.assertEqual(self.page.evaluate("JSON.stringify(snapshot.travellers)===originalHistory"), True)
        self.assertEqual(self.errors, [])

    def test_country_banner_failed_save_keeps_selection_and_can_retry(self):
        self.open_panels()
        panel = self.page.locator('beenthere-panel')
        panel.locator('#view').select_option('t:alice')
        panel.locator('[data-location-select="FR"]').click()
        self.page.wait_for_function("renderer(0).querySelector('.search-result-name')?.textContent==='France'")
        self.page.evaluate('failNextSave=true')
        panel.get_by_role('button', name='Mark unvisited', exact=True).click()
        self.page.wait_for_function("renderer(0).error==='Storage unavailable' && !renderer(0)._pendingChanges")
        self.assertTrue(panel.get_by_role('button', name='Mark unvisited', exact=True).is_visible())
        self.assertEqual(panel.locator('.search-result-name').inner_text(), 'France')
        self.assertIn('FR', self.page.evaluate('snapshot.travellers.alice.countries'))
        panel.get_by_role('button', name='Mark unvisited', exact=True).click()
        self.page.wait_for_function("renderer(0).querySelector('#toggle-search-result')?.textContent.trim()==='Mark visited'")
        self.assertEqual(panel.locator('.search-result-name').inner_text(), 'France')
        self.assertNotIn('FR', self.page.evaluate('snapshot.travellers.alice.countries'))
        self.assertEqual(self.errors, [])

    def test_regional_map_and_controls_fit_mobile_layout(self):
        self.open_panels()
        panel = self.open_us_map()
        for width in (1440, 1051, 1050, 621, 620, 390, 320):
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
        first.get_by_role("checkbox", name="Show regional detail for United States", exact=True).check()
        self.wait_for_detail(1, True)
        self.assertTrue(second.get_by_role("checkbox", name="Show regional detail for United States", exact=True).is_checked())
        self.assertEqual(self.page.evaluate("renderer(0).selection"), "t:alice")
        self.assertEqual(self.page.evaluate("renderer(1).selection"), "g:family")
        self.assertEqual(self.page.evaluate("renderer(1).continent"), "Europe")
        self.assertEqual(self.errors, [])

    def test_failed_save_restores_control_and_keyboard_focus(self):
        self.open_panels()
        panel = self.show_settings()
        self.page.evaluate("failNextSave=true;")
        checkbox = panel.get_by_role("checkbox", name="Show regional detail for United States", exact=True)
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

    def test_mobile_header_centres_branding_between_icon_controls(self):
        self.page.add_init_script("""
            customElements.define('ha-menu-button', class extends HTMLElement {
                constructor() {
                    super();
                    this.attachShadow({mode:'open'}).innerHTML=`
                        <style>button{width:var(--mdc-icon-button-size,48px);
                            height:var(--mdc-icon-button-size,48px);padding:0}</style>
                        <button aria-label="Toggle sidebar">Menu</button>`;
                    this.shadowRoot.querySelector('button').onclick=()=>{
                        this.dispatchEvent(new CustomEvent('hass-toggle-menu',
                            {bubbles:true,composed:true}));
                    };
                }
            });
            window.sidebarToggleCount=0;
            document.addEventListener('hass-toggle-menu',()=>sidebarToggleCount++);
        """)
        self.open_panels()
        panel = self.page.locator("beenthere-panel")
        header = panel.locator("header")
        self.page.evaluate("""
            const panel=document.querySelector('beenthere-panel');
            panel.narrow=true;
            renderer(0).selection='t:alice';
            renderer(0).continent='Europe';
        """)
        for width in (320, 375, 430, 599):
            with self.subTest(width=width):
                self.page.set_viewport_size({"width": width, "height": 1000})
                for settings_open in (False, True):
                    with self.subTest(settings_open=settings_open):
                        self.assertEqual(header.locator("h1").inner_text(), "BeenThere")
                        self.assertEqual(header.bounding_box()["height"], 56)
                        self.assertFalse(header.locator(".subtitle").is_visible())
                        self.assertFalse(header.locator(".settings-toggle span").is_visible())
                        boxes = {
                            name: header.locator(selector).bounding_box()
                            for name, selector in (
                                ("menu", "ha-menu-button"), ("brand", ".title-block"),
                                ("title", "h1"),
                                ("navigation", ".settings-toggle"),
                            )
                        }
                        menu, brand, navigation = (boxes[key] for key in ("menu", "brand", "navigation"))
                        self.assertEqual(menu["x"], 16)
                        self.assertGreaterEqual(brand["x"], menu["x"] + menu["width"] + 8)
                        self.assertLessEqual(brand["x"] + brand["width"] + 8, navigation["x"])
                        self.assertEqual(menu["width"], navigation["width"])
                        self.assertAlmostEqual(boxes["title"]["x"] + boxes["title"]["width"] / 2,
                                               width / 2)
                        self.assertAlmostEqual(navigation["x"] + navigation["width"], width - 16)
                        for box in boxes.values():
                            self.assertGreaterEqual(box["x"], 0)
                            self.assertLessEqual(box["x"] + box["width"], width)
                            self.assertAlmostEqual(box["y"] + box["height"] / 2, 28)
                        self.assertTrue(header.locator("h1").evaluate(
                            "element=>element.scrollWidth<=element.clientWidth"))
                        for target in (header.get_by_role("button", name="Toggle sidebar"),
                                       header.locator(".settings-toggle")):
                            box = target.bounding_box()
                            self.assertGreaterEqual(box["width"], 44)
                            self.assertGreaterEqual(box["height"], 44)
                        self.assertTrue(panel.evaluate(
                            "element=>element.scrollWidth<=element.clientWidth"))
                        self.assertTrue(self.page.evaluate(
                            "document.documentElement.scrollWidth<=innerWidth"))
                        heading = header.get_by_role("heading", name="Settings", exact=True)
                        self.assertFalse(heading.is_visible())
                        self.assertEqual(header.locator("ha-icon").get_attribute("icon"),
                                         "mdi:arrow-left" if settings_open else "mdi:cog")
                        if settings_open:
                            self.assertTrue(panel.locator("#vc-settings-title").is_visible())
                        label = "Back to map" if settings_open else "Settings"
                        header.get_by_role("button", name=label, exact=True).click()
                        self.assertEqual(self.page.evaluate("!!renderer(0).settingsOpen"), not settings_open)
                        self.assertEqual(header.locator(".settings-toggle").get_attribute("aria-expanded"),
                                         str(not settings_open).lower())
                header.get_by_role("button", name="Toggle sidebar").click()
        self.assertEqual(self.page.evaluate("sidebarToggleCount"), 4)
        self.assertTrue(panel.locator("ha-menu-button").evaluate(
            "element=>element.narrow && element.hass===document.querySelector('beenthere-panel').hass"))
        self.assertEqual(self.page.evaluate("renderer(0).selection"), "t:alice")
        self.assertEqual(self.page.evaluate("renderer(0).continent"), "Europe")
        self.assertEqual(self.errors, [])

    def test_desktop_header_keeps_full_subtitle_and_top_right_navigation(self):
        self.open_panels()
        panel = self.page.locator("beenthere-panel")
        header = panel.locator("header")
        for width in (600, 1024, 1440):
            with self.subTest(width=width):
                self.page.set_viewport_size({"width": width, "height": 1000})
                for settings_open in (False, True):
                    self.assertEqual(header.evaluate("element=>getComputedStyle(element).display"), "flex")
                    self.assertEqual(header.bounding_box()["height"], 56)
                    self.assertEqual(header.locator(".subtitle").inner_text(),
                                     "Track the countries you've visited, individually or together.")
                    self.assertFalse(header.locator(".page-title").is_visible())
                    navigation = header.locator(".settings-toggle").bounding_box()
                    self.assertEqual(navigation["height"], 40)
                    self.assertAlmostEqual(navigation["x"] + navigation["width"], width - 16)
                    self.assertAlmostEqual(navigation["y"] + navigation["height"] / 2, 28)
                    if settings_open:
                        self.assertTrue(panel.locator("#vc-settings-title").is_visible())
                    label = "Back to map" if settings_open else "Settings"
                    header.get_by_role("button", name=label, exact=True).click()
        self.assertEqual(self.errors, [])

    def test_mobile_header_hides_navigation_for_non_admins(self):
        self.page.set_viewport_size({"width": 320, "height": 1000})
        self.open_panels(admin=False)
        header = self.page.locator("beenthere-panel header")
        self.assertFalse(header.locator(".settings-toggle").is_visible())
        self.assertFalse(header.locator(".page-title").is_visible())
        self.assertFalse(header.locator(".subtitle").is_visible())
        self.assertEqual(header.bounding_box()["height"], 56)
        title = header.locator("h1").bounding_box()
        self.assertAlmostEqual(title["x"] + title["width"] / 2, 160)
        self.assertEqual(self.errors, [])

    def test_settings_fit_desktop_and_mobile(self):
        self.open_panels()
        self.show_settings()
        for width in (1440, 390, 320):
            with self.subTest(width=width):
                self.page.set_viewport_size({"width": width, "height": 1000})
                self.assertTrue(self.page.evaluate("document.documentElement.scrollWidth<=window.innerWidth"))
                self.assertTrue(self.page.locator(".map-detail-option").evaluate_all("labels=>labels.every(label=>label.querySelector('span').getBoundingClientRect().right<=label.querySelector('input').getBoundingClientRect().left)"))
                cards = self.page.locator(".settings-grid > .settings-card").evaluate_all(
                    "cards=>cards.map(card=>{const {x,y,width}=card.getBoundingClientRect();return {x,y,width};})"
                )
                travellers, groups, regional = cards
                if width > 1050:
                    total_width = sum(card["width"] for card in cards)
                    for card, share in zip(cards, (0.3, 0.3, 0.4)):
                        self.assertAlmostEqual(card["width"], total_width * share, delta=1)
                        self.assertEqual(card["y"], travellers["y"])
                elif width > 620:
                    self.assertAlmostEqual(travellers["width"], groups["width"], delta=1)
                    self.assertEqual(travellers["y"], groups["y"])
                    self.assertGreater(regional["y"], travellers["y"])
                    self.assertAlmostEqual(regional["width"], travellers["width"] + groups["width"] + 16, delta=1)
                else:
                    for card in cards:
                        self.assertEqual(card["x"], travellers["x"])
                        self.assertAlmostEqual(card["width"], travellers["width"], delta=1)
                    self.assertLess(travellers["y"], groups["y"])
                    self.assertLess(groups["y"], regional["y"])
                self.page.screenshot(path=str(Path(tempfile.gettempdir()) / f"beenthere-settings-{width}.png"), full_page=True)
        self.assertEqual(self.errors, [])

    def test_settings_scroll_only_when_content_exceeds_the_viewport(self):
        self.open_panels()
        panel = self.show_settings()
        for height in (1000, 600):
            with self.subTest(height=height):
                self.page.set_viewport_size({"width": 1440, "height": height})
                self.assertTrue(self.page.evaluate(
                    "document.documentElement.scrollHeight<=innerHeight"))
                self.assertTrue(panel.evaluate(
                    "element=>element.scrollHeight<=element.clientHeight"))
        self.page.set_viewport_size({"width": 320, "height": 480})
        last_option = panel.locator(".map-detail-option").last
        last_option.scroll_into_view_if_needed()
        self.assertLessEqual(last_option.bounding_box()["y"] + last_option.bounding_box()["height"], 480)
        self.assertEqual(self.errors, [])

    def test_settings_empty_states_are_compact_and_clear(self):
        self.open_panels()
        self.show_settings()
        panel = self.page.locator("beenthere-panel").first
        self.assertEqual(panel.locator(".manager-empty").count(), 0)
        self.page.evaluate("""
            renderer(0).data.travellers={};
            renderer(0).data.groups={};
            renderer(0).render();
        """)
        travellers = panel.locator(".settings-card").nth(0)
        groups = panel.locator(".settings-card").nth(1)
        self.assertEqual(travellers.locator(".manager-help").inner_text(),
                         "Track the countries each person has visited on their own map.")
        self.assertEqual(groups.locator(".manager-help").inner_text(),
                         "Combine travellers' existing visits on a shared, read-only map. No separate tracking needed.")
        self.assertEqual(travellers.locator(".manager-empty").inner_text(),
                         "No travellers yet. Add your first traveller to get started.")
        self.assertEqual(groups.locator(".manager-empty").inner_text(),
                         "No groups yet. Create a group to explore your travels together.")
        self.assertEqual(groups.locator('.manager-empty ha-icon[aria-hidden="true"]').get_attribute("icon"),
                         "mdi:account-group-outline")
        for width in (1440, 1051, 620, 320):
            with self.subTest(width=width):
                self.page.set_viewport_size({"width": width, "height": 1000})
                self.assertTrue(self.page.evaluate("document.documentElement.scrollWidth<=window.innerWidth"))
                for card, button_name in ((travellers, "Add traveller"), (groups, "Add group")):
                    self.assertLessEqual(card.locator(".manager-empty").bounding_box()["height"], 90)
                    self.assertTrue(card.get_by_role("button", name=button_name, exact=True).is_visible())
        travellers.get_by_role("button", name="Add traveller", exact=True).click()
        dialog = panel.locator(".settings-dialog")
        self.assertTrue(dialog.is_visible())
        dialog.get_by_role("button", name="Cancel", exact=True).click()
        groups.get_by_role("button", name="Add group", exact=True).click()
        self.assertTrue(dialog.is_visible())
        dialog.get_by_role("button", name="Cancel", exact=True).click()
        self.page.evaluate("""
            renderer(0).data=JSON.parse(JSON.stringify(snapshot));
            renderer(0).render();
        """)
        self.assertEqual(panel.locator(".manager-empty").count(), 0)
        self.assertEqual(panel.locator(".manager-list .chip").count(), 2)
        self.assertEqual(self.errors, [])

    def test_map_settings_switch_preserves_selection_and_delete_requires_confirmation(self):
        self.open_panels()
        panel = self.page.locator("beenthere-panel").first
        self.page.evaluate("""
            const card=renderer(0);
            card.selection='g:family';
            card.continent='North America';
            card.selectedLocation='US';
            card.searchResult='US';
            card.render();
        """)
        self.assertTrue(panel.locator("#map-view").is_visible())
        self.show_settings()
        self.assertTrue(panel.locator("#vc-settings").is_visible())
        self.assertFalse(panel.locator("#map-view").is_visible())
        self.assertEqual(self.page.evaluate(
            "[renderer(0).selection,renderer(0).continent,renderer(0).selectedLocation].join('|')"
        ), "g:family|North America|US")
        panel.get_by_role("checkbox", name="Show regional detail for United States", exact=True).check()
        self.page.wait_for_function(
            "renderer(0).data.map_settings.subdivision_countries.includes('US') && !!renderer(0).regionalMaps?.US"
        )
        panel.get_by_role("button", name="Back to map", exact=True).click()
        self.assertTrue(panel.locator("#map-view").is_visible())
        self.assertEqual(panel.locator("#view").input_value(), "g:family")
        self.assertEqual(panel.locator("#continent").input_value(), "North America")
        self.assertGreater(panel.locator('[data-location="US-CA"]').count(), 0)

        self.show_settings()
        panel.get_by_role("button", name="Delete Alice", exact=True).click()
        dialog = panel.locator(".settings-dialog")
        self.assertTrue(dialog.is_visible())
        self.assertIn("recorded visits will be deleted", dialog.inner_text())
        self.assertIn("removed from any groups", dialog.inner_text())
        self.assertEqual(self.page.evaluate(
            "wsMessages.filter(message=>message.action==='delete_traveller').length"
        ), 0)
        dialog.get_by_role("button", name="Cancel", exact=True).click()
        self.assertEqual(self.page.evaluate(
            "wsMessages.filter(message=>message.action==='delete_traveller').length"
        ), 0)
        self.assertIn("alice", self.page.evaluate("Object.keys(snapshot.travellers)"))
        self.assertEqual(self.errors, [])

    def test_traveller_and_group_forms_validate_names_and_manage_members(self):
        self.open_panels()
        panel = self.show_settings()
        panel.get_by_role("button", name="Add traveller", exact=True).click()
        dialog = panel.locator(".settings-dialog")
        dialog.get_by_label("Traveller name", exact=True).fill("Alice")
        dialog.get_by_role("button", name="Save", exact=True).click()
        self.assertIn("already exists", dialog.get_by_role("alert").inner_text())
        self.assertEqual(self.page.evaluate(
            "wsMessages.filter(message=>message.action==='add_traveller').length"
        ), 0)
        dialog.get_by_label("Traveller name", exact=True).fill("Bob")
        dialog.get_by_role("button", name="Save", exact=True).click()
        self.page.wait_for_function("snapshot.travellers.bob?.name==='Bob' && !renderer(0)._pendingChanges")

        panel.get_by_role("button", name="Add group", exact=True).click()
        dialog = panel.locator(".settings-dialog")
        dialog.get_by_label("Group name", exact=True).fill("Trip")
        dialog.get_by_label("Alice", exact=True).check()
        dialog.get_by_label("Bob", exact=True).check()
        dialog.get_by_role("button", name="Save", exact=True).click()
        self.page.wait_for_function("snapshot.groups.trip?.members.length===2 && !renderer(0)._pendingChanges")
        self.assertEqual(set(self.page.evaluate("snapshot.groups.trip.members")), {"alice", "bob"})
        self.assertEqual(self.errors, [])

    def test_visited_country_expands_only_visited_regions(self):
        self.open_panels()
        panel = self.open_us_map()
        self.assertEqual(panel.locator('.regional-checklists, .regional-checklist').count(), 0)
        self.assertEqual(panel.get_by_role("button", name="Regions", exact=True).count(), 0)
        country = panel.locator('.visited-country-item', has_text='United States')
        self.assertEqual(panel.locator('.visited-country-item').count(), 2)
        country.get_by_role('button', name='United States', exact=True).click()
        self.assertFalse(country.locator('.visited-subdivision-list').count())
        country.get_by_role('button', name='Expand visited regions in United States').click()
        self.assertEqual(
            panel.locator('.visited-country-list > li').evaluate_all(
                "items=>items.map(item=>item.dataset.countryItem)"
            ),
            ["FR", "US"],
        )
        self.assertEqual(country.locator('.visited-subdivision-list li').count(), 1)
        self.assertIn('California', country.locator('.visited-subdivision-list').inner_text())
        self.assertEqual(country.locator('.visited-subdivision-list input').count(), 0)
        self.assertEqual(country.get_by_role('button', name='Remove country-only visit to United States').count(), 0)
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
        self.assertEqual(country.count(), 0)
        self.assertEqual(self.errors, [])

    def test_region_expansion_is_independent_and_resets_on_view_or_continent_change(self):
        self.open_panels()
        panel = self.page.locator("beenthere-panel").first
        self.page.evaluate("""
            const card=renderer(0);
            snapshot.travellers.alice.countries=['US-CA','GB-ENG'];
            snapshot.map_settings.subdivision_countries=['GB','US'];
            card.data=JSON.parse(JSON.stringify(snapshot));
            card.render();
        """)
        for country in ("GB", "US"):
            self.assertEqual(
                panel.locator(f'[data-country-item="{country}"] .region-link').get_attribute("aria-expanded"),
                "false",
            )
        panel.get_by_role('button', name='Expand visited regions in United Kingdom').click()
        panel.get_by_role('button', name='Collapse visited regions in United Kingdom').wait_for()
        panel.get_by_role('button', name='Expand visited regions in United States').click()
        panel.get_by_role('button', name='Collapse visited regions in United States').wait_for()
        for country in ("GB", "US"):
            self.assertEqual(
                panel.locator(f'[data-country-item="{country}"] .region-link').get_attribute("aria-expanded"),
                "true",
            )
        self.page.locator("beenthere-panel").locator("#view").select_option("g:family")
        self.page.wait_for_function(
            "renderer(0).selection==='g:family' && renderer(0).expandedCountries.size===0 && !renderer(0).querySelector('.region-link[aria-expanded=\"true\"]')"
        )
        for country in ("GB", "US"):
            self.assertEqual(
                panel.locator(f'[data-country-item="{country}"] .region-link').get_attribute("aria-expanded"),
                "false",
            )
        for country in ("GB", "US"):
            panel.get_by_role('button', name=f'Expand visited regions in {"United Kingdom" if country == "GB" else "United States"}').click()
            panel.get_by_role('button', name=f'Collapse visited regions in {"United Kingdom" if country == "GB" else "United States"}').wait_for()
        panel.locator("#continent").select_option("Europe")
        self.page.wait_for_function("renderer(0).querySelector('#continent')?.value==='Europe' && !renderer(0).querySelector('.region-link[aria-expanded=\"true\"]')")
        for country in ("GB", "US"):
            self.assertEqual(
                panel.locator(f'[data-country-item="{country}"] .region-link').get_attribute("aria-expanded"),
                "false",
            )
        self.assertEqual(self.page.evaluate("JSON.stringify(snapshot.travellers.alice.countries)"), '["US-CA","GB-ENG"]')
        self.assertEqual(self.errors, [])