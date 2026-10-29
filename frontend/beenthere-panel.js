import './beenthere-card.js';

class VisitedCountriesPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({mode: 'open'});
    this.shadowRoot.innerHTML = `
      <style>
        :host{display:block;height:100%;overflow:auto;background:var(--primary-background-color);color:var(--primary-text-color)}
        header{display:flex;align-items:center;gap:8px;min-height:var(--header-height,56px);padding:0 16px 0 4px;box-sizing:border-box;background:var(--app-header-background-color);color:var(--app-header-text-color)}
        h1{margin:0;font-size:20px;font-weight:400;letter-spacing:0;overflow-wrap:anywhere}
        .settings-toggle{display:inline-flex;align-items:center;justify-content:center;width:36px;height:36px;margin-left:auto;padding:0;border:0;border-radius:50%;background:transparent;color:inherit;cursor:pointer}.settings-toggle:hover{background:var(--app-header-edit-background-color,rgba(255,255,255,.12))}.settings-toggle:focus-visible{outline:2px solid currentColor;outline-offset:2px}.settings-toggle ha-icon{--mdc-icon-size:22px}
        main{min-width:0}
        beenthere-card{display:block}
        beenthere-card ha-card{display:block;border:0;border-radius:0;box-shadow:none;background:transparent}
        beenthere-card .vc{border-radius:0;min-height:calc(100dvh - var(--header-height,56px));box-sizing:border-box}
      </style>
      <header><ha-menu-button></ha-menu-button><h1>BeenThere</h1><button class="settings-toggle" type="button" title="Settings" aria-label="Settings" aria-expanded="false"><ha-icon icon="mdi:cog" aria-hidden="true"></ha-icon></button></header>
      <main></main>
    `;
    this._menu = this.shadowRoot.querySelector('ha-menu-button');
    this._card = document.createElement('beenthere-card');
    this._card.setConfig({type: 'custom:beenthere-card'});
    this.shadowRoot.querySelector('main').append(this._card);
    this._settingsToggle = this.shadowRoot.querySelector('.settings-toggle');
    this._settingsToggle.onclick = () => {
      this._card.dispatchEvent(new CustomEvent('beenthere-toggle-settings'));
      this._settingsToggle.setAttribute('aria-expanded', String(!!this._card.settingsOpen));
    };
  }

  set hass(hass) {
    this._hass = hass;
    this._menu.hass = hass;
    this._card.hass = hass;
  }

  get hass() {
    return this._hass;
  }

  set narrow(narrow) {
    this._menu.narrow = narrow;
  }
}

if (!customElements.get('beenthere-panel')) {
  customElements.define('beenthere-panel', VisitedCountriesPanel);
}