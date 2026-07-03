// Test 1 — what ttv produces in streaming mode.
// Calls the provider's transcribeLive() directly (the CLI only accepts --uid/--youtubeUrl).
// Input is paced at 1x by the temporary `-re` patch in utils/ffmpeg.ts so it behaves like a live feed.
import path from 'node:path';
import { DeepgramProvider } from '../src/providers/deepgram.ts';

const wav = path.resolve('audios/RUANR5L17S2026IDC458774-3min.wav');
const out = path.resolve('spike-streaming/out/ttv-live.ndjson');

const provider = new DeepgramProvider();
console.log(`[test1] ttv transcribeLive START  in=${wav}  out=${out}`);
const t0 = Date.now();

await provider.transcribeLive({
  url: wav,
  outPath: out,
  language: 'fr',
  diarize: true,
  punctuate: true,
});

console.log(`[test1] ttv transcribeLive DONE in ${((Date.now() - t0) / 1000).toFixed(1)}s -> ${out}`);
