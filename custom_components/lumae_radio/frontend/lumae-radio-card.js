/**
 * Lumae Radio card: what the radio plays, as the Lumae app's remote shows it.
 *
 * Artwork, title and why this track; progress; stop, play/pause, skip and the station switcher;
 * volume; and Favor · Less · Rest · Ban for the playing track. It reads the `media_player` of the
 * Lumae Radio integration and calls its actions; it has no setup screens of its own.
 *
 * The words and decisions match the app (src/lib/radioRemoteView.ts, src/lib/radioStatus.ts),
 * and the colors are the app's tokens (src/constants/theme.ts). The pure parts are exported and
 * tested on their own (tests/card.test.mjs).
 */

export const CARD_VERSION = '0.1.0';
const DAY_MS = 86_400_000;
export const WEEK_MS = 7 * DAY_MS;

// ── What the remote says ───────────────────────────────────────────────────

export const STATE_LABELS = {
  playing: 'On air',
  paused: 'Paused',
  stopped: 'Stopped',
  buffering: 'Starting',
  fault: 'Needs attention',
};

export const NOT_ANSWERING_BANNER =
  'Can’t reach the radio right now. What you see may be out of date.';

/** "Not answering" once the radio stops answering (never a stale "On air"). */
export function remoteStateLabel(state, answering) {
  if (!answering) return 'Not answering';
  return STATE_LABELS[state] ?? 'Connecting';
}

/** The one command the big round button sends now, or null (it opens the stations instead). */
export function mainAction(view) {
  if (!view) return null;
  if (view.state === 'playing' || view.state === 'buffering') return 'pause';
  if (view.state === 'paused') return 'resume';
  return view.stationId ? 'play' : null;
}

/** "Morning drift · Daily flow · Stealth" under the radio's name. */
export function stationLine(station, stationId) {
  if (!station) return stationId ? 'Stealth' : 'No station playing · Stealth';
  return `${station.name} · ${station.mode === 'steady' ? 'Steady' : 'Daily flow'} · Stealth`;
}

export function formatAgo(ms) {
  const minutes = Math.round(ms / 60000);
  if (minutes < 60) return `${Math.max(1, minutes)} min ago`;
  const hours = Math.round(ms / 3600000);
  if (hours < 48) return `${hours} hour${hours === 1 ? '' : 's'} ago`;
  return `${Math.round(ms / 86400000)} days ago`;
}

/** "Fits the station 87% · last aired 3 hours ago", or null without an explanation. */
export function whyLine(selection) {
  if (!selection) return null;
  const parts = [];
  if (typeof selection.fit === 'number')
    parts.push(`Fits the station ${Math.round(selection.fit * 100)}%`);
  parts.push(
    typeof selection.prior_rest_ms === 'number'
      ? `last aired ${formatAgo(selection.prior_rest_ms)}`
      : 'first time on this radio',
  );
  const line = parts.join(' · ');
  return line.charAt(0).toUpperCase() + line.slice(1);
}

/** "3:24" for 204000 ms. */
export function formatClock(ms) {
  const total = Math.max(0, Math.round(ms / 1000));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = String(total % 60).padStart(2, '0');
  return hours ? `${hours}:${String(minutes).padStart(2, '0')}:${seconds}` : `${minutes}:${seconds}`;
}

/** "19 days", "5 hours", "40 minutes". */
export function formatRest(ms) {
  const minutes = Math.round(ms / 60000);
  if (minutes < 60) return `${Math.max(1, minutes)} minute${minutes === 1 ? '' : 's'}`;
  const hours = Math.round(ms / 3600000);
  if (hours < 48) return `${hours} hour${hours === 1 ? '' : 's'}`;
  return `${Math.round(ms / 86400000)} days`;
}

/** Where the track is now, in ms: moving on from the last read while it plays. */
export function positionNow(view, now) {
  if (!view || typeof view.positionMs !== 'number') return null;
  const moved = view.state === 'playing' && view.readAt ? Math.max(0, now - view.readAt) : 0;
  const position = view.positionMs + moved;
  return typeof view.durationMs === 'number' ? Math.min(position, view.durationMs) : position;
}

const ROTATION = {
  preferred: 'Preferred gap kept',
  'album-rest-shortened': 'Album gap shortened',
  'artist-rest-shortened': 'Artist gap shortened',
  'recording-rest-shortened': 'Track gap shortened',
};

/** The why-this-track facts in the remote's words. */
export function selectionFacts(selection) {
  const energy = selection?.track_energy;
  const target = selection?.energy_target;
  let relation = null;
  if (typeof energy === 'number' && typeof target === 'number') {
    const difference = energy - target;
    relation = Math.abs(difference) <= 0.01 ? 'at' : difference > 0 ? 'above' : 'below';
  }
  return {
    fitPercent: typeof selection?.fit === 'number' ? Math.round(selection.fit * 100) : null,
    lastAired:
      typeof selection?.prior_rest_ms === 'number' ? formatRest(selection.prior_rest_ms) : 'Never',
    energy:
      relation === 'at'
        ? 'At target'
        : relation === 'above'
          ? 'Above target'
          : relation === 'below'
            ? 'Below target'
            : 'Not measured',
    energyValue: typeof energy === 'number' ? energy : null,
    targetValue: typeof target === 'number' ? target : null,
    rotation: selection?.scarcity ? (ROTATION[selection.scarcity] ?? null) : null,
    earlierPlays: selection?.prior_radio_plays ?? 0,
  };
}

const FAULTS = {
  'clock-uncertain':
    'The radio isn’t sure of the time yet, so it waits before playing. It sets its clock once it’s online.',
  'native-audio-fault': 'The radio’s sound output stopped working. Check the speaker connection.',
  'media-unavailable': 'The radio couldn’t get this track from your music server.',
  'playback-unavailable': 'The radio’s player isn’t answering.',
  'connection-lost': 'The radio’s player isn’t answering.',
  unavailable:
    'The radio’s player isn’t running yet. If the radio has no sound output, choose one in the Lumae app: ⋯ → The radio.',
  'output-not-configured':
    'The radio has no sound output yet. Choose one in the Lumae app: ⋯ → The radio.',
  'delivery-ledger-failed': 'The radio couldn’t record what it played. It will try again.',
  'no-active-queue': 'Nothing is queued on the radio. Press play to start a station.',
  'catalogue-not-ready':
    'The radio doesn’t have your library yet. The Lumae app shows its library sync under ⋯ → Music.',
  'preparation-not-ready': 'This station is still being prepared.',
  'preparation-changed': 'The station changed. The radio is picking up the new version.',
  'station-not-found': 'This station is gone from the radio.',
  'provider-scope-changed': 'The radio is connected to a different music library now.',
  'cached-media-unavailable': 'The radio couldn’t find this track in its saved music.',
  'unsupported-media': 'The radio can’t play this track’s file format.',
  'output-change-pending': 'The radio is switching its sound output.',
  'delivery-replay-pending': 'The radio is catching up on what it played.',
  'no-candidate-within-spacing-floor':
    'Nothing on this station can play now without repeating sooner than its Rotation allows. Shorten its gaps or widen its sound.',
  exhausted:
    'Nothing on this station can play now without repeating sooner than its Rotation allows. Shorten its gaps or widen its sound.',
};

/** A radio fault code in plain words; never the code itself. */
export function faultText(code) {
  if (!code) return null;
  return (
    FAULTS[code] ??
    'The radio ran into a problem. Press play to try again; if it stays, restart the radio.'
  );
}

/** One line for the banner above the artwork, or null when all is well. */
export function healthBanner(view) {
  if (!view) return null;
  if (!view.answering) return NOT_ANSWERING_BANNER;
  const health = view.health ?? {};
  if (view.state === 'fault') return faultText(health.fault) ?? 'The radio has a problem.';
  if (health.continuity === 'offline-cache')
    return 'Your music server is out of reach. The radio plays from what it saved.';
  if (health.maintenance === 'running') return 'The radio is tidying up in the background.';
  if (health.maintenance === 'failed')
    return 'The radio’s last tidy-up didn’t finish. It will try again.';
  if (health.auto_resume_suppressed && view.state !== 'playing')
    return 'The radio restarted and is waiting for you to press play.';
  if (health.clock_trusted === false) return faultText('clock-uncertain');
  return null;
}

// ── Steering this track ────────────────────────────────────────────────────

/** The chips under the volume (Favor · Less · Rest · Ban), as on the remote. */
export const STEER_CHIPS = [
  { id: 'favor', label: '↑ Favor' },
  { id: 'less', label: '↓ Less' },
  { id: 'rest', label: 'Rest a week' },
  { id: 'ban', label: 'Ban' },
];

