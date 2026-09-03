/**
 * DroneTower map card — a live Leaflet map of registered drone flights near the
 * monitored point. Reads the integration's binary_sensor (its `drones`,
 * `monitored_latitude/longitude`, `radius_m` attributes); no configuration needed.
 *
 * The auto-registration and Leaflet-loading approach is inspired by the MIT-licensed
 * Dectyr RX-5 card by Alexandre Thomas (https://github.com/DECTYR/ha-integration).
 * Leaflet is bundled locally under /dronetower_amu_static/leaflet/.
 */

const STATIC_BASE = "/dronetower_amu_static";
const LEAFLET_JS = `${STATIC_BASE}/leaflet/leaflet.js`;
const LEAFLET_CSS = `${STATIC_BASE}/leaflet/leaflet.css`;
const TILE_URL = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";
const TILE_ATTR = "© OpenStreetMap";

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

let _leafletPromise = null;
function loadLeaflet() {
  if (window.L) return Promise.resolve(window.L);
  if (_leafletPromise) return _leafletPromise;
  _leafletPromise = new Promise((resolve, reject) => {
    if (!document.getElementById("dronetower-leaflet-css")) {
      const link = document.createElement("link");
      link.id = "dronetower-leaflet-css";
      link.rel = "stylesheet";
      link.href = LEAFLET_CSS;
      document.head.appendChild(link);
    }
    const script = document.createElement("script");
    script.src = LEAFLET_JS;
    script.async = true;
    script.onload = () => (window.L ? resolve(window.L) : reject(new Error("Leaflet missing")));
    script.onerror = () => reject(new Error("Failed to load bundled Leaflet"));
    document.head.appendChild(script);
  });
  return _leafletPromise;
}

const esc = (s) =>
  String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

/** Type guard: entity attributes are untrusted, numbers must actually be numbers. */
const isFiniteNumber = (v) => typeof v === "number" && Number.isFinite(v);

/** Safe meters formatter — only ever emits a finite number or a dash. */
const fmtMeters = (v) => (isFiniteNumber(v) ? `${v} m` : "—");

