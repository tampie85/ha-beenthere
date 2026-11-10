# BeenThere

BeenThere adds a dedicated **BeenThere** sidebar page to Home
Assistant. Open it to manage travellers and groups and track visited countries
on the interactive map. The page uses the integration's existing stored data.
Administrators can switch between the map and a dedicated Settings view from
the header; returning to the map preserves the current traveller, continent and
selection. On desktop, Settings uses 30% / 30% / 40% columns for Travellers,
Groups and Regional detail, respectively, excluding gaps. Tablet and mobile
layouts retain two columns and a single column, respectively.
Below 600px, the header puts the menu and branding above page navigation and
shortens the subtitle to "Track the countries you've visited." In Settings, the
second row pairs the page heading with Back to map; desktop keeps the full
subtitle and its existing header layout.
Each traveller has their own map and visit history. Groups combine travellers'
existing visits on a shared, read-only map, without separate tracking.

The world map shows country and territory outlines. Subdivision detail can be
enabled independently for the United Kingdom, United States, Australia, Canada,
and Germany in Settings. Their boundaries and region records are bundled locally.
Territories with their own country code remain separate from their
administering country: France and French Guiana, for example, are independent
selections.

## Geographic model and regional tracking

The backend has a shared geographic catalogue in `geography.json` and a
version-2 storage model. Global map-detail controls are available in the
administrator Settings view. When subdivision detail is enabled, region
boundaries appear on the main map and the visited-country sidebar can expand a
country to show only its visited regions. Only explicitly visited regions are
filled; a country-level visit does not fill any region. Administrators viewing
one traveller can change country and region visits independently through the
map. Keyboard users can focus map boundaries and press Enter or Space. Clicking
a map area or sidebar entry highlights the corresponding area in both views.

Group and Everyone views show the **union** of explicit visits across their
selected members, not an intersection. All group views are read-only, including
for administrators. Selecting a map area or list entry identifies the selected
travellers who recorded that exact region; country details include travellers
with an explicit country visit or at least one known region visit. Outsiders are
not included. Individual non-administrator views are also read-only. An explicit
country visit never implies any subdivision visits.

The world map and country count treat a country as visited either because it is
explicitly recorded or because at least one of its subdivisions is explicitly
recorded. With subdivision detail enabled, only the explicitly visited regions
are filled and the country-level state is shown separately in the list. When
detail is disabled, the country is shown as one visited shape if it has an
explicit visit or any region visit. The region list and `visited_subdivisions`
remain exact and are unaffected by country-level visits. Unknown historical
IDs are retained but never used to infer parent visits.

The main traveller/group selector and continent filter control the map. The
sidebar lists unique visited countries alphabetically, including countries
visited through regions, and shows the count. Selecting a country only highlights
it on the map. Administrators can remove an explicit country-only visit from
the sidebar after confirmation; this does not remove any regional history.
The three sidebar headings share the same typography. The visited-country
heading and divider stay inside the rounded card, above the independently
scrolling list. The selectors and heading remain visible while only the country list scrolls;
visited-region entries start collapsed and can be expanded independently.
Expanded entries are read-only and region visits are managed through the map.
A country remains visible when its visits come only from regions, including
while regional detail is disabled. Visit controls
are disabled during a pending write; a failed write leaves the published visit
state unchanged, shows an error and permits retry. Changes synchronize across
open panels. Disabling a country's detail setting hides regional boundaries and
entries without deleting history or losing derived country highlights.

The catalogue separates countries/territories from their subdivisions. It covers
all 249 ISO 3166-1 alpha-2 identifiers and retains the existing map's `XK` identifier
for Kosovo as an explicit non-ISO compatibility exception. Subdivision identifiers
follow ISO 3166-2: the four UK constituent countries, 50 US states and Washington,
DC, six Australian states and ACT/NT, 10 Canadian provinces and three territories,
and 16 German federal states. Russian subdivisions are not supported. Azores and
Madeira remain valid legacy locations, without adding Portugal detail settings.
Identifiers were checked against an ISO reference using development-only tooling;
no ISO lookup library or online service is required at runtime.

Each traveller's existing `countries` array holds **explicit location IDs**, not
inferred visits. `US` and `US-CA` may coexist. The backend's geographic helpers
derive one visited country from California and Florida, while retaining two
subdivision visits. A country visit never implies visits to all its subdivisions.
Removing an explicit country visit does not remove its children. Independent
country-coded territories remain independent: visiting French Guiana does not
imply visiting France. The panel now applies this same derivation when drawing
the world map and the "Visited" summary and list; the regional list itself still
shows each subdivision's exact, non-inferred state.

Global settings live separately under `map_settings.subdivision_countries`, with
`["GB"]` as the default. Administrators can enable or disable the five supported
countries from the Settings view; the preference is shared by all travellers and
groups and does not change saved visits. Geographic metadata is not copied into
traveller history or map settings. Changes are synchronized to other open panels
through the existing `beenthere_updated` event.

