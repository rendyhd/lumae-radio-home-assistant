// The card's words and decisions, without a browser: node --test tests/card.test.mjs
import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  applyChange,
  chipChange,
  chosenChip,
  formatAgo,
  formatClock,
  healthBanner,
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
