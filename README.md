# Lumae Radio for Home Assistant

Control a [Lumae Radio](https://lumaemusic.app) from Home Assistant, and show what it plays on
a dashboard the way the Lumae app's remote does: the cover, why this track, play and pause,
skip, stop, volume, the station switcher, and Favor · Less · Rest · Ban for the playing track.

One install from HACS gives you both:

- **The integration** (`lumae_radio`): a media player for each radio, with its stations as
  sources, and an action to steer the playing track. It finds radios on your network by itself.
- **The card** (`custom:lumae-radio-card`): served by the integration and loaded on every
  dashboard, so there is no separate resource to add.

The radio plays its own stations, and an album, playlist or collection start to end; Home
Assistant controls it like a remote. Radio listening is always Stealth: nothing here reaches
your listening history, scrobbles or The Pulse.

## What you need

- A Lumae Radio set up with the Lumae app, on the same network as Home Assistant.
- Home Assistant 2025.6 or later (tested on 2026.10). The integration's own icon shows from
  2026.3.
- An API key from the radio (below). Home Assistant never uses the radio's password.

## Install

1. In HACS, open ⋮ → **Custom repositories**, add this repository's address with the type
   **Integration**, then install **Lumae Radio**.
2. Restart Home Assistant.
3. Home Assistant shows the radio under **Settings → Devices & services → Discovered**. If it
   doesn't, choose **Add integration → Lumae Radio** and enter the radio's web address, such
   as `https://lumae-radio.local:8443`.

### The API key

Make a key for Home Assistant on the radio:

- **In the Lumae app:** open the radio's remote, tap ⋯ → **The radio** → **Access** →
  **+ New key**.
- **On the radio's web page:** **API access** → **Create a key**.

Tick **Read** and **Control playback**. Tick **Stations** too if you want Favor, Less, Rest and
Ban from Home Assistant; without it the card hides those chips. Copy the key (it starts with
`lrk.`) into Home Assistant: the radio shows it only once. If you revoke or replace the key
later, Home Assistant asks for a new one.

### The radio's identity

The radio uses its own certificate, not one from a public authority. Like the Lumae app,
Home Assistant pins that certificate the first time it connects and refuses any other one
after that. When you add the radio, Home Assistant shows its identity (for example
`3F:A1:07 … 52:9C`): the Lumae app shows the same under the radio's **Access** page, and
`lumae-radio.mjs doctor` prints it in full. If you set the radio up again, it gets a new
identity: remove it from Home Assistant and add it again.

## The card

Add it from the card picker (search for "Lumae Radio"), or in YAML:

```yaml
type: custom:lumae-radio-card
entity: media_player.lumae_radio
```

| Option | Default | What it does |
|---|---|---|
| `entity` | | The radio's media player. |
| `theme` | `auto` | `auto` follows Home Assistant's light or dark mode; `dark` or `light` keeps one. |
| `layout` | `auto` | `auto` keeps the whole card on screen (see below); `full` always shows the full card; `compact` puts a small cover beside the title and the controls. |
| `bottom_offset` | `72` | With `layout: auto`, the room in px kept free under the card, so a bar along the bottom of the screen doesn't cover the controls. |
| `show_volume` | `true` | Show the volume slider. |
| `show_steering` | `true` | Show Favor · Less · Rest · Ban (needs the key's Stations scope). |

With `layout: auto` the card fits the height it has. When the full card would run past the
bottom of the screen (less `bottom_offset`), the cover gets smaller; the line under the title goes
before the cover drops below 160 px; below 120 px the card turns compact, and its cover grows into
the room left. It stays compact until the screen, its place or its width changes, so it doesn't
switch as tracks start and stop. A card that starts too far down the page to fit there is one you
scroll to, so it fits the screen instead. With fixed rows in a sections view
(`grid_options: rows`), it fills and fits those rows instead.

On the card:

- **The round button** pauses, resumes, or starts the station that was on. With no station yet,
  it opens the stations.
- **The radio glyph** opens the stations: tap one to play it.
- **The sliders glyph**, or the line under the title, opens **This track**: why the radio chose
  it, its energy against the target, and Favor, No preference, Less, Rest for a day, a week or
  30 days, and Ban.
- **The chips** under the volume favor, play less, rest for a week or ban the playing track on
  its station. Each change shows a note with **Undo** for a few seconds. Ban asks first, then
  skips the track.
- While an album, playlist or collection plays, the line under the radio's name names it and
  its place ("Kind of Blue · Album · 3 of 12"); a list has no station, so there is nothing to
  steer.

## The media player

`media_player.<radio>` supports play, pause, stop, next, volume, **source** (the radio's
stations by name) and **media browsing** (the stations, to play one). Its attributes include
`radio_state` (`playing`, `paused`, `stopped`, `buffering` or `fault`), `station_id`,
`station_mode`, `stations`, `standing` (the playing track's preference, rest and ban),
`selection` (why the radio chose it) and `health`.

A radio that plays albums, playlists and collections (it reports this itself; `plays_lists` is
true) also offers:

- **Media** with Stations, Albums (from the radio's library), Playlists (its music server
  account's own and public ones) and Collections (from Lumae Analysis), 64 at a time with
  **More** to go on, and **search** across stations and all three.
- **Play** of an album, playlist or collection: it plays start to end in its own order, albums
  gapless, then the station that was on (or a schedule's) returns. **Previous** goes back
  within it, and **source** and `media_playlist` name it. The `list` attribute is
  `{kind, id, name, artist, index, count, shuffled, place}`.
- **Shuffle**, from a radio that shuffles lists: turned on, the next album, playlist or
  collection you play plays in the Lumae app's Shuffle order, worked out once as it starts (the
  card adds "Shuffled" to its line). It doesn't reorder a list already playing, and it's off
  again after Home Assistant restarts.

The radio pushes every change, so Home Assistant updates at once; it also checks every minute,
and every 10 seconds while the push connection is down.

### Steer the playing track

```yaml
action: lumae_radio.steer_track
target:
  entity_id: media_player.lumae_radio
data:
  choice: rest      # favor, less, no_preference, rest, end_rest, ban, allow
  rest_days: 30     # or rest_until: "2026-12-24 08:00"; a week if left out
```

The choice applies to the track playing now, on the station it plays on. Your personal
favorites, history and The Pulse stay as they are.

### Examples

Start a station in the morning:

```yaml
action: media_player.select_source
target:
  entity_id: media_player.lumae_radio
data:
  source: Morning drift
```

Or by station ID, which doesn't change when a station is renamed:

```yaml
action: media_player.play_media
target:
  entity_id: media_player.lumae_radio
data:
  media_content_id: station:<station id>
  media_content_type: station
```

Play an album by the music server's album ID (a playlist or collection the same way, with
`playlist` or `collection`):

```yaml
action: media_player.play_media
target:
  entity_id: media_player.lumae_radio
data:
  media_content_id: album:<album id>
  media_content_type: album
```

## Troubleshooting

- **"Couldn't reach the radio."** Check that the radio is on and on the same network. The
  radio answers only private network addresses, so Home Assistant must reach it directly, not
  through a VPN or a cloud relay.
- **"The radio doesn't answer to this address."** The radio answers only to the names it was
  set up with: use its `.local` name, or the address its installer printed.
- **"This radio has no owner yet."** Set the radio up in the Lumae app first.
- **The card says "Not answering".** Home Assistant can't reach the radio right now. The card
  keeps showing the last thing it heard from the radio until the radio answers again.

## Development

Most tests run against the radio's own HTTPS code through `tests/radio_harness.mjs`, so they
need Node 24 and the Lumae source tree next to this folder (`../headless`); without it they are
skipped. The card's tests need only Node:

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements_test.txt
.venv/bin/pytest
node --test tests/card.test.mjs
```

`tests/radio_harness.mjs` starts a test radio (`--port 18443 --origins 'https://127.0.0.1:{port}'`)
and prints its API keys, which is also handy for trying the card in a local Home Assistant.

The Geist fonts in `custom_components/lumae_radio/frontend/fonts` are under the SIL Open Font
License (`OFL-Geist.txt`).
