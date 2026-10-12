/**
 * A Lumae Radio for the integration's tests and for trying the card: the radio's real HTTPS
 * boundary and auth store (headless/service/http-server.mjs, auth-store.mjs), with an in-memory
 * radio behind them that keeps revisions, receipts and events as the real one does.
 *
 *   node tests/radio_harness.mjs --port 18443 --origins 'https://127.0.0.1:{port}'
 *
 * Prints one JSON line ({port, origins, fingerprint, keys}) once it listens, then takes commands
 * on stdin, one per line: `advance`, `state <playing|paused|stopped|buffering|fault> [code]`,
 * `revoke <key name>`, `rest-ban-clear`. Uses the public synthetic test certificate only.
 */

import { X509Certificate } from 'node:crypto';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';
import { deflateSync } from 'node:zlib';
import { createServer } from 'node:net';

const headless = new URL('../../headless/', import.meta.url);
const { openAuthStore } = await import(new URL('service/auth-store.mjs', headless));
const { createRadioHttpsServer } = await import(new URL('service/http-server.mjs', headless));

const argument = (name, fallback) => {
  const index = process.argv.indexOf(`--${name}`);
  return index > 0 ? process.argv[index + 1] : fallback;
};
// `auto` picks a free port first, since the radio's origins name the port it listens on.
const port =
  argument('port', 'auto') === 'auto' ? await freePort() : Number(argument('port', 'auto'));
const origins = argument('origins', 'https://127.0.0.1:{port}')
  .replaceAll('{port}', String(port))
  .split(',');
const operationDelayMs = Number(argument('operation-delay', '150'));

function freePort() {
  return new Promise((resolve, reject) => {
    const probe = createServer();
    probe.once('error', reject);
    probe.listen(0, '127.0.0.1', () => {
      const { port: chosen } = probe.address();
      probe.close(() => resolve(chosen));
    });
  });
}

const certPath = fileURLToPath(new URL('tests/fixtures/https-test-cert.fixture', headless));
const keyPath = fileURLToPath(new URL('tests/fixtures/https-test-key.fixture', headless));
const fingerprint = new X509Certificate(readFileSync(certPath)).fingerprint256
  .replaceAll(':', '')
  .toLowerCase();

// ── Owner and keys ────────────────────────────────────────────────────────

const root = mkdtempSync(join(tmpdir(), 'lumae-radio-ha-'));
const authStore = openAuthStore({ path: join(root, 'auth', 'auth.db') });
const claim = authStore.issueClaimToken();
const owner = await authStore.claimOwner({
  claimToken: claim.claimToken,
  password: 'Synthetic owner password for tests',
});
const keys = {};
for (const [name, scopes] of Object.entries({
  full: ['read', 'control', 'stations'],
  control: ['read', 'control'],
  read: ['read'],
  admin: ['admin'],
}))
  keys[name] = authStore.createApiKey({
    sessionToken: owner.sessionToken,
    csrfToken: owner.csrfToken,
    label: `Home Assistant ${name}`,
    scopes,
  }).apiKey;

// ── The radio ─────────────────────────────────────────────────────────────

const TRACKS = [
  { id: 'trk-holocene', title: 'Holocene', artist: 'Bon Iver', album: 'Bon Iver, Bon Iver', durationMs: 336_000, hue: 28 },
  { id: 'trk-motion', title: 'Motion Sickness', artist: 'Phoebe Bridgers', album: 'Stranger in the Alps', durationMs: 229_000, hue: 200 },
  { id: 'trk-untitled', title: null, artist: 'Nils Frahm', album: 'Spaces', durationMs: 412_000, hue: 280 },
  { id: 'trk-nightcall', title: 'Nightcall', artist: 'Kavinsky', album: 'OutRun', durationMs: 258_000, hue: 330 },
];
const definition = (mode, steadyEnergy = 0.5) => ({
  source: { kind: 'direct', seeds: [] },
  constraints: {},
  energySchedule: { mode, steadyEnergy, timeZone: 'Europe/Amsterdam', daily: [], weekend: null, variation: 0.5 },
  rotation: {},
});
const stations = [
  { id: 'stn-morning', name: 'Morning drift', revision: '3', definition: definition('daily'), preparationStatus: 'ready', feedbackRevision: 2, feedback: [{ trackId: 'trk-motion', stationPreference: 1, restUntilMs: null }], bans: [] },
  { id: 'stn-focus', name: 'Deep focus', revision: '7', definition: definition('steady', 0.4), preparationStatus: 'ready', feedbackRevision: 0, feedback: [], bans: [] },
  { id: 'stn-late', name: 'Late night', revision: '1', definition: definition('daily'), preparationStatus: 'needed', feedbackRevision: 0, feedback: [], bans: [] },
];
let deviceRevision = 41;
let stationsRevision = 5;
let volume = 0.62;
const playback = {
  state: 'playing',
  stationId: 'stn-morning',
  index: 0,
  occurrence: 1,
  startedAt: Date.now() - 64_000,
  heldAt: null,
  fault: null,
};
const operations = new Map();
const receipts = new Map();
const listeners = new Set();
const emit = (type) => {
  for (const listener of listeners) listener({ type, data: {} });
};

