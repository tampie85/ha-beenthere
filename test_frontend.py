"""Frontend contracts; install quickjs-ng only in the development environment."""

from pathlib import Path
import unittest

try:
    import quickjs
except ImportError:
    quickjs = None


@unittest.skipIf(quickjs is None, "Optional frontend test runtime: quickjs-ng")
class FrontendTests(unittest.TestCase):
    def setUp(self):
        self.context = quickjs.Context()
        self.context.eval("""
            globalThis.HTMLElement=class {};
            globalThis.customElements={get:()=>false,define:()=>{}};
            globalThis.console={error:()=>{}};
        """)
        source = Path(__file__).parent / "frontend" / "beenthere-card.js"
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
        """)

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
        self.assertIsNone(self.context.eval("card.iso({properties:{ISO_A2_EH:'US-CA'}})"))


if __name__ == "__main__":
    unittest.main()