export const NO_STANDING = { preference: 0, rest_until_ms: null, banned: false };

/** Which chip shows as chosen. */
export function chosenChip(standing, now) {
  if (!standing) return null;
  if (standing.banned) return 'ban';
  if (typeof standing.rest_until_ms === 'number' && standing.rest_until_ms > now) return 'rest';
  if (standing.preference === 1) return 'favor';
  if (standing.preference === -1) return 'less';
  return null;
}

/**
 * What tapping a chip asks for: choosing it, or undoing it when it is already chosen. A change is
 * the integration's `steer_track` choice, with `restUntilMs` for a rest.
 */
export function chipChange(chip, chosen, now) {
  switch (chip) {
    case 'favor':
      return { choice: chosen ? 'no_preference' : 'favor' };
    case 'less':
      return { choice: chosen ? 'no_preference' : 'less' };
    case 'rest':
      return chosen ? { choice: 'end_rest' } : { choice: 'rest', restUntilMs: now + WEEK_MS };
    default:
      return { choice: chosen ? 'allow' : 'ban' };
  }
}

/** The standing after a change, shown at once while the radio applies it. */
export function applyChange(standing, change) {
  const base = standing ?? NO_STANDING;
  switch (change.choice) {
    case 'ban':
      return { ...base, banned: true };
    case 'allow':
      return { ...base, banned: false };
    case 'favor':
      return { ...base, preference: 1 };
    case 'less':
      return { ...base, preference: -1 };
    case 'no_preference':
      return { ...base, preference: 0 };
    case 'rest':
      return { ...base, rest_until_ms: change.restUntilMs };
    default:
      return { ...base, rest_until_ms: null };
  }
}

/** The change that undoes `change`, back to the standing before it. */
export function undoChange(change, before, now) {
  const base = before ?? NO_STANDING;
  switch (change.choice) {
    case 'ban':
    case 'allow':
      return { choice: base.banned ? 'ban' : 'allow' };
    case 'rest':
    case 'end_rest':
      return typeof base.rest_until_ms === 'number' && base.rest_until_ms > now
        ? { choice: 'rest', restUntilMs: base.rest_until_ms }
        : { choice: 'end_rest' };
    default:
      return {
        choice: base.preference === 1 ? 'favor' : base.preference === -1 ? 'less' : 'no_preference',
      };
  }
}

/** "a day", "a week", "30 days" for a rest from now. */
export function restLength(untilMs, now) {
  const days = Math.max(1, Math.round((untilMs - now) / DAY_MS));
  if (days === 1) return 'a day';
  if (days === 7) return 'a week';
  return `${days} days`;
}

/** The note after a change. */
export function steerNote(change, stationName, now) {
  const station = stationName || 'this station';
  switch (change.choice) {
    case 'favor':
      return `Favored on ${station}`;
    case 'less':
      return `Plays less often on ${station}`;
    case 'no_preference':
      return `No preference on ${station}`;
    case 'rest':
      return `Resting for ${restLength(change.restUntilMs, now)} on ${station}`;
    case 'end_rest':
      return `Back in rotation on ${station}`;
    case 'ban':
      return `Banned from ${station} · skipping now`;
    default:
      return `Allowed on ${station} again`;
  }
}

/** The action's data for a change. */
export function steerData(change) {
  return change.choice === 'rest'
    ? { choice: 'rest', rest_until: new Date(change.restUntilMs).toISOString() }
    : { choice: change.choice };
}

// ── Stations ──────────────────────────────────────────────────────────────

const TINTS = {
  amber: ['#D4A54A', '#5A3A1A', '#2A1810'],
  teal: ['#6EC4B8', '#2A4A48', '#0F1F22'],
  rose: ['#D48AA0', '#4A2028', '#1F1418'],
  lavender: ['#C9A0E8', '#2A1A3E', '#1A1424'],
  sky: ['#88C5E8', '#1A3348', '#0A1824'],
};
const TINT_NAMES = ['amber', 'teal', 'rose', 'lavender', 'sky'];

/** A steady color for a station's cover, from its ID (the app picks the same). */
export function stationTint(stationId) {
  let hash = 0;
  for (let index = 0; index < stationId.length; index += 1)
    hash = (hash * 31 + stationId.charCodeAt(index)) % 2_147_483_647;
  return TINT_NAMES[hash % TINT_NAMES.length];
}

const VIBE_STATE_LINES = {
  'other-account': 'Vibe from another account',
  deleted: 'Its vibe was deleted',
  missing: 'Its vibe is no longer synced',
  rejected: 'AudioMuse-AI didn’t take its changes',
  unusable: 'Its vibe can’t be used now',
};

/** One line under a station's name. */
export function stationStateLine(station) {
  const mode =
    station.mode === 'steady'
      ? typeof station.steady_energy === 'number'
        ? `Steady at ${Math.round(station.steady_energy * 100)}%`
        : 'Steady'
      : 'Daily flow';
  if (station.vibe) {
    if (station.vibe === 'conflict') return 'Your vibe and the radio disagree · choose one';
    if (station.vibe !== 'following' && station.vibe !== 'pushing')
      return VIBE_STATE_LINES[station.vibe] ?? 'Its vibe needs a look in the Lumae app';
  }
  switch (station.preparation) {
    case 'preparing':
      return `${mode} · preparing`;
    case 'failed':
      return 'Couldn’t prepare · the Lumae app shows why';
    case 'needed':
      return `${mode} · needs preparing`;
    default:
      return station.vibe ? 'Follows your vibe · ready' : `${mode} · ready`;
  }
}

// ── The entity, as the card reads it ──────────────────────────────────────

/** What the card shows, from the media player's state; null for a missing entity. */
export function viewOf(stateObj) {
  if (!stateObj) return null;
  const attributes = stateObj.attributes ?? {};
  const answering = !['unavailable', 'unknown'].includes(stateObj.state);
  const stations = Array.isArray(attributes.stations) ? attributes.stations : [];
  const stationId = attributes.station_id ?? null;
  const updated = Date.parse(attributes.media_position_updated_at ?? '');
  return {
    answering,
    name: attributes.friendly_name ?? 'Lumae Radio',
    state: attributes.radio_state ?? null,
    stationId,
    station: stations.find((station) => station.id === stationId) ?? null,
    stations,
    trackId: attributes.track_id ?? null,
    title: attributes.media_title ?? null,
    artist: attributes.media_artist ?? null,
    album: attributes.media_album_name ?? null,
    picture: attributes.entity_picture ?? null,
    volume: typeof attributes.volume_level === 'number' ? attributes.volume_level : null,
    positionMs:
      typeof attributes.media_position === 'number' ? attributes.media_position * 1000 : null,
    durationMs:
      typeof attributes.media_duration === 'number' ? attributes.media_duration * 1000 : null,
    readAt: Number.isFinite(updated) ? updated : null,
    standing: attributes.standing ?? NO_STANDING,
    selection: attributes.selection ?? null,
    health: attributes.health ?? {},
    canSteer: attributes.can_steer === true,
  };
}

/**
 * Whether the radio now reports what a press asked for, so the card stops showing it ahead:
 * a pause once paused; a play once starting or playing, on the station chosen.
 */
export function settled(optimistic, view) {
  if (!optimistic.settle.includes(view.state)) return false;
  return !optimistic.stationId || view.stationId === optimistic.stationId;
}

/** Whether a dragged volume should go out now (at most every 250 ms). */
export const VOLUME_SEND_MS = 250;
export function volumeDue(value, sent, now) {
  if (!sent) return true;
  return Math.round(value * 100) !== Math.round(sent.value * 100) && now - sent.at >= VOLUME_SEND_MS;
}

// ── Look ──────────────────────────────────────────────────────────────────

const THEMES = {
  dark: {
    bg: '#0D0D0F',
    surface: '#161719',
    surface2: '#202225',
    surfaceDim: '#111214',
    text: '#F4F3F1',
    text2: '#A6A7AB',
    muted: '#6D6E72',
    accent: '#D8A07A',
    fillA: '#EAB98F',
    fillB: '#B37458',
    accentSoft: 'rgba(216,160,122,.16)',
    border: '#2A2B2E',
    overlay: '#08080A',
    danger: '#E85454',
    teal: '#7AD0C2',
    gold: '#E0A93E',
  },
  light: {
    bg: '#F7F7F4',
    surface: '#FFFFFF',
    surface2: '#EAE9E6',
    surfaceDim: '#F1F0ED',
    text: '#151619',
    text2: '#57585B',
    muted: '#85868A',
    accent: '#8C5331',
    fillA: '#B37646',
    fillB: '#7E432B',
    accentSoft: 'rgba(140,83,49,.12)',
    border: '#DFDEDB',
    overlay: '#08080A',
    danger: '#C23B3B',
    teal: '#218373',
    gold: '#A97416',
  },
};

