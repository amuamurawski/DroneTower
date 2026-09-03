// Testy jednostkowe karty mapy (dronetower-map-card.js).
// Leaflet jest podstawiany fałszywką (rejestrującą HTML popupów), żeby
// przetestować escapowanie w bindPopup, deduplikację i ścieżki błędów bez
// prawdziwego DOM/mapy.

import test from "node:test";
import assert from "node:assert/strict";

import { loadCard } from "./load-card.mjs";

const FILE = "dronetower-map-card.js";
const TAG = "dronetower-map-card";

function areaAttrs(overrides = {}) {
  return {
    monitored_latitude: 52.2297,
    monitored_longitude: 21.0122,
    radius_m: 5000,
    total_active_in_poland: 7,
    stream_connected: true,
    drones: [],
    ...overrides,
  };
}

function makeHass(states) {
  return { locale: { language: "pl" }, states };
}

/** Minimalna fałszywka Leaflet — łańcuchowe API + rejestracja popupów. */
function makeFakeLeaflet(popups) {
  const boundsObj = { extend() { return this; } };
  const layer = () => ({
    addTo() { return this; },
    bindPopup(html) { popups.push(String(html)); return this; },
    getBounds: () => boundsObj,
    clearLayers() {},
  });
  return {
    map: () => ({
      setView() { return this; },
      remove() {},
      invalidateSize() {},
      fitBounds() {},
    }),
    tileLayer: layer,
    layerGroup: layer,
    circle: layer,
    circleMarker: layer,
    marker: layer,
    divIcon: (o) => o,
    latLng: () => ({ toBounds: () => boundsObj }),
  };
}

/**
 * Tworzy kartę z fałszywym Leafletem i przepuszcza mikrozadania ładowania mapy.
 * Zwraca też tablicę popups zapełnianą przy każdym bindPopup.
 */
async function renderMap(hass, config = {}) {
  const card = loadCard(FILE);
  const popups = [];
  card.window.L = makeFakeLeaflet(popups);
  const el = card.run(`new (customElements.get('${TAG}'))()`);
  el.setConfig(config);
  el.hass = hass;
  // _build już się wykonał; mapa inicjalizuje się w mikrozadaniu i wymaga
  // podpiętego do DOM kontenera.
  if (el._mapEl) el._mapEl.isConnected = true;
  await new Promise((r) => setImmediate(r));
  return { card, el, popups };
}

test("XSS: popup drona escapuje id/status/daty, liczby przechodzą przez guard", async () => {
  const evil = '<img src=x onerror=alert(1)>';
  const { popups } = await renderMap(
    makeHass({
      "binary_sensor.dt": {
        attributes: areaAttrs({
          drones: [
            {
              id: evil,
              status: evil,
              latitude: 52.23,
              longitude: 21.01,
              radius_m: "500", // string → guard → "—"
              max_height_m: "120",
              distance_to_area_m: NaN,
              start: "<i>zle</i>", // niepoprawna data → escapowana w fmtTime
              end: "2026-09-03T11:00:00+02:00",
            },
          ],
        }),
      },
    }),
  );
  const dronePopups = popups.filter((p) => p.includes("Dron"));
  assert.equal(dronePopups.length, 1, "brak popupu drona (mapa się nie narysowała)");
  const html = dronePopups[0];
  assert.ok(!html.includes("<img"), "surowy <img w popupie");
  assert.ok(!html.includes("<i>"), "surowy <i> w popupie");
  assert.ok(html.includes("&lt;img"), "brak escapowanej wersji id/statusu");
  assert.ok(html.includes("Wysokość maks.: —"), "string max_height_m nie przeszedł przez guard");
  assert.ok(html.includes("Do obszaru: —"), "NaN distance nie dał kreski");
  assert.ok(html.includes("Promień strefy: —"), "string radius_m nie przeszedł przez guard");
});

test("popup: poprawne liczby i id liczbowy (String()) bez wyjątku", async () => {
  const { popups } = await renderMap(
    makeHass({
      "binary_sensor.dt": {
        attributes: areaAttrs({
          drones: [
            {
              id: 123456789, // liczbowy id nie może rzucać na .slice
              status: "ACTIVE",
              latitude: 52.23,
              longitude: 21.01,
              radius_m: 500,
              max_height_m: 120,
              distance_to_area_m: 1234,
            },
          ],
        }),
      },
    }),
  );
  const html = popups.filter((p) => p.includes("Dron")).join("\n");
  assert.ok(html.includes("Dron 12345678"), "id liczbowy nie został znormalizowany");
  assert.ok(html.includes("Wysokość maks.: 120 m"));
  assert.ok(html.includes("Do obszaru: 1234 m"));
  assert.ok(html.includes("Status: Aktywny"), "brak polskiej etykiety statusu");
});

test("deduplikacja dronów między encjami; licznik po deduplikacji", async () => {
  const d = {
    id: "dup-0001",
    status: "ACTIVE",
    latitude: 52.23,
    longitude: 21.01,
    distance_to_area_m: 300,
  };
  const { el, popups } = await renderMap(
    makeHass({
      "binary_sensor.a": { attributes: areaAttrs({ drones: [d] }) },
      "binary_sensor.b": { attributes: areaAttrs({ drones: [{ ...d }] }) },
    }),
  );
  assert.equal(popups.filter((p) => p.includes("Dron")).length, 1, "dron zdublowany między encjami");
  assert.match(el._count.textContent, /^1 w zasięgu/, "licznik nie liczy po deduplikacji");
  assert.ok(el._count.textContent.includes("7 w Polsce"));
});

