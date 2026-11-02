// The card's words and decisions, without a browser: node --test tests/card.test.mjs
import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  applyChange,
  bottomOffset,
  chipChange,
  chooseFit,
  chosenChip,
  fitFull,
  formatAgo,
  formatClock,
  healthBanner,
  listLine,
  listOf,
  mainAction,
  mixColor,
  NOT_ANSWERING_BANNER,
  positionNow,
  remoteStateLabel,
  settled,
  selectionFacts,
  stationLine,
  stationStateLine,
  stationTint,
  steerData,
  steerNote,
  undoChange,
  viewOf,
  volumeDue,
  WEEK_MS,
  whyLine,
} from '../custom_components/lumae_radio/frontend/lumae-radio-card.js';

const NOW = Date.UTC(2026, 9, 12, 12);
const DAY = 86_400_000;

const entity = (state = 'playing', attributes = {}) => ({
  state,
  attributes: {
    friendly_name: 'Lumae Radio',
    radio_state: state === 'idle' ? 'stopped' : state,
    station_id: 'stn-morning',
    track_id: 'trk-holocene',
    media_title: 'Holocene',
    media_artist: 'Bon Iver',
    media_position: 64,
    media_duration: 336,
    media_position_updated_at: new Date(NOW).toISOString(),
    volume_level: 0.62,
    stations: [{ id: 'stn-morning', name: 'Morning drift', mode: 'daily', preparation: 'ready' }],
    standing: { preference: 0, rest_until_ms: null, banned: false },
    selection: { fit: 0.87, prior_rest_ms: 3 * 3_600_000 },
    health: {},
    can_steer: true,
    ...attributes,
  },
});

test('the remote names the state, never a stale one', () => {
  assert.equal(remoteStateLabel('playing', true), 'On air');
  assert.equal(remoteStateLabel('buffering', true), 'Starting');
  assert.equal(remoteStateLabel('fault', true), 'Needs attention');
  assert.equal(remoteStateLabel(null, true), 'Connecting');
  assert.equal(remoteStateLabel('playing', false), 'Not answering');
});

test('the big button pauses, resumes, plays or opens the stations', () => {
  assert.equal(mainAction({ state: 'playing' }), 'pause');
  assert.equal(mainAction({ state: 'buffering' }), 'pause');
  assert.equal(mainAction({ state: 'paused' }), 'resume');
  assert.equal(mainAction({ state: 'stopped', stationId: 's' }), 'play');
  assert.equal(mainAction({ state: 'stopped', stationId: null }), null);
  assert.equal(mainAction(null), null);
});

test('the station line and the why line read like the app', () => {
  assert.equal(stationLine({ name: 'Morning drift', mode: 'daily' }, 's'), 'Morning drift · Daily flow · Stealth');
  assert.equal(stationLine({ name: 'Deep focus', mode: 'steady' }, 's'), 'Deep focus · Steady · Stealth');
  assert.equal(stationLine(null, null), 'No station playing · Stealth');
  assert.equal(whyLine({ fit: 0.87, prior_rest_ms: 3 * 3_600_000 }), 'Fits the station 87% · last aired 3 hours ago');
  assert.equal(whyLine({ fit: null, prior_rest_ms: null }), 'First time on this radio');
  assert.equal(whyLine(null), null);
  assert.equal(formatAgo(20_000), '1 min ago');
  assert.equal(formatAgo(3 * DAY), '3 days ago');
});

test('clocks and the moving position', () => {
  assert.equal(formatClock(204_000), '3:24');
  assert.equal(formatClock(3_725_000), '1:02:05');
  const view = { state: 'playing', positionMs: 64_000, durationMs: 336_000, readAt: NOW };
  assert.equal(positionNow(view, NOW + 2_000), 66_000);
  assert.equal(positionNow({ ...view, state: 'paused' }, NOW + 2_000), 64_000);
  assert.equal(positionNow(view, NOW + 999_000), 336_000);
  assert.equal(positionNow({ positionMs: null }, NOW), null);
});

test('the banner says what is wrong in plain words', () => {
  assert.equal(healthBanner({ answering: false }), NOT_ANSWERING_BANNER);
  assert.match(healthBanner({ answering: true, state: 'fault', health: { fault: 'native-audio-fault' } }), /speaker connection/);
  assert.match(healthBanner({ answering: true, state: 'fault', health: { fault: 'brand-new-code' } }), /ran into a problem/);
  assert.match(healthBanner({ answering: true, state: 'playing', health: { continuity: 'offline-cache' } }), /out of reach/);
  assert.equal(healthBanner({ answering: true, state: 'playing', health: {} }), null);
});

