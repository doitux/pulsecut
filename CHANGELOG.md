# Changelog

## 1.0.7 – 2026-10-23
- Timeline (step 9): **original sound per shot** – Auto / On / Off in the shot inspector, with the reason when a
  shot has no original sound (music in the video, nothing atmospheric, switched off for the clip …). “On” also works
  where music plays in the video – that is then your decision. The switch for the whole film (music only /
  atmosphere added / music quieter) is also at the top of the timeline. Existing projects open as they are, nothing
  is analysed again.
- Timeline: **insert another clip of the same scene** right after the selected shot – pick it from the scene's clips
  (with thumbnail and how often it is already in the film) or let Pulsecut choose. The film length stays the same:
  an unlocked shot of another scene makes room.
- Preview: no more flicker on hard cuts into another video file. The next shots are loaded earlier, held exactly at
  their first frame, and if a video is not ready at the cut, the last picture stays for a moment instead of a still
  image.

## 1.0.6 – 2026-10-23
- Faster video analysis in **one pass**: analysis, sound and the preview video now come from a single ffmpeg run
  (before, every video was read two to three times). The results are identical.
- **Decoding on the graphics chip** (VAAPI, e.g. Intel onboard graphics): for each video format Pulsecut measures
  once whether the chip works and is worthwhile, and remembers it. Formats the chip cannot handle (e.g. HEVC on older
  Intel chips), missing drivers and errors fall back to the processor automatically, per video. The analysis
  results are the same either way. With “⚡ Full power” two videos go through the chip and the other cores work on
  the processor at the same time. The video step shows what decodes where. `PULSECUT_HWDEC=0` switches it off.

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
