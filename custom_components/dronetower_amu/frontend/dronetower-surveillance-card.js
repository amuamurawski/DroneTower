/**
 * DroneTower surveillance card — a compact list of registered drone flights near the
 * monitored point, with stat tiles. Reads the integration's binary_sensor (its
 * `drones`, `total_active_in_poland` attributes); no configuration needed.
 *
 * Inspired by the MIT-licensed Dectyr RX-5 surveillance card by Alexandre Thomas
 * (https://github.com/DECTYR/ha-integration).
 */

const PALETTE = { red: "#e5484d", orange: "#f5a623", blue: "#4c8dff", green: "#3ba55d", grey: "#8a8a8a" };
const STATUS_COLORS = { ACTIVE: PALETTE.red, OVERDUE: PALETTE.orange, CREATED: PALETTE.blue };
const STATUS_LABELS = { ACTIVE: "Aktywny", OVERDUE: "Po czasie", CREATED: "Zgłoszony" };

const esc = (s) =>
  String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// Entity attributes are untrusted input — numbers go through a type guard
// instead of straight into the HTML template.
const asNumber = (v) => (typeof v === "number" && Number.isFinite(v) ? v : null);

function distanceBadge(raw) {
  const m = asNumber(raw);
  if (m == null) return { color: PALETTE.grey, text: "—" };
  // Consistent formatting — km from 1000 m regardless of the color threshold.
  const text = m >= 1000 ? `${(m / 1000).toFixed(1)} km` : `${Math.round(m)} m`;
  if (m <= 500) return { color: PALETTE.red, text };
  if (m <= 2000) return { color: PALETTE.orange, text };
  return { color: PALETTE.green, text };
}

function fmtTime(iso, locale) {
  if (!iso) return "—";
  const d = new Date(iso);
  // Returns a raw string — escaping happens only at the insertion point.
  return Number.isNaN(d.getTime())
    ? String(iso)
    : d.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" });
}

// Static style rendered once into the shadow root; the dynamic connection-dot
// color is set inline in _render().
const CARD_STYLE = `
  .dt-head{display:flex;align-items:center;gap:8px;padding:12px 16px 4px;}
  .dt-head .dt-title{font-size:1.1rem;font-weight:500;flex:1;}
  .dt-dot{width:10px;height:10px;border-radius:50%;}
  .dt-count{font-size:.85rem;color:var(--secondary-text-color);}
  .dt-tiles{display:flex;gap:8px;padding:8px 16px;}
  .dt-tile{flex:1;background:var(--secondary-background-color);border-radius:12px;padding:10px;text-align:center;}
  .dt-tile-v{font-size:1.5rem;font-weight:600;}
  .dt-tile-l{font-size:.75rem;color:var(--secondary-text-color);}
  .dt-row{display:flex;align-items:center;gap:10px;padding:8px 16px;border-top:1px solid var(--divider-color);}
  .dt-status{width:8px;height:8px;border-radius:50%;flex:none;}
  .dt-main{flex:1;min-width:0;}
  .dt-name{font-weight:500;}
  .dt-sub{font-size:.8rem;color:var(--secondary-text-color);}
  .dt-badge{color:#fff;font-size:.75rem;font-weight:600;padding:2px 8px;border-radius:999px;flex:none;}
  .dt-empty{padding:16px;color:var(--secondary-text-color);}
  .dt-error{padding:16px;color:var(--error-color,#e5484d);}`;

class DroneTowerSurveillanceCard extends HTMLElement {
  constructor() {
    super();
    // Shadow DOM isolates styles and lets us render <style> exactly once.
    this.attachShadow({ mode: "open" });
    this.shadowRoot.innerHTML = `<style>${CARD_STYLE}</style><div id="root"></div>`;
    this._root = this.shadowRoot.getElementById("root");
  }

  setConfig(config) {
    if (config?.entity != null && typeof config.entity !== "string") {
      throw new Error("dronetower-surveillance-card: `entity` musi być identyfikatorem encji");
    }
    this._config = config || {};
    this._title = this._config.title || "Drony w okolicy";
    // A config change invalidates the signature — otherwise the card would not
    // refresh its title/entity until the drone data itself changed.
    this._sig = undefined;
    if (this._hass) this._update();
  }

  set hass(hass) {
    this._hass = hass;
    this._update();
  }

  _update() {
    const areas = this._collect();
    // Signature computed from the same data projection the render uses —
    // one selection logic, and start/end are now covered by change detection.
    const sig = JSON.stringify(areas);
    if (sig === this._sig) return;
    this._sig = sig;
    try {
      this._render(areas);
    } catch (err) {
      // Malformed data must not leave a dead card behind.
      const msg = err && err.message ? err.message : String(err);
      this._root.innerHTML = `<ha-card><div class="dt-error">Błąd renderowania karty: ${esc(msg)}</div></ha-card>`;
    }
  }