/** 20% of `color` mixed into `base`, for the light backdrop's tint. */
export function mixColor(color, base, share) {
  const parse = (hex) => [1, 3, 5].map((index) => parseInt(hex.slice(index, index + 2), 16));
  const [a, b] = [parse(color), parse(base)];
  return `#${a
    .map((value, index) => Math.round(value * share + b[index] * (1 - share)))
    .map((value) => value.toString(16).padStart(2, '0'))
    .join('')}`;
}

const GLYPH = {
  steer:
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/></svg>',
  stop: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><rect x="6" y="6" width="12" height="12" rx="2.5"/></svg>',
  play: '<svg viewBox="0 0 28 28" fill="currentColor"><polygon points="5.04,5.04 5.04,22.96 22.96,14"/></svg>',
  pause:
    '<svg viewBox="0 0 28 28" fill="currentColor"><rect x="7.28" y="5.04" width="4.48" height="17.92"/><rect x="16.24" y="5.04" width="4.48" height="17.92"/></svg>',
  next: '<svg viewBox="0 0 24 24" fill="currentColor"><polygon points="2.88,2.88 2.88,21.12 16.32,12"/><rect x="18.24" y="2.88" width="2.88" height="18.24"/></svg>',
  stations:
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-linecap="round" stroke-width="1.6"><path d="M7 8l9-4.5"/><rect x="3" y="8" width="18" height="12.5" rx="2.5"/><path d="M6.5 12h4.5M6.5 14.25h4.5M6.5 16.5h4.5" stroke-width="1.4"/><circle cx="16" cy="14.25" r="2.6"/></svg>',
  speaker:
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M11 5L6 9H3v6h3l5 4z"/></svg>',
  spark:
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/></svg>',
  chevron:
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M9 6l6 6-6 6"/></svg>',
  close:
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>',
  ban: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><circle cx="12" cy="12" r="8.5"/><path d="M6 6l12 12"/></svg>',
};

