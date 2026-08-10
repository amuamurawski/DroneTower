// Minimal STOMP-over-WebSocket client for the DroneTower broadcast topic.
//
//     node tools/wstest.mjs
//
// Prints raw STOMP frames for 45 seconds. Requires Node 22+ for the global
// WebSocket. Useful for confirming the handshake independently of the Home
// Assistant integration; see tools/live_check.py for the parsed equivalent.

const URL = "wss://bff-drone-tower.uav.pansa.pl/ws";
const TOPIC =
  "/websocket/topic/drone-tower-queue/drone-tower-active-checkins-topic/broadcast";
const NUL = String.fromCharCode(0);

const ws = new WebSocket(URL, ["v12.stomp", "v11.stomp", "v10.stomp"]);
let frames = 0;

ws.onopen = () => {
  console.log("WS OPEN, negotiated subprotocol:", JSON.stringify(ws.protocol));
  ws.send("CONNECT\naccept-version:1.0,1.1,1.2\nheart-beat:10000,10000\n\n" + NUL);
};

ws.onmessage = (e) => {
  const data = typeof e.data === "string" ? e.data : "[binary]";
  frames++;
  console.log("--- FRAME " + frames + " ---");
  console.log(data.slice(0, 800).replace(/\0/g, "<NUL>"));
  if (data.startsWith("CONNECTED")) {
    console.log(">>> subscribing to broadcast topic");
    ws.send("SUBSCRIBE\nid:sub-0\ndestination:" + TOPIC + "\n\n" + NUL);
  }
};

ws.onerror = (e) => console.log("WS ERROR", e.message || e.type);
ws.onclose = (e) => console.log("WS CLOSE code=" + e.code + " reason=" + e.reason);

setTimeout(() => {
  console.log("=== finished, total frames: " + frames);
  ws.close();
  process.exit(0);
}, 45000);