const fail = (code) => {
  throw Object.assign(new Error(code), { code });
};
const station = (id) => stations.find((entry) => entry.id === id) ?? fail('station-not-found');
const current = () => (playback.state === 'stopped' ? null : TRACKS[playback.index]);
const position = () => {
  const track = current();
  if (!track) return null;
  const at = playback.heldAt ?? Date.now();
  return Math.min(track.durationMs, Math.max(0, at - playback.startedAt));
};
const startTrack = (index) => {
  playback.index = index % TRACKS.length;
  playback.occurrence += 1;
  playback.startedAt = Date.now();
  playback.heldAt = playback.state === 'paused' ? Date.now() : null;
};
const stationDto = (entry) => ({
  ...entry,
  prepared: entry.preparationStatus === 'ready',
  preparationError: null,
  report: null,
  vibe: null,
  feedbackCursor: null,
});

function statusDto() {
  const track = current();
  return {
    revision: deviceRevision,
    playback: {
      state: playback.state,
      stationId: playback.stationId,
      track: track ? { id: track.id, title: track.title, artist: track.artist, album: track.album, artworkId: track.id } : null,
      currentOccurrenceId: track ? `occ-${playback.occurrence}` : null,
      remaining: track ? 3 : 0,
      positionMs: position(),
      durationMs: track?.durationMs ?? null,
      selection: track
        ? { preparationId: 'prep-1', definitionRevision: '3', policyVersion: 'v2', fit: 0.87, priorRadioPlays: 4, priorRestMs: 3 * 3_600_000 + 120_000, energyTarget: 0.55, trackEnergy: 0.61, scarcityTier: 'preferred', stealth: true }
        : null,
      fadeIn: null,
      next: track ? { id: TRACKS[(playback.index + 1) % TRACKS.length].id, artworkId: TRACKS[(playback.index + 1) % TRACKS.length].id } : null,
    },
    health: {
      maintenance: { state: 'idle' },
      continuity: playback.state === 'buffering' ? 'buffering' : 'online',
      message: playback.fault,
      clockTrusted: true,
      smoothFade: { state: 'smoothfade', reason: null, sinceMs: 0 },
      audio: { lastStop: null, lastResumeAtMs: null },
      autoResumeSuppressed: false,
      deviceQualified: false,
    },
    volume,
    sonic: { dimensions: 'sonic-dimensions-v3', calibration: 'v1' },
    stealth: true,
  };
}

function finishLater(operation, apply) {
  setTimeout(() => {
    try {
      apply?.();
      operation.status = 'completed';
    } catch (error) {
      operation.status = 'failed';
      operation.message = error.code ?? 'internal-error';
    }
    emit('status');
  }, operationDelayMs);
}

function accept(principal, idempotencyKey, apply) {
  const receipt = `${principal.id}:${idempotencyKey}`;
  if (receipts.has(receipt)) return receipts.get(receipt);
  const operationId = `op-${operations.size + 1}`;
  const operation = { operationId, status: 'accepted', owner: principal.id };
  operations.set(operationId, operation);
  finishLater(operation, apply);
  deviceRevision += 1;
  const result = { data: { operationId, status: 'accepted', revision: deviceRevision }, revision: String(deviceRevision), operationId };
  receipts.set(receipt, result);
  emit('status');
  return result;
}