test("zdeformowane wpisy dronów i brak współrzędnych nie wysadzają renderu", async () => {
  const { el, popups } = await renderMap(
    makeHass({
      "binary_sensor.dt": {
        attributes: areaAttrs({
          drones: [
            null,
            "śmieć",
            42,
            { id: "bez-wsp", status: "ACTIVE", latitude: "52", longitude: 21.01 }, // lat string → pomijany na mapie
            { id: "ok-00001", status: "ACTIVE", latitude: 52.23, longitude: 21.01 },
          ],
        }),
      },
    }),
  );
  assert.equal(popups.filter((p) => p.includes("Dron")).length, 1, "dron bez liczbowych współrzędnych trafił na mapę");
  // Licznik obejmuje też drona bez współrzędnych (jest w zasięgu, tylko bez pinezki).
  assert.match(el._count.textContent, /^2 w zasięgu/);
  assert.equal(el._errEl.textContent, "", "render zgłosił błąd zamiast odfiltrować");
});

test("skonfigurowane, nieistniejące entity → komunikat błędu", async () => {
  const { el } = await renderMap(
    makeHass({ "binary_sensor.inny": { attributes: areaAttrs() } }),
    { entity: "binary_sensor.nie_ma" },
  );
  assert.ok(
    el._errEl.textContent.includes("Nie znaleziono skonfigurowanej encji"),
    "brak komunikatu o brakującej encji",
  );
  assert.ok(el._errEl.textContent.includes("binary_sensor.nie_ma"));
});

test("skonfigurowane entity bez danych DroneTower → dedykowany komunikat", async () => {
  const { el } = await renderMap(
    makeHass({ "binary_sensor.zwykly": { attributes: { device_class: "motion" } } }),
    { entity: "binary_sensor.zwykly" },
  );
  assert.ok(
    el._errEl.textContent.includes("nie udostępnia danych DroneTower"),
    "brak komunikatu o encji bez danych DroneTower",
  );
});

test("setConfig po renderze: zmiana title przebudowuje kartę bez duplikatów", async () => {
  const hass = makeHass({ "binary_sensor.dt": { attributes: areaAttrs() } });
  const { el } = await renderMap(hass, { title: "Stary tytuł" });
  assert.equal(el.children.length, 1, "karta nie ma dokładnie jednego ha-card");
  const titleOf = (node) => node.children[0].children[0].textContent;
  assert.equal(titleOf(el.children[0]), "Stary tytuł");
  el.setConfig({ title: "Nowy tytuł" });
  assert.equal(el.children.length, 1, "przebudowa zdublowała ha-card");
  assert.equal(titleOf(el.children[0]), "Nowy tytuł", "setConfig nie przebudował nagłówka");
});

test("cache sygnatury: identyczne dane nie renderują ponownie", async () => {
  const attrs = areaAttrs({
    drones: [{ id: "x1", status: "CREATED", latitude: 52.23, longitude: 21.01 }],
  });
  const { el } = await renderMap(makeHass({ "binary_sensor.dt": { attributes: attrs } }));
  el._count.textContent = "MARKER";
  el.hass = makeHass({ "binary_sensor.dt": { attributes: JSON.parse(JSON.stringify(attrs)) } });
  assert.equal(el._count.textContent, "MARKER", "rerender mimo identycznych danych");
  const changed = JSON.parse(JSON.stringify(attrs));
  changed.drones[0].max_height_m = 150; // pole popupu — musi być objęte sygnaturą
  el.hass = makeHass({ "binary_sensor.dt": { attributes: changed } });
  assert.notEqual(el._count.textContent, "MARKER", "brak rerenderu po zmianie pola popupu");
});

test("setConfig: entity innego typu niż string rzuca; getCardSize liczy z height", async () => {
  const card = loadCard(FILE);
  const el = card.run(`new (customElements.get('${TAG}'))()`);
  assert.throws(() => el.setConfig({ entity: 42 }), /entity/);
  el.setConfig({});
  assert.equal(el.getCardSize(), 8); // 400 px / 50
  el.setConfig({ height: 600 });
  assert.equal(el.getCardSize(), 12);
  el.setConfig({ height: 100 });
  assert.equal(el.getCardSize(), 3); // minimum 3
});

test("fmtMeters/fmtTime/isFiniteNumber: guardy wartości niezaufanych", () => {
  const card = loadCard(FILE);
  const fmtMeters = card.getFunction("fmtMeters");
  const fmtTime = card.getFunction("fmtTime");
  const isFiniteNumber = card.getFunction("isFiniteNumber");
  assert.equal(fmtMeters(100), "100 m");
  for (const bad of ["100", null, NaN, Infinity, {}]) {
    assert.equal(fmtMeters(bad), "—");
  }
  assert.equal(fmtTime(null), "—");
  assert.equal(fmtTime(12345), "—"); // fmtTime przyjmuje tylko stringi
  assert.equal(fmtTime("<b>x</b>"), "&lt;b&gt;x&lt;/b&gt;"); // niepoprawna data → escapowana
  assert.equal(isFiniteNumber(1.5), true);
  assert.equal(isFiniteNumber("1.5"), false);
  assert.equal(isFiniteNumber(NaN), false);
});

test("rozłączony strumień: szara kropka i tytuł kropki", async () => {
  const { el } = await renderMap(
    makeHass({ "binary_sensor.dt": { attributes: areaAttrs({ stream_connected: false }) } }),
  );
  assert.equal(el._dot.style.background, "#8a8a8a");
  assert.equal(el._dot.title, "Strumień rozłączony");
});