const STYLE = `
:host { display: block; }
[hidden] { display: none !important; }
ha-card { overflow: hidden; background: var(--lr-bg); color: var(--lr-text); border: 1px solid var(--lr-border); }
.lr { position: relative; container-type: inline-size; color: var(--lr-text); font-family: 'Lumae Geist', ui-sans-serif, system-ui, -apple-system, 'Segoe UI', sans-serif; -webkit-font-smoothing: antialiased; }
:host([data-theme=dark]) { ${vars(THEMES.dark)} --lr-cover-opacity: .72; }
:host([data-theme=light]) { ${vars(THEMES.light)} --lr-cover-opacity: .35; }
.mono { font-family: 'Lumae Geist Mono', ui-monospace, 'SF Mono', Menlo, monospace; }
button { font: inherit; color: inherit; background: none; border: 0; padding: 0; cursor: pointer; -webkit-tap-highlight-color: transparent; }
button:disabled { opacity: .35; cursor: default; }
button:focus-visible, input:focus-visible { outline: 2px solid var(--lr-accent); outline-offset: 2px; border-radius: 999px; }
svg { display: block; width: 100%; height: 100%; }

.backdrop { position: absolute; inset: 0; overflow: hidden; pointer-events: none; }
.backdrop img { position: absolute; inset: -40px; width: calc(100% + 80px); height: calc(100% + 80px); object-fit: cover; filter: blur(24px); opacity: var(--lr-cover-opacity); transition: opacity .6s ease; }
.backdrop .shade { position: absolute; inset: 0; background: var(--lr-shade); transition: background .6s ease; }

.content { position: relative; padding: 18px 0 16px; display: flex; flex-direction: column; align-items: stretch; }
header { display: flex; flex-direction: column; align-items: center; gap: 3px; padding: 0 16px; text-align: center; }
.kicker { display: flex; align-items: center; gap: 6px; font-size: 11px; font-weight: 500; letter-spacing: 1.3px; text-transform: uppercase; color: var(--lr-accent); }
.dot { width: 6px; height: 6px; border-radius: 50%; background: var(--lr-muted); flex: none; }
.dot.on { background: var(--lr-teal); }
.dot.fault { background: var(--lr-danger); }
.subline { font-size: 11px; color: var(--lr-text2); }

.banner { margin: 10px 24px 0; padding: 8px 16px; border-radius: 10px; background: color-mix(in srgb, var(--lr-surface) 82%, transparent); border: 1px solid var(--lr-border); font-size: 13px; line-height: 18px; color: var(--lr-text); }

.art { align-self: center; margin-top: 14px; width: min(294px, calc(100cqw - 96px)); min-width: 140px; aspect-ratio: 1; border-radius: 4px; overflow: hidden; position: relative;
  background: linear-gradient(135deg, var(--lr-surface2), var(--lr-surface), var(--lr-surfaceDim));
  box-shadow: 0 30px 35px -12px color-mix(in srgb, var(--lr-dominant) 55%, transparent); transition: box-shadow .6s ease; }
.art img { width: 100%; height: 100%; object-fit: cover; display: block; }
.art img[hidden] { display: none; }
.art .disc { position: absolute; inset: 16%; border-radius: 50%; background: color-mix(in srgb, var(--lr-muted) 20%, transparent); }
.art img:not([hidden]) + .disc { display: none; }

.meta { padding: 22px 32px 0; min-width: 0; }
.title { font-weight: 600; font-size: clamp(24px, 8.5cqw, 34px); line-height: 1.06; letter-spacing: -0.5px; color: var(--lr-text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.artist { margin-top: 6px; font-size: 14px; color: var(--lr-text2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.album { margin-top: 4px; font-size: 10px; letter-spacing: 1.5px; text-transform: uppercase; color: var(--lr-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.prompt { margin-top: 8px; font-size: 14px; color: var(--lr-accent); text-align: left; }
.why { margin-top: 10px; min-height: 32px; display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--lr-text2); text-align: left; max-width: 100%; }
.why .spark { width: 14px; height: 14px; flex: none; color: var(--lr-accent); }
.why .chev { width: 12px; height: 12px; flex: none; color: var(--lr-muted); }
.why span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.progress { padding: 16px 32px 0; }
.bar { position: relative; height: 2px; border-radius: 1px; background: var(--lr-border); }
.fill { position: absolute; left: 0; top: 0; bottom: 0; border-radius: 1px; background: var(--lr-accent); }
.knob { position: absolute; top: -3px; width: 8px; height: 8px; margin-left: -4px; border-radius: 50%; background: var(--lr-accent); }
.times { margin-top: 8px; display: flex; justify-content: space-between; font-size: 10px; letter-spacing: 1px; color: var(--lr-text2); font-variant-numeric: tabular-nums; }

.transport { padding: 10px 32px 0; display: flex; align-items: center; justify-content: space-between; }
.icon { width: 44px; height: 44px; display: grid; place-items: center; border-radius: 50%; color: var(--lr-text); }
.icon > svg { width: 22px; height: 22px; }
.icon.stop > svg { width: 20px; height: 20px; }
.icon.next > svg { width: 24px; height: 24px; }
.icon.steer { color: var(--lr-accent); }
.primary { width: 68px; height: 68px; border-radius: 50%; display: grid; place-items: center; background: var(--lr-text); color: var(--lr-bg);
  box-shadow: 0 10px 34px color-mix(in srgb, var(--lr-accent) 38%, transparent); transition: transform .12s ease; }
.primary:active:not(:disabled) { transform: scale(.96); }
.primary > svg { width: 28px; height: 28px; }
.spinner { width: 26px; height: 26px; border-radius: 50%; border: 2.5px solid color-mix(in srgb, var(--lr-bg) 30%, transparent); border-top-color: var(--lr-bg); animation: spin .9s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

.volume { padding: 8px 32px 0; display: flex; align-items: center; gap: 12px; }
.volume .speaker { width: 16px; height: 16px; color: var(--lr-text2); flex: none; }
.volume .value { width: 24px; text-align: right; font-size: 10px; color: var(--lr-text2); font-variant-numeric: tabular-nums; flex: none; }
input[type=range] { -webkit-appearance: none; appearance: none; flex: 1; height: 32px; margin: 0; background: transparent; cursor: pointer; --pct: 50%; }
input[type=range]::-webkit-slider-runnable-track { height: 4px; border-radius: 2px; background: linear-gradient(to right, var(--lr-accent) var(--pct), var(--lr-surface2) var(--pct)); }
input[type=range]::-moz-range-track { height: 4px; border-radius: 2px; background: var(--lr-surface2); }
input[type=range]::-moz-range-progress { height: 4px; border-radius: 2px; background: var(--lr-accent); }
input[type=range]::-webkit-slider-thumb { -webkit-appearance: none; width: 18px; height: 18px; margin-top: -7px; border-radius: 50%; border: 0; background: linear-gradient(135deg, var(--lr-fillA), var(--lr-fillB)); box-shadow: 0 2px 6px rgba(0,0,0,.3); }
input[type=range]::-moz-range-thumb { width: 18px; height: 18px; border-radius: 50%; border: 0; background: linear-gradient(135deg, var(--lr-fillA), var(--lr-fillB)); }
input[type=range]:focus-visible { outline: none; }
input[type=range]:focus-visible::-webkit-slider-thumb { outline: 2px solid var(--lr-accent); outline-offset: 2px; }

.chips { padding: 12px 20px 0; display: flex; flex-wrap: wrap; justify-content: center; gap: 8px; }
.chip { height: 30px; padding: 0 12px; border-radius: 999px; border: 1px solid var(--lr-border); background: color-mix(in srgb, var(--lr-bg) 35%, transparent);
  font-size: 11px; letter-spacing: .3px; color: var(--lr-text2); white-space: nowrap; }
.chip[aria-pressed=true] { border-color: color-mix(in srgb, var(--lr-accent) 55%, transparent); background: var(--lr-accentSoft); color: var(--lr-accent); }

.note { margin: 12px 24px 0; align-self: center; max-width: calc(100% - 48px); padding: 8px 14px; border-radius: 999px; background: color-mix(in srgb, var(--lr-surface) 95%, transparent); border: 1px solid var(--lr-border); font-size: 12px; color: var(--lr-text); display: flex; gap: 4px; align-items: baseline; flex-wrap: wrap; justify-content: center; text-align: center; }
.note button { color: var(--lr-accent); font-weight: 500; }

.sheet { position: absolute; inset: 0; z-index: 2; display: flex; flex-direction: column; background: var(--lr-surface); border-radius: 0; transform: translateY(100%); visibility: hidden; transition: transform .28s cubic-bezier(.2,.8,.2,1), visibility 0s linear .28s; }
.sheet.open { transform: none; visibility: visible; transition: transform .28s cubic-bezier(.2,.8,.2,1); }
.sheet-head { display: flex; align-items: flex-start; justify-content: space-between; padding: 18px 16px 8px 24px; gap: 12px; }
.sheet-kicker { font-size: 11px; font-weight: 500; letter-spacing: 1.3px; text-transform: uppercase; color: var(--lr-accent); }
.sheet-title { margin-top: 4px; font-size: 28px; font-weight: 600; letter-spacing: -0.5px; line-height: 1.1; }
.sheet-title .period { color: var(--lr-accent); }
.sheet-body { flex: 1; overflow-y: auto; padding: 4px 24px 20px; overscroll-behavior: contain; }
.sheet .icon > svg { width: 20px; height: 20px; }

.station { display: flex; align-items: center; gap: 14px; padding: 10px 0; width: 100%; text-align: left; border-bottom: 1px solid var(--lr-border); }
.station:last-child { border-bottom: 0; }
.orb { width: 56px; height: 56px; border-radius: 6px; flex: none; }
.station .text { flex: 1; min-width: 0; }
.station .name { font-size: 15px; font-weight: 500; color: var(--lr-text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.station .line { margin-top: 3px; font-size: 13px; color: var(--lr-text2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.station .line.warn { color: var(--lr-gold); }
.onair { display: flex; align-items: center; gap: 6px; font-size: 10px; letter-spacing: 1px; color: var(--lr-accent); flex: none; }
.bars { display: flex; align-items: flex-end; gap: 2px; height: 12px; }
.bars i { width: 2px; background: var(--lr-accent); border-radius: 1px; animation: eq 1s ease-in-out infinite; }
.bars i:nth-child(1) { height: 6px; } .bars i:nth-child(2) { height: 12px; animation-delay: -.3s; } .bars i:nth-child(3) { height: 8px; animation-delay: -.6s; }
.paused .bars i { animation: none; }
@keyframes eq { 50% { transform: scaleY(.4); } }
.bars i { transform-origin: bottom; }
.round { width: 40px; height: 40px; border-radius: 50%; border: 1px solid var(--lr-border); display: grid; place-items: center; color: var(--lr-text); flex: none; }
.round > svg { width: 16px; height: 16px; margin-left: 2px; }
.empty { padding: 24px 0; color: var(--lr-text2); font-size: 14px; }

.track-head { display: flex; gap: 12px; align-items: center; padding-bottom: 6px; }
.track-head img, .track-head .thumb { width: 52px; height: 52px; border-radius: 4px; object-fit: cover; flex: none; background: var(--lr-surface2); }
.track-head .text { flex: 1; min-width: 0; }
.track-head .name { font-size: 16px; font-weight: 600; line-height: 1.2; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.track-head .sub { margin-top: 2px; font-size: 13px; color: var(--lr-text2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.stealth { font-size: 10px; letter-spacing: 1px; text-transform: uppercase; color: var(--lr-muted); flex: none; }
.label { margin: 18px 0 8px; font-size: 11px; font-weight: 500; letter-spacing: 1.3px; text-transform: uppercase; color: var(--lr-accent); }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.cell { padding: 10px 12px; border-radius: 10px; background: var(--lr-surfaceDim); border: 1px solid var(--lr-border); min-width: 0; }
.cell .k { font-size: 11px; color: var(--lr-text2); }
.cell .v { margin-top: 4px; font-size: 18px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.energy { margin-top: 8px; }
.energy .head { display: flex; justify-content: space-between; gap: 8px; font-size: 11px; color: var(--lr-text2); }
.energy .verdict { color: var(--lr-text); font-weight: 500; }
.scale-bar { position: relative; height: 4px; margin: 12px 0 8px; border-radius: 2px; background: var(--lr-surface2); }
.scale-bar .target { position: absolute; top: -4px; width: 2px; height: 12px; margin-left: -1px; background: var(--lr-text2); }
.scale-bar .point { position: absolute; top: -3px; width: 10px; height: 10px; margin-left: -5px; border-radius: 50%; background: var(--lr-accent); }
.scale { display: flex; justify-content: space-between; font-size: 10px; color: var(--lr-muted); letter-spacing: .5px; }
.facts { margin-top: 8px; }
.fact { display: flex; justify-content: space-between; gap: 12px; padding: 8px 0; border-bottom: 1px solid var(--lr-border); font-size: 13px; }
.fact:last-child { border-bottom: 0; }
.fact .k { color: var(--lr-text2); }
.segment { display: flex; padding: 3px; border-radius: 999px; background: var(--lr-surfaceDim); border: 1px solid var(--lr-border); }
.segment button { flex: 1; height: 32px; padding: 0 6px; border-radius: 999px; font-size: 12px; color: var(--lr-text2); white-space: nowrap; }
.segment button[aria-pressed=true] { background: var(--lr-accentSoft); color: var(--lr-accent); }
.hint { margin-top: 8px; font-size: 12px; color: var(--lr-text2); line-height: 1.4; }
.rest-row { margin-top: 14px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.rest-row .k { flex-basis: 100%; font-size: 13px; color: var(--lr-text2); }
.link { margin-top: 10px; font-size: 13px; color: var(--lr-accent); }
.danger { margin-top: 18px; display: flex; align-items: center; gap: 8px; font-size: 14px; color: var(--lr-danger); }
.danger svg { width: 18px; height: 18px; }
.allow { margin-top: 18px; font-size: 14px; color: var(--lr-accent); }

.confirm { position: absolute; inset: 0; z-index: 3; display: grid; place-items: center; padding: 24px; background: color-mix(in srgb, var(--lr-overlay) 55%, transparent); }
.confirm[hidden] { display: none; }
.dialog { width: 100%; max-width: 320px; padding: 20px; border-radius: 16px; background: var(--lr-surface); border: 1px solid var(--lr-border); }
.dialog .h { font-size: 17px; font-weight: 600; }
.dialog .p { margin-top: 8px; font-size: 13px; line-height: 1.45; color: var(--lr-text2); }
.dialog .actions { margin-top: 18px; display: flex; justify-content: flex-end; gap: 8px; }
.pill { height: 36px; padding: 0 16px; border-radius: 999px; border: 1px solid var(--lr-border); font-size: 14px; }
.pill.bad { background: var(--lr-danger); border-color: var(--lr-danger); color: #fff; }
.message { padding: 24px; font-size: 14px; color: var(--lr-text2); }

@container (max-width: 380px) {
  .chips { padding: 12px 12px 0; gap: 6px; }
  .chip { padding: 0 10px; }
}
@container (max-width: 340px) {
  .meta, .progress, .transport, .volume { padding-left: 20px; padding-right: 20px; }
  .primary { width: 60px; height: 60px; }
}
@media (prefers-reduced-motion: reduce) {
  .sheet, .sheet.open, .backdrop img, .backdrop .shade, .art { transition: none; }
  .bars i, .spinner { animation: none; }
}
`;

