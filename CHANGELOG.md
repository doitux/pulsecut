# Changelog

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