The existing `beenthere/get`, `beenthere/change` and `toggle_country` contracts are
retained. Administrators may also call `beenthere/change` with action `set_visit`,
`target_id` for a traveller, `location` for a catalogue ID, and a boolean `visited`.
This operation is idempotent and changes only the exact explicit location.
Unknown location IDs, non-boolean states and action-inappropriate fields are
rejected before saving. Group IDs cannot be used as traveller targets.

Storage upgrades from version 1 add default global settings without converting
visits or changing traveller/group IDs. Unsupported storage versions fail rather
than resetting history. Loading retains well-formed unknown historical IDs, so a
future catalogue change cannot silently discard them; unknown IDs do not acquire
inferred parent visits and cannot be added through new writes. Back up storage
before upgrading. Downgrading from storage version 2 is not supported.

After updating the integration, restart Home Assistant to register the sidebar
page. Its URL is `/beenthere`. Refresh the browser if the new sidebar
entry does not appear immediately.

BeenThere is available as a dedicated sidebar panel and does not register a
dashboard card.

## Access and privacy

All authenticated Home Assistant users can view all travellers, groups and
visited countries. Only administrators can add, rename or delete travellers,
manage groups, or change visits. These permissions are enforced by the backend,
not just by hiding editing controls. BeenThere does not provide private records
for individual Home Assistant users.

The world map currently loads country boundaries from Natural Earth on GitHub
and flag images from FlagCDN. These browser requests require internet access and
expose the browser's IP address and requested resources to those services.
Country outlines have no explicit offline fallback yet. No travel history is
included in the boundary request; requested flag URLs identify individual flags.
Subdivision maps for all five supported countries are bundled locally and make
no external boundary requests. Their generalized 1:50m boundaries are Natural
Earth v5.1.2 public-domain data, not legal/survey boundaries. Provenance,
license and extraction details are in `frontend/maps/SOURCES.txt`. No new
mapping framework or runtime dependency is required.

## Storage and recovery

Travel data uses Home Assistant's versioned storage under the key
`beenthere.<config_entry_id>`. Include Home Assistant's `.storage` directory in
backups. Do not edit storage while Home Assistant is running.

Changes are serialized and saved as independent snapshots, using private,
atomic file writes. Unloading the integration rejects new requests and waits
for an already-started change to finish. A storage exception exposed by Home
Assistant leaves the published snapshot unchanged and returns an error.
Home Assistant's storage helper can also log some write failures without
raising them, so an API response is not an independent guarantee of disk
durability. Check Home Assistant logs and maintain backups.

## Development checks

From the integration repository root, run the storage tests without Home
Assistant or additional test dependencies:

```sh
python3 -B -m unittest discover -s tests -p 'test_storage.py'
python3 -B -m unittest discover -s tests -p 'test_travellers_groups.py'
```

For all contract tests, create a separate development environment outside the
integration directory. Do not install test dependencies into Home Assistant:

```sh
python3 -m venv /tmp/beenthere-test-venv
. /tmp/beenthere-test-venv/bin/activate
python3 -m pip install pytest coverage voluptuous quickjs-ng
python3 -B -m unittest discover -s tests -p 'test_*.py' -v
python3 -m pytest -q
```

The tests retain their `unittest` fixtures and assertions; pytest is an
alternative runner and needs no async plugin. The flat `tests/` directory
groups storage validation, traveller/group operations, persistence, integration
lifecycle/WebSocket contracts, geographic hierarchy and frontend behaviour. Shared loaders and the
backend harness live in `tests/helpers.py`; frontend setup stays local.

Optional Chromium browser checks exercise the actual bundled US boundaries,
state selection, group unions and member details, explicit/derived country
states, failed/pending saves, cross-panel settings changes and mobile layouts.
In the separate development environment, install `playwright`, run
`python3 -m playwright install chromium`, then run
`python3 -B -m unittest discover -s tests -p 'test_frontend_browser.py' -v`.
Backend persistence tests separately verify save failures, idempotency,
concurrent writes and reloads through Home Assistant boundary doubles.

To measure Python line and branch coverage:

```sh
python3 -m coverage run --branch --source=. --omit='test_*.py,tests/*' -m unittest discover -s tests -p 'test_*.py'
python3 -m coverage report -m
```

Frontend tests are explicitly skipped when `quickjs-ng` is unavailable. Backend
tests use lightweight Home Assistant boundary doubles; frontend tests execute
JavaScript without a browser. Install `quickjs-ng` for a full run with no skips.
Coverage.py measures Python, not JavaScript executed by QuickJS. These checks
do not replace testing against real Home Assistant versions, HACS/hassfest
validation, or browser accessibility and responsive-layout checks.

## Release packaging

The `.gitattributes` export exclusions keep `tests/` and `pytest.ini` out of
Git archives. Once these changes are committed, a runtime ZIP can be created
from a release tag with `git archive --format=zip --output=beenthere.zip <tag>`.
No release workflow is configured yet. Future custom ZIP or HACS release
workflows must preserve these exclusions; copying the working directory
directly does not apply Git archive attributes.
Include `frontend/maps/US.geojson` and `frontend/maps/SOURCES.txt` in every
runtime archive. Neither file is export-ignored.