function vars(theme) {
  return Object.entries(theme)
    .map(([key, value]) => `--lr-${key}: ${value};`)
    .join(' ');
}

function fontsUrl(file) {
  return new URL(`./fonts/${file}`, import.meta.url).href;
}

/** The app's faces, under their own family names so a system Geist never stands in. */
function loadFonts() {
  if (typeof document === 'undefined' || document.getElementById('lumae-radio-fonts')) return;
  const face = (family, file, weight) =>
    `@font-face{font-family:'${family}';src:url('${fontsUrl(file)}') format('woff2');font-weight:${weight};font-style:normal;font-display:swap}`;
  const style = document.createElement('style');
  style.id = 'lumae-radio-fonts';
  style.textContent = [
    face('Lumae Geist', 'geist-400.woff2', 400),
    face('Lumae Geist', 'geist-500.woff2', 500),
    face('Lumae Geist', 'geist-600.woff2', 600),
    face('Lumae Geist Mono', 'geist-mono-400.woff2', 400),
    face('Lumae Geist Mono', 'geist-mono-500.woff2', 500),
  ].join('');
  document.head.append(style);
}

const SKELETON = `
<ha-card>
  <div class="lr">
    <div class="backdrop" aria-hidden="true"><img alt="" hidden /><div class="shade"></div></div>
    <div class="content">
      <header>
        <div class="kicker mono"><span class="dot"></span><span class="kicker-text"></span></div>
        <div class="subline"></div>
      </header>
      <div class="banner" role="status" hidden></div>
      <div class="art"><img alt="" hidden /><div class="disc"></div></div>
      <div class="meta">
        <div class="title"></div>
        <div class="artist"></div>
        <div class="album mono"></div>
        <button class="prompt" type="button" hidden></button>
        <button class="why" type="button" hidden><span class="spark">${GLYPH.spark}</span><span class="why-text"></span><span class="chev">${GLYPH.chevron}</span></button>
      </div>
      <div class="progress" hidden>
        <div class="bar"><div class="fill"></div><div class="knob"></div></div>
        <div class="times mono"><span class="elapsed"></span><span class="left"></span></div>
      </div>
      <div class="transport">
        <button class="icon steer" type="button" aria-label="Steer this track">${GLYPH.steer}</button>
        <button class="icon stop" type="button" aria-label="Stop">${GLYPH.stop}</button>
        <button class="primary" type="button"></button>
        <button class="icon next" type="button" aria-label="Next">${GLYPH.next}</button>
        <button class="icon stations-button" type="button" aria-label="Switch station">${GLYPH.stations}</button>
      </div>
      <div class="volume">
        <span class="speaker">${GLYPH.speaker}</span>
        <input type="range" min="0" max="100" step="1" aria-label="Volume" />
        <span class="value mono"></span>
      </div>
      <div class="chips" role="group" aria-label="Steer this track"></div>
      <div class="note" role="status" hidden><span class="note-text"></span><button type="button" class="undo">· Undo</button></div>
    </div>
    <section class="sheet stations-sheet" aria-label="Stations">
      <div class="sheet-head">
        <div><div class="sheet-kicker mono stations-kicker"></div><div class="sheet-title">Stations<span class="period">.</span></div></div>
        <button class="icon close" type="button" aria-label="Close">${GLYPH.close}</button>
      </div>
      <div class="sheet-body stations-list"></div>
    </section>
    <section class="sheet track-sheet" aria-label="This track">
      <div class="sheet-head">
        <div><div class="sheet-kicker mono">This track</div></div>
        <button class="icon close" type="button" aria-label="Close">${GLYPH.close}</button>
      </div>
      <div class="sheet-body track-body"></div>
    </section>
    <div class="confirm" hidden>
      <div class="dialog" role="alertdialog" aria-modal="true">
        <div class="h"></div>
        <div class="p">It skips now and never plays on this station again. Your favorites and Pulse stay as they are.</div>
        <div class="actions"><button type="button" class="pill cancel">Cancel</button><button type="button" class="pill bad ban-confirm">Ban</button></div>
      </div>
    </div>
  </div>
</ha-card>`;

const Base = globalThis.HTMLElement ?? class {};
const OPTIMISTIC_MS = 4000;
const NOTE_MS = 8000;

/** The dashboard card. */
export class LumaeRadioCard extends Base {
  static getConfigElement() {
    return document.createElement('lumae-radio-card-editor');
  }

  static getStubConfig(hass) {
    const fromRegistry = Object.entries(hass?.entities ?? {}).find(
      ([id, entry]) => entry?.platform === 'lumae_radio' && id.startsWith('media_player.'),
    )?.[0];
    const fromState = Object.keys(hass?.states ?? {}).find(
      (id) => id.startsWith('media_player.') && 'radio_state' in (hass.states[id].attributes ?? {}),
    );
    return { entity: fromRegistry ?? fromState ?? '' };
  }

  constructor() {
    super();
    this._config = null;
    this._hass = null;
    this._view = null;
    this._lastAnswered = null;
    this._optimistic = null;
    this._override = null;
    this._note = null;
    this._pendingBan = null;
    this._volumeDragging = false;
    this._volumeSent = null;
    this._volumeTimer = null;
    this._ticker = null;
    this._dominant = null;
    this._dominantFor = null;
  }

  setConfig(config) {
    if (!config || typeof config.entity !== 'string' || !config.entity)
      throw new Error('Choose a Lumae Radio for this card.');
    this._config = { theme: 'auto', show_volume: true, show_steering: true, ...config };
    this._render();
  }

  set hass(hass) {
    const previous = this._hass;
    this._hass = hass;
    const entity = this._config?.entity;
    if (
      !previous ||
      previous.states[entity] !== hass.states[entity] ||
      previous.themes?.darkMode !== hass.themes?.darkMode
    )
      this._render();
  }

