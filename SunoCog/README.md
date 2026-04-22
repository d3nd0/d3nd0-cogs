# SunoCog

Queue public Suno share links into Red's core Audio cog.

## What It Does

`SunoCog` adds Suno support in two ways:

1. A dedicated `suno` / `sunoplay` command
2. Runtime patching for Audio's built-in `play` command

Both paths:

1. Fetch a public Suno song page
2. Extract the direct MP3 URL from the page payload
3. Hand that track to Red's `Audio` cog for normal queuing/playback

## Commands

- `[p]suno <suno_url>`
- `[p]sunoplay <suno_url>`
- `[p]play <suno_url>`

Example:

```text
[p]play https://suno.com/s/QxPq5J6zTWcMdUsA
```

## Requirements

- Red `Audio` must be loaded: `[p]load audio`
- The Suno link must be accessible without logging in
- If you use an external Lavalink node, its HTTP source must be enabled

## Why A Separate Command?

This cog now patches Audio's `play` command at runtime so `[p]play <suno link>`
works directly. The dedicated `suno` command remains available as a fallback.

This is intentionally more invasive than a normal third-party cog, so it may be
more sensitive to Red Audio internals changing in future releases.