  /** Single source of truth: matching entities projected to render-relevant data. */
  _collect() {
    const hass = this._hass;
    if (!hass) return [];
    const wanted = this._config?.entity;
    // With an explicit `entity` we read one state instead of iterating the
    // whole hass.states dictionary on every state update.
    const entries = wanted
      ? (hass.states[wanted] ? [[wanted, hass.states[wanted]]] : [])
      : Object.entries(hass.states).filter(([id]) => id.startsWith("binary_sensor."));
    const areas = [];
    for (const [, st] of entries) {
      const a = st.attributes || {};
      if (a.monitored_latitude == null || !Array.isArray(a.drones)) continue;
      areas.push({
        drones: a.drones.filter((d) => d && typeof d === "object"),
        total: asNumber(a.total_active_in_poland),
        connected: Boolean(a.stream_connected),
      });
    }
    return areas;
  }

  getCardSize() {
    return 2 + Math.min(8, this._lastCount || 0);
  }

  _render(areas) {
    const locale = this._hass?.locale?.language || [];
    // Dedupe by id — the same flight within range of two monitored points
    // used to show up twice.
    const byId = new Map();
    for (const a of areas) for (const d of a.drones) byId.set(d.id ?? Symbol(), d);
    const drones = [...byId.values()].sort(
      (x, y) =>
        (asNumber(x.distance_to_area_m) ?? Number.POSITIVE_INFINITY) -
        (asNumber(y.distance_to_area_m) ?? Number.POSITIVE_INFINITY),
    );
    this._lastCount = drones.length;

    // A missing entity is not the same as no drones — show an explicit error
    // instead of a falsely reassuring empty state.
    if (this._config?.entity && !areas.length) {
      this._root.innerHTML = `<ha-card><div class="dt-error">Nie znaleziono encji ${esc(this._config.entity)} z danymi DroneTower.</div></ha-card>`;
      return;
    }

    // Total as the max across all entities, not an arbitrary first one.
    const totals = areas.map((a) => a.total).filter((t) => t != null);
    const total = totals.length ? Math.max(...totals) : null;
    const connected = areas.some((a) => a.connected);

    const rows = drones.length
      ? drones
          .map((d) => {
            const color = STATUS_COLORS[d.status] || PALETTE.blue;
            const status = STATUS_LABELS[d.status] || d.status || "—";
            const badge = distanceBadge(d.distance_to_area_m);
            const height = asNumber(d.max_height_m);
            return `
              <div class="dt-row">
                <span class="dt-status" style="background:${color}"></span>
                <div class="dt-main">
                  <div class="dt-name">Dron ${esc(String(d.id ?? "").slice(0, 8))}
                    <span class="dt-sub">· ${esc(status)}</span></div>
                  <div class="dt-sub">pułap do ${height != null ? `${height} m` : "—"}
                    · ${esc(fmtTime(d.start, locale))}–${esc(fmtTime(d.end, locale))}</div>
                </div>
                <span class="dt-badge" style="background:${badge.color}">${esc(badge.text)}</span>
              </div>`;
          })
          .join("")
      : `<div class="dt-empty">Brak zgłoszonych lotów w monitorowanym obszarze.</div>`;

    this._root.innerHTML = `
      <ha-card>
        <div class="dt-head">
          <span class="dt-title">${esc(this._title)}</span>
          <span class="dt-dot" style="background:${connected ? PALETTE.green : PALETTE.grey}"
                title="${connected ? "Strumień połączony" : "Strumień rozłączony"}"></span>
          <span class="dt-count">${drones.length} w zasięgu</span>
        </div>
        <div class="dt-tiles">
          <div class="dt-tile"><div class="dt-tile-v">${drones.length}</div><div class="dt-tile-l">w zasięgu</div></div>
          <div class="dt-tile"><div class="dt-tile-v">${total == null ? "—" : total}</div><div class="dt-tile-l">w Polsce</div></div>
        </div>
        ${rows}
      </ha-card>`;
  }

  static getStubConfig() {
    return { type: "custom:dronetower-surveillance-card", title: "Drony w okolicy" };
  }
}

customElements.define("dronetower-surveillance-card", DroneTowerSurveillanceCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "dronetower-surveillance-card",
  name: "DroneTower — lista dronów",
  description: "Lista zgłoszonych lotów w okolicy z kafelkami statystyk.",
  preview: false,
  documentationURL: "https://github.com/amuamurawski/DroneTower#karta-listy-dronów",
});