  getCardSize() {
    return 10;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6 };
  }

  connectedCallback() {
    loadFonts();
    this._ticker = setInterval(() => this._tick(), 1000);
    this._render();
  }

  disconnectedCallback() {
    clearInterval(this._ticker);
    this._ticker = null;
  }

  // ── Building ──────────────────────────────────────────────────────────

  _build() {
    if (this._root) return;
    this._root = this.attachShadow({ mode: 'open' });
    const style = document.createElement('style');
    style.textContent = STYLE;
    this._root.append(style);
    const template = document.createElement('template');
    template.innerHTML = SKELETON;
    this._root.append(template.content.cloneNode(true));
    const $ = (selector) => this._root.querySelector(selector);
    this._el = {
      lr: $('.lr'),
      backdrop: $('.backdrop img'),
      shade: $('.backdrop .shade'),
      dot: $('.dot'),
      kicker: $('.kicker-text'),
      subline: $('.subline'),
      banner: $('.banner'),
      art: $('.art'),
      artImg: $('.art img'),
      title: $('.title'),
      artist: $('.artist'),
      album: $('.album'),
      prompt: $('.prompt'),
      why: $('.why'),
      whyText: $('.why-text'),
      progress: $('.progress'),
      fill: $('.fill'),
      knob: $('.knob'),
      elapsed: $('.elapsed'),
      left: $('.left'),
      steer: $('.steer'),
      stop: $('.stop'),
      primary: $('.primary'),
      next: $('.next'),
      stationsButton: $('.stations-button'),
      volume: $('.volume'),
      slider: $('input[type=range]'),
      volumeValue: $('.volume .value'),
      chips: $('.chips'),
      note: $('.note'),
      noteText: $('.note-text'),
      undo: $('.undo'),
      stationsSheet: $('.stations-sheet'),
      stationsKicker: $('.stations-kicker'),
      stationsList: $('.stations-list'),
      trackSheet: $('.track-sheet'),
      trackBody: $('.track-body'),
      confirm: $('.confirm'),
      confirmTitle: $('.confirm .h'),
    };
    const el = this._el;
    for (const chip of STEER_CHIPS) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'chip mono';
      button.dataset.chip = chip.id;
      button.textContent = chip.label;
      button.addEventListener('click', () => this._onChip(chip.id));
      el.chips.append(button);
    }
    el.artImg.addEventListener('load', () => this._onArtwork());
    el.artImg.addEventListener('error', () => {
      el.artImg.hidden = true;
      el.backdrop.hidden = true;
    });
    el.primary.addEventListener('click', () => this._onPrimary());
    el.stop.addEventListener('click', () => this._command('media_stop', 'stopped'));
    el.next.addEventListener('click', () => this._command('media_next_track'));
    el.stationsButton.addEventListener('click', () => this._openSheet('stations'));
    el.prompt.addEventListener('click', () => this._openSheet('stations'));
    el.steer.addEventListener('click', () => this._openSheet('track'));
    el.why.addEventListener('click', () => this._openSheet('track'));
    for (const close of this._root.querySelectorAll('.sheet .close'))
      close.addEventListener('click', () => this._closeSheets());
    el.undo.addEventListener('click', () => this._onUndo());
    this._root.querySelector('.confirm .cancel').addEventListener('click', () => {
      this._pendingBan = null;
      el.confirm.hidden = true;
    });
    this._root.querySelector('.ban-confirm').addEventListener('click', () => {
      const change = this._pendingBan;
      this._pendingBan = null;
      el.confirm.hidden = true;
      if (change) this._steer(change);
    });
    el.slider.addEventListener('pointerdown', () => (this._volumeDragging = true));
    el.slider.addEventListener('input', () => this._onVolume(false));
    el.slider.addEventListener('change', () => this._onVolume(true));
    this._root.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') {
        if (!el.confirm.hidden) el.confirm.hidden = true;
        else this._closeSheets();
      }
    });
  }

  // ── Rendering ─────────────────────────────────────────────────────────

  _theme() {
    const choice = this._config?.theme;
    if (choice === 'dark' || choice === 'light') return choice;
    return this._hass?.themes?.darkMode === false ? 'light' : 'dark';
  }

  _currentView() {
    const stateObj = this._hass?.states?.[this._config?.entity];
    let view = viewOf(stateObj);
    if (!view) return null;
    if (view.answering) this._lastAnswered = view;
    else if (this._lastAnswered) view = { ...this._lastAnswered, answering: false, state: this._lastAnswered.state };
    const now = Date.now();
    if (this._optimistic) {
      if (now > this._optimistic.until || settled(this._optimistic, view)) this._optimistic = null;
      else view = { ...view, state: this._optimistic.state };
    }
    if (this._override) {
      const sameTrack = this._override.trackId === view.trackId;
      const settled =
        JSON.stringify(view.standing) === JSON.stringify(this._override.standing);
      if (!sameTrack || settled || now > this._override.until) this._override = null;
      else view = { ...view, standing: this._override.standing };
    }
    return view;
  }

  _render() {
    if (!this._config || !this._hass || !this.isConnected) return;
    this._build();
    const el = this._el;
    this.dataset.theme = this._theme();
    const view = this._currentView();
    this._view = view;
    const content = this._root.querySelector('.content');
    if (!view) {
      this._showMessage('This Lumae Radio isn’t in Home Assistant. Choose another in the card’s settings.');
      return;
    }
    this._showMessage(null);
    content.hidden = false;

    const answering = view.answering;
    const label = remoteStateLabel(view.state, answering);
    el.kicker.textContent = `${view.name} · ${label}`;
    el.dot.className = `dot${answering && view.state === 'playing' ? ' on' : ''}${view.state === 'fault' && answering ? ' fault' : ''}`;
    el.subline.textContent = stationLine(view.station, view.stationId);

    const banner = healthBanner(view);
    el.banner.hidden = !banner;
    el.banner.textContent = banner ?? '';

    // Artwork, and the backdrop it colors.
    const picture = view.trackId && view.picture ? this._hass.hassUrl(view.picture) : null;
    if (picture !== this._picture) {
      this._picture = picture;
      if (picture) {
        el.artImg.src = picture;
        el.backdrop.src = picture;
      } else {
        el.artImg.removeAttribute('src');
        el.artImg.hidden = true;
        el.backdrop.hidden = true;
        this._dominant = null;
      }
    }
    this._paintBackdrop();

    // Title block.
    const hasTrack = Boolean(view.trackId);
    el.title.textContent = hasTrack
      ? view.title || 'Untitled track'
      : view.state === 'buffering'
        ? 'Starting…'
        : 'Nothing playing';
    el.artist.textContent = hasTrack ? (view.artist ?? '') : '';
    el.artist.hidden = !hasTrack || !view.artist;
    el.album.textContent = hasTrack ? (view.album ?? '') : '';
    el.album.hidden = !hasTrack || !view.album;
    const idle = !hasTrack && view.state !== 'buffering';
    el.prompt.hidden = !idle || !answering;
    el.prompt.textContent = view.stationId ? 'Press play, or choose a station' : 'Choose a station';
    const why = hasTrack ? whyLine(view.selection) : null;
    el.why.hidden = !why;
    el.whyText.textContent = why ?? '';

    this._tick();

    // Transport.
    const action = mainAction(view);
    const buffering = view.state === 'buffering';
    el.primary.innerHTML = buffering
      ? '<span class="spinner" aria-hidden="true"></span>'
      : action === 'pause'
        ? GLYPH.pause
        : GLYPH.play;
    el.primary.setAttribute(
      'aria-label',
      action === 'pause' ? 'Pause' : action ? 'Play' : 'Choose a station',
    );
    el.primary.disabled = !answering;
    el.stop.disabled = !answering || view.state === 'stopped';
    el.next.disabled = !answering || !hasTrack || view.state === 'stopped';
    el.steer.disabled = !hasTrack;
    el.stationsButton.disabled = !answering && view.stations.length === 0;

    // Volume.
    el.volume.hidden = !this._config.show_volume || view.volume === null;
    if (!this._volumeDragging && view.volume !== null) this._setSlider(view.volume);
    el.slider.disabled = !answering;

    // Steering chips.
    const now = Date.now();
    const chosen = chosenChip(view.standing, now);
    const showChips =
      this._config.show_steering && view.canSteer && hasTrack && Boolean(view.stationId);
    el.chips.hidden = !showChips;
    for (const button of el.chips.children) {
      button.setAttribute('aria-pressed', String(button.dataset.chip === chosen));
      button.disabled = !answering;
    }
    if (this._note && (this._note.trackId !== view.trackId || now > this._note.until)) this._note = null;
    el.note.hidden = !this._note;
    el.noteText.textContent = this._note?.text ?? '';
    el.undo.hidden = !this._note?.undo;

    this._renderStations(view);
    this._renderTrack(view);
  }

  _showMessage(text) {
    let message = this._root.querySelector('.message');
    const content = this._root.querySelector('.content');
    if (!text) {
      message?.remove();
      return;
    }
    content.hidden = true;
    if (!message) {
      message = document.createElement('div');
      message.className = 'message';
      this._root.querySelector('.lr').append(message);
    }
    message.textContent = text;
  }

  _tick() {
    const view = this._view;
    const el = this._el;
    if (!view || !el) return;
    const now = Date.now();
    const position = view.trackId ? positionNow(view, now) : null;
    const duration = view.durationMs;
    const show = position !== null && typeof duration === 'number' && duration > 0;
    el.progress.hidden = !show;
    if (show) {
      const share = Math.min(1, Math.max(0, position / duration));
      el.fill.style.width = `${share * 100}%`;
      el.knob.style.left = `${share * 100}%`;
      el.elapsed.textContent = formatClock(position);
      el.left.textContent = `−${formatClock(duration - position)}`;
    }
    if (this._note && now > this._note.until) {
      this._note = null;
      el.note.hidden = true;
    }
  }

  _setSlider(level) {
    const percent = Math.round(level * 100);
    this._el.slider.value = String(percent);
    this._el.slider.style.setProperty('--pct', `${percent}%`);
    this._el.volumeValue.textContent = String(percent);
  }

  _onArtwork() {
    const el = this._el;
    el.artImg.hidden = false;
    el.backdrop.hidden = false;
    const src = el.artImg.currentSrc || el.artImg.src;
    if (this._dominantFor === src) return;
    this._dominantFor = src;
    this._dominant = dominantColor(el.artImg);
    this._paintBackdrop();
  }

  _paintBackdrop() {
    const theme = THEMES[this._theme()];
    const dominant = this._dominant ?? theme.surface2;
    const shade =
      this._theme() === 'dark'
        ? `linear-gradient(180deg, ${dominant}AA 0%, ${theme.bg}EE 55%, ${theme.overlay} 100%)`
        : `linear-gradient(180deg, ${mixColor(dominant, theme.bg, 0.2)}E6 0%, ${theme.bg}F2 55%, ${theme.bg} 100%)`;
    this._el.shade.style.background = shade;
    this._el.lr.style.setProperty('--lr-dominant', this._dominant ?? theme.overlay);
  }

  _renderStations(view) {
    const el = this._el;
    el.stationsKicker.textContent = view.name;
    const key = JSON.stringify([view.stations, view.stationId, view.state, view.answering]);
    if (key === this._stationsKey) return;
    this._stationsKey = key;
    el.stationsList.replaceChildren();
    if (view.stations.length === 0) {
      const empty = document.createElement('div');
      empty.className = 'empty';
      empty.textContent = 'No stations on this radio yet. Make one in the Lumae app.';
      el.stationsList.append(empty);
      return;
    }
    for (const station of view.stations) {
      const row = document.createElement('button');
      row.type = 'button';
      row.className = 'station';
      const [glow, middle, edge] = TINTS[stationTint(station.id)];
      const orb = document.createElement('span');
      orb.className = 'orb';
      orb.style.background = `radial-gradient(circle at 35% 30%, ${glow} 0%, ${middle} 48%, ${edge} 100%)`;
      const text = document.createElement('span');
      text.className = 'text';
      const name = document.createElement('div');
      name.className = 'name';
      name.textContent = station.name;
      const line = document.createElement('div');
      line.className = `line${station.preparation === 'failed' ? ' warn' : ''}`;
      line.textContent = stationStateLine(station);
      text.append(name, line);
      const onAir =
        station.id === view.stationId && ['playing', 'paused', 'buffering'].includes(view.state);
      let side;
      if (onAir) {
        side = document.createElement('span');
        side.className = `onair mono${view.state === 'paused' ? ' paused' : ''}`;
        side.innerHTML = '<span class="bars"><i></i><i></i><i></i></span>ON AIR';
      } else {
        side = document.createElement('span');
        side.className = 'round';
        side.innerHTML = GLYPH.play;
      }
      row.append(orb, text, side);
      row.setAttribute('aria-label', `${station.name}. ${stationStateLine(station)}${onAir ? '. On air' : ''}`);
      row.disabled = !view.answering;
      row.addEventListener('click', () => this._playStation(station, onAir));
      el.stationsList.append(row);
    }
  }

  _renderTrack(view) {
    const body = this._el.trackBody;
    const now = Date.now();
    const key = JSON.stringify([
      view.trackId,
      view.title,
      view.standing,
      view.selection,
      view.canSteer,
      view.station?.name,
      view.answering,
      Math.floor(now / 60000),
    ]);
    if (key === this._trackKey) return;
    this._trackKey = key;
    body.replaceChildren();
    if (!view.trackId) {
      const empty = document.createElement('div');
      empty.className = 'empty';
      empty.textContent = 'Nothing is playing on a station right now.';
      body.append(empty);
      return;
    }
    const make = (tag, className, text) => {
      const node = document.createElement(tag);
      if (className) node.className = className;
      if (text !== undefined) node.textContent = text;
      return node;
    };
    const head = make('div', 'track-head');
    if (this._picture) {
      const image = make('img');
      image.alt = '';
      image.src = this._picture;
      head.append(image);
    } else head.append(make('div', 'thumb'));
    const headText = make('div', 'text');
    headText.append(
      make('div', 'name', view.title || 'Untitled track'),
      make(
        'div',
        'sub',
        [view.artist, view.station ? `on ${view.station.name}` : null].filter(Boolean).join(' · '),
      ),
    );
    head.append(headText, make('span', 'stealth mono', 'Stealth'));
    body.append(head);

    const facts = selectionFacts(view.selection);
    body.append(make('div', 'label mono', 'Why this track'));
    const grid = make('div', 'grid');
    const cell = (label, value) => {
      const node = make('div', 'cell');
      node.append(make('div', 'k', label), make('div', 'v', value));
      return node;
    };
    grid.append(
      cell('Station fit', facts.fitPercent !== null ? `${facts.fitPercent}%` : '—'),
      cell('Last on this radio', facts.lastAired),
    );
    body.append(grid);
    const energy = make('div', 'cell energy');
    const energyHead = make('div', 'head');
    energyHead.append(make('span', '', 'Energy against the target'), make('span', 'verdict', facts.energy));
    energy.append(energyHead);
    if (facts.energyValue !== null && facts.targetValue !== null) {
      const bar = make('div', 'scale-bar');
      const target = make('span', 'target');
      target.style.left = `${Math.round(Math.min(1, Math.max(0, facts.targetValue)) * 100)}%`;
      const point = make('span', 'point');
      point.style.left = `${Math.round(Math.min(1, Math.max(0, facts.energyValue)) * 100)}%`;
      bar.append(target, point);
      energy.append(bar);
    }
    const scale = make('div', 'scale mono');
    scale.append(
      make('span', '', 'calm'),
      make(
        'span',
        '',
        facts.energyValue !== null && facts.targetValue !== null
          ? `track ${Math.round(facts.energyValue * 100)} · target ${Math.round(facts.targetValue * 100)}`
          : 'not measured',
      ),
      make('span', '', 'lively'),
    );
    energy.append(scale);
    body.append(energy);
    const list = make('div', 'facts');
    const fact = (label, value) => {
      const node = make('div', 'fact');
      node.append(make('span', 'k', label), make('span', '', value));
      return node;
    };
    list.append(fact('Earlier plays on this radio', String(facts.earlierPlays)));
    if (facts.rotation) list.append(fact('Rotation', facts.rotation));
    list.append(fact('Your listening history', 'Always Stealth'));
    body.append(list);

    if (!view.stationId) return;
    const stationName = view.station?.name ?? 'this station';
    body.append(make('div', 'label mono', `On ${stationName}`));
    if (!view.canSteer) {
      body.append(
        make(
          'div',
          'hint',
          'To favor, rest or ban tracks from Home Assistant, give its API key the Stations scope on the radio’s Access page, then add the new key in Home Assistant.',
        ),
      );
      return;
    }
    const standing = view.standing ?? NO_STANDING;
    const disabled = !view.answering || standing.banned;
    const segment = make('div', 'segment');
    segment.setAttribute('role', 'group');
    for (const [value, label, choice] of [
      [1, '↑ Favor', 'favor'],
      [0, 'No preference', 'no_preference'],
      [-1, '↓ Less', 'less'],
    ]) {
      const option = make('button', '', label);
      option.type = 'button';
      option.setAttribute('aria-pressed', String(standing.preference === value));
      option.disabled = disabled;
      option.addEventListener('click', () => {
        if (standing.preference !== value) this._steer({ choice });
      });
      segment.append(option);
    }
    body.append(segment);
    body.append(make('div', 'hint', 'Gentle nudges among tracks that already fit. Nothing is forced in or out.'));

    const resting = typeof standing.rest_until_ms === 'number' && standing.rest_until_ms > now;
    const restDays = resting ? Math.round((standing.rest_until_ms - now) / DAY_MS) : null;
    const rest = make('div', 'rest-row');
    rest.append(make('span', 'k', resting ? 'Resting' : 'Rest this track'));
    for (const [label, days] of [
      ['1 day', 1],
      ['1 week', 7],
      ['30 days', 30],
    ]) {
      const on = resting && restDays === days;
      const chip = make('button', 'chip mono', label);
      chip.type = 'button';
      chip.setAttribute('aria-pressed', String(on));
      chip.disabled = disabled;
      chip.addEventListener('click', () =>
        this._steer(on ? { choice: 'end_rest' } : { choice: 'rest', restUntilMs: Date.now() + days * DAY_MS }),
      );
      rest.append(chip);
    }
    body.append(rest);
    if (resting && ![1, 7, 30].includes(restDays)) {
      const end = make(
        'button',
        'link',
        `End the rest (${restDays < 1 ? 'less than a day left' : `${restDays} ${restDays === 1 ? 'day' : 'days'} left`})`,
      );
      end.type = 'button';
      end.disabled = !view.answering;
      end.addEventListener('click', () => this._steer({ choice: 'end_rest' }));
      body.append(end);
    }
    if (standing.banned) {
      const allow = make('button', 'allow', `Allow on ${stationName} again`);
      allow.type = 'button';
      allow.disabled = !view.answering;
      allow.addEventListener('click', () => this._steer({ choice: 'allow' }));
      body.append(allow, make('div', 'hint', 'Banned tracks never play on this station.'));
    } else {
      const ban = make('button', 'danger');
      ban.type = 'button';
      ban.innerHTML = GLYPH.ban;
      ban.append(make('span', '', 'Ban from this station'));
      ban.disabled = !view.answering;
      ban.addEventListener('click', () => this._confirmBan({ choice: 'ban' }));
      body.append(ban, make('div', 'hint', 'Skips now. Your favorites and Pulse stay as they are.'));
    }
  }

  // ── Sheets ────────────────────────────────────────────────────────────

  _openSheet(which) {
    this._closeSheets();
    const sheet = which === 'stations' ? this._el.stationsSheet : this._el.trackSheet;
    sheet.classList.add('open');
    sheet.querySelector('.close')?.focus({ preventScroll: true });
  }

  _closeSheets() {
    this._el.stationsSheet.classList.remove('open');
    this._el.trackSheet.classList.remove('open');
  }

  // ── Actions ───────────────────────────────────────────────────────────

  async _call(domain, service, data = {}) {
    try {
      // The card says what went wrong in its own note, so Home Assistant's toast stays off.
      await this._hass.callService(domain, service, data, { entity_id: this._config.entity }, false);
      return true;
    } catch (error) {
      this._showNote(error?.message || 'The radio couldn’t do that. Try again.', null);
      return false;
    }
  }

  _command(service, optimisticState) {
    if (optimisticState)
      this._optimistic = {
        state: optimisticState,
        until: Date.now() + (optimisticState === 'buffering' ? 30_000 : OPTIMISTIC_MS),
        settle: optimisticState === 'buffering' ? ['buffering', 'playing'] : [optimisticState],
        stationId: null,
      };
    this._render();
    void this._call('media_player', service).then((ok) => {
      if (!ok) {
        this._optimistic = null;
        this._render();
      }
    });
  }

  _onPrimary() {
    const action = mainAction(this._view);
    if (action === 'pause') this._command('media_pause', 'paused');
    else if (action === 'resume') this._command('media_play', 'playing');
    else if (action === 'play') this._command('media_play', 'buffering');
    else this._openSheet('stations');
  }

  _playStation(station, onAir) {
    this._closeSheets();
    if (onAir) {
      if (this._view?.state === 'paused') this._command('media_play', 'playing');
      return;
    }
    this._optimistic = {
      state: 'buffering',
      until: Date.now() + 30_000,
      settle: ['buffering', 'playing'],
      stationId: station.id,
    };
    this._render();
    void this._call('media_player', 'play_media', {
      media_content_id: `station:${station.id}`,
      media_content_type: 'station',
    }).then((ok) => {
      if (!ok) {
        this._optimistic = null;
        this._render();
      }
    });
  }

  _onVolume(final) {
    const el = this._el;
    const level = Number(el.slider.value) / 100;
    el.slider.style.setProperty('--pct', `${el.slider.value}%`);
    el.volumeValue.textContent = el.slider.value;
    const now = Date.now();
    clearTimeout(this._volumeTimer);
    if (final || volumeDue(level, this._volumeSent, now)) {
      this._volumeSent = { value: level, at: now };
      void this._call('media_player', 'volume_set', { volume_level: level });
    } else this._volumeTimer = setTimeout(() => this._onVolume(false), VOLUME_SEND_MS);
    if (final) {
      // Keep the dragged value until the radio reports it.
      setTimeout(() => (this._volumeDragging = false), 1500);
    }
  }

  _onChip(chip) {
    const view = this._view;
    if (!view?.trackId) return;
    const now = Date.now();
    const chosen = chosenChip(view.standing, now) === chip;
    const change = chipChange(chip, chosen, now);
    if (change.choice === 'ban') this._confirmBan(change);
    else this._steer(change);
  }

  _confirmBan(change) {
    this._pendingBan = change;
    this._el.confirmTitle.textContent = `Ban from ${this._view?.station?.name ?? 'this station'}?`;
    this._el.confirm.hidden = false;
    this._root.querySelector('.confirm .cancel').focus({ preventScroll: true });
  }

  _steer(change, undoable = true) {
    const view = this._view;
    if (!view?.trackId) return;
    const now = Date.now();
    const before = view.standing ?? NO_STANDING;
    this._override = { trackId: view.trackId, standing: applyChange(before, change), until: now + 20_000 };
    this._showNote(steerNote(change, view.station?.name, now), undoable ? undoChange(change, before, now) : null);
    void this._call('lumae_radio', 'steer_track', steerData(change)).then((ok) => {
      if (!ok) {
        this._override = null;
        this._render();
      }
    });
  }

  _onUndo() {
    const undo = this._note?.undo;
    if (!undo) return;
    this._steer(undo, false);
  }

  _showNote(text, undo) {
    this._note = { text, undo, trackId: this._view?.trackId ?? null, until: Date.now() + NOTE_MS };
    this._render();
  }
}