test('chips: which is chosen, what a tap sends, and how undo goes back', () => {
  const none = { preference: 0, rest_until_ms: null, banned: false };
  assert.equal(chosenChip(none, NOW), null);
  assert.equal(chosenChip({ ...none, preference: 1 }, NOW), 'favor');
  assert.equal(chosenChip({ ...none, preference: -1, rest_until_ms: NOW + 1 }, NOW), 'rest');
  assert.equal(chosenChip({ ...none, rest_until_ms: NOW - 1 }, NOW), null);
  assert.equal(chosenChip({ ...none, banned: true, preference: 1 }, NOW), 'ban');

  assert.deepEqual(chipChange('favor', false, NOW), { choice: 'favor' });
  assert.deepEqual(chipChange('favor', true, NOW), { choice: 'no_preference' });
  assert.deepEqual(chipChange('less', false, NOW), { choice: 'less' });
  assert.deepEqual(chipChange('rest', false, NOW), { choice: 'rest', restUntilMs: NOW + WEEK_MS });
  assert.deepEqual(chipChange('rest', true, NOW), { choice: 'end_rest' });
  assert.deepEqual(chipChange('ban', true, NOW), { choice: 'allow' });

  const rested = { ...none, rest_until_ms: NOW + 3 * DAY };
  const change = { choice: 'end_rest' };
  assert.equal(applyChange(rested, change).rest_until_ms, null);
  assert.deepEqual(undoChange(change, rested, NOW), { choice: 'rest', restUntilMs: NOW + 3 * DAY });
  assert.deepEqual(undoChange({ choice: 'favor' }, { ...none, preference: -1 }, NOW), { choice: 'less' });
  assert.deepEqual(undoChange({ choice: 'ban' }, none, NOW), { choice: 'allow' });
});

test('notes and the action data', () => {
  assert.equal(steerNote({ choice: 'favor' }, 'Morning drift', NOW), 'Favored on Morning drift');
  assert.equal(steerNote({ choice: 'rest', restUntilMs: NOW + WEEK_MS }, 'X', NOW), 'Resting for a week on X');
  assert.equal(steerNote({ choice: 'rest', restUntilMs: NOW + DAY }, 'X', NOW), 'Resting for a day on X');
  assert.equal(steerNote({ choice: 'ban' }, null, NOW), 'Banned from this station · skipping now');
  assert.deepEqual(steerData({ choice: 'less' }), { choice: 'less' });
  assert.deepEqual(steerData({ choice: 'rest', restUntilMs: NOW }), {
    choice: 'rest',
    rest_until: '2026-10-12T12:00:00.000Z',
  });
});

test('stations: tint and state line as in the app', () => {
  assert.ok(['amber', 'teal', 'rose', 'lavender', 'sky'].includes(stationTint('stn-morning')));
  assert.equal(stationTint('stn-morning'), stationTint('stn-morning'));
  assert.equal(stationStateLine({ mode: 'daily', preparation: 'ready' }), 'Daily flow · ready');
  assert.equal(stationStateLine({ mode: 'steady', steady_energy: 0.4, preparation: 'preparing' }), 'Steady at 40% · preparing');
  assert.equal(stationStateLine({ mode: 'daily', preparation: 'needed' }), 'Daily flow · needs preparing');
  assert.equal(stationStateLine({ mode: 'daily', preparation: 'ready', vibe: 'following' }), 'Follows your vibe · ready');
  assert.equal(stationStateLine({ mode: 'daily', preparation: 'ready', vibe: 'conflict' }), 'Your vibe and the radio disagree · choose one');
});

test('the entity becomes a view; an unavailable radio is not answering', () => {
  const view = viewOf(entity());
  assert.equal(view.answering, true);
  assert.equal(view.station.name, 'Morning drift');
  assert.equal(view.positionMs, 64_000);
  assert.equal(view.readAt, NOW);
  assert.equal(view.canSteer, true);
  assert.equal(viewOf({ state: 'unavailable', attributes: { friendly_name: 'Lumae Radio' } }).answering, false);
  assert.equal(viewOf(undefined), null);
});

test('volume goes out at most every 250 ms, and only when it changed', () => {
  assert.equal(volumeDue(0.5, null, NOW), true);
  assert.equal(volumeDue(0.51, { value: 0.5, at: NOW }, NOW + 100), false);
  assert.equal(volumeDue(0.51, { value: 0.5, at: NOW }, NOW + 300), true);
  assert.equal(volumeDue(0.5, { value: 0.5, at: NOW }, NOW + 300), false);
});

test('the light backdrop mixes a fifth of the cover into the ground', () => {
  assert.equal(mixColor('#FF0000', '#000000', 0.2), '#330000');
  assert.equal(mixColor('#D8A07A', '#F7F7F4', 0.2), '#f1e6dc');
});

test('selection facts', () => {
  const facts = selectionFacts({ fit: 0.873, prior_rest_ms: 19 * DAY, prior_radio_plays: 4, energy_target: 0.55, track_energy: 0.61, scarcity: 'preferred' });
  assert.equal(facts.fitPercent, 87);
  assert.equal(facts.lastAired, '19 days');
  assert.equal(facts.energy, 'Above target');
  assert.equal(facts.rotation, 'Preferred gap kept');
  assert.equal(selectionFacts(null).lastAired, 'Never');
});