const application = {
  async read({ resource, id }) {
    if (resource === 'status') return { data: statusDto(), revision: String(deviceRevision) };
    if (resource === 'stations' && !id)
      return { data: { stations: stations.map((entry) => ({ ...stationDto(entry), bans: entry.bans.map((trackId) => ({ trackId })) })) }, revision: `stations-${stationsRevision}` };
    if (resource === 'stations') {
      const entry = station(id);
      return {
        data: { ...stationDto(entry), bans: entry.bans.map((trackId) => ({ trackId, title: null, artist: null })), seedNames: {} },
        revision: entry.revision,
      };
    }
    if (resource === 'operations') {
      const operation = operations.get(id) ?? fail('operation-not-found');
      const { owner: _owner, ...dto } = operation;
      return { data: dto, revision: `${id}-${operation.status}` };
    }
    return fail('not-found');
  },
  async mutate({ resource, id, action, body, expectedRevision, idempotencyKey, principal }) {
    if (resource === 'commands') {
      if (expectedRevision !== String(deviceRevision)) {
        const replay = receipts.get(`${principal.id}:${idempotencyKey}`);
        if (replay) return replay;
        fail('stale-device-revision');
      }
      const command = body.action;
      if (command === 'pause' && !['playing', 'buffering'].includes(playback.state)) fail('invalid-playback-state');
      if (command === 'resume' && playback.state !== 'paused') fail('invalid-playback-state');
      if (command === 'play') station(body.stationId);
      return accept(principal, idempotencyKey, () => {
        if (command === 'play') {
          playback.stationId = body.stationId;
          playback.state = 'playing';
          playback.fault = null;
          startTrack(playback.index + 1);
        } else if (command === 'pause') {
          playback.state = 'paused';
          playback.heldAt = Date.now();
        } else if (command === 'resume') {
          playback.startedAt += Date.now() - (playback.heldAt ?? Date.now());
          playback.heldAt = null;
          playback.state = 'playing';
        } else if (command === 'stop') {
          playback.state = 'stopped';
          playback.heldAt = null;
        } else if (command === 'skip') {
          if (playback.state === 'stopped') fail('no-active-queue');
          startTrack(playback.index + 1);
        } else if (command === 'volume') {
          volume = body.volume;
        }
      });
    }
    if (resource === 'stations' && action === 'feedback') {
      const entry = station(id);
      if (expectedRevision !== entry.revision) fail('stale-station-revision');
      const soft = !['ban', 'unban'].includes(body.action);
      if (soft && body.feedbackRevision !== entry.feedbackRevision) fail('stale-feedback-revision');
      return accept(principal, idempotencyKey, () => {
        const item = () => {
          let found = entry.feedback.find((row) => row.trackId === body.trackId);
          if (!found) {
            found = { trackId: body.trackId, stationPreference: 0, restUntilMs: null };
            entry.feedback.push(found);
          }
          return found;
        };
        if (body.action === 'ban') {
          if (!entry.bans.includes(body.trackId)) entry.bans.push(body.trackId);
          entry.revision = String(Number(entry.revision) + 1);
        } else if (body.action === 'unban') {
          entry.bans = entry.bans.filter((trackId) => trackId !== body.trackId);
          entry.revision = String(Number(entry.revision) + 1);
        } else if (body.action === 'favour') item().stationPreference = 1;
        else if (body.action === 'avoid') item().stationPreference = -1;
        else if (body.action === 'neutral') item().stationPreference = 0;
        else if (body.action === 'rest') item().restUntilMs = body.restUntilMs;
        else if (body.action === 'unrest') item().restUntilMs = null;
        entry.feedbackRevision += 1;
        stationsRevision += 1;
        emit('stations');
      });
    }
    return fail('not-found');
  },
  currentRevision({ resource, id }) {
    if (resource === 'stations' && id) return station(id).revision;
    return String(deviceRevision);
  },
  subscribe({ onEvent }) {
    listeners.add(onEvent);
    return () => listeners.delete(onEvent);
  },
  async artwork({ id }) {
    const track = TRACKS.find((entry) => entry.id === id) ?? fail('artwork-unavailable');
    return { bytes: cover(track.hue), contentType: 'image/png' };
  },
};

// ── Covers: a soft two-color field per track, as a real PNG ───────────────