function fmtTime(iso) {
  if (typeof iso !== "string" || !iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? esc(iso) : esc(d.toLocaleString());
}

class DroneTowerMapCard extends HTMLElement {
  setConfig(config) {
    if (config && config.entity != null && typeof config.entity !== "string") {
      throw new Error("Opcja 'entity' musi być identyfikatorem encji (tekst).");
    }
    this._config = config || {};
    this._title = this._config.title || "Drony w okolicy";
    // A config change must invalidate the render cache and rebuild the card,
    // otherwise the previous signature suppresses the re-render.
    this._sig = null;
    this._fitted = false;
    if (this._built) this._teardown();
    if (this._hass) this._render();
  }

  set hass(hass) {
    this._hass = hass;
    // HA calls this on every state change anywhere; only re-render when *our* data
    // actually changed, otherwise a busy instance rebuilds the map constantly and
    // drags the whole UI down. The signature is derived from the exact projection
    // the render uses, so the two can never drift apart.
    const proj = this._collect();
    const sig = JSON.stringify(proj);
    if (sig === this._sig) return;
    this._sig = sig;
    this._render(proj);
  }

  /**
   * Single source of truth for entity selection and data projection — used both
   * for the change signature and for rendering. With an explicit `entity` in the
   * config only that one state is read (no full hass.states scan); otherwise all
   * matching binary_sensors are auto-discovered. Drones are de-duplicated by id
   * across entities, and every untrusted attribute is normalised via type guards.
   */
  _collect() {
    const hass = this._hass;
    if (!hass) return { error: null, areas: [] };

    const entity = this._config?.entity;
    const candidates = [];
    if (entity) {
      const st = hass.states[entity];
      if (!st) return { error: `Nie znaleziono skonfigurowanej encji: ${entity}`, areas: [] };
      candidates.push([entity, st]);
    } else {
      for (const [id, st] of Object.entries(hass.states)) {
        if (id.startsWith("binary_sensor.")) candidates.push([id, st]);
      }
    }

    const areas = [];
    const seenDroneIds = new Set();
    for (const [entityId, st] of candidates) {
      const a = st.attributes || {};
      const isDroneTower =
        isFiniteNumber(a.monitored_latitude) &&
        isFiniteNumber(a.monitored_longitude) &&
        Array.isArray(a.drones);
      if (!isDroneTower) {
        if (entity) {
          return { error: `Encja ${entityId} nie udostępnia danych DroneTower.`, areas: [] };
        }
        continue;
      }
      const drones = [];
      for (const d of a.drones) {
        if (!d || typeof d !== "object") continue;
        const id = String(d.id ?? "");
        if (id) {
          if (seenDroneIds.has(id)) continue;
          seenDroneIds.add(id);
        }
        drones.push({
          id,
          status: typeof d.status === "string" ? d.status : "",
          latitude: isFiniteNumber(d.latitude) ? d.latitude : null,
          longitude: isFiniteNumber(d.longitude) ? d.longitude : null,
          radius_m: isFiniteNumber(d.radius_m) ? d.radius_m : null,
          max_height_m: isFiniteNumber(d.max_height_m) ? d.max_height_m : null,
          distance_to_area_m: isFiniteNumber(d.distance_to_area_m) ? d.distance_to_area_m : null,
          start: typeof d.start === "string" ? d.start : null,
          end: typeof d.end === "string" ? d.end : null,
        });
      }
      areas.push({
        entityId,
        lat: a.monitored_latitude,
        lon: a.monitored_longitude,
        radius: isFiniteNumber(a.radius_m) ? a.radius_m : 0,
        drones,
        total: isFiniteNumber(a.total_active_in_poland) ? a.total_active_in_poland : null,
        connected: Boolean(a.stream_connected),
      });
    }
    return { error: null, areas };
  }

  getCardSize() {
    return Math.max(3, Math.round((this._config?.height || 400) / 50));
  }

  _mapHeight() {
    if (this._config?.height) return `${this._config.height}px`;
    const ratio = this._config?.aspect_ratio;
    if (ratio) return null; // handled via padding wrapper
    return "400px";
  }

  _render(proj) {
    try {
      if (!this._built) this._build();
      const { error, areas } = proj || this._collect();
      this._showError(error);

      // Header stats (drones are already de-duplicated by id in _collect).
      const nearby = areas.reduce((n, a) => n + a.drones.length, 0);
      const withTotal = areas.find((a) => a.total != null);
      const total = withTotal ? withTotal.total : null;
      const connected = areas.some((a) => a.connected);
      this._count.textContent = total == null
        ? `${nearby} w zasięgu`
        : `${nearby} w zasięgu · ${total} w Polsce`;
      this._dot.style.background = connected ? "#3ba55d" : "#8a8a8a";
      this._dot.title = connected ? "Strumień na żywo połączony" : "Strumień rozłączony";

      if (!window.L || !this._map) {
        loadLeaflet()
          .then(() => this._initMap(areas))
          .catch((e) => this._showError(`Nie udało się załadować mapy: ${e.message}`));
        return;
      }
      this._draw(areas);
    } catch (e) {
      if (this._errEl && this._errEl.isConnected) {
        this._showError(`Błąd renderowania karty: ${e.message}`);
      } else {
        this.textContent = `Błąd renderowania karty: ${e.message}`;
        this._built = false;
      }
    }
  }

  _showError(msg) {
    if (!this._errEl) return;
    if (msg) {
      this._errEl.textContent = msg;
      this._errEl.style.display = "block";
    } else {
      this._errEl.textContent = "";
      this._errEl.style.display = "none";
    }
  }

  _build() {
    this._built = true;
    const card = document.createElement("ha-card");

    const header = document.createElement("div");
    header.style.cssText =
      "display:flex;align-items:center;gap:8px;padding:12px 16px 8px;font-weight:500;";
    const title = document.createElement("div");
    title.textContent = this._title;
    title.style.cssText = "font-size:1.1rem;flex:1;";
    this._dot = document.createElement("span");
    this._dot.style.cssText = "width:10px;height:10px;border-radius:50%;display:inline-block;";
    this._count = document.createElement("div");
    this._count.style.cssText = "font-size:.85rem;color:var(--secondary-text-color);";
    header.append(title, this._dot, this._count);

    this._errEl = document.createElement("div");
    this._errEl.style.cssText =
      "display:none;padding:0 16px 8px;color:var(--error-color,#e5484d);font-size:.9rem;";

    this._mapEl = document.createElement("div");
    const h = this._mapHeight();
    this._mapEl.style.cssText = `width:100%;height:${h || "400px"};border-radius:0 0 var(--ha-card-border-radius,12px) var(--ha-card-border-radius,12px);overflow:hidden;`;

    card.append(header, this._errEl, this._mapEl);
    this.innerHTML = "";
    this.append(card);
  }

  _teardown() {
    if (this._ro) {
      this._ro.disconnect();
      this._ro = null;
    }
    if (this._map) {
      this._map.remove();
      this._map = null;
    }
    this._areaLayer = null;
    this._droneLayer = null;
    this._errEl = null;
    this._mapEl = null;
    this._built = false;
    this.innerHTML = "";
  }

  _initMap(areas) {
    const L = window.L;
    if (!this._mapEl || !this._mapEl.isConnected) return;
    if (this._map) {
      // Another render queued Leaflet loading before init finished — just redraw.
      this._draw(areas);
      return;
    }
    const center = areas[0] ? [areas[0].lat, areas[0].lon] : [52.115, 19.424];
    this._map = L.map(this._mapEl, { zoomControl: true, attributionControl: true }).setView(center, 12);
    L.tileLayer(TILE_URL, { maxZoom: 19, attribution: TILE_ATTR }).addTo(this._map);
    this._areaLayer = L.layerGroup().addTo(this._map);
    this._droneLayer = L.layerGroup().addTo(this._map);
    // The card is often laid out (or made visible) after the map is created, which
    // leaves Leaflet with a stale 0×0 size — a ResizeObserver keeps it in sync.
    setTimeout(() => this._map && this._map.invalidateSize(), 200);
    this._observeResize();
    this._draw(areas);
  }

  _observeResize() {
    if (this._ro || !this._mapEl || typeof ResizeObserver === "undefined") return;
    this._ro = new ResizeObserver(() => this._map && this._map.invalidateSize());
    this._ro.observe(this._mapEl);
  }

  connectedCallback() {
    // Re-attach the observer after the card is moved in the DOM (dashboard edits).
    if (this._map) {
      this._observeResize();
      this._map.invalidateSize();
    }
  }

  disconnectedCallback() {
    if (this._ro) {
      this._ro.disconnect();
      this._ro = null;
    }
  }

  _draw(areas) {
    const L = window.L;
    if (!this._map) return;
    this._areaLayer.clearLayers();
    this._droneLayer.clearLayers();
    const bounds = [];

    for (const area of areas) {
      if (area.lat != null && area.lon != null) {
        if (area.radius > 0) {
          const c = L.circle([area.lat, area.lon], {
            radius: area.radius,
            color: "#00875f",
            weight: 2,
            fillColor: "#00875f",
            fillOpacity: 0.06,
          }).addTo(this._areaLayer);
          bounds.push(c.getBounds());
        }
        L.circleMarker([area.lat, area.lon], {
          radius: 4,
          color: "#00875f",
          fillColor: "#00875f",
          fillOpacity: 1,
        })
          .bindPopup("Monitorowany punkt")
          .addTo(this._areaLayer);
      }

      for (const d of area.drones) {
        if (d.latitude == null || d.longitude == null) continue;
        const color = STATUS_COLORS[d.status] || "#4c8dff";
        const ll = [d.latitude, d.longitude];
        if (d.radius_m) {
          L.circle(ll, {
            radius: d.radius_m,
            color,
            weight: 1,
            fillColor: color,
            fillOpacity: 0.12,
          }).addTo(this._droneLayer);
        }
        const icon = L.divIcon({
          className: "dronetower-marker",
          html: `<div style="font-size:22px;line-height:22px;filter:drop-shadow(0 1px 1px rgba(0,0,0,.5));">🚁</div>`,
          iconSize: [22, 22],
          iconAnchor: [11, 11],
        });
        const status = STATUS_LABELS[d.status] || d.status || "—";
        // bindPopup accepts raw HTML — every entity-derived string is escaped at the
        // point of insertion, numbers only pass through the isFiniteNumber guard.
        const popup = `
          <strong>Dron ${esc(d.id.slice(0, 8))}</strong><br>
          Status: ${esc(status)}<br>
          Wysokość maks.: ${fmtMeters(d.max_height_m)}<br>
          Do obszaru: ${fmtMeters(d.distance_to_area_m)}<br>
          Promień strefy: ${fmtMeters(d.radius_m)}<br>
          Od: ${fmtTime(d.start)}<br>
          Do: ${fmtTime(d.end)}`;
        L.marker(ll, { icon }).bindPopup(popup).addTo(this._droneLayer);
        bounds.push(L.latLng(ll).toBounds(Math.max(200, (d.radius_m || 0) * 2)));
      }
    }

    if (bounds.length && !this._fitted) {
      try {
        let b = bounds[0];
        for (let i = 1; i < bounds.length; i++) b = b.extend(bounds[i]);
        this._map.fitBounds(b, { padding: [24, 24], maxZoom: 15 });
        this._fitted = true;
      } catch (_e) {
        /* keep default view */
      }
    }
  }

  static getConfigElement() {
    return null;
  }
  static getStubConfig() {
    return { type: "custom:dronetower-map-card", title: "Drony w okolicy" };
  }
}

customElements.define("dronetower-map-card", DroneTowerMapCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "dronetower-map-card",
  name: "DroneTower — mapa dronów",
  description: "Mapa na żywo zgłoszonych lotów dronów wokół monitorowanego punktu.",
  preview: false,
});

// eslint-disable-next-line no-console
console.info("%c DRONETOWER-MAP-CARD %c loaded ", "background:#00875f;color:#fff", "");