test('a press shows ahead until the radio reports it', () => {
  const play = { state: 'buffering', settle: ['buffering', 'playing'], stationId: 'stn-focus' };
  assert.equal(settled(play, { state: 'playing', stationId: 'stn-morning' }), false);
  assert.equal(settled(play, { state: 'playing', stationId: 'stn-focus' }), true);
  const pause = { state: 'paused', settle: ['paused'], stationId: null };
  assert.equal(settled(pause, { state: 'playing', stationId: 's' }), false);
  assert.equal(settled(pause, { state: 'paused', stationId: 's' }), true);
});

test('an album, playlist or collection on air takes the station line (RL.11)', () => {
  const list = { kind: 'album', id: 'al-1', name: 'Kind of Blue', artist: 'Miles Davis', index: 2, count: 5, place: 'Album · 3 of 5' };
  const view = viewOf(entity('playing', { station_id: null, list }));
  assert.deepEqual(view.list, { kind: 'album', name: 'Kind of Blue', index: 2, count: 5, shuffled: false });
  assert.equal(listLine(view.list), 'Kind of Blue · Album · 3 of 5 · Stealth');
  // A shuffled list says so (RL.6).
  assert.equal(
    listLine(viewOf(entity('playing', { station_id: null, list: { ...list, shuffled: true } })).list),
    'Kind of Blue · Album · 3 of 5 · Shuffled · Stealth',
  );
  assert.equal(listLine({ kind: 'collection', name: 'Rain', index: 0, count: 1 }), 'Rain · Collection · 1 of 1 · Stealth');
  // A station plays, or an older integration sends nothing: no list.
  assert.equal(viewOf(entity()).list, null);
  assert.equal(listOf({ ...list, kind: 'station' }), null);
  assert.equal(listOf({ ...list, index: 5 }), null);
  assert.equal(listOf({ ...list, index: '2' }), null);
});

test('short of height: a smaller cover, the why line before 160 px, then nothing below 120 (HA.3)', () => {
  // The full card while playing on the wall iPad: 715 px, 421 of them besides the cover.
  const full = { height: 715, art: 294, why: 42 };
  assert.deepEqual(fitFull(800, full), { art: null, tight: false });
  assert.deepEqual(fitFull(715, full), { art: null, tight: false });
  assert.deepEqual(fitFull(600, full), { art: 179, tight: false });
  assert.deepEqual(fitFull(560, full), { art: 181, tight: true });
  assert.deepEqual(fitFull(500, full), { art: 121, tight: true });
  assert.equal(fitFull(497, full), null);
  // Losing the why line can give a smaller cover its whole width back.
  assert.deepEqual(fitFull(570, { height: 600, art: 180, why: 42 }), { art: null, tight: true });
  // Without a why line the cover shrinks to 120, then the full card no longer fits.
  const noWhy = { height: 673, art: 294, why: 0 };
  assert.deepEqual(fitFull(500, noWhy), { art: 121, tight: false });
  assert.equal(fitFull(498, noWhy), null);
  // A narrow card, whose cover is already under 160, keeps the why line until the cover would shrink.
  assert.deepEqual(fitFull(600, { height: 600, art: 150, why: 42 }), { art: null, tight: false });
  assert.deepEqual(fitFull(580, { height: 600, art: 150, why: 42 }), { art: null, tight: true });
});

test('fitting the screen: below its top, then compact, then the screen for a card you scroll to (HA.3)', () => {
  const playing = { height: 715, art: 294, why: 42 };
  const stopped = { height: 578, art: 294, why: 0 };
  const compact = () => 254;
  const unmeasured = () => assert.fail('the compact card is measured only when the full one fails');
  // The wall iPad: 475 px under the card. Stopped, a 191 px cover; playing, compact, with the 475 px
  // for its cover to grow into.
  assert.deepEqual(chooseFit({ below: 475, screen: 682 }, stopped, unmeasured), {
    compact: false,
    art: 191,
    tight: false,
  });
  assert.deepEqual(chooseFit({ below: 475, screen: 682 }, playing, compact), {
    compact: true,
    art: null,
    tight: false,
    available: 475,
  });
  // A card that starts too far down for even the compact card fits the screen you scroll it into.
  assert.deepEqual(chooseFit({ below: 150, screen: 716 }, playing, compact), {
    compact: false,
    art: null,
    tight: false,
  });
  assert.deepEqual(chooseFit({ below: -300, screen: 300 }, playing, compact).compact, true);
  // Fixed rows: their height, never the screen.
  assert.deepEqual(chooseFit({ box: 504 }, playing, unmeasured), { compact: false, art: 125, tight: true });
  assert.deepEqual(chooseFit({ box: 248 }, playing, unmeasured), {
    compact: true,
    art: null,
    tight: false,
    available: 248,
  });
});

test('the room kept free at the bottom: 72 px unless set (HA.3)', () => {
  assert.equal(bottomOffset({}), 72);
  assert.equal(bottomOffset({ bottom_offset: null }), 72);
  assert.equal(bottomOffset({ bottom_offset: 0 }), 0);
  assert.equal(bottomOffset({ bottom_offset: 120 }), 120);
  assert.equal(bottomOffset({ bottom_offset: -8 }), 72);
  assert.equal(bottomOffset({ bottom_offset: 'tall' }), 72);
});
