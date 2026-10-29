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