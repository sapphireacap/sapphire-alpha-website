// Ambient audio for The Geode -- a low sawtooth drone (gated by user
// toggle, off by default) plus an occasional data-tick chime. Native Web
// Audio API only, no dependency. A single module-level AudioContext is
// created lazily on first user gesture (browsers block autoplay of audio
// without one) and reused for both the drone and tick sounds.
let ctx = null;
let droneOsc = null;
let droneGain = null;

function getContext() {
  if (!ctx) {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    ctx = new AudioCtx();
  }
  if (ctx.state === "suspended") ctx.resume();
  return ctx;
}

export function startAmbientDrone() {
  const audioCtx = getContext();
  if (droneOsc) return; // already running

  const osc = audioCtx.createOscillator();
  osc.type = "sawtooth";
  osc.frequency.value = 55;

  const filter = audioCtx.createBiquadFilter();
  filter.type = "lowpass";
  filter.frequency.value = 200;
  filter.Q.value = 1;

  const gain = audioCtx.createGain();
  gain.gain.value = 0.03;

  osc.connect(filter).connect(gain).connect(audioCtx.destination);
  osc.start();

  droneOsc = osc;
  droneGain = gain;
}

export function stopAmbientDrone() {
  if (!droneOsc) return;
  droneOsc.stop();
  droneOsc.disconnect();
  droneGain.disconnect();
  droneOsc = null;
  droneGain = null;
}

export function playDataTick() {
  const audioCtx = getContext();
  const osc = audioCtx.createOscillator();
  osc.type = "sine";
  osc.frequency.value = 2000;

  const gain = audioCtx.createGain();
  const now = audioCtx.currentTime;
  gain.gain.setValueAtTime(0, now);
  gain.gain.linearRampToValueAtTime(0.05, now + 0.05); // 50ms attack
  gain.gain.linearRampToValueAtTime(0, now + 0.15); // 100ms decay

  osc.connect(gain).connect(audioCtx.destination);
  osc.start(now);
  osc.stop(now + 0.15);
}