/** The average color of an image, leaning to its saturated pixels; null if unreadable. */
function dominantColor(image) {
  try {
    const canvas = document.createElement('canvas');
    canvas.width = 24;
    canvas.height = 24;
    const context = canvas.getContext('2d', { willReadFrequently: true });
    context.drawImage(image, 0, 0, 24, 24);
    const { data } = context.getImageData(0, 0, 24, 24);
    let [red, green, blue, weight] = [0, 0, 0, 0];
    for (let index = 0; index < data.length; index += 4) {
      const [r, g, b] = [data[index], data[index + 1], data[index + 2]];
      const max = Math.max(r, g, b);
      const min = Math.min(r, g, b);
      const share = 0.15 + (max === 0 ? 0 : (max - min) / max);
      red += r * share;
      green += g * share;
      blue += b * share;
      weight += share;
    }
    if (!weight) return null;
    const hex = (value) => Math.round(value / weight).toString(16).padStart(2, '0');
    return `#${hex(red)}${hex(green)}${hex(blue)}`;
  } catch {
    return null;
  }
}

// ── The card's settings ───────────────────────────────────────────────────

const EDITOR_SCHEMA = [
  {
    name: 'entity',
    required: true,
    selector: { entity: { filter: [{ integration: 'lumae_radio', domain: 'media_player' }] } },
  },
  {
    name: 'theme',
    required: true,
    selector: {
      select: {
        mode: 'dropdown',
        options: [
          { value: 'auto', label: 'Match Home Assistant' },
          { value: 'dark', label: 'Dark' },
          { value: 'light', label: 'Light' },
        ],
      },
    },
  },
  { name: 'show_volume', selector: { boolean: {} } },
  { name: 'show_steering', selector: { boolean: {} } },
];

