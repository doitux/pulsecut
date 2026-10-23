# Changelog

## 1.0.9 – 2026-10-24
- Timeline: **removing a shot no longer brings in a replacement from the same scene.** The shots behind it move up,
  and you choose where the free bars go: *balance the rest of the film* (new shots for the categories after this
  point, following the weighting, in chronological order, never from an earlier scene), *longer neighbours* (the next
  shot gets the bars, e.g. twice as long) or *shorter film* (the music ends that many bars earlier with a fade-out;
  can be undone). Options that are not possible are greyed out with the reason. The choice can be remembered.
- The removed passage and the same camera view a few seconds around it are no longer chosen automatically.
- **Del key** removes the selected shot.
- **“Finished up to here”**: a green line in the timeline. Everything before it is left alone by filling, balancing
  and re-planning. It moves along automatically with every edit (never backwards by itself), can be dragged, or set
  with “✓ Finished up to here” on a shot.
- **Notice when the shares shift**: if a category ends up noticeably above or below the plan (more than 1½ shots or
  3 percentage points), the timeline says so – *keep it like this*, *balance after “finished up to here”* or *change
  the weighting*.
- If there is no footage left anywhere for all of the music, the music now ends earlier with a fade-out instead of
  leaving the film shorter than the music.

## 1.0.8 – 2026-10-23
- Timeline (step 9): the preview can be made smaller (S / M / L next to the play buttons), leaving more room for the
  timeline and the shot options below. The choice is remembered.

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
