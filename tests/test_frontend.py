"""Frontend contracts; install quickjs-ng only in the development environment."""

import unittest

from helpers import COMPONENT_ROOT

try:
    import quickjs
except ImportError:
    quickjs = None


@unittest.skipIf(quickjs is None, "Optional frontend test runtime: quickjs-ng")
class FrontendTests(unittest.TestCase):
    def setUp(self):
        self.context = quickjs.Context()
        self.context.eval("""
            globalThis.HTMLElement=class {
                addEventListener() {}
                removeEventListener() {}
            };
            globalThis.customElements={get:()=>false,define:()=>{}};
            globalThis.console={error:()=>{}};
        """)
        source = COMPONENT_ROOT / "frontend" / "beenthere-card.js"
        self.context.eval(source.read_text())
        self.context.eval("""
            const card=new VisitedCountriesCard();
            card.render=()=>{};
            card.selection='t:alice';
            card.continent='World';
            card.data={travellers:{alice:{name:'Alice',countries:['GF','US-CA']}},groups:{}};
            let calls=0;
            card._hass={user:{is_admin:false},callWS:async()=>{
                calls++;
                return card.data;
            }};
            const france={properties:{ISO_A2_EH:'FR',ADMIN:'France'}};
            const guiana={properties:{ISO_A2_EH:'GF',ADMIN:'French Guiana'}};
            let subscriptions=0, unsubscribes=0;
            let update;
            const listeners=new Map();
            const connection={
                connected:true,
                addEventListener:(type,handler)=>listeners.set(type,handler),
                removeEventListener:(type,handler)=>{if(listeners.get(type)===handler)listeners.delete(type);},
                subscribeEvents:async(handler,type)=>{
                    if(type!=='beenthere_updated')throw new Error('Wrong event type');
                    subscriptions++; update=handler;
                    return ()=>{unsubscribes++;};
                },
            };
        """)
        self.context.eval("card.catalogue="+(COMPONENT_ROOT / "geography.json").read_text()+";")

    def test_map_html_response_identifies_missing_static_url(self):
        self.context.eval("""
            let failure='';
            globalThis.fetch=async()=>({ok:true,headers:{get:()=> 'text/html'},
                json:async()=>{throw new Error('HTML must not be parsed');}});
            card.fetchGeoJson('/beenthere/maps/GB.geojson', 'GB subdivision')
                .catch(error=>{failure=error.message;});
        """)
        self.drain_jobs()
        self.assertIn('HTML instead of JSON', self.context.eval('failure'))
        self.assertIn('/beenthere/maps/GB.geojson', self.context.eval('failure'))
        self.assertIn('restart Home Assistant', self.context.eval('failure'))

    def drain_jobs(self):
        while self.context.execute_pending_job():
            pass

    def test_subscription_is_deduplicated_and_disconnect_cleans_up(self):
        self.context.eval("card._hass.connection=connection; card.connectedCallback(); card.syncConnection();")
        self.drain_jobs()
        self.assertEqual(self.context.eval("subscriptions"), 1)
        self.assertEqual(self.context.eval("listeners.size"), 2)
        self.context.eval("card.disconnectedCallback();")
        self.drain_jobs()
        self.assertEqual(self.context.eval("unsubscribes"), 1)
        self.assertEqual(self.context.eval("listeners.size"), 0)

    def test_updates_refresh_without_resetting_view_or_fetching_geometry(self):
        self.context.eval("card._hass.connection=connection; card.connectedCallback();")
        self.drain_jobs()
        self.context.eval("calls=0; card.selection='g:family'; card.continent='Europe'; update({});")
        self.drain_jobs()
        self.assertEqual(self.context.eval("calls"), 1)
        self.assertEqual(self.context.eval("card.selection"), "g:family")
        self.assertEqual(self.context.eval("card.continent"), "Europe")

    def test_reconnect_refreshes_without_duplicate_subscription(self):
        self.context.eval("card._hass.connection=connection; card.connectedCallback();")
        self.drain_jobs()
        self.context.eval("calls=0; listeners.get('disconnected')(); update({});")
        self.drain_jobs()
        self.assertEqual(self.context.eval("calls"), 0)
        self.context.eval("listeners.get('ready')();")
        self.drain_jobs()
        self.assertEqual(self.context.eval("calls"), 1)
        self.assertEqual(self.context.eval("subscriptions"), 1)

    def test_delayed_subscription_is_released_after_detach(self):
        self.context.eval("""
            let finishSubscribe;
            connection.subscribeEvents=()=>new Promise(resolve=>{finishSubscribe=resolve; subscriptions++;});
            card._hass.connection=connection;
            card.connectedCallback();
            card.disconnectedCallback();
            finishSubscribe(()=>{unsubscribes++;});
        """)
        self.drain_jobs()
        self.assertEqual(self.context.eval("unsubscribes"), 1)
        self.assertEqual(self.context.eval("calls"), 0)

    def test_stale_refresh_cannot_overwrite_newer_mutation(self):
        self.context.eval("""
            let finishRead;
            card._hass.user.is_admin=true;
            card._hass.callWS=message=>message.type==='beenthere/get'
                ? new Promise(resolve=>{finishRead=resolve;})
                : Promise.resolve({travellers:{},groups:{},map_settings:{subdivision_countries:['GB','US']}});
            card.refreshData();
            card.change('set_map_detail',{country:'US',enabled:true});
        """)
        self.drain_jobs()
        self.context.eval("finishRead({travellers:{},groups:{},map_settings:{subdivision_countries:['GB']}});")
        self.drain_jobs()
        self.assertEqual(self.context.eval("card.data.map_settings.subdivision_countries.join(',')"), "GB,US")

    def test_inflight_update_events_coalesce_into_one_followup_read(self):
        self.context.eval("card._hass.connection=connection; card.connectedCallback();")
        self.drain_jobs()
        self.context.eval("""
            let finishRead;
            calls=0;
            card._hass.callWS=()=>{calls++;return new Promise(resolve=>{finishRead=resolve;});};
            update({}); update({}); update({});
        """)
        self.drain_jobs()
        self.assertEqual(self.context.eval("calls"), 1)
        self.context.eval("finishRead(card.data);")
        self.drain_jobs()
        self.assertEqual(self.context.eval("calls"), 2)
        self.context.eval("finishRead(card.data);")
        self.drain_jobs()
        self.assertEqual(self.context.eval("calls"), 2)

    def test_map_detail_settings_use_catalogue_and_global_saved_values(self):
        self.context.eval("""
            card._hass.user.is_admin=true;
            card.catalogue={countries:{Europe:{GB:'United Kingdom',DE:'Germany'},'North America':{US:'United States'}},
                subdivision_countries:['US','GB','DE']};
            card.data.map_settings={subdivision_countries:['GB']};
        """)
        self.assertEqual(self.context.eval("card.mapDetailOptions().map(country=>country.code).join(',')"), "DE,GB,US")
        markup = self.context.eval("card.mapDetailSettings()")
        self.assertIn('data-map-detail="GB"', markup)
        self.assertEqual(markup.count('checked'), 1)
        self.assertNotIn('disabled', markup)
        self.context.eval("card._pendingChanges=1;")
        self.assertEqual(self.context.eval("card.mapDetailSettings().split('disabled').length-1"), 3)
        self.context.eval("card._hass.user.is_admin=false;")
        self.assertEqual(self.context.eval("card.mapDetailSettings()"), "")

    def test_sync_websocket_error_does_not_leave_refresh_stuck(self):
        self.context.eval("card._hass.callWS=()=>{throw new Error('Connection unavailable');}; card.refreshData();")
        self.drain_jobs()
        self.assertIn("Connection unavailable", self.context.eval("card.error"))
        self.assertFalse(self.context.eval("!!card._refreshPromise"))

    def test_non_admin_change_never_sends_request(self):
        self.context.eval("card.change('delete_traveller',{id:'alice'});")
        while self.context.execute_pending_job():
            pass
        self.assertEqual(self.context.eval("calls"), 0)
        self.assertIn("Administrator", self.context.eval("card.error"))

    def test_admin_can_change(self):
        self.context.eval("card._hass.user.is_admin=true; card.change('toggle_country',{id:'alice',country:'FR'});")
        while self.context.execute_pending_job():
            pass
        self.assertEqual(self.context.eval("calls"), 1)

    def test_read_only_map_click_shows_details_without_mutating(self):
        self.context.eval("card.clickCountry(france);")
        self.assertEqual(self.context.eval("calls"), 0)
        self.assertEqual(self.context.eval("card.searchResult"), "FR")

    def test_non_admin_cannot_open_settings_or_group_editor(self):
        self.context.eval("card.toggleSettings(); card.editGroup();")
        self.assertFalse(self.context.eval("!!card.settingsOpen"))

    def test_losing_admin_access_closes_settings(self):
        self.context.eval("""
            card._hass.user.is_admin=true;
            card.settingsOpen=true;
            card._started=true;
            card.hass={user:{is_admin:false}};
        """)
        self.assertFalse(self.context.eval("card.settingsOpen"))

    def test_websocket_error_message_is_preserved(self):
        self.context.eval("card.setError({code:'storage_error',message:'Storage unavailable'});")
        self.assertEqual(self.context.eval("card.error"), "Storage unavailable")

    def test_territories_and_legacy_visits_do_not_merge(self):
        self.context.eval("""
            card.geo=card.prepareMap({features:[france,guiana]});
            const visited=card.visited(card.chosen());
        """)
        self.assertTrue(self.context.eval("visited.has('GF')"))
        self.assertFalse(self.context.eval("visited.has('FR')||visited.has('US')"))

    def test_effective_countries_derives_country_from_subdivision_only(self):
        self.context.eval("""
            card.geo=card.prepareMap({features:[france,guiana]});
            const effective=card.effectiveCountries(card.chosen());
        """)
        self.assertTrue(self.context.eval("effective.has('US')"))
        self.assertTrue(self.context.eval("effective.has('GF')"))
        self.assertFalse(self.context.eval("effective.has('FR')"))

    def test_effective_countries_and_locations_are_a_group_union(self):
        self.context.eval("""
            card.data.travellers.bob={name:'Bob',countries:['US','US-FL']};
            card.data.groups={pair:{name:'Pair',members:['alice','bob']}};
            card.selection='g:pair';
            const effective=card.effectiveCountries(card.chosen());
        """)
        self.assertTrue(self.context.eval("effective.has('US')"))
        self.assertTrue(self.context.eval("effective.has('GF')"))
        self.assertEqual(self.context.eval("card.visited(card.chosen()).size"), 4)

    def test_sidebar_countries_are_unique_and_sorted_by_display_name(self):
        self.context.eval("""
            card.data.travellers.alice.countries=['US','US-CA','GF'];
            card.catalogue={countries:{'North America':{US:'United States'},'South America':{GF:'French Guiana'}},
                subdivisions:{US:{'US-CA':'California'}}};
        """)
        self.assertEqual(
            self.context.eval("card.visitedCountries().map(country=>country.code).join(',')"),
            "GF,US",
        )
        self.context.eval("""
            card.data.travellers.bob={name:'Bob',countries:['US-FL']};
            card.data.groups.pair={name:'Pair',members:['alice','bob']};
            card.selection='g:pair';
        """)
        self.assertEqual(self.context.eval("card.visitedCountries().map(country=>country.code).join(',')"), "GF,US")

    def test_regions_for_uses_catalogue_and_is_name_sorted(self):
        self.context.eval("""
            card.catalogue={countries:{'North America':{US:'United States'}},
                subdivision_countries:['US'],
                subdivisions:{US:{'US-CA':'California','US-AK':'Alaska'}}};
        """)
        self.assertEqual(
            self.context.eval("card.regionsFor('US').map(region=>region.code).join(',')"), "US-AK,US-CA",
        )
        self.assertEqual(self.context.eval("card.regionsFor('FR').length"), 0)

    def test_subdivision_tracking_enabled_reflects_saved_settings(self):
        self.context.eval("card.data.map_settings={subdivision_countries:['GB']};")
        self.assertTrue(self.context.eval("card.subdivisionTrackingEnabled('GB')"))
        self.assertFalse(self.context.eval("card.subdivisionTrackingEnabled('US')"))

    def test_region_screen_renderer_is_removed(self):
        self.assertEqual(self.context.eval("typeof card.renderRegionView"), "undefined")
        self.assertEqual(self.context.eval("typeof card.openRegion"), "undefined")

    def test_country_name_from_catalogue_falls_back_to_code(self):
        self.context.eval("""
            card.catalogue={countries:{'North America':{US:'United States'}}};
        """)
        self.assertEqual(self.context.eval("card.countryNameFromCatalogue('US')"), "United States")
        self.assertEqual(self.context.eval("card.countryNameFromCatalogue('ZZ')"), "ZZ")

    def test_unknown_historical_ids_do_not_infer_parent_countries(self):
        self.context.eval("card.data.travellers.alice.countries=['DE-XYZ','ZZ','US-XX'];")
        self.assertEqual(self.context.eval("card.effectiveCountries(card.chosen()).size"), 0)

    def test_visitors_use_effective_country_and_exact_subdivision_membership(self):
        self.context.eval("""
            card.data.travellers.bob={name:'Bob',countries:['US','US-FL']};
            card.data.travellers.carol={name:'Carol',countries:['US-CA']};
            card.data.groups.pair={name:'Pair',members:['alice','bob']};
            card.selection='g:pair';
        """)
        self.assertEqual(self.context.eval("card.visitors('US').map(person=>person.name).join(',')"), "Alice,Bob")
        self.assertEqual(self.context.eval("card.visitors('US-CA').map(person=>person.name).join(',')"), "Alice")
        self.assertEqual(self.context.eval("card.visitors('US-FL').map(person=>person.name).join(',')"), "Bob")
        self.assertEqual(self.context.eval("card.visitors('US-AK').length"), 0)

    def test_country_and_subdivision_statuses_remain_distinct(self):
        self.assertEqual(self.context.eval("card.visitStatus('US')"), "Visited via subdivisions")
        self.assertEqual(self.context.eval("card.visitStatus('US-CA')"), "Visited")
        self.assertEqual(self.context.eval("card.visitStatus('US-FL')"), "Not visited")
        self.context.eval("card.data.travellers.alice.countries=['US'];")
        self.assertEqual(self.context.eval("card.visitStatus('US')"), "Visited")
        self.assertEqual(self.context.eval("card.visitStatus('US-CA')"), "Not visited")

    def test_group_and_non_admin_region_writes_are_blocked(self):
        self.context.eval("card.setLocationVisit('US-CA',false);")
        self.drain_jobs()
        self.context.eval("card._hass.user.is_admin=true; card.selection=''; card.setLocationVisit('US-CA',false);")
        self.drain_jobs()
        self.assertEqual(self.context.eval("calls"), 0)

    def test_empty_groups_have_no_effective_or_explicit_visits(self):
        self.context.eval("card.data.groups.empty={name:'Empty',members:[]}; card.selection='g:empty';")
        self.assertEqual(self.context.eval("card.visited(card.chosen()).size"), 0)
        self.assertEqual(self.context.eval("card.effectiveCountries(card.chosen()).size"), 0)
        self.assertEqual(self.context.eval("card.visitors('US').length"), 0)

    def test_regional_paths_use_the_main_map_projection(self):
        path = self.context.eval("card.regionalPath({geometry:{type:'Polygon',coordinates:[[[-120,25],[-119,25],[-119,26],[-120,25]]]}})")
        self.assertIn("144.00000,156.00000", path)

    def test_malformed_regional_map_surfaces_error_without_caching(self):
        self.context.eval("""
            card.data.map_settings={subdivision_countries:['US']};
            card.fetchGeoJson=async()=>({type:'FeatureCollection',features:[]});
            card.ensureRegionalMap('US');
        """)
        self.drain_jobs()
        self.assertIn("does not match", self.context.eval("card.error"))
        self.assertFalse(self.context.eval("!!card.regionalMaps?.US"))
        self.assertFalse(self.context.eval("!!card._regionLoads.US"))