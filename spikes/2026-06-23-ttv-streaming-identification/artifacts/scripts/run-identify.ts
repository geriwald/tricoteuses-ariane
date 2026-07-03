// Trigger ttv's value-add pipeline (speaker identification + compte-rendu) on a fixture,
// using its offline transcript + NVS files. No Deepgram call. Writes under spike-streaming/,
// never touches the versioned fixture expected/.
// Adapted from tests/generate-expected.ts (minus the part that overwrites the fixture).
import path from 'node:path';
import fs from 'fs-extra';
import { getCompteRenduPath } from '../src/utils/path';
import { transcribeOne } from '../src/scripts/transcribeOne';

const UID = process.argv[2] ?? 'RUANR5L17S2026IDC458774';
const FIXTURE_DIR = path.join(process.cwd(), 'tests', 'fixtures', UID);
const OUT_DIR = path.join(process.cwd(), 'spike-streaming', 'out', 'identify', UID);
const fixture = (...parts: string[]) => path.join(FIXTURE_DIR, ...parts);

async function main() {
  await fs.remove(OUT_DIR);
  await fs.ensureDir(OUT_DIR);

  const ctx = await fs.readJson(fixture('input', UID + '.json'));
  const offlineTranscription = await fs.readJson(fixture('input', 'transcript.json'));

  const options: any = {
    transcriptsDir: OUT_DIR,
    audioDir: path.join(OUT_DIR, 'audios'),
    force: true,
    forceIdentify: true,
    reextract: true,
    diarize: true,
    lang: 'fr',
    provider: 'deepgram',
    dataDir: 'unused',
    legislature: 17,
    fromSession: '2025',
    chambre: 'AN',
    ss: '0',
  };

  const deps: any = {
    fs,
    exists: async (p: string) => fs.pathExists(p),
    nowIso: () => '2026-01-15T00:00:00.000Z',
    // stub ffmpeg (no audio needed, transcript is offline)
    extractWavMono16k: async ({ outputWavPath }: { outputWavPath: string }) => {
      await fs.ensureDir(path.dirname(outputWavPath));
      await fs.writeFile(outputWavPath, Buffer.from('RIFF----WAVEfmt '), 'binary');
    },
    // stub Deepgram with the fixture's offline transcript
    transcribeVideo: async () => offlineTranscription,
    // force NVS paths to the fixture files -> triggers identifySpeakersOnSegments
    findNvsPaths: () => ({
      finalplayerPath: fixture('input', 'nvs', 'finalplayer.nvs'),
      dataNvsPath: fixture('input', 'nvs', 'data.nvs'),
    }),
  };

  await transcribeOne(UID, ctx.urlVideo, options, ctx, deps);

  const crPath = getCompteRenduPath(UID, OUT_DIR);
  console.log(`[identify] compte-rendu généré -> ${crPath}`);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
