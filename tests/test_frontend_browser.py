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
        headings = sidebar.locator(".sidebar-heading")
        self.assertEqual(headings.count(), 3)
        typography = headings.evaluate_all("""elements=>elements.map(element=>{
            const style=getComputedStyle(element);
            return [style.fontSize,style.fontWeight,style.color,style.lineHeight];
        })""")
        self.assertEqual(typography, [typography[0]] * 3)
        self.assertEqual(typography[0][:3], ["13px", "400", "rgb(182, 232, 241)"])
        self.assertEqual(country_card.locator(".country-count").evaluate("""element=>{
            const style=getComputedStyle(element);
            return [style.fontSize,style.fontWeight,style.color,style.lineHeight];
        }"""), typography[0])
        spacing = headings.evaluate_all("""elements=>elements.map(element=>{
            const content=element.tagName==='LABEL'
                ?element.nextElementSibling:element.parentElement.querySelector('.visited-country-list');
            return content.getBoundingClientRect().top-element.getBoundingClientRect().bottom;
        })""")
        self.assertEqual(spacing, [20, 20, 20])
        heading = country_card.locator(".sidebar-heading")
        divider = country_card.locator(".visited-country-divider")
        self.assertEqual(country_list.locator(".sidebar-heading, .visited-country-divider").count(), 0)
        self.assertEqual(panel.locator(".visited-subdivision-list").count(), 0)
        panel.get_by_role('button', name='Expand visited regions in United Kingdom').click()
        panel.get_by_role('button', name='Expand visited regions in United States').click()
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
        self.assertEqual(panel.locator('[data-country-item="US"] .visited-subdivision-list').count(), 0)
        panel.get_by_role('button', name='Expand visited regions in United States').click()
        panel.locator('[data-location-select="US-CA"]').click()
        self.page.wait_for_function("renderer(0).selectedLocation==='US-CA'")
        self.assertEqual(panel.locator('[data-location="US-CA"]').get_attribute("aria-current"), "true")
        self.assertEqual(panel.locator('[data-location-select="US-CA"]').get_attribute("aria-current"), "true")
        self.assertEqual(self.page.evaluate("JSON.stringify(snapshot.travellers)"), before)
        self.assertEqual(self.page.evaluate("wsMessages.filter(message=>message.type==='beenthere/change').length"), 0)
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
        messages = []
        self.page.once("dialog", lambda dialog: (messages.append(dialog.message), dialog.accept()))
        france.click()
        self.page.wait_for_function("!renderer(0)._pendingChanges && !snapshot.travellers.alice.countries.includes('FR')")
        self.assertIn("Regional visits, if any, will be preserved.", messages[0])
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
        panel.get_by_role('button', name='Expand visited regions in United States').click()
        for country in ("GB", "US"):
            self.assertEqual(
                panel.locator(f'[data-country-item="{country}"] .region-link').get_attribute("aria-expanded"),
                "true",
            )
        self.page.locator("beenthere-panel").locator("#view").select_option("g:family")
        self.page.wait_for_function(
            "renderer(0).selection==='g:family' && renderer(0).expandedCountries.size===0"
        )
        for country in ("GB", "US"):
            self.assertEqual(
                panel.locator(f'[data-country-item="{country}"] .region-link').get_attribute("aria-expanded"),
                "false",
            )
        for country in ("GB", "US"):
            panel.get_by_role('button', name=f'Expand visited regions in {"United Kingdom" if country == "GB" else "United States"}').click()
        panel.locator("#continent").select_option("Europe")
        for country in ("GB", "US"):
            self.assertEqual(
                panel.locator(f'[data-country-item="{country}"] .region-link').get_attribute("aria-expanded"),
                "false",
            )
        self.assertEqual(self.page.evaluate("JSON.stringify(snapshot.travellers.alice.countries)"), '["US-CA","GB-ENG"]')
        self.assertEqual(self.errors, [])