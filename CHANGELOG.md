# Changelog

## 1.0.1 – 2026-10-22
- Window stayed white on some Intel graphics (e.g. Haswell, Vulkan in QtWebEngine): Pulsecut now checks after
  start whether the page is really shown and otherwise restarts itself without Vulkan, then without GPU
  acceleration, and remembers what works. Manual choice: `PULSECUT_GRAFIK=gpu|opengl|software`.

## 1.0.0 – 2026-10-22
- First public version (formerly “Taktschnitt”): beat-synced recap films from phone footage, German and English
  interface, local AI recognition, Kdenlive export, original sound options.
