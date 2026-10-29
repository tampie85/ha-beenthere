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
class VisitedCountriesCard extends HTMLElement {
  connectedCallback() {
    this.addEventListener('beenthere-toggle-settings', () => this.toggleSettings());
  }
  setConfig(config) {
    if (!config || typeof config !== 'object') throw new Error('Card configuration must be an object.');
    this.config = config;
    this.selection = this.selection || '';
    this.continent = this.continent || 'World';
    this.render();
  }
  set hass(hass) {
    this._hass = hass;
    if (!this._started && hass) {
      this._started = true;
      this.load().catch(error => this.setError(error));
    }
  }
  getCardSize() { return 8; }
  getGridOptions() {
    return {columns: 12, min_columns: 12, max_columns: 12, rows: 8};
  }
  toggleSettings() {
    this.settingsOpen=!this.settingsOpen;
    this.render();
  }
  async load() {
    if (this._loadPromise) return this._loadPromise;
    this._loadPromise = this.loadData();
    return this._loadPromise;
  }
  async loadData() {
    try {
      this.data = await this._hass.callWS({type:'beenthere/get'});
      this.render();
      if (!this.geo) {
        const world=await this.fetchGeoJson(MAP_SOURCES.countries,'country');
        this.geo = this.prepareMap(world);
        this.render();
      }
    } catch(e) {
      this.setError(e);
    }
  }
  async fetchGeoJson(url, label) {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`${label} map request failed (${response.status})`);
    return response.json();
  }
  setError(error) {
    console.error('BeenThere error:', error);
    this.error = error instanceof Error ? error.message : String(error);
    this.render();
  }
  async change(action, args={}) {
    try {
      
      const { id, ...rest } = args;
      this.data = await this._hass.callWS({
        type: 'beenthere/change',
        action,
        ...rest,
        ...(id !== undefined ? { target_id: id } : {})
      });

      this.error = '';
      this.render();
    } catch(e) {
      this.setError(e);
    }
  }
  chosen() {
    const t=this.data?.travellers||{}, g=this.data?.groups||{};
    if (this.selection.startsWith('t:') && t[this.selection.slice(2)]) return {type:'traveller',id:this.selection.slice(2),...t[this.selection.slice(2)]};
    if (this.selection.startsWith('g:') && g[this.selection.slice(2)]) return {type:'group',id:this.selection.slice(2),...g[this.selection.slice(2)]};
    return {type:'all',name:'Everyone',members:Object.keys(t)};
  }
  selectedMembers(view) { return view.type==='traveller'?[view.id]:view.members; }
  visited(view) {
    const members=this.selectedMembers(view);
    const countries=members.map(id=>new Set(this.data?.travellers?.[id]?.countries||[]));
    const codes=new Set(countries[0]||[]);
    for(const code of codes) {
      if(!countries.every(visited=>visited.has(code)))codes.delete(code);
    }
    return codes;
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
  render() {
    if(!this.config)return;
    const data=this.data||{travellers:{},groups:{}};
    const view=this.chosen();
    const visited=this.visited(view);
    const features=this.visibleFeatures();
    const bounds=this.mapBounds(features);
    const countryCodes=new Set(features.map(feature=>this.iso(feature)).filter(Boolean));
    const visibleVisited=new Set([...countryCodes].filter(code=>visited.has(code)));
    const countryNames=this.countryNames(features);
    const resultFeature=this.searchResult?features.find(feature=>this.iso(feature)===this.searchResult):null;
    const searchOptions=[...countryCodes].map(code=>countryNames.get(code)).sort((first,second)=>first.localeCompare(second)).map(name=>`<option value="${this.esc(name)}"></option>`).join('');
    const visitedCountries=[...visibleVisited].map(code=>({code,name:countryNames.get(code)})).sort((first,second)=>first.name.localeCompare(second.name));
    const percentage=countryCodes.size?Math.round(visibleVisited.size/countryCodes.size*100):0;
    const continentOptions=['World',...CONTINENTS].map(continent=>`<option value="${continent}" ${this.continent===continent?'selected':''}>${continent}</option>`).join('');
    const options=[`<option value="">Everyone</option>`,...Object.entries(data.travellers).map(([id,p])=>`<option value="t:${id}" ${this.selection===`t:${id}`?'selected':''}>${this.esc(p.name)}</option>`),...Object.entries(data.groups).map(([id,g])=>`<option value="g:${id}" ${this.selection===`g:${id}`?'selected':''}>${this.esc(g.name)} (group)</option>`)].join('');
    const shapes=features.map((f,i)=>{const code=this.iso(f);const active=code&&visited.has(code);return `<path data-idx="${i}" class="country ${active?'active':''}" d="${this.countryPath(f)}"><title>${this.esc(this.name(f))}</title></path>`;}).join('');
    this.innerHTML=`<ha-card><style>
      .vc{background:radial-gradient(ellipse at 75% 0%,#193b57 0%,#0d182b 43%,#090f1c 100%);color:#e6f8ff;border-radius:18px;padding:20px;font-family:inherit;overflow:hidden}
      select,input,button{border:1px solid #37536a;border-radius:10px;background:#14283a;color:#e8faff;padding:9px;font:inherit}button{cursor:pointer}button:hover{border-color:#45dce5}select{max-width:100%}
      .stats{display:flex;gap:12px;margin:14px 0}.stat{border:1px solid #234a61;background:#112b3f;border-radius:12px;padding:10px 16px}.stat strong{font-size:24px;color:#63f3e5}.stat small{display:block;color:#91afc4}
      .map{position:relative;box-sizing:border-box;border:1px solid #1d425a;border-radius:14px;background:radial-gradient(ellipse at center,#16364e,#0a1a2d);overflow:hidden;height:13vh;height:71dvh}.map svg{position:absolute;inset:0;display:block;width:100%;height:100%}.country{fill:#244159;stroke:#4e7790;stroke-width:.6;cursor:pointer;transition:fill .15s}.country:hover{fill:#6c85b1}.country.active{fill:#23d9cf;stroke:#b4fffb;stroke-width:.65;filter:drop-shadow(0 0 2px #2de4d9)}
      .muted{color:#9bb4c8;font-size:13px}.error{color:#ffb6ae;margin:10px 0}.details{margin-top:12px;padding:12px;border:1px solid #31516a;border-radius:12px;background:#11283c}.details strong{color:#7ff8e9}.hidden{display:none}
      .manager{margin-top:16px;border:1px solid #234a61;background:#112b3f;border-radius:8px;padding:16px}.manager-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,240px),1fr));gap:24px}.manager section{display:flex;flex-direction:column;gap:12px;min-width:0}.manager h3{margin:0;font-size:15px;font-weight:650;color:#b6e8f1;letter-spacing:0}.manager-help{margin:-6px 0 0;color:#9bb4c8;font-size:12px;line-height:1.45}.manager-list{display:flex;flex-direction:column;gap:6px;flex:1}.manager-list:empty::before{content:attr(data-empty);color:#9bb4c8;font-size:13px;padding:10px 0}.chip{display:grid;grid-template-columns:minmax(0,1fr) 36px 36px;align-items:center;gap:6px;padding:6px 0;border-bottom:1px solid #27445c;font-size:14px}.chip-name{overflow-wrap:anywhere;min-width:0}.chip-name small{display:block;color:#9bb4c8;font-size:12px;margin-top:3px}.manager button{box-sizing:border-box;display:inline-flex;align-items:center;justify-content:center;gap:8px;height:36px;padding:0 10px;border-radius:6px;font-size:13px;letter-spacing:0}.manager button ha-icon{--mdc-icon-size:18px;flex-shrink:0}.chip button{width:36px;padding:0;background:transparent}.chip button:hover{background:#203a51}.chip button[data-delete]:hover,.chip button[data-delete-group]:hover{color:#ffb6ae;border-color:#ffb6ae}.manager .add-button{width:100%;background:#203a51}.manager button:focus-visible,.settings-toggle:focus-visible{outline:2px solid #63f3e5;outline-offset:2px}
      .manager h2{margin:0 0 16px;font-size:18px;font-weight:700;letter-spacing:0;overflow-wrap:anywhere}
      .map-layout{display:grid;grid-template-columns:minmax(0,1fr) 270px;gap:16px;margin-top:14px;align-items:start}.region-panel{min-width:0;border-left:1px solid #31516a;padding-left:16px}.region-panel label{display:block;font-size:13px;color:#b6e8f1;margin-bottom:8px}.region-panel select{box-sizing:border-box;width:100%}.region-panel .stats{flex-direction:column}.region-panel .stat{border:0;border-radius:0;background:transparent;padding:8px 0}.map-layout .map{min-width:0}
      .region-panel select+label{margin-top:16px}
      .map-column{min-width:0}.search-row{display:grid;grid-template-columns:1fr 2fr;gap:12px;margin-bottom:12px;align-items:start;min-height:66px}.country-search{align-self:start;display:grid;grid-template-columns:minmax(0,1fr) auto;align-content:start;gap:8px;min-width:0}.country-search input{box-sizing:border-box;min-width:0;width:100%;height:38px;font-size:13px;border-radius:6px}.country-search button{align-self:start;display:inline-flex;align-items:center;justify-content:center;gap:6px;height:38px;min-height:38px;border-radius:6px;font-size:13px}.country-search ha-icon{--mdc-icon-size:18px}.country-search-status{grid-column:1 / -1;margin:0;overflow-wrap:anywhere}.country-search-status:empty{display:none}.search-result{align-self:start;box-sizing:border-box;display:grid;grid-template-columns:32px minmax(0,1fr) auto;gap:10px;align-items:center;min-width:0;min-height:66px;padding:10px 12px;border:1px solid #31516a;border-radius:8px;background:#112b3f}.search-result img{display:block;width:32px;height:22px;object-fit:contain}.search-result-info{min-width:0}.search-result-name{display:block;font-size:14px;font-weight:650;overflow-wrap:anywhere}.search-result-status{display:block;margin-top:3px;color:#9bb4c8;font-size:12px}.search-result button{white-space:nowrap;font-size:12px;padding:7px 9px}.search-result-empty{display:flex;align-items:center;color:#9bb4c8;font-size:13px}
      .visited-country-list{list-style:none;margin:12px 0 0;padding:0;max-height:320px;max-height:min(320px,40dvh);overflow-y:auto;scrollbar-width:thin}.visited-country-list li{display:grid;grid-template-columns:24px minmax(0,1fr);gap:8px;align-items:center;min-height:36px;padding:6px 0;border-top:1px solid #27445c;font-size:13px;line-height:1.4}.visited-country-list img{display:block;width:24px;height:18px;object-fit:contain}.visited-country-list span{min-width:0;overflow-wrap:anywhere}.visited-country-empty{margin:10px 0 0}
      .region-summary{box-sizing:border-box;min-width:0;margin-top:16px;padding:12px;border:1px solid #31516a;border-radius:8px;background:#112b3f}.region-title{margin:0;font-size:15px;font-weight:650;line-height:1.4;letter-spacing:0;overflow-wrap:anywhere}.progress{margin:8px 0 0;color:#9bb4c8;font-size:13px;line-height:1.5;overflow-wrap:anywhere}.progress strong{color:#63f3e5;font-weight:650;font-variant-numeric:tabular-nums}.region-summary progress{display:block;width:100%;height:6px;margin-top:12px;border:0;border-radius:3px;overflow:hidden;appearance:none;background:#27445c;accent-color:#63f3e5}.region-summary progress::-webkit-progress-bar{background:#27445c}.region-summary progress::-webkit-progress-value{background:#63f3e5}.region-summary progress::-moz-progress-bar{background:#63f3e5}
      @media(max-width:520px){.map-layout{grid-template-columns:minmax(0,1fr) 130px;gap:10px}.region-panel{padding-left:10px}.region-panel select{padding:8px 4px;font-size:12px}.search-row{grid-template-columns:1fr}.country-search{width:100%}.map{height:45vh;height:45dvh}.vc{padding:12px}.region-summary{padding:10px}}
    </style><div class="vc">
    <div id="vc-settings" class="manager${this.settingsOpen?'':' hidden'}" role="region" aria-labelledby="vc-settings-title"><h2 id="vc-settings-title">Settings</h2><div class="manager-grid"><section><h3>Travellers</h3><p class="manager-help">Individual people whose visited countries you can track.</p><div id="travellers" class="manager-list" data-empty="No travellers yet">${Object.entries(data.travellers).map(([id,p])=>`<div class="chip"><span class="chip-name">${this.esc(p.name)}</span><button data-rename="${id}" title="Rename traveller" aria-label="Rename ${this.esc(p.name)}"><ha-icon icon="mdi:pencil-outline" aria-hidden="true"></ha-icon></button><button data-delete="${id}" title="Delete traveller" aria-label="Delete ${this.esc(p.name)}"><ha-icon icon="mdi:trash-can-outline" aria-hidden="true"></ha-icon></button></div>`).join('')}</div><button id="add-traveller" class="add-button"><ha-icon icon="mdi:plus" aria-hidden="true"></ha-icon>Add traveller</button></section>
    <section><h3>Groups</h3><p class="manager-help">Combine travellers to compare the countries everyone in the group has visited.</p><div class="manager-list" data-empty="No groups yet">${Object.entries(data.groups).map(([id,g])=>`<div class="chip"><span class="chip-name">${this.esc(g.name)}<small>${g.members.length} ${g.members.length===1?'traveller':'travellers'}</small></span><button data-edit-group="${id}" title="Edit group" aria-label="Edit ${this.esc(g.name)}"><ha-icon icon="mdi:pencil-outline" aria-hidden="true"></ha-icon></button><button data-delete-group="${id}" title="Delete group" aria-label="Delete ${this.esc(g.name)}"><ha-icon icon="mdi:trash-can-outline" aria-hidden="true"></ha-icon></button></div>`).join('')}</div><button id="add-group" class="add-button"><ha-icon icon="mdi:plus" aria-hidden="true"></ha-icon>Add group</button></section></div></div>
    <div class="map-layout"><div class="map-column"><div class="search-row"><form id="country-search" class="country-search" aria-label="Find country"><input id="search" type="search" list="country-suggestions" placeholder="Country name" aria-label="Country name" required ${this.geo?'':'disabled'}/><datalist id="country-suggestions">${searchOptions}</datalist><button id="find" type="submit" ${this.geo?'':'disabled'}><ha-icon icon="mdi:magnify" aria-hidden="true"></ha-icon>Find</button><p id="country-search-status" class="muted country-search-status" role="status"></p></form>${resultFeature?`<div class="search-result" aria-live="polite"><img src="https://flagcdn.com/w40/${this.flagCode(this.iso(resultFeature))}.png" alt="" width="32" height="22"/><div class="search-result-info"><span class="search-result-name">${this.esc(this.name(resultFeature))}</span><span class="search-result-status">${visited.has(this.iso(resultFeature))?'Visited':'Not visited'}</span></div>${view.type==='traveller'?`<button id="toggle-search-result" type="button">${visited.has(this.iso(resultFeature))?'Remove':'Add'}</button>`:''}</div>`:'<div class="search-result search-result-empty" aria-live="polite">Search for a country to see its details.</div>'}</div><div class="map">${this.geo?`<svg viewBox="${bounds}" preserveAspectRatio="xMidYMid meet" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="Interactive ${this.esc(this.continent)} map">${shapes}</svg>`:'<p class="muted" style="padding:20px">Loading map… Internet access is required to load country outlines.</p>'}</div></div>
    <aside class="region-panel" aria-label="Map filters"><label for="continent">Continent</label><select id="continent">${continentOptions}</select><label for="view">Travellers / Groups</label><select id="view">${options}</select><section class="region-summary" aria-label="Visited countries summary"><h2 class="region-title">${this.esc(this.continent)}</h2><p class="progress"><strong>${visibleVisited.size}</strong> out of <strong>${countryCodes.size}</strong> countries visited <strong>(${percentage}%)</strong></p><progress value="${percentage}" max="100" aria-label="${this.esc(this.continent)} countries visited">${percentage}%</progress></section>
    <section class="region-summary" aria-label="Visited country list"><h2 class="region-title">Visited</h2>${visitedCountries.length?`<ul class="visited-country-list" aria-label="Visited countries">${visitedCountries.map(country=>`<li><img src="https://flagcdn.com/w40/${country.code==='GB-NIR'?'gb':country.code.startsWith('PT-')?'pt':country.code.toLowerCase()}.png" alt="" title="${country.code==='GB-NIR'?'United Kingdom flag (Northern Ireland has no official flag)':this.esc(country.name)}" width="24" height="18" loading="lazy"/><span>${this.esc(country.name)}</span></li>`).join('')}</ul>`:`<p class="muted visited-country-empty">${this.geo?'No countries visited in this region.':'Loading countries...'}</p>`}</section>
    </aside></div>
    <div id="details" class="details hidden"></div>${this.error?`<div class="error">${this.esc(this.error)}</div>`:''}
    </div></ha-card>`;
    this.querySelector('#view').onchange=e=>{this.selection=e.target.value;this.render();};
    this.querySelector('#continent').onchange=e=>{this.continent=e.target.value;this.render();};
    this.querySelector('#country-search').onsubmit=e=>{
      e.preventDefault();
      const query=this.querySelector('#search').value.trim().toLowerCase();
      if(!query)return;
      const searchable=features.filter(feature=>this.iso(feature));
      const feature=searchable.find(feature=>this.name(feature).toLowerCase()===query)||searchable.find(feature=>this.name(feature).toLowerCase().includes(query));
      this.querySelector('#country-search-status').textContent=feature?'':'Country not found in this region.';
      this.searchResult=feature?this.iso(feature):null;
      this.render();
    };
    this.querySelector('#toggle-search-result')?.addEventListener('click',()=>{
      if(resultFeature&&view.type==='traveller')this.change('toggle_country',{id:view.id,country:this.iso(resultFeature)});
    });
    this.querySelectorAll('.country').forEach(el=>el.onclick=()=>this.clickCountry(features[Number(el.dataset.idx)]));
    this.querySelector('#add-traveller').onclick=()=>{const name=prompt('Traveller name');if(name?.trim())this.change('add_traveller',{name});};
    this.querySelectorAll('[data-rename]').forEach(el=>el.onclick=()=>{const id=el.dataset.rename;const name=prompt('Rename traveller',data.travellers[id].name);if(name?.trim())this.change('rename_traveller',{id,name});});
    this.querySelectorAll('[data-delete]').forEach(el=>el.onclick=()=>{const id=el.dataset.delete; if(confirm(`Delete ${data.travellers[id].name} and their visited-country history?`))this.change('delete_traveller',{id});});
    this.querySelector('#add-group').onclick=()=>this.editGroup();
    this.querySelectorAll('[data-edit-group]').forEach(el=>el.onclick=()=>this.editGroup(el.dataset.editGroup));
    this.querySelectorAll('[data-delete-group]').forEach(el=>el.onclick=()=>{const id=el.dataset.deleteGroup;if(confirm(`Delete group ${data.groups[id].name}? Travellers will be kept.`))this.change('delete_group',{id});});
  }
  showDetail(html) {const el=this.querySelector('#details');el.innerHTML=html;el.classList.remove('hidden');}
  clickCountry(feature) {
    const code=this.iso(feature),view=this.chosen();
    if(!code) {this.showDetail(`${this.esc(name)} cannot be edited because its country code is unavailable.`);return;}
    if(view.type==='traveller') {this.change('toggle_country',{id:view.id,country:code});return;}
    this.searchResult=code;
    this.render();
  }
  editGroup(id) {
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
