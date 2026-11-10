/* BeenThere - Lovelace custom card, v0.1.0 */
const MAP_SOURCES = Object.freeze({
  countries: 'https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_0_map_units.geojson',
});
const TERRITORY_CODES = Object.freeze({NJM:'SJ'});
const COUNTRY_NAME_OVERRIDES = Object.freeze({AU:'Australia'});
const EUROPE_VIEW_WEST = -25;
const EUROPE_VIEW_EAST = 40;
const CONTINENTS = Object.freeze(['Africa','Antarctica','Asia','Europe','North America','Oceania','South America']);
const DEFAULT_DATA = Object.freeze({travellers:{},groups:{}});
const GEOGRAPHY_URL = '/beenthere/geography.json?v=1';
const REGIONAL_MAPS = Object.freeze(Object.fromEntries(
  ['AU','CA','DE','GB','US'].map(code=>[code,`/beenthere/maps/${code}.geojson?v=1`])
));
class VisitedCountriesCard extends HTMLElement {
  connectedCallback() {
    this._connected = true;
    this._toggleSettingsHandler ||= () => this.toggleSettings();
    this.addEventListener('beenthere-toggle-settings', this._toggleSettingsHandler);
    this.syncConnection();
  }
  disconnectedCallback() {
    this._connected = false;
    this.removeEventListener('beenthere-toggle-settings', this._toggleSettingsHandler);
    this.stopConnection();
  }
  setConfig(config) {
    if (!config || typeof config !== 'object') throw new Error('Card configuration must be an object.');
    this.config = config;
    this.selection = this.selection || '';
    this.continent = this.continent || 'World';
    this.expandedCountries ||= new Set();
    this.focusedCountry ||= null;
    this.render();
  }
  set hass(hass) {
    const couldEdit=this.canEdit();
    this._hass = hass;
    if(!this.canEdit())this.settingsOpen=false;
    this.syncConnection();
    if (!this._started && hass) {
      this._started = true;
      this.load().catch(error => this.setError(error));
    }
    if(couldEdit!==this.canEdit())this.render();
  }
  stopConnection() {
    this._connectionEpoch = (this._connectionEpoch || 0) + 1;
    this._dataVersion = (this._dataVersion || 0) + 1;
    if (this._connection) {
      this._connection.removeEventListener('ready', this._readyHandler);
      this._connection.removeEventListener('disconnected', this._disconnectedHandler);
    }
    if (this._unsubscribeUpdates) this.releaseSubscription(this._unsubscribeUpdates);
    this._unsubscribeUpdates = null;
    this._subscriptionAttempt = null;
    this._refreshPromise = null;
    this._refreshAgain = false;
    this._connection = null;
  }
  releaseSubscription(unsubscribe) {
    Promise.resolve().then(unsubscribe).catch(error => console.error('BeenThere unsubscribe failed:', error));
  }
  syncConnection() {
    const connection = this._hass?.connection;
    if (!this._connected || connection === this._connection) return;
    this.stopConnection();
    if (!connection) return;
    this._connection = connection;
    this._connectionReady = connection.connected !== false;
    this._readyHandler = () => {
      this._connectionReady = true;
      this._dataVersion++;
      this.subscribeUpdates();
      this.refreshData();
    };
    this._disconnectedHandler = () => {
      this._connectionReady = false;
      this._dataVersion++;
    };
    connection.addEventListener('ready', this._readyHandler);
    connection.addEventListener('disconnected', this._disconnectedHandler);
    this.subscribeUpdates();
  }
  async subscribeUpdates() {
    if (!this._connectionReady || this._unsubscribeUpdates || this._subscriptionAttempt) return;
    const connection = this._connection;
    if (!connection) return;
    const epoch = this._connectionEpoch;
    const attempt = {};
    this._subscriptionAttempt = attempt;
    const current = () => this._connected && this._connection === connection && this._connectionEpoch === epoch;
    try {
      const unsubscribe = await connection.subscribeEvents(() => {
        if (current()) this.refreshData();
      }, 'beenthere_updated');
      if (current()) {
        this._unsubscribeUpdates = unsubscribe;
        this.refreshData();
      } else {
        this.releaseSubscription(unsubscribe);
      }
    } catch (error) {
      if (current()) this.setError(error);
    } finally {
      if (this._subscriptionAttempt === attempt) this._subscriptionAttempt = null;
    }
  }
  canEdit() { return this._hass?.user?.is_admin===true; }
  getCardSize() { return 8; }
  getGridOptions() {
    return {columns: 12, min_columns: 12, max_columns: 12, rows: 8};
  }
  toggleSettings() {
    if(!this.canEdit())return;
    this.settingsOpen=!this.settingsOpen;
    this.render();
    this.dispatchEvent(new CustomEvent('beenthere-settings-changed', {
      bubbles: true,
      composed: true,
    }));
  }
  async load() {
    if (this._loadPromise) return this._loadPromise;
    this._loadPromise = this.loadData();
    try {
      return await this._loadPromise;
    } finally {
      this._loadPromise = null;
    }
  }
  refreshData() {
    if (!this._hass) return Promise.resolve();
    if (this._pendingChanges || (this._connection && !this._connectionReady) || this._refreshPromise) {
      this._refreshAgain = true;
      return this._refreshPromise || Promise.resolve();
    }
    this._refreshAgain = false;
    const connection = this._hass.connection;
    const epoch = this._connectionEpoch || 0;
    const version = this._dataVersion || 0;
    const current = () => epoch === (this._connectionEpoch || 0)
      && version === (this._dataVersion || 0) && connection === this._hass?.connection;
    const task = Promise.resolve().then(async () => {
      try {
        const data = await this._hass.callWS({type:'beenthere/get'});
        if (current() && !this._pendingChanges) {
          this.data = data;
          this.render();
        }
      } catch (error) {
        if (current()) this.setError(error);
      } finally {
        if (this._refreshPromise === task) {
          this._refreshPromise = null;
          if (this._refreshAgain && this._connected && !this._pendingChanges) this.refreshData();
        }
      }
    });
    this._refreshPromise = task;
    return task;
  }
  async loadData() {
    try {
      await this.refreshData();
      await Promise.all([this.loadCatalogue(), this.loadWorld()].map(task =>
        task.catch(error => this.setError(error))));
    } catch(e) {
      this.setError(e);
    }
  }
  async loadCatalogue() {
    if (this.catalogue) return;
    const catalogue = await this.fetchGeoJson(GEOGRAPHY_URL, 'Geographic catalogue');
    if (catalogue.version !== 1 || !Array.isArray(catalogue.subdivision_countries)) {
      throw new Error('Unsupported geographic catalogue');
    }
    this.catalogue = catalogue;
    this.render();
  }
  async loadWorld() {
    if (this.geo) return;
    const world = await this.fetchGeoJson(MAP_SOURCES.countries, 'country');
    this.geo = this.prepareMap(world);
    this.render();
  }
  async fetchGeoJson(url, label) {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`${label} map request failed (${response.status})`);
    const contentType=response.headers?.get('content-type')||'';
    if(contentType.includes('text/html')) {
      throw new Error(`${label} map returned HTML instead of JSON (${url}). Check the bundled map file and restart Home Assistant to register its URL.`);
    }
    try {
      return await response.json();
    } catch(error) {
      throw new Error(`${label} map returned invalid JSON (${url}): ${error.message}`);
    }
  }
  setError(error, render=true) {
    console.error('BeenThere error:', error);
    this.error = typeof error?.message==='string' ? error.message : String(error);
    if(render)this.render();
  }
  scheduleRender() {
    if(this._renderScheduled)return;
    this._renderScheduled=true;
    const render=()=>{
      this._renderScheduled=false;
      this.render();
    };
    if(typeof requestAnimationFrame==='function')requestAnimationFrame(render);
    else render();
  }
  async change(action, args={}) {
    if(!this.canEdit()) {
      this.setError(new Error('Administrator access is required to change BeenThere data.'));
      return;
    }
    if(this._pendingChanges)return;
    const version = this._dataVersion = (this._dataVersion || 0) + 1;
    const epoch = this._connectionEpoch || 0;
    this._pendingChanges = (this._pendingChanges || 0) + 1;
    let succeeded = false;
    try {
      
      const { id, ...rest } = args;
      const data = await this._hass.callWS({
        type: 'beenthere/change',
        action,
        ...rest,
        ...(id !== undefined ? { target_id: id } : {})
      });

      if (version === this._dataVersion && epoch === (this._connectionEpoch || 0)) {
        this.data = data;
        this.error = '';
        succeeded = true;
      }
    } catch(e) {
      if (epoch === (this._connectionEpoch || 0)) this.setError(e, false);
    } finally {
      this._pendingChanges--;
      this.scheduleRender();
      if (!this._pendingChanges && this._refreshAgain && this._connected && this._connection) {
        const refresh=()=>this.refreshData();
        if(typeof requestAnimationFrame==='function')requestAnimationFrame(refresh);
        else refresh();
      }
    }
    return succeeded;
  }
  chosen() {
    const t=this.data?.travellers||{}, g=this.data?.groups||{};
    if (this.selection.startsWith('t:') && t[this.selection.slice(2)]) return {type:'traveller',id:this.selection.slice(2),...t[this.selection.slice(2)]};
    if (this.selection.startsWith('g:') && g[this.selection.slice(2)]) return {type:'group',id:this.selection.slice(2),...g[this.selection.slice(2)]};
    return {type:'all',name:'Everyone',members:Object.keys(t)};
  }
  selectedMembers(view) { return view.type==='traveller'?[view.id]:view.members; }
  resetRegionExpansion() {
    this.expandedCountries.clear();
  }
  visited(view) {
    return new Set(this.selectedMembers(view).flatMap(id=>this.data?.travellers?.[id]?.countries||[]));
  }
  parentCountry(code) {
    if(typeof code!=='string')return null;
    const index=code.indexOf('-');
    const parent=index===-1?null:code.slice(0,index);
    return parent&&this.catalogue?.subdivisions?.[parent]?.[code]?parent:null;
  }
  effectiveCountries(view) {
    const codes=new Set();
    const countries=new Set(Object.values(this.catalogue?.countries||{}).flatMap(group=>Object.keys(group)));
    for(const code of this.visited(view)) {
      const parent=this.parentCountry(code);
      if(parent)codes.add(parent);
      else if(countries.has(code))codes.add(code);
    }
    return codes;
  }
  visitedCountries(view=this.chosen()) {
    const names=this.countryNames(this.geo?.features||[]);
    return [...this.effectiveCountries(view)].map(code=>({
      code,name:names.get(code)||this.countryNameFromCatalogue(code),
    })).sort((first,second)=>first.name.localeCompare(second.name));
  }
  visitors(code, view=this.chosen()) {
    return this.selectedMembers(view).filter(id=>{
      const explicit=this.data?.travellers?.[id]?.countries||[];
      return explicit.includes(code)||(!code.includes('-')&&explicit.some(location=>this.parentCountry(location)===code));
    }).map(id=>this.data.travellers[id]);
  }
  visitStatus(code, view=this.chosen(), explicit=this.visited(view), effective=this.effectiveCountries(view)) {
    if(explicit.has(code))return 'Visited';
    if(effective.has(code))return 'Visited via subdivisions';
    return 'Not visited';
  }
  confirmCountryVisitRemoval(code, view=this.chosen()) {
    if(this.parentCountry(code)||!this.visited(view).has(code))return true;
    const country=this.visitedCountries(view).find(item=>item.code===code);
    return !!country&&confirm(`Remove the country-only visit to ${country.name}? Regional visits, if any, will be preserved.`);
  }
  async setLocationVisit(code, visited, focusAttribute='data-location') {
    const view=this.chosen();
    if(view.type!=='traveller'||!this.canEdit()||this._pendingChanges)return;
    if(!visited&&!this.confirmCountryVisitRemoval(code,view))return;
    await this.change('set_visit',{id:view.id,location:code,visited});
    const target=this.querySelector(`[${focusAttribute}="${code}"]`)
      ||this.querySelector(`.country[data-country-shape="${code}"]`);
    target?.focus({preventScroll:true});
  }
  async removeCountryVisit(code) {
    const view=this.chosen();
    if(view.type!=='traveller'||!this.canEdit()||this._pendingChanges||!this.visited(view).has(code))return;
    if(!this.confirmCountryVisitRemoval(code,view))return;
    this.selectedLocation=code;
    this.focusedCountry=code;
    await this.change('set_visit',{id:view.id,location:code,visited:false});
    if(this.error)return;
    if(typeof requestAnimationFrame==='function') {
      requestAnimationFrame(()=>this.querySelector('.country.selected')?.focus({preventScroll:true}));
    }
  }
  regionsFor(code) {
    const subdivisions=this.catalogue?.subdivisions?.[code];
    return subdivisions ? Object.entries(subdivisions).map(([id,name])=>({code:id,name}))
      .sort((first,second)=>first.name.localeCompare(second.name)) : [];
  }
  subdivisionTrackingEnabled(code) {
    return (this.data?.map_settings?.subdivision_countries||['GB']).includes(code);
  }
  countryNameFromCatalogue(code) {
    for(const countries of Object.values(this.catalogue?.countries||{})) {
      if(countries[code]) return countries[code];
    }
    return code;
  }
  async ensureRegionalMap(code) {
    if(!this.subdivisionTrackingEnabled(code)||!this.regionsFor(code).length)return;
    if(!REGIONAL_MAPS[code]||this.regionalMaps?.[code])return;
    if(this._regionMapErrors?.[code])return;
    this._regionLoads ||= {};
    if(this._regionLoads[code])return this._regionLoads[code];
    const task=(async()=>{
      try {
        const map=await this.fetchGeoJson(REGIONAL_MAPS[code], `${code} subdivision`);
        const expected=new Set(this.regionsFor(code).map(region=>region.code));
        if(map.type!=='FeatureCollection'||!Array.isArray(map.features)
          ||map.features.length!==expected.size
          ||map.features.some(feature=>!expected.delete(feature.properties?.id)
            ||!['Polygon','MultiPolygon'].includes(feature.geometry?.type))) {
          throw new Error('Regional map does not match the geographic catalogue.');
        }
        this.regionalMaps ||= {};
        this.regionalMaps[code]=map;
        if(this.error===this._regionMapErrors?.[code])this.error='';
      } catch(error) {
        this._regionMapErrors ||= {};
        this._regionMapErrors[code]=error.message;
        this.setError(error);
      } finally {
        delete this._regionLoads[code];
        this.render();
      }
    })();
    this._regionLoads[code]=task;
    return task;
  }
  regionalPolygons(feature) {
    const geometry=feature.geometry;
    return geometry?.type==='Polygon'?[geometry.coordinates]:geometry?.type==='MultiPolygon'?geometry.coordinates:[];
  }
  regionalPath(feature) {
    return this.regionalPolygons(feature).map(polygon=>polygon.map(ring=>ring.map((point,index)=>{
      const [x,y]=this.xy(point);
      return `${index?'L':'M'}${x.toFixed(5)},${y.toFixed(5)}`;
    }).join(' ')+'Z').join(' ')).join(' ');
  }
  selectRegion(code, toggle=false) {
    const parent=this.parentCountry(code);
    if(!parent||!this.subdivisionTrackingEnabled(parent)
      ||!this.regionsFor(parent).some(region=>region.code===code))return;
    this.selectedLocation=code;
    this.focusedCountry=parent;
    this.expandedCountries.add(parent);
    if(toggle&&this.chosen().type==='traveller'&&this.canEdit()) {
      this.scheduleRender();
      this.setLocationVisit(code,!this.visited(this.chosen()).has(code),'data-location');
    } else {
      this.scheduleRender();
    }
    if(typeof requestAnimationFrame==='function') {
      requestAnimationFrame(()=>this.querySelector(`[data-location-select="${code}"]`)?.scrollIntoView({block:'nearest'}));
    }
  }
  selectLocation(code) {
    const parent=this.parentCountry(code);
    const country=parent||code;
    if(this.continent!=='World'
      &&!this.visibleFeatures().some(feature=>this.iso(feature)===country)) {
      this.continent='World';
      this.resetRegionExpansion();
    }
    if(parent) {
      if(!this.subdivisionTrackingEnabled(parent))return;
      this.expandedCountries.add(parent);
      this.focusedCountry=parent;
    } else {
      this.focusedCountry=code;
    }
    this.selectedLocation=code;
    this.scheduleRender();
    if(typeof requestAnimationFrame==='function') {
      requestAnimationFrame(()=>this.querySelector(`[data-location-select="${code}"]`)?.scrollIntoView({block:'nearest'}));
    }
  }
  prepareMap(units) {
    const features=units.features.map(feature=>{
      const properties=feature.properties||{};
      const unit=properties.GU_A3;
      const code=TERRITORY_CODES[unit]||properties.ISO_A2_EH;
      const continent=properties.CONTINENT==='Seven seas (open ocean)'?properties.REGION_UN:properties.CONTINENT;
      return {...feature,properties:{...properties,ISO_A2_EH:code,CONTINENT:continent}};
    });
    const counts=new Map();
    for(const feature of features){const code=this.iso(feature);counts.set(code,(counts.get(code)||0)+1);}
    for(const feature of features){
      const properties=feature.properties;
      const code=this.iso(feature);
      properties.ADMIN=code==='SJ'?'Svalbard and Jan Mayen':counts.get(code)===1?(properties.GEOUNIT||properties.ADMIN):properties.ADMIN;
    }
    return {...units,features};
  }
  iso(feature) {
    const p=feature.properties||{};
    const value=p.ISO_A2_EH||p.ISO_A2||p.iso_a2||p.ISO_A2_UN||'';
    return /^[A-Z]{2}$/.test(value)?value:null;
  }
  name(feature) {const p=feature.properties||{};return p.ADMIN||p.NAME||p.name||'Unknown';}
  flagCode(code) {
    return code.toLowerCase();
  }
  countryNames(features) {
    const names=new Map();
    for(const feature of features) {
      const code=this.iso(feature);
      if(code&&!names.has(code))names.set(code,COUNTRY_NAME_OVERRIDES[code]||this.name(feature));
    }
    return names;
  }
  visibleFeatures() {return (this.geo?.features||[]).filter(feature=>this.continent==='World'||feature.properties?.CONTINENT===this.continent);}
  xy(pt) {
    const centers={'Africa':20,'Antarctica':0,'Asia':100,'Europe':20,'North America':-100,'Oceania':160,'South America':-60};
    const center=centers[this.continent];
    const longitude=center===undefined?pt[0]:((pt[0]-center+540)%360)-180+center;
    return [(longitude+180)*2.4,(90-pt[1])*2.4];
  }
  mapBounds(features) {
    if(this.continent==='World'||!features.length)return '0 0 864 432';
    let minX=Infinity,minY=Infinity,maxX=-Infinity,maxY=-Infinity;
    for(const feature of features) {
      const geometry=feature.geometry;
      const polygons=geometry?.type==='Polygon'?[geometry.coordinates]:geometry?.type==='MultiPolygon'?geometry.coordinates:[];
      for(const polygon of polygons)for(const ring of polygon)for(const point of ring) {
        const [x,y]=this.xy(point);
        minX=Math.min(minX,x);minY=Math.min(minY,y);maxX=Math.max(maxX,x);maxY=Math.max(maxY,y);
      }
    }
    if(!Number.isFinite(minX))return '0 0 864 432';
    if(this.continent==='Europe') {
      const west=this.xy([EUROPE_VIEW_WEST,0])[0]-12;
      const east=this.xy([EUROPE_VIEW_EAST,0])[0]+12;
      return `${west} ${minY-12} ${east-west} ${maxY-minY+24}`;
    }
    return `${minX-12} ${minY-12} ${maxX-minX+24} ${maxY-minY+24}`;
  }
  path(rings) {return rings.map(r=>r.map((p,i)=>{const [x,y]=this.xy(p);return `${i?'L':'M'}${x.toFixed(2)},${y.toFixed(2)}`;}).join(' ')+'Z').join(' ');}
  countryPath(f) {
    const g=f.geometry;if(!g)return '';
    if(g.type==='Polygon')return this.path(g.coordinates);
    if(g.type==='MultiPolygon')return g.coordinates.map(poly=>this.path(poly)).join(' ');
    return '';
  }
  esc(s) {return String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
  mapDetailOptions() {
    if (!this.catalogue) return [];
    const names = new Map(Object.values(this.catalogue.countries).flatMap(countries => Object.entries(countries)));
    return this.catalogue.subdivision_countries
      .filter(code => names.has(code))
      .map(code => ({code, name:names.get(code)}))
      .sort((first, second) => first.name.localeCompare(second.name));
  }
  async setMapDetail(country, enabled) {
    const previousError=this._regionMapErrors?.[country];
    if(previousError) {
      delete this._regionMapErrors[country];
      if(this.error===previousError)this.error='';
    }
    await this.change('set_map_detail', {country, enabled});
    if (!this._connected || !this.canEdit()) return;
    const root = this.getRootNode();
    if (!root.activeElement || root.activeElement === document.body) {
      this.querySelector(`[data-map-detail="${country}"]`)?.focus();
    }
  }
  mapDetailSettings() {
    if (!this.canEdit()) return '';
    const enabled = new Set(this.data?.map_settings?.subdivision_countries || ['GB']);
    const disabled = !this.data || this._pendingChanges;
    const options = this.mapDetailOptions();
    return `<section class="settings-card regional-card" aria-labelledby="map-detail-title"><h2 id="map-detail-title">Regional detail</h2>
      <p class="manager-help">Choose which countries show individual regions or states. Your existing visits are always preserved when regional detail is turned off.</p>
      <div class="map-detail-options">${options.length ? options.map(country =>
        `<label class="map-detail-option"><img src="https://flagcdn.com/w40/${this.flagCode(country.code)}.png" alt="" width="24" height="18" loading="lazy"/><span>${this.esc(country.name)}</span><input type="checkbox" data-map-detail="${this.esc(country.code)}" aria-label="Show regional detail for ${this.esc(country.name)}" ${enabled.has(country.code)?'checked ':''}${disabled?'disabled':''}/></label>`
      ).join('') : '<p class="muted" role="status">Loading map detail settings...</p>'}</div></section>`;
  }
  openDialog(kind, id=null) {
    if(!this.canEdit()||this._pendingChanges)return;
    const active=this.getRootNode().activeElement;
    const focusAttribute=['data-rename','data-delete','data-edit-group','data-delete-group']
      .find(attribute=>active?.hasAttribute(attribute));
    this.dialogReturnFocus=active?.id
      ?{id:active.id}
      :focusAttribute
        ?{attribute:focusAttribute,value:active.getAttribute(focusAttribute)}
        :null;
    const traveller=this.data?.travellers?.[id];
    const group=this.data?.groups?.[id];
    if((kind==='traveller-edit'&&!traveller)||(kind==='group-edit'&&!group))return;
    this.dialog={
      kind,
      id,
      name:traveller?.name||group?.name||'',
      members:group?[...group.members]:[],
      error:'',
    };
    this.error='';
    this.render();
    this.querySelector('#settings-name')?.focus();
  }
  closeDialog() {
    const returnFocus=this.dialogReturnFocus;
    this.dialogReturnFocus=null;
    this.dialog=null;
    this.render();
    const restore=()=>{
      const target=returnFocus?.id
        ?this.querySelector(`#${returnFocus.id}`)
        :returnFocus
          ?[...this.querySelectorAll(`[${returnFocus.attribute}]`)]
            .find(element=>element.getAttribute(returnFocus.attribute)===returnFocus.value)
          :null;
      target?.focus();
    };
    if(typeof requestAnimationFrame==='function')requestAnimationFrame(restore);
    else restore();
  }
  dialogMarkup(data) {
    if(!this.dialog)return '';
    const {kind,id,name,members,error}=this.dialog;
    const isTraveller=kind.includes('traveller');
    const deleting=kind.startsWith('delete-');
    const isGroup=kind.includes('group');
    const record=isTraveller?data.travellers[id]:data.groups[id];
    const title=deleting
      ?`Delete ${isTraveller?'traveller':'group'}?`
      :`${kind.endsWith('edit')?'Edit':'Add'} ${isTraveller?'traveller':'group'}`;
    if(deleting&&!record)return '';
    const memberOptions=isGroup&&!deleting
      ?Object.entries(data.travellers).map(([travellerId,traveller])=>
        `<label class="member-option"><input type="checkbox" name="group-member" value="${this.esc(travellerId)}" ${members.includes(travellerId)?'checked ':''}/><span>${this.esc(traveller.name)}</span></label>`
      ).join('')
      : '';
    const content=deleting
      ?`<p>${isTraveller
        ?`“${this.esc(record.name)}” and their recorded visits will be deleted. They will also be removed from any groups.`
        :`“${this.esc(record.name)}” will be removed. Individual travellers and their visit histories will remain unchanged.`}</p>${error?`<p class="dialog-error" role="alert">${this.esc(error)}</p>`:''}`
      :`<label class="form-field" for="settings-name">${isTraveller?'Traveller name':'Group name'}
          <input id="settings-name" name="name" type="text" maxlength="80" required autofocus value="${this.esc(name)}"/>
        </label>${isGroup?`<fieldset class="member-list"><legend>Travellers</legend>${memberOptions||'<p class="muted">Add travellers before choosing group members.</p>'}</fieldset>`:''}
        ${error?`<p class="dialog-error" role="alert">${this.esc(error)}</p>`:''}`;
    return `<dialog class="settings-dialog" aria-labelledby="settings-dialog-title">
      <form class="dialog-content" ${deleting?'':'id="settings-form"'}>
        <h2 id="settings-dialog-title">${title}</h2>${content}
        <div class="dialog-actions"><button type="button" class="dialog-cancel">Cancel</button>
        ${deleting?'<button type="button" class="dialog-delete">Delete</button>':'<button type="submit" class="dialog-save">Save</button>'}</div>
      </form>
    </dialog>`;
  }
  async saveDialog(event) {
    event.preventDefault();
    if(!this.dialog||this._pendingChanges)return;
    const {kind,id}=this.dialog;
    const isTraveller=kind.startsWith('traveller-');
    const name=this.querySelector('#settings-name')?.value.trim()||'';
    this.dialog.name=name;
    this.dialog.members=[...this.querySelectorAll('input[name="group-member"]:checked')]
      .map(input=>input.value);
    const collection=isTraveller?(this.data?.travellers||{}):(this.data?.groups||{});
    const duplicate=Object.entries(collection).some(([recordId,record])=>
      recordId!==id&&record.name.trim().toLocaleLowerCase()===name.toLocaleLowerCase());
    if(!name||name.length>80) {
      this.dialog.error='Enter a name between 1 and 80 characters.';
      this.render();
      this.querySelector('#settings-name')?.focus();
      return;
    }
    if(duplicate) {
      this.dialog.error=`A ${isTraveller?'traveller':'group'} with that name already exists.`;
      this.render();
      this.querySelector('#settings-name')?.focus();
      return;
    }
    const members=this.dialog.members;
    const action=isTraveller
      ?(kind==='traveller-edit'?'rename_traveller':'add_traveller')
      :(kind==='group-edit'?'update_group':'add_group');
    const result=await this.change(action,{
      ...(id?{id}:{}),
      name,
      ...(!isTraveller?{members}:{}),
    });
    if(result) {
      this.dialog=null;
      this.scheduleRender();
    } else if(this.dialog) {
      this.dialog.error=this.error||'Unable to save changes.';
      this.scheduleRender();
    }
  }
  async confirmDelete() {
    if(!this.dialog||!this.dialog.kind.startsWith('delete-')||this._pendingChanges)return;
    const {kind,id}=this.dialog;
    const result=await this.change(kind==='delete-traveller'?'delete_traveller':'delete_group',{id});
    if(result) {
      this.dialog=null;
      this.scheduleRender();
    } else if(this.dialog) {
      this.dialog.error=this.error||'Unable to delete this item.';
      this.scheduleRender();
    }
  }
  viewOptions() {
    const data=this.data||DEFAULT_DATA;
    return [`<option value="">Everyone</option>`,...Object.entries(data.travellers).map(([id,p])=>`<option value="t:${this.esc(id)}" ${this.selection===`t:${id}`?'selected':''}>${this.esc(p.name)}</option>`),...Object.entries(data.groups).map(([id,g])=>`<option value="g:${this.esc(id)}" ${this.selection===`g:${id}`?'selected':''}>${this.esc(g.name)} (group)</option>`)].join('');
  }
  render() {
    if(!this.config)return;
    const focusedDetail = this.querySelector('[data-map-detail]:focus')?.dataset.mapDetail;
    const focusedLocation = this.querySelector('[data-location]:focus')?.dataset.location;
    const data=this.data||{travellers:{},groups:{}};
    const view=this.chosen();
    const visited=this.visited(view);
    const derivedCountries=this.effectiveCountries(view);
    const features=this.visibleFeatures();
    const bounds=this.mapBounds(features);
    const countryCodes=new Set(features.map(feature=>this.iso(feature)).filter(Boolean));
    const countryNames=this.countryNames(features);
    const resultFeature=this.searchResult?features.find(feature=>this.iso(feature)===this.searchResult):null;
    const searchOptions=[...countryCodes].map(code=>countryNames.get(code)).sort((first,second)=>first.localeCompare(second)).map(name=>`<option value="${this.esc(name)}"></option>`).join('');
    const enabledRegionalCodes=(this.catalogue?.subdivision_countries||[])
      .filter(code=>this.subdivisionTrackingEnabled(code)&&this.regionsFor(code).length
        &&(this.continent==='World'||countryCodes.has(code)));
    const menuCountries=this.visitedCountries(view);
    enabledRegionalCodes.forEach(code=>this.ensureRegionalMap(code));
    const regionalShapes=enabledRegionalCodes.flatMap(parent=>this.regionalMaps?.[parent]?.features||[])
      .filter(feature=>this.parentCountry(feature.properties?.id));
    const continentOptions=['World',...CONTINENTS].map(continent=>`<option value="${continent}" ${this.continent===continent?'selected':''}>${continent}</option>`).join('');
    const options=this.viewOptions();
    const selectedLocation=this.selectedLocation;
    const shapes=features.map((f,i)=>{
      const code=this.iso(f),active=code&&derivedCountries.has(code);
      const regional=this.subdivisionTrackingEnabled(code)&&this.regionsFor(code).length>0;
      return `<path data-idx="${i}" data-country-shape="${this.esc(code||'')}" class="country ${active?'active ':''}${regional?'regional-detail ':''}${this.selectedLocation===code?'selected':''}" d="${this.countryPath(f)}" tabindex="0" role="button" aria-label="${this.esc(this.name(f))}" aria-pressed="${!!active}" aria-current="${this.selectedLocation===code}"><title>${this.esc(this.name(f))}: ${this.esc(this.visitStatus(code,view,visited,derivedCountries))}</title></path>`;
    }).join('');
    const subdivisionShapes=regionalShapes.map(feature=>{
      const code=feature.properties.id;
      const parent=this.parentCountry(code);
      const region=this.regionsFor(parent).find(item=>item.code===code);
      return region?`<path class="region-shape ${visited.has(code)?'active ':''}${this.selectedLocation===code?'selected':''}" data-location="${this.esc(code)}" d="${this.regionalPath(feature)}" fill-rule="evenodd" vector-effect="non-scaling-stroke" tabindex="0" role="button" aria-label="${this.esc(region.name)}" aria-pressed="${visited.has(code)}" aria-current="${this.selectedLocation===code}"><title>${this.esc(region.name)}: ${visited.has(code)?'Visited':'Not visited'}</title></path>`:'';
    }).join('');
    this.innerHTML=`<ha-card><style>
      .vc{background:radial-gradient(ellipse at 75% 0%,#193b57 0%,#0d182b 43%,#090f1c 100%);color:#e6f8ff;border-radius:18px;padding:20px;font-family:inherit;overflow:hidden}
      select,input,button{border:1px solid #37536a;border-radius:10px;background:#14283a;color:#e8faff;padding:9px;font:inherit}button{cursor:pointer}button:hover{border-color:#45dce5}select{max-width:100%}
      .stats{display:flex;gap:12px;margin:14px 0}.stat{border:1px solid #234a61;background:#112b3f;border-radius:12px;padding:10px 16px}.stat strong{font-size:24px;color:#63f3e5}.stat small{display:block;color:#91afc4}
      .map{position:relative;box-sizing:border-box;border:1px solid #1d425a;border-radius:14px;background:radial-gradient(ellipse at center,#16364e,#0a1a2d);overflow:hidden;height:13vh;height:71dvh}.map svg{position:absolute;inset:0;display:block;width:100%;height:100%}.country{fill:#244159;stroke:#395C74;stroke-width:.6;cursor:pointer;transition:fill .15s}.country:hover{fill:#6c85b1}.country.active{fill:#23d9cf;stroke:#b4fffb;stroke-width:.65;filter:drop-shadow(0 0 2px #2de4d9)}
      .muted{color:#9bb4c8;font-size:13px}.error{color:#ffb6ae;margin:10px 0}.hidden{display:none!important}
      .settings-view{box-sizing:border-box;min-height:calc(100dvh - 56px);padding:4px 0 20px}.settings-view>h2{margin:0 0 16px;font-size:22px;color:#e6f8ff}.settings-grid{display:grid;grid-template-columns:minmax(0,3fr) minmax(0,3fr) minmax(0,4fr);align-items:start;gap:16px}.settings-card{box-sizing:border-box;display:flex;flex-direction:column;gap:12px;min-width:0;padding:16px;border:1px solid #234a61;border-radius:11px;background:#112b3f}.settings-card h2{margin:0;font-size:16px;font-weight:700;color:#b6e8f1}.manager-help{margin:-6px 0 0;color:#9bb4c8;font-size:12px;line-height:1.45}.manager-list{display:flex;flex-direction:column;gap:0}.chip{display:grid;grid-template-columns:minmax(0,1fr) 36px 36px;align-items:center;gap:6px;padding:5px 0;border-bottom:1px solid #27445c;font-size:14px}.chip-name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0}.chip-name small{display:block;color:#9bb4c8;font-size:12px;margin-top:3px}.settings-card button{box-sizing:border-box;display:inline-flex;align-items:center;justify-content:center;gap:8px;min-height:40px;padding:0 10px;border-radius:7px;font-size:13px;letter-spacing:0}.settings-card button ha-icon{--mdc-icon-size:18px;flex-shrink:0}.chip button{width:40px;height:40px;padding:0;background:transparent}.chip button:hover{background:#203a51}.chip button[data-delete]:hover,.chip button[data-delete-group]:hover{color:#ffb6ae;border-color:#ffb6ae}.settings-card .add-button{width:100%;background:#203a51}.settings-card button:focus-visible,.map-detail-option:focus-within,.settings-dialog button:focus-visible{outline:2px solid #63f3e5;outline-offset:2px}.settings-card .regional-card{grid-column:auto}
      .manager-empty{display:flex;align-items:flex-start;gap:8px;margin:0;padding:6px 0;color:#9bb4c8;font-size:13px;line-height:1.45}.manager-empty ha-icon{--mdc-icon-size:18px;flex-shrink:0}
      .map-detail-options{display:flex;flex-direction:column;gap:0}.map-detail-option{display:grid;grid-template-columns:24px minmax(0,1fr) 24px;align-items:center;gap:10px;min-height:44px;border-bottom:1px solid #27445c;font-size:14px;cursor:pointer}.map-detail-option img{display:block;width:24px;height:18px;object-fit:contain}.map-detail-option span{min-width:0;overflow-wrap:anywhere}.map-detail-option input{box-sizing:border-box;width:20px;height:20px;margin:0;padding:0;accent-color:#63f3e5;cursor:pointer}.map-detail-option input:focus-visible{outline:2px solid #63f3e5;outline-offset:3px}.map-detail-option input:disabled{cursor:default}
      .settings-dialog{width:min(440px,calc(100vw - 32px));max-width:none;max-height:calc(100dvh - 32px);overflow:auto;padding:0;border:1px solid #37536a;border-radius:12px;background:#112b3f;color:#e6f8ff;box-shadow:0 18px 60px #0009}.settings-dialog::backdrop{background:#050b14bb}.dialog-content{display:flex;flex-direction:column;gap:16px;padding:20px}.dialog-content h2{margin:0;font-size:19px}.dialog-content p{margin:0;color:#c6d9e5;line-height:1.5}.form-field{display:flex;flex-direction:column;gap:8px;font-size:14px}.form-field input{box-sizing:border-box;width:100%;min-height:44px}.member-list{display:flex;flex-direction:column;gap:2px;max-height:240px;overflow:auto;margin:0;padding:10px;border:1px solid #37536a;border-radius:8px}.member-list legend{padding:0 6px;color:#b6e8f1;font-size:14px}.member-option{display:flex;align-items:center;gap:10px;min-height:40px;cursor:pointer}.member-option input{width:20px;height:20px;margin:0;accent-color:#63f3e5}.member-option span{overflow-wrap:anywhere}.dialog-error{color:#ffb6ae!important}.dialog-actions{display:flex;justify-content:flex-end;gap:10px}.dialog-actions button{min-width:92px;min-height:44px}.dialog-actions .dialog-delete{border-color:#a74343;background:#652b34;color:#fff}.dialog-actions .dialog-delete:hover{border-color:#ff8b8b;background:#7c303a}
      .map-layout{display:grid;grid-template-columns:minmax(0,1fr) 270px;gap:16px;margin-top:14px;align-items:stretch}.map-column{min-width:0;min-height:0}.region-panel{box-sizing:border-box;contain:size;display:flex;flex-direction:column;gap:12px;min-width:0;min-height:0;overflow:hidden}.region-panel select{box-sizing:border-box;width:100%;border-radius:6px;background:#14283a}.region-panel .stats{flex-direction:column}.region-panel .stat{border:0;border-radius:0;background:transparent;padding:8px 0}.map-layout .map{min-width:0}
      .region-panel .sidebar-heading{display:block;flex:none;margin:0 0 8px;font-size:13px;font-weight:400;line-height:normal;color:#b6e8f1}.region-panel select+.sidebar-heading{margin-top:16px}
      .visited-country-divider{flex:none;height:1px;margin:0 0 11px;border:0;background:#27445c}.visited-country-section>.visited-country-list,.visited-country-section>.visited-country-empty{margin-top:0}.visited-country-list>.visited-country-item:first-child{border-top:0}
      .map-column{min-width:0}.search-row{display:grid;grid-template-columns:1fr 2fr;gap:12px;margin-bottom:12px;align-items:start;min-height:66px}.country-search{align-self:start;display:grid;grid-template-columns:minmax(0,1fr) auto;align-content:start;gap:8px;min-width:0}.country-search input{box-sizing:border-box;min-width:0;width:100%;height:38px;font-size:13px;border-radius:6px}.country-search button{align-self:start;display:inline-flex;align-items:center;justify-content:center;gap:6px;height:38px;min-height:38px;border-radius:6px;font-size:13px}.country-search ha-icon{--mdc-icon-size:18px}.country-search-status{grid-column:1 / -1;margin:0;overflow-wrap:anywhere}.country-search-status:empty{display:none}.search-result{align-self:start;box-sizing:border-box;display:grid;grid-template-columns:32px minmax(0,1fr) auto;gap:10px;align-items:center;min-width:0;min-height:66px;padding:10px 12px;border:1px solid #31516a;border-radius:8px;background:#112b3f}.search-result img{display:block;width:32px;height:22px;object-fit:contain}.search-result-info{min-width:0}.search-result-name{display:block;font-size:14px;font-weight:650;overflow-wrap:anywhere}.search-result-status{display:block;margin-top:3px;color:#9bb4c8;font-size:12px}.search-result button{white-space:nowrap;font-size:12px;padding:7px 9px}.search-result-empty{display:flex;align-items:center;color:#9bb4c8;font-size:13px}
      .visited-country-section{box-sizing:border-box;display:flex;flex:1;flex-direction:column;min-height:0;overflow:hidden;border:1px solid #31516a;border-radius:11px;background:#112b3f;padding:12px}.visited-country-section .region-title{flex:none}.visited-country-list{flex:1;min-height:0;overflow-y:auto;overscroll-behavior:contain;scrollbar-width:thin;scrollbar-color:#37536a #112b3f;list-style:none;margin:12px 0 0;padding:0}.visited-country-list::-webkit-scrollbar{width:6px}.visited-country-list::-webkit-scrollbar-track{background:#112b3f}.visited-country-list::-webkit-scrollbar-thumb{border-radius:3px;background:#37536a}.visited-country-item{border-top:1px solid #27445c;font-size:13px;line-height:1.4;transition:background-color .15s ease}.visited-country-item:hover{background:#142d40}.visited-country-item.selected,.visited-subdivision-list li.selected{background:#18374b}.visited-country-row{display:flex;align-items:center;gap:4px;min-width:0;min-height:44px}.visited-country-list .country-link{display:flex;flex:1;align-items:center;gap:8px;min-width:0;min-height:44px;padding:2px 0;border:0;border-radius:0;background:transparent;color:inherit;text-align:left;font-size:inherit;transition:color .15s ease}.visited-country-list .country-link:hover{color:#63f3e5}.visited-country-list .country-link img{display:block;flex:0 0 24px;width:24px;height:18px;object-fit:contain}.visited-country-list .country-name{min-width:0;overflow-wrap:anywhere}.country-actions{display:flex;align-items:center;gap:2px}.region-link,.remove-country-visit{display:inline-flex;flex:0 0 44px;align-items:center;justify-content:center;width:44px;height:44px;padding:0;border:0;border-radius:0;background:transparent;color:#9bb4c8;transition:background-color .15s ease,color .15s ease,border-color .15s ease}.region-link:hover{background:#203a51;color:#63f3e5}.region-link ha-icon{--mdc-icon-size:20px}.remove-country-visit{font-size:20px;line-height:1}.remove-country-visit:hover{background:#203a51;color:#ffb6ae}.remove-country-visit:focus-visible,.region-link:focus-visible,.visited-country-list .country-link:focus-visible,.visited-subdivision-list .location-select:focus-visible{outline:2px solid #63f3e5;outline-offset:-2px}.remove-country-visit:disabled{cursor:default;opacity:.5}.visited-subdivision-list{list-style:none;margin:0 0 6px;padding:0 0 0 32px}.visited-subdivision-list li{min-height:36px;border-top:1px solid #203c52;font-size:12px}.visited-subdivision-list li.selected{background:#18374b}.location-select{display:block;width:100%;min-height:36px;padding:4px 0;border:0;border-radius:0;background:transparent;color:inherit;text-align:left;font:inherit;transition:color .15s ease}.location-select:hover{color:#63f3e5}.visited-country-empty{flex:1;margin:10px 0 0}
      .map .country,.map .region-shape{outline:none}.map .country:focus-visible{stroke:#fff;stroke-width:2}
      .region-view{margin-top:14px}.region-view #region-back{display:inline-flex;align-items:center;gap:6px;margin-bottom:12px;background:transparent}.region-list{list-style:none;margin:12px 0 0;padding:0}.region-row{display:block;padding:6px 0;border-top:1px solid #27445c;font-size:14px}.region-row label{display:flex;align-items:center;gap:10px;cursor:pointer}.region-row input{width:20px;height:20px;margin:0;padding:0;accent-color:#63f3e5}.region-row input:disabled{cursor:default}
      .country.regional-detail.active{fill:#244159;stroke:#395C74;stroke-dasharray:none;filter:none}.country.regional-detail:focus-visible{stroke:#fff;stroke-width:2}.country.selected,.country.selected:hover{stroke:#fff;stroke-width:1.6;filter:none}.region-shape{fill:#244159;fill-opacity:1;stroke:#395C74;stroke-width:.7;cursor:pointer}.region-shape.active{fill:#23d9cf;fill-opacity:1;stroke:#b4fffb}.region-shape.selected,.region-shape:focus-visible{stroke:#fff;stroke-width:1.6;outline:none}
      .region-view>progress{display:block;width:100%;height:6px;margin-top:12px;accent-color:#63f3e5}
      .region-summary{box-sizing:border-box;min-width:0;margin-top:16px;padding:12px;border:1px solid #31516a;border-radius:8px;background:#112b3f}.region-title{margin:0;font-size:15px;font-weight:650;line-height:1.4;letter-spacing:0;overflow-wrap:anywhere}.progress{margin:8px 0 0;color:#9bb4c8;font-size:13px;line-height:1.5;overflow-wrap:anywhere}.progress strong{color:#63f3e5;font-weight:650;font-variant-numeric:tabular-nums}.region-summary progress{display:block;width:100%;height:6px;margin-top:12px;border:0;border-radius:3px;overflow:hidden;appearance:none;background:#27445c;accent-color:#63f3e5}.region-summary progress::-webkit-progress-bar{background:#27445c}.region-summary progress::-webkit-progress-value{background:#63f3e5}.region-summary progress::-moz-progress-bar{background:#63f3e5}
      @media(max-width:1050px){.settings-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.regional-card{grid-column:1/-1}}
      @media(max-width:620px){.settings-grid{grid-template-columns:minmax(0,1fr)}.regional-card{grid-column:auto}.settings-view{padding-top:0}.dialog-content{padding:16px}}
      @media(max-width:520px){.map-layout{grid-template-columns:minmax(0,1fr) 130px;gap:10px}.region-panel{padding-left:10px}.region-panel select{padding:8px 4px;font-size:12px}.search-row{grid-template-columns:1fr}.country-search{width:100%}.map{height:45vh;height:45dvh}.vc{padding:12px}.region-summary{padding:10px}}
    </style><div class="vc">
    <div id="vc-settings" class="settings-view${this.settingsOpen?'':' hidden'}" role="region" aria-labelledby="vc-settings-title"><h2 id="vc-settings-title">Settings</h2><div class="settings-grid">
      <section class="settings-card"><h2>Travellers</h2><p class="manager-help">Track the countries each person has visited on their own map.</p><div id="travellers" class="manager-list">${Object.entries(data.travellers).map(([id,p])=>`<div class="chip"><span class="chip-name" title="${this.esc(p.name)}">${this.esc(p.name)}</span><button type="button" data-rename="${this.esc(id)}" title="Edit traveller" aria-label="Edit ${this.esc(p.name)}"><ha-icon icon="mdi:pencil-outline" aria-hidden="true"></ha-icon></button><button type="button" data-delete="${this.esc(id)}" title="Delete traveller" aria-label="Delete ${this.esc(p.name)}"><ha-icon icon="mdi:trash-can-outline" aria-hidden="true"></ha-icon></button></div>`).join('')||'<p class="manager-empty">No travellers yet. Add your first traveller to get started.</p>'}</div><button type="button" id="add-traveller" class="add-button"><ha-icon icon="mdi:plus" aria-hidden="true"></ha-icon>Add traveller</button></section>
      <section class="settings-card"><h2>Groups</h2><p class="manager-help">Combine travellers' existing visits on a shared, read-only map. No separate tracking needed.</p><div class="manager-list">${Object.entries(data.groups).map(([id,g])=>`<div class="chip"><span class="chip-name" title="${this.esc(g.name)}">${this.esc(g.name)}<small>${g.members.length} ${g.members.length===1?'traveller':'travellers'}</small></span><button type="button" data-edit-group="${this.esc(id)}" title="Edit group" aria-label="Edit ${this.esc(g.name)}"><ha-icon icon="mdi:pencil-outline" aria-hidden="true"></ha-icon></button><button type="button" data-delete-group="${this.esc(id)}" title="Delete group" aria-label="Delete ${this.esc(g.name)}"><ha-icon icon="mdi:trash-can-outline" aria-hidden="true"></ha-icon></button></div>`).join('')||'<p class="manager-empty"><ha-icon icon="mdi:account-group-outline" aria-hidden="true"></ha-icon><span>No groups yet. Create a group to explore your travels together.</span></p>'}</div><button type="button" id="add-group" class="add-button"><ha-icon icon="mdi:plus" aria-hidden="true"></ha-icon>Add group</button></section>
      ${this.mapDetailSettings()}</div>${this.error?`<div class="error" role="alert">${this.esc(this.error)}</div>`:''}</div>
    ${this.dialogMarkup(data)}
    <div id="map-view" class="map-view${this.settingsOpen?' hidden':''}">
    <div class="search-row">
    <form id="country-search" class="country-search" aria-label="Find country"><input id="search" type="search" list="country-suggestions" placeholder="Country name" aria-label="Country name" required ${this.geo?'':'disabled'}/><datalist id="country-suggestions">${searchOptions}</datalist><button id="find" type="submit" ${this.geo?'':'disabled'}><ha-icon icon="mdi:magnify" aria-hidden="true"></ha-icon>Find</button><p id="country-search-status" class="muted country-search-status" role="status">${this.esc(this.searchStatus||'')}</p></form>
    ${resultFeature?`<div class="search-result" aria-live="polite"><img src="https://flagcdn.com/w40/${this.flagCode(this.iso(resultFeature))}.png" alt="" width="32" height="22"/><div class="search-result-info"><span class="search-result-name">${this.esc(this.name(resultFeature))}</span><span class="search-result-status">${this.esc(this.visitStatus(this.iso(resultFeature),view))}</span></div>${view.type==='traveller'?`<button id="toggle-search-result" type="button" ${this._pendingChanges?'disabled':''}>${visited.has(this.iso(resultFeature))?'Remove country visit':'Add country visit'}</button>`:''}</div>`:'<div class="search-result search-result-empty" aria-live="polite">Search for a country to see its details.</div>'}
    </div><div class="map-layout"><div class="map-column"><div class="map">${this.geo?`<svg viewBox="${bounds}" preserveAspectRatio="xMidYMid meet" xmlns="http://www.w3.org/2000/svg" role="group" aria-label="Interactive ${this.esc(this.continent)} map">${shapes}${subdivisionShapes}</svg>`:'<p class="muted" style="padding:20px">Loading map… Internet access is required to load country outlines.</p>'}</div></div>
    <aside class="region-panel" aria-label="Visited countries sidebar"><label class="sidebar-heading" for="continent">Continent</label><select id="continent">${continentOptions}</select><label class="sidebar-heading" for="view">Travellers / Groups</label><select id="view">${options}</select>
    <section class="visited-country-section" aria-label="Visited countries"><h2 class="sidebar-heading">Visited countries <span class="country-count">(${menuCountries.length})</span></h2><hr class="visited-country-divider" aria-hidden="true"/>${menuCountries.length?`<ul class="visited-country-list" aria-label="Visited countries">${menuCountries.map(country=>{const regions=this.regionsFor(country.code);const visitedRegions=regions.filter(region=>visited.has(region.code));const expandable=this.subdivisionTrackingEnabled(country.code)&&visitedRegions.length>0;const expanded=expandable&&this.expandedCountries.has(country.code);const canRemove=this.canEdit()&&view.type==='traveller'&&visited.has(country.code);return `<li class="visited-country-item${this.selectedLocation===country.code||this.parentCountry(this.selectedLocation)===country.code?' selected':''}" data-country-item="${this.esc(country.code)}"><div class="visited-country-row"><button type="button" data-location-select="${this.esc(country.code)}" class="country-link" aria-current="${this.selectedLocation===country.code}"><img src="https://flagcdn.com/w40/${this.flagCode(country.code)}.png" alt="" width="24" height="18" loading="lazy"/><span class="country-name">${this.esc(country.name)}</span></button><span class="country-actions">${expandable?`<button type="button" data-region-toggle="${this.esc(country.code)}" class="region-link" aria-expanded="${expanded}" aria-label="${expanded?'Collapse':'Expand'} visited regions in ${this.esc(country.name)}"><ha-icon icon="mdi:chevron-${expanded?'down':'right'}" aria-hidden="true"></ha-icon></button>`:''}${canRemove?`<button type="button" data-remove-country="${this.esc(country.code)}" class="remove-country-visit" aria-label="Remove country-only visit to ${this.esc(country.name)}" title="Remove country-only visit"${this._pendingChanges?' disabled':''}>&times;</button>`:''}</span></div>${expanded?`<ul id="visited-${this.esc(country.code)}" class="visited-subdivision-list" aria-label="Visited regions in ${this.esc(country.name)}">${visitedRegions.map(region=>`<li${this.selectedLocation===region.code?' class="selected"':''}><button type="button" class="location-select" data-location-select="${this.esc(region.code)}" aria-current="${this.selectedLocation===region.code}">${this.esc(region.name)}</button></li>`).join('')}</ul>`:''}</li>`;}).join('')}</ul>`:`<p class="muted visited-country-empty" role="status">${this.data?'No countries visited yet.':'Loading countries...'}</p>`}</section>
    </aside></div>
    ${this.error?`<div class="error" role="alert">${this.esc(this.error)}</div>`:''}
    </div></div></ha-card>`;
    const viewSelect=this.querySelector('#view');
    if(viewSelect)viewSelect.onchange=e=>{this.selection=e.target.value;this.resetRegionExpansion();this.scheduleRender();};
    const continentSelect=this.querySelector('#continent');
    if(continentSelect)continentSelect.onchange=e=>{this.continent=e.target.value;this.resetRegionExpansion();this.scheduleRender();};
    const searchForm=this.querySelector('#country-search');
    if(searchForm)searchForm.onsubmit=e=>{
      e.preventDefault();
      const query=this.querySelector('#search').value.trim().toLowerCase();
      if(!query)return;
      const searchable=features.filter(feature=>this.iso(feature));
      const feature=searchable.find(feature=>this.name(feature).toLowerCase()===query)||searchable.find(feature=>this.name(feature).toLowerCase().includes(query));
      this.searchStatus=feature?'':'Country not found in this region.';
      this.searchResult=feature?this.iso(feature):null;
      this.scheduleRender();
    };
    this.querySelector('#toggle-search-result')?.addEventListener('click',()=>{
      if(resultFeature)this.setLocationVisit(this.iso(resultFeature),!visited.has(this.iso(resultFeature)));
    });
    this.querySelectorAll('[data-region-toggle]').forEach(button=>button.onclick=()=>{
      const code=button.dataset.regionToggle;
      if(this.expandedCountries.has(code))this.expandedCountries.delete(code);else this.expandedCountries.add(code);
      this.scheduleRender();
    });
    this.querySelectorAll('[data-location-select]').forEach(button=>button.onclick=()=>{
      this.selectLocation(button.dataset.locationSelect);
    });
    this.querySelectorAll('[data-remove-country]').forEach(button=>button.onclick=()=>{
      this.removeCountryVisit(button.dataset.removeCountry);
    });
    this.querySelectorAll('[data-location]').forEach(el=>{
      el.onclick=()=>this.selectRegion(el.dataset.location,true);
      el.onkeydown=event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();this.selectRegion(el.dataset.location,true);}};
    });
    this.querySelectorAll('.country[data-idx]').forEach(el=>{
      el.onclick=()=>this.clickCountry(features[Number(el.dataset.idx)]);
      el.onkeydown=event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();el.onclick();}};
    });
    this.querySelector('#add-traveller').onclick=()=>this.openDialog('traveller-add');
    this.querySelectorAll('[data-rename]').forEach(el=>el.onclick=()=>this.openDialog('traveller-edit',el.dataset.rename));
    this.querySelectorAll('[data-delete]').forEach(el=>el.onclick=()=>this.openDialog('delete-traveller',el.dataset.delete));
    this.querySelector('#add-group').onclick=()=>this.openDialog('group-add');
    this.querySelectorAll('[data-edit-group]').forEach(el=>el.onclick=()=>this.openDialog('group-edit',el.dataset.editGroup));
    this.querySelectorAll('[data-delete-group]').forEach(el=>el.onclick=()=>this.openDialog('delete-group',el.dataset.deleteGroup));
    this.querySelectorAll('.settings-card button').forEach(button=>{button.disabled=!this.canEdit()||!!this._pendingChanges;});
    const settingsDialog=this.querySelector('.settings-dialog');
    if(settingsDialog) {
      settingsDialog.showModal();
      settingsDialog.addEventListener('cancel',event=>{
        event.preventDefault();
        this.closeDialog();
      });
      this.querySelector('.dialog-cancel').onclick=()=>this.closeDialog();
      this.querySelector('.dialog-delete')?.addEventListener('click',()=>this.confirmDelete());
      this.querySelector('#settings-form')?.addEventListener('submit',event=>this.saveDialog(event));
      const nameInput=this.querySelector('#settings-name');
      if(nameInput)nameInput.oninput=()=>{if(this.dialog)this.dialog.name=nameInput.value;};
      this.querySelectorAll('input[name="group-member"]').forEach(input=>{
        input.onchange=()=>{
          if(!this.dialog)return;
          this.dialog.members=[...this.querySelectorAll('input[name="group-member"]:checked')]
            .map(member=>member.value);
        };
      });
    }
    this.querySelectorAll('[data-map-detail]').forEach(input=>{
      input.onchange = event => this.setMapDetail(input.dataset.mapDetail, event.target.checked);
    });
    this.querySelector('#vc-settings').classList.toggle('hidden',!this.canEdit()||!this.settingsOpen);
    const toggle=this.querySelector('#toggle-search-result');
    if(toggle){toggle.hidden=!this.canEdit();toggle.disabled=!this.canEdit()||!!this._pendingChanges;}
    if (focusedDetail && !this._pendingChanges) this.querySelector(`[data-map-detail="${focusedDetail}"]`)?.focus();
    if (focusedLocation) this.querySelector(`[data-location="${focusedLocation}"]`)?.focus({preventScroll:true});
  }
  clickCountry(feature) {
    const code=this.iso(feature),view=this.chosen();
    if(!code)return;
    this.searchResult=code;
    this.selectedLocation=code;
    this.focusedCountry=code;
    if(view.type==='traveller'&&this.canEdit()
      &&!(this.subdivisionTrackingEnabled(code)&&this.regionsFor(code).length)) {
      if(this.effectiveCountries(view).has(code)&&!this.visited(view).has(code)) {
        this.error=`${this.name(feature)} has hidden region visits. Enable subdivision tracking to remove them.`;
        this.scheduleRender();
        return;
      }
      this.scheduleRender();
      this.setLocationVisit(code,!this.visited(view).has(code));
      return;
    }
    this.scheduleRender();
    if(typeof requestAnimationFrame==='function') {
      requestAnimationFrame(()=>this.querySelector(`[data-location-select="${code}"]`)?.scrollIntoView({block:'nearest'}));
    }
  }
  editGroup(id) {
    if(!this.canEdit())return;
    const old=id?this.data.groups[id]:null;
    const name=prompt('Group name',old?.name||'');if(!name?.trim())return;
    const entries=Object.entries(this.data.travellers);
    if(!entries.length){alert('Add travellers first.');return;}
    const names=entries.map(([key,p])=>`${p.name} [${key.slice(0,6)}]`).join(', ');
    const current=old?old.members.map(m=>this.data.travellers[m]?.name).filter(Boolean).join(', '):'';
    const response=prompt(`Enter traveller names separated by commas. Available: ${names}`,current);
    if(response===null)return;
    const requested=response.split(',').map(x=>x.trim()).filter(Boolean);
    const members=[];
    for(const n of requested){const found=entries.find(([key,p])=>p.name.toLowerCase()===n.toLowerCase());if(!found){alert(`Unknown traveller: ${n}`);return;}members.push(found[0]);}
    this.change(id?'update_group':'add_group',{...(id?{id}:{}),name,members});
  }
}
if (!customElements.get('beenthere-card')) {
  customElements.define('beenthere-card', VisitedCountriesCard);
}
