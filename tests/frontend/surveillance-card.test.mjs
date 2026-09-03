// Testy jednostkowe karty listy (dronetower-surveillance-card.js).
// Pokrycie: XSS/escapowanie, distanceBadge (progi i formaty), deduplikacja
// dronów po id, rerender po setConfig, odporność na zdeformowane dane,
// komunikat o brakującej encji, cache sygnatury, total = max po encjach.

import test from "node:test";
import assert from "node:assert/strict";

import { loadCard } from "./load-card.mjs";

const FILE = "dronetower-surveillance-card.js";
const TAG = "dronetower-surveillance-card";

function areaAttrs(overrides = {}) {
  return {
    monitored_latitude: 52.2297,
    monitored_longitude: 21.0122,
    radius_m: 5000,
    total_active_in_poland: 42,
    stream_connected: true,
    drones: [],
    ...overrides,
  };
}

function makeHass(states) {
  return { locale: { language: "pl" }, states };
}

function newCard(config = {}) {
  const card = loadCard(FILE);
  const el = card.run(`new (customElements.get('${TAG}'))()`);
  el.setConfig(config);
  const root = el.shadowRoot.getElementById("root");
  return { card, el, root };
}

const countRows = (html) => html.split('class="dt-row"').length - 1;

test("XSS: HTML w id/status/distance/start nie trafia surowo do innerHTML", () => {
  const evil = '<img src=x onerror=alert(1)>';
  const { el, root } = newCard();
  el.hass = makeHass({
    "binary_sensor.dt": {
      attributes: areaAttrs({
        drones: [
          {
            id: evil,
            status: evil,
            distance_to_area_m: evil, // string → guard → "—"
            max_height_m: "120", // string → guard → "—"
            start: "<i>zle</i>", // niepoprawna data → surowy string, escapowany przy wstawianiu
            end: null,
          },
        ],
      }),
    },
  });
  const html = root.innerHTML;
  assert.ok(!html.includes("<img"), "surowy <img w renderze");
  assert.ok(!html.includes("<i>"), "surowy <i> w renderze");
  assert.ok(html.includes("&lt;img"), "brak escapowanej wersji id/statusu");
  assert.ok(html.includes("pułap do —"), "string max_height_m nie przeszedł przez guard");
});

test("XSS: HTML w title konfiguracji jest escapowany", () => {
  const { el, root } = newCard({ title: '<script>alert(1)</script>' });
  el.hass = makeHass({ "binary_sensor.dt": { attributes: areaAttrs() } });
  assert.ok(!root.innerHTML.includes("<script"), "surowy <script z config.title");
  assert.ok(root.innerHTML.includes("&lt;script&gt;"), "brak escapowanego tytułu");
});

test("distanceBadge: progi kolorów i formaty m/km", () => {
  const { card } = newCard();
  const distanceBadge = card.getFunction("distanceBadge");
  assert.equal(typeof distanceBadge, "function", "brak top-level distanceBadge");

  let b = distanceBadge(400);
  assert.equal(b.text, "400 m");
  assert.equal(b.color, "#e5484d"); // red ≤500

  b = distanceBadge(500);
  assert.equal(b.color, "#e5484d"); // granica czerwieni włącznie

  b = distanceBadge(501);
  assert.equal(b.color, "#f5a623"); // orange ≤2000

  b = distanceBadge(1000);
  assert.equal(b.text, "1.0 km"); // km od 1000 m
  assert.equal(b.color, "#f5a623");

  b = distanceBadge(2000);
  assert.equal(b.color, "#f5a623");

  b = distanceBadge(2001);
  assert.equal(b.color, "#3ba55d"); // green >2000
  assert.equal(b.text, "2.0 km");

  b = distanceBadge(3456);
  assert.equal(b.text, "3.5 km");

  b = distanceBadge(123.6);
  assert.equal(b.text, "124 m"); // Math.round dla metrów
});

test("distanceBadge: null/string/NaN/Infinity → guard i kreska", () => {
  const { card } = newCard();
  const distanceBadge = card.getFunction("distanceBadge");
  for (const bad of [null, undefined, "1234", NaN, Infinity, -Infinity, {}, []]) {
    const b = distanceBadge(bad);
    assert.equal(b.text, "—", `wartość ${String(bad)} nie dała kreski`);
    assert.equal(b.color, "#8a8a8a", `wartość ${String(bad)} nie dała szarości`);
  }
});

test("fmtTime: brak wartości i niepoprawna data", () => {
  const { card } = newCard();
  const fmtTime = card.getFunction("fmtTime");
  assert.equal(fmtTime(null, "pl"), "—");
  assert.equal(fmtTime("", "pl"), "—");
  assert.equal(fmtTime("nie-data", "pl"), "nie-data"); // surowy string, escapowany dopiero przy wstawianiu
  assert.match(fmtTime("2026-09-03T10:30:00+02:00", "pl"), /\d{2}:\d{2}/);
});

test("deduplikacja: ten sam id w dwóch encjach → jeden wiersz; total = max", () => {
  const d = { id: "dup-0001", status: "ACTIVE", distance_to_area_m: 300 };
  const { el, root } = newCard();
  el.hass = makeHass({
    "binary_sensor.a": { attributes: areaAttrs({ drones: [d], total_active_in_poland: 5 }) },
    "binary_sensor.b": { attributes: areaAttrs({ drones: [{ ...d }], total_active_in_poland: 9 }) },
  });
  const html = root.innerHTML;
  assert.equal(countRows(html), 1, "dron zdublowany między encjami");
  assert.ok(html.includes("1 w zasięgu"), "licznik nie liczy po deduplikacji");
  assert.ok(html.includes(">9<"), "total nie jest maksimum po encjach");
  assert.ok(!html.includes(">5<"), "użyto total z pierwszej encji zamiast maksimum");
});

