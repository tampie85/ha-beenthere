import subprocess
import sys
import unittest
from pathlib import Path

import test_frontend_browser as tests

baseline = subprocess.check_output([
    r'C:\Program Files\Git\cmd\git.exe', 'show', ':frontend/beenthere-card.js'
]).decode('utf-8')
original_read = Path.read_text


def baseline_read(path, *args, **kwargs):
    return baseline if path.name == 'beenthere-card.js' else original_read(path, *args, **kwargs)


Path.read_text = baseline_read
original_setup = tests.PanelBrowserTests.setUp


def baseline_setup(self):
    original_setup(self)
    self.page.set_default_timeout(3000)


tests.PanelBrowserTests.setUp = baseline_setup
names = [
    'test_explicit_country_visit_does_not_infer_states_or_get_removed_with_state',
    'test_many_visited_countries_scroll_inside_sidebar',
    'test_map_selection_persists_exact_subdivision_and_survives_reload',
    'test_unvisited_region_outlines_match_country_outlines_until_a_region_is_visited',
] * 4
result = unittest.TextTestRunner(verbosity=2).run(
    unittest.TestSuite(tests.PanelBrowserTests(name) for name in names)
)
sys.exit(not result.wasSuccessful())