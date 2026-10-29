# BeenThere

BeenThere adds a dedicated **BeenThere** sidebar page to Home
Assistant. Open it to manage travellers and groups and track visited countries
on the interactive map. The page uses the integration's existing stored data.

Map selection is at country and territory level, not state or province level.
Territories with their own country code remain separate from their administering
country: France and French Guiana, for example, are independent selections.
Existing subdivision visits are retained in storage but are not shown or
automatically converted into country visits.

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

The map currently loads country boundaries from Natural Earth on GitHub and
flag images from FlagCDN. These browser requests require internet access and
expose the browser's IP address and requested resources to those services.
Country outlines have no explicit offline fallback yet. No travel history is
included in the boundary request; requested flag URLs identify individual flags.

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
lifecycle/WebSocket contracts and frontend behaviour. Shared loaders and the
backend harness live in `tests/helpers.py`; frontend setup stays local.

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