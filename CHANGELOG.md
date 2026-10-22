# Changelog

## 1.0.5 – 2026-10-22
- Title library: 12 styles for title and end credits (band, clean, card, light card, glass, lines, frame, lower
  third, highlighter, glow, outline, cinema), any installed font, accent colour, position bottom/centre. The step
  “Cut settings” shows a gallery rendered on a frame of your own film; live preview, Kdenlive project and renders
  use exactly the same picture.
- Fix: after the automatic graphics restart, ffmpeg got the AppImage's library paths (“ffmpeg has no VP8”).
- Music step: the track list appears once click tracks are ready (no stale redraws while preparing).

## 1.0.4 – 2026-10-22
- Videos set to “Out” in the video step stay out: the recognition ignores them (the recognition step says how many).
- Wrongly sorted scenes: the selection under each scene (recognition step) and next to each scene and clip
  (weighting step) can move it to another keyword, create a **new keyword** right there, or take it out. A new
  keyword is placed where its scenes happened and works without running the AI again.

## 1.0.3 – 2026-10-22
- Video analysis runs quietly by default (one worker, lowest priority for the analysis threads and the ffmpeg
  processes) so music check and playback stay smooth. In the video step a switch “⚡ Full power” uses all cores
  (except one) – it takes effect immediately, also during a running analysis.

## 1.0.2 – 2026-10-22
- Click tracks and the music preview are prepared right after the music analysis, so “play” starts at once
  (before, they were made on the first click – slow while the videos were analysed).
- Video analysis starts after the music analysis and runs with low priority, so the interface and playback stay
  smooth; the music step says when the videos are being analysed in the background.
- Quieter terminal: aborted media connections are no longer reported; the system's xkbcommon is used.

## 1.0.1 – 2026-10-22
- Window stayed white on some Intel graphics (e.g. Haswell, Vulkan in QtWebEngine): Pulsecut now checks after
  start whether the page is really shown and otherwise restarts itself without Vulkan, then without GPU
  acceleration, and remembers what works. Manual choice: `PULSECUT_GRAFIK=gpu|opengl|software`.

## 1.0.0 – 2026-10-22
- First public version (formerly “Taktschnitt”): beat-synced recap films from phone footage, German and English
  interface, local AI recognition, Kdenlive export, original sound options.