test("setConfig po renderze (zmiana title) → rerender mimo niezmienionych danych", () => {
  const { el, root } = newCard({ title: "Stary tytuł" });
  const hass = makeHass({ "binary_sensor.dt": { attributes: areaAttrs() } });
  el.hass = hass;
  assert.ok(root.innerHTML.includes("Stary tytuł"));
  el.setConfig({ title: "Nowy tytuł" });
  assert.ok(root.innerHTML.includes("Nowy tytuł"), "setConfig nie wymusił rerenderu");
  assert.ok(!root.innerHTML.includes("Stary tytuł"));
});

test("cache sygnatury: identyczne dane nie renderują ponownie, zmiana danych tak", () => {
  const attrs = areaAttrs({ drones: [{ id: "x1", status: "CREATED", distance_to_area_m: 100 }] });
  const { el, root } = newCard();
  el.hass = makeHass({ "binary_sensor.dt": { attributes: attrs } });
  root.innerHTML = "MARKER";
  // Świeże, ale strukturalnie identyczne obiekty — sygnatura ta sama.
  el.hass = makeHass({ "binary_sensor.dt": { attributes: JSON.parse(JSON.stringify(attrs)) } });
  assert.equal(root.innerHTML, "MARKER", "rerender mimo identycznych danych");
  // Zmiana danych (w tym pola start — pokrywanego przez sygnaturę) → rerender.
  const changed = JSON.parse(JSON.stringify(attrs));
  changed.drones[0].start = "2026-09-03T12:00:00+02:00";
  el.hass = makeHass({ "binary_sensor.dt": { attributes: changed } });
  assert.notEqual(root.innerHTML, "MARKER", "brak rerenderu po zmianie danych");
});

test("zdeformowane wpisy dronów (null/string/liczba w tablicy) nie wysadzają renderu", () => {
  const { el, root } = newCard();
  el.hass = makeHass({
    "binary_sensor.dt": {
      attributes: areaAttrs({
        drones: [null, undefined, "śmieć", 42, { id: "ok-00001", status: "ACTIVE" }],
      }),
    },
  });
  const html = root.innerHTML;
  assert.equal(countRows(html), 1, "zdeformowane wpisy nie zostały odfiltrowane");
  assert.ok(!html.includes("Błąd renderowania"), "render zgłosił błąd zamiast odfiltrować");
});

test("skonfigurowane, nieistniejące entity → komunikat błędu, nie pusty stan", () => {
  const { el, root } = newCard({ entity: "binary_sensor.nie_ma" });
  el.hass = makeHass({ "binary_sensor.inny": { attributes: areaAttrs() } });
  const html = root.innerHTML;
  assert.ok(html.includes("Nie znaleziono encji"), "brak komunikatu o brakującej encji");
  assert.ok(html.includes("binary_sensor.nie_ma"));
  assert.ok(!html.includes("Brak zgłoszonych lotów"), "pokazano mylący pusty stan");
});

test("jawne entity: czytana jest tylko wskazana encja", () => {
  const { el, root } = newCard({ entity: "binary_sensor.a" });
  el.hass = makeHass({
    "binary_sensor.a": { attributes: areaAttrs({ drones: [{ id: "a-1", status: "ACTIVE" }] }) },
    "binary_sensor.b": { attributes: areaAttrs({ drones: [{ id: "b-1", status: "ACTIVE" }] }) },
  });
  const html = root.innerHTML;
  assert.equal(countRows(html), 1);
  assert.ok(html.includes("a-1"));
  assert.ok(!html.includes("b-1"), "przy jawnym entity karta czyta cudze encje");
});

test("setConfig: entity innego typu niż string rzuca", () => {
  const { el } = newCard();
  assert.throws(() => el.setConfig({ entity: 123 }), /entity/);
});

test("pusty stan i kropka połączenia", () => {
  const { el, root } = newCard();
  el.hass = makeHass({
    "binary_sensor.dt": { attributes: areaAttrs({ stream_connected: false }) },
  });
  let html = root.innerHTML;
  assert.ok(html.includes("Brak zgłoszonych lotów"), "brak pustego stanu");
  assert.ok(html.includes("#8a8a8a"), "kropka rozłączenia nie jest szara");
  el.hass = makeHass({
    "binary_sensor.dt": { attributes: areaAttrs({ stream_connected: true }) },
  });
  html = root.innerHTML;
  assert.ok(html.includes("#3ba55d"), "kropka połączenia nie jest zielona");
});

test("sortowanie po dystansie; brak dystansu na końcu", () => {
  const { el, root } = newCard();
  el.hass = makeHass({
    "binary_sensor.dt": {
      attributes: areaAttrs({
        drones: [
          { id: "bez-dyst", status: "ACTIVE" },
          { id: "daleki-1", status: "ACTIVE", distance_to_area_m: 4000 },
          { id: "bliski-1", status: "ACTIVE", distance_to_area_m: 100 },
        ],
      }),
    },
  });
  const html = root.innerHTML;
  const order = ["bliski-1", "daleki-1", "bez-dyst"].map((id) => html.indexOf(id));
  assert.ok(order[0] !== -1 && order[0] < order[1] && order[1] < order[2], "zła kolejność sortowania");
});
