# Changelog

There is no stable release yet – the first one will be **1.0.0**. Until then every change on `main` that passes all
tests is published as a [nightly test build](https://github.com/doitux/pulsecut/releases/tag/nightly) (`Pulsecut-nightly-<build>-<commit>`).

The preview versions 1.0.0–1.0.10 published before have been withdrawn; their changes are listed below by date.

## Unreleased (nightly)
- Fixed (step 9): the space bar starts and pauses the preview again, and ←/→ jump between shots – this was broken
  in nightly 39. The space bar now also works right after clicking a button or using the zoom slider.
- Timeline (step 9), “insert another clip of this scene”: **a click on a clip shows it first** instead of inserting it
  at once. The preview plays the clip from the suggested passage; a bar shows the suggested passage, the parts already
  in the film and the passage from the current point. Then “✓ Insert the suggested passage”, “Insert from here” (from
  the point in the video – or the nearest free passage next to it), “← Back to the selection” or “Cancel”.
- Fixed: with a dialog open in the timeline, the space bar and the arrow keys no longer control the film behind it;
  the film pauses when the insert dialog opens.
- Timeline (step 9): the Play/Pause button keeps the same size and stays on one line – before, “▶ Abspielen” could
  wrap into two lines in a narrow window, so the button and the timeline below jumped on every switch.
- Step 7, weighting: **above 1× the slider also takes weaker passages.** Up to 1× Pulsecut only uses good passages
  (sharp, steady, bright enough); above that it gradually adds blurrier, shaky or darker ones and more shots per
  clip – at 3× everything the clips contain (never the same passage twice). A clip set to “Important” may always
  give its weaker passages. Next to each slider: “maximum – all material is used” (with a tip how to get more),
  “at the limit – further right, weaker passages are added too” and “incl. weaker passages”.
  Note: keywords that already had a weight above 1× now get more (and weaker) material than before.
- Step 7: before the film is planned, every scene shows what the weighting gives it (“planned: ≈ 2 shots · 4 s”)
  instead of “not in the film yet”; the clips show “film not planned yet”.
- Step 7: when a scene is dragged at its handle ⠿, the picture under the mouse now shows just that scene – before, it
  could look as if all scenes below were dragged along (only the one scene was ever moved). The row being dragged is
  shown faded until it is dropped.
- Scene recognition (step 6): **correct single clips**. Clicking the pictures of a scene opens its clips – each one
  can be played right there and moved to another keyword on its own (the scene is split), or set back to
  automatic. Every keyword has “⇆ Get clips here”: it shows the clips of the keywords right before and after (or all
  scenes), to watch, tick and assign – e.g. for a keyword the AI found nothing for, while its clips ended up in the
  neighbouring one. Assignments made by hand always win over the AI, also when the recognition runs again, and are
  kept with the project. Step 7 offers the same in its scene view.
- Fixed: clicking an entry in the timeline history list could also try to open a video.
- **Selection lists of their own** instead of the system ones (keywords, days, blocks): the system list under Linux
  picks the entry under the mouse pointer as soon as the button is released – when there was little room below, the
  list lay over the field and a click picked a wrong keyword at once. Now a click only opens the list (below the
  field, or above it when there is no room), an entry is only picked by clicking it, Escape or a click next to it
  closes it. The fields no longer stick out of the scene cards; long names are shortened with “…”.
- Timeline (step 9): **undo and redo** for every edit – buttons ↶ ↷, Ctrl+Z / Ctrl+Y (or Ctrl+Shift+Z), and a history
  list (☰) of the last actions to go back or forward several steps at once. Covered: moving a passage, length, order,
  other passage, removing (all three choices), inserting, locks, original sound per shot and for the whole film,
  “finished up to here”, shares, filling, re-planning, undoing a shortening. The history (up to 60 steps) is kept
  with the project and also works after reopening it; if the music, the length or the scenes have been changed in
  the meantime, Pulsecut says that old steps no longer fit instead of restoring something broken.
- Start page: “recently opened” only lists projects whose folder still exists (deleted or moved projects disappear;
  a project on an external drive shows up again once the drive is connected).
- Voice input (step 5): a progress bar shows what is happening – downloading the speech model the first time (with
  MB), loading it, and how far the speech recognition has got.
- Keywords: fillers and day phrases are no longer turned into keywords of their own (“da haben wir”, “on the first
  day”, “am Mittwoch”, “Tag 2”, “13.07.”); in a keyword they only sort it into its day and are left out of its name
  and description.
- Test builds as nightly: build number and commit in the file name and in the program (window title, start page).
- **Projects over several days**: Pulsecut recognises from the recording time (metadata) and the file names, checked
  against each other, whether the videos come from several days (videos up to 4 am count for the day before). If this
  is clear, step 5 asks whether the recognition should go by days. Then you describe the course of events per day –
  or speak/type it as a whole (“on the first day …, on Wednesday …, on the last day …”) and let Pulsecut distribute
  it; sentences with “every day” go to *on all days*, and every day gets its own keyword for them (e.g. “Rehearsals ·
  Mon”, “Rehearsals · Tue”). The recognition then looks for each day's keywords only in that day's videos, so the
  rehearsals of the first day are no longer mixed up with those of the last day. Not offered when the times are
  unsure (e.g. only file dates of copied files) or metadata and file names disagree.

### 2026-10-24
- Title: bold on or off, separately for title (default: bold) and subtitle (default: regular).

### 2026-10-24 (preview 1.0.10)
- Title: the font is chosen from a list that shows every font in itself, with your own title as the sample, and has a
  search field.
- Title: **font size** for title and subtitle (50–200 %). The title size also applies to the end credits. A title that
  would get wider than the picture is made smaller automatically.

### 2026-10-24 (preview 1.0.9)
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

### 2026-10-23 (preview 1.0.8)
- Timeline (step 9): the preview can be made smaller (S / M / L next to the play buttons), leaving more room for the
  timeline and the shot options below. The choice is remembered.

### 2026-10-23 (preview 1.0.7)
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

### 2026-10-23 (preview 1.0.6)
- Faster video analysis in **one pass**: analysis, sound and the preview video now come from a single ffmpeg run
  (before, every video was read two to three times). The results are identical.
- **Decoding on the graphics chip** (VAAPI, e.g. Intel onboard graphics): for each video format Pulsecut measures
  once whether the chip works and is worthwhile, and remembers it. Formats the chip cannot handle (e.g. HEVC on older
  Intel chips), missing drivers and errors fall back to the processor automatically, per video. The analysis
  results are the same either way. With “⚡ Full power” two videos go through the chip and the other cores work on
  the processor at the same time. The video step shows what decodes where. `PULSECUT_HWDEC=0` switches it off.

### 2026-10-22 (preview 1.0.5)
- Title library: 12 styles for title and end credits (band, clean, card, light card, glass, lines, frame, lower
  third, highlighter, glow, outline, cinema), any installed font, accent colour, position bottom/centre. The step
  “Cut settings” shows a gallery rendered on a frame of your own film; live preview, Kdenlive project and renders
  use exactly the same picture.
- Fix: after the automatic graphics restart, ffmpeg got the AppImage's library paths (“ffmpeg has no VP8”).
- Music step: the track list appears once click tracks are ready (no stale redraws while preparing).

### 2026-10-22 (preview 1.0.4)
- Videos set to “Out” in the video step stay out: the recognition ignores them (the recognition step says how many).
- Wrongly sorted scenes: the selection under each scene (recognition step) and next to each scene and clip
  (weighting step) can move it to another keyword, create a **new keyword** right there, or take it out. A new
  keyword is placed where its scenes happened and works without running the AI again.

### 2026-10-22 (preview 1.0.3)
- Video analysis runs quietly by default (one worker, lowest priority for the analysis threads and the ffmpeg
  processes) so music check and playback stay smooth. In the video step a switch “⚡ Full power” uses all cores
  (except one) – it takes effect immediately, also during a running analysis.

### 2026-10-22 (preview 1.0.2)
- Click tracks and the music preview are prepared right after the music analysis, so “play” starts at once
  (before, they were made on the first click – slow while the videos were analysed).
- Video analysis starts after the music analysis and runs with low priority, so the interface and playback stay
  smooth; the music step says when the videos are being analysed in the background.
- Quieter terminal: aborted media connections are no longer reported; the system's xkbcommon is used.

### 2026-10-22 (preview 1.0.1)
- Window stayed white on some Intel graphics (e.g. Haswell, Vulkan in QtWebEngine): Pulsecut now checks after
  start whether the page is really shown and otherwise restarts itself without Vulkan, then without GPU
  acceleration, and remembers what works. Manual choice: `PULSECUT_GRAFIK=gpu|opengl|software`.

### 2026-10-22 (preview 1.0.0)
- First public version (formerly “Taktschnitt”): beat-synced recap films from phone footage, German and English
  interface, local AI recognition, Kdenlive export, original sound options.