const EDITOR_LABELS = {
  entity: 'Radio',
  theme: 'Look',
  show_volume: 'Show volume',
  show_steering: 'Show Favor · Less · Rest · Ban',
};

export class LumaeRadioCardEditor extends Base {
  setConfig(config) {
    this._config = { theme: 'auto', show_volume: true, show_steering: true, ...config };
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  _render() {
    if (!this._hass || !this._config) return;
    if (!this._form) {
      this._form = document.createElement('ha-form');
      this._form.computeLabel = (schema) => EDITOR_LABELS[schema.name] ?? schema.name;
      this._form.addEventListener('value-changed', (event) => {
        this._config = event.detail.value;
        this.dispatchEvent(
          new CustomEvent('config-changed', {
            detail: { config: this._config },
            bubbles: true,
            composed: true,
          }),
        );
      });
      this.append(this._form);
    }
    this._form.hass = this._hass;
    this._form.schema = EDITOR_SCHEMA;
    this._form.data = this._config;
  }
}

/**
 * Defines the card once Home Assistant's own element registry is in place. The integration loads
 * this module while the frontend boots, and the frontend then replaces `window.customElements` with
 * a scoped registry; an element defined before that is invisible to the dashboard.
 */
export async function registerCard(page = globalThis.document) {
  if (!globalThis.customElements || !page) return;
  if (page.readyState === 'loading')
    await new Promise((resolve) => page.addEventListener('DOMContentLoaded', resolve, { once: true }));
  if (page.querySelector('home-assistant'))
    await globalThis.customElements.whenDefined('home-assistant');
  const registry = globalThis.customElements;
  if (!registry.get('lumae-radio-card')) registry.define('lumae-radio-card', LumaeRadioCard);
  if (!registry.get('lumae-radio-card-editor'))
    registry.define('lumae-radio-card-editor', LumaeRadioCardEditor);
  globalThis.customCards = globalThis.customCards ?? [];
  if (!globalThis.customCards.some((card) => card.type === 'lumae-radio-card'))
    globalThis.customCards.push({
      type: 'lumae-radio-card',
      name: 'Lumae Radio',
      description:
        'What your Lumae Radio plays, with play, stations, volume and Favor · Less · Rest · Ban.',
      preview: true,
      documentationURL: 'https://github.com/rendyhd/lumae-radio-home-assistant',
    });
  console.info(
    `%c LUMAE RADIO CARD %c ${CARD_VERSION} `,
    'color:#0D0D0F;background:#D8A07A;font-weight:600',
    'color:#D8A07A',
  );
}

void registerCard();
