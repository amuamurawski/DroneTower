/**
 * DroneTower surveillance card — a compact list of registered drone flights near the
 * monitored point, with stat tiles. Reads the integration's binary_sensor (its
 * `drones`, `total_active_in_poland` attributes); no configuration needed.
 *
 * Inspired by the MIT-licensed Dectyr RX-5 surveillance card by Alexandre Thomas
 * (https://github.com/DECTYR/ha-integration).
 */

const STATUS_COLORS = {
  ACTIVE: "#e5484d",
  OVERDUE: "#f5a623",
  CREATED: "#4c8dff",
};
const STATUS_LABELS = {
  ACTIVE: "Aktywny",
  OVERDUE: "Po czasie",
  CREATED: "Zgłoszony",
};

const esc = (s) =>
  String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function distanceBadge(m) {
  if (m == null) return { color: "#8a8a8a", text: "—" };
  if (m <= 500) return { color: "#e5484d", text: `${m} m` };
  if (m <= 2000) return { color: "#f5a623", text: `${m} m` };
  return { color: "#3ba55d", text: m >= 1000 ? `${(m / 1000).toFixed(1)} km` : `${m} m` };
}

function fmtWindow(start, end) {
  const f = (iso) => {
    if (!iso) return "—";
    const d = new Date(iso);
    return Number.isNaN(d.getTime())
      ? esc(iso)
      : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  };
  return `${f(start)}–${f(end)}`;
}

class DroneTowerSurveillanceCard extends HTMLElement {
  setConfig(config) {
    this._config = config || {};
    this._title = this._config.title || "Drony w okolicy";
  }

  set hass(hass) {
    this._hass = hass;
    // Re-render only when our data changed, not on every unrelated state update.
    const sig = this._signature();
    if (sig === this._sig) return;
    this._sig = sig;
    this._render();
  }

  _signature() {
    const hass = this._hass;
    if (!hass) return "";
    const wanted = this._config?.entity ? [this._config.entity] : null;
    let sig = "";
    for (const [id, st] of Object.entries(hass.states)) {
      if (!id.startsWith("binary_sensor.")) continue;
      const a = st.attributes || {};
      if (a.monitored_latitude == null || !Array.isArray(a.drones)) continue;
      if (wanted && !wanted.includes(id)) continue;
      sig += `${id}:${a.total_active_in_poland}:${a.stream_connected};`;
      for (const d of a.drones) sig += `${d.id}#${d.status}/${d.distance_to_area_m}/${d.max_height_m};`;
    }
    return sig;
  }

  getCardSize() {
    const n = this._lastCount || 0;
    return 2 + Math.min(8, n);
  }

  _areas() {
    const hass = this._hass;
    if (!hass) return [];
    const wanted = this._config?.entity ? [this._config.entity] : null;
    const areas = [];
    for (const [entityId, st] of Object.entries(hass.states)) {
      if (!entityId.startsWith("binary_sensor.")) continue;
      const a = st.attributes || {};
      if (a.monitored_latitude == null || !Array.isArray(a.drones)) continue;
      if (wanted && !wanted.includes(entityId)) continue;
      areas.push({
        drones: a.drones,
        total: a.total_active_in_poland,
        connected: a.stream_connected,
      });
    }
    return areas;
  }

  _render() {
    const areas = this._areas();
    const drones = [];
    for (const a of areas) drones.push(...a.drones);
    drones.sort((x, y) => (x.distance_to_area_m ?? 1e12) - (y.distance_to_area_m ?? 1e12));
    this._lastCount = drones.length;

    const total = areas.length ? areas[0].total : undefined;
    const connected = areas.some((a) => a.connected);

    const tiles = `
      <div class="dt-tiles">
        <div class="dt-tile"><div class="dt-tile-v">${drones.length}</div><div class="dt-tile-l">w zasięgu</div></div>
        <div class="dt-tile"><div class="dt-tile-v">${total == null ? "—" : esc(total)}</div><div class="dt-tile-l">w Polsce</div></div>
      </div>`;

    let list;
    if (!drones.length) {
      list = `<div class="dt-empty">Brak zgłoszonych lotów w monitorowanym obszarze.</div>`;
    } else {
      list = drones
        .map((d) => {
          const color = STATUS_COLORS[d.status] || "#4c8dff";
          const status = STATUS_LABELS[d.status] || d.status || "—";
          const badge = distanceBadge(d.distance_to_area_m);
          return `
            <div class="dt-row">
              <span class="dt-status" style="background:${color}"></span>
              <div class="dt-main">
                <div class="dt-name">Dron ${esc((d.id || "").slice(0, 8))}
                  <span class="dt-sub">· ${esc(status)}</span></div>
                <div class="dt-sub">pułap do ${d.max_height_m != null ? esc(d.max_height_m) + " m" : "—"}
                  · ${fmtWindow(d.start, d.end)}</div>
              </div>
              <span class="dt-badge" style="background:${badge.color}">${badge.text}</span>
            </div>`;
        })
        .join("");
    }

    this.innerHTML = `
      <ha-card>
        <style>
          .dt-head{display:flex;align-items:center;gap:8px;padding:12px 16px 4px;}
          .dt-head .dt-title{font-size:1.1rem;font-weight:500;flex:1;}
          .dt-dot{width:10px;height:10px;border-radius:50%;background:${connected ? "#3ba55d" : "#8a8a8a"};}
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
        </style>
        <div class="dt-head">
          <span class="dt-title">${esc(this._title)}</span>
          <span class="dt-dot" title="${connected ? "Strumień połączony" : "Strumień rozłączony"}"></span>
          <span class="dt-count">${drones.length} w zasięgu</span>
        </div>
        ${tiles}
        ${list}
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
  documentationURL: "https://github.com/amuamurawski/DroneTower#karta-mapy-dronów",
});