function cover(hue) {
  const size = 240;
  const rgb = (h, s, l) => {
    const k = (n) => (n + h / 30) % 12;
    const a = s * Math.min(l, 1 - l);
    const f = (n) => l - a * Math.max(-1, Math.min(k(n) - 3, Math.min(9 - k(n), 1)));
    return [f(0), f(8), f(4)].map((value) => Math.round(value * 255));
  };
  const [ax, ay, bx, by] = [0.25, 0.3, 0.8, 0.75];
  const first = rgb(hue, 0.65, 0.55);
  const second = rgb((hue + 40) % 360, 0.5, 0.18);
  const rows = Buffer.alloc((size * 3 + 1) * size);
  for (let y = 0; y < size; y += 1) {
    rows[y * (size * 3 + 1)] = 0;
    for (let x = 0; x < size; x += 1) {
      const u = x / size;
      const v = y / size;
      const near = Math.hypot(u - ax, v - ay);
      const far = Math.hypot(u - bx, v - by);
      const t = Math.min(1, Math.max(0, near / (near + far)));
      const offset = y * (size * 3 + 1) + 1 + x * 3;
      for (let c = 0; c < 3; c += 1) rows[offset + c] = Math.round(first[c] * (1 - t) + second[c] * t);
    }
  }
  const crcTable = Array.from({ length: 256 }, (_, n) => {
    let c = n;
    for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    return c >>> 0;
  });
  const crc = (bytes) => {
    let c = 0xffffffff;
    for (const byte of bytes) c = crcTable[(c ^ byte) & 0xff] ^ (c >>> 8);
    return (c ^ 0xffffffff) >>> 0;
  };
  const chunk = (type, data) => {
    const head = Buffer.alloc(8);
    head.writeUInt32BE(data.length, 0);
    head.write(type, 4, 'ascii');
    const tail = Buffer.alloc(4);
    tail.writeUInt32BE(crc(Buffer.concat([head.subarray(4), data])), 0);
    return Buffer.concat([head, data, tail]);
  };
  const header = Buffer.alloc(13);
  header.writeUInt32BE(size, 0);
  header.writeUInt32BE(size, 4);
  header[8] = 8;
  header[9] = 2;
  return Buffer.concat([
    Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]),
    chunk('IHDR', header),
    chunk('IDAT', deflateSync(rows)),
    chunk('IEND', Buffer.alloc(0)),
  ]);
}

// ── Serve ─────────────────────────────────────────────────────────────────

const server = createRadioHttpsServer({
  authStore,
  application,
  tls: { keyPath, certPath },
  allowedOrigins: origins,
  sseRecheckMs: 1000,
});
const address = await server.listen({ host: '127.0.0.1', port });
process.stdout.write(`${JSON.stringify({ port: address.port, origins, fingerprint, keys })}\n`);

// The track moves on by itself at its end, as on the radio.
setInterval(() => {
  const track = current();
  if (track && playback.state === 'playing' && position() >= track.durationMs) {
    startTrack(playback.index + 1);
    deviceRevision += 1;
    emit('status');
  }
}, 500).unref();

const lines = createInterface({ input: process.stdin });
lines.on('line', (line) => {
  const [command, ...rest] = line.trim().split(/\s+/u);
  if (command === 'advance') startTrack(playback.index + 1);
  else if (command === 'state') {
    playback.state = rest[0];
    playback.fault = rest[0] === 'fault' ? (rest[1] ?? 'native-audio-fault') : null;
    playback.heldAt = rest[0] === 'paused' ? Date.now() : null;
  } else if (command === 'revoke') {
    const keyId = keys[rest[0]].split('.')[1];
    authStore.revokeApiKey({ sessionToken: owner.sessionToken, csrfToken: owner.csrfToken, keyId });
  } else if (command === 'stations') {
    stations[1].name = rest.join(' ') || stations[1].name;
    stationsRevision += 1;
    emit('stations');
    process.stdout.write('ok\n');
    return;
  } else return;
  deviceRevision += 1;
  emit('status');
  process.stdout.write('ok\n');
});
const shutdown = async () => {
  await server.close();
  authStore.close();
  rmSync(root, { recursive: true, force: true });
  process.exit(0);
};
process.on('SIGTERM', shutdown);
process.on('SIGINT', shutdown);
