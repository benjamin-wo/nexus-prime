# Speech-to-text bake-off for voice notes (2026-10-26)

Goal: choose an OpenRouter STT model for Nexus voice messages, which are short money and travel commands such as "grab twelve fifty". All clips are synthetic and contain made-up content only.

## Recommendation

**Use `openai/gpt-4o-mini-transcribe`** with a short formatting prompt passed through `provider.options.openai.prompt`, plus `language: "en"` and `temperature: 0`:

```json
{
  "model": "openai/gpt-4o-mini-transcribe",
  "input_audio": { "data": "<base64>", "format": "ogg" },
  "language": "en",
  "temperature": 0,
  "provider": { "options": { "openai": {
    "prompt": "Voice note to a personal expense tracker. Write money amounts as digits with a dollar sign and a decimal point, for example $4.20, $35.75, $6.05, $2.3k."
  } } }
}
```

- **Amount exact: 96.3%.** No other configuration scored above 78%. The prompted model also had the lowest p90 latency (1.04 s) and costs about $0.0026 per minute billed (≈ $0.0001 per 3-second note).
- **No ffmpeg conversion is needed.** All 4 models accepted all 3 container formats with zero rejections. Send the bytes as they are, with `format` set to `ogg` (Telegram voice), `webm` (Chrome/Android MediaRecorder) or `m4a` (iPhone Safari MP4/AAC).
- **The parser should still treat `H:MM` as a possible amount.** The only remaining amount misses were "Lunch at Maxwell 8:40". When a message has a spend verb or merchant and no `$`, the parser should read `8:40` as $8.40 (or ask). It should also confirm amounts in the reply, as it does today for typed input.
- **Do not prompt Whisper.** See below.

Fallback: `openai/whisper-large-v3-turbo` without a prompt. It is about 8× cheaper (~$0.0003/min) but has 77.8% strict amount accuracy, and its WER is roughly 1.5× higher.

## Method

1. **Clips.** 12 phrases were spoken by 2 voices each, giving 24 base clips. They were generated with `POST /api/v1/audio/speech` using `microsoft/mai-voice-2.1-flash` in four accents: en-US Harper, en-GB Harry, en-IN Priya and en-AU Isla. The TTS has no en-SG voice. Each clip got 0.25 s of silence padding at each end.
2. **Noise.** Each clip also got a **noisy** copy: a white plus brown noise mix and a 120 Hz hum at ~15 dB SNR, generated with numpy (`scripts/gen.py`). That makes 48 clips.
3. **Formats.** Each clip was encoded the way Nexus receives it, for 144 files:
   - OGG/Opus, 48 kHz mono, 24 kbps, `-application voip` (Telegram voice note)
   - WebM/Opus, 48 kHz mono, 24 kbps (MediaRecorder)
   - MP4/AAC `.m4a`, 44.1 kHz mono, 48 kbps (Safari)
4. **Transcription.** Every file went through `POST /api/v1/audio/transcriptions` as base64 JSON with `language: "en"` and `temperature: 0`, 6 requests at a time, from this cloud container. Latency is wall-clock time for the whole request, including the upload, so it is an upper bound on what the bot would see.
5. **Scoring** (`scripts/score.py`):
   - **amount exact (strict, main metric).** The transcript contains the expected value as a number (`12.50`, `$12.50`, `1.8K`, `60`) or as spoken words ("twelve fifty"). Clock-style `8:40` and dropped decimals such as `1799` count as wrong, because a parser would read them wrongly.
   - **lenient.** Also accepts a split pair like "12. 50".
   - **amount digits heard.** The right digits are present in any form. This separates hearing errors from formatting errors.
   - **key noun.** The merchant or name is present. "Anne" is accepted for Ann because they are homophones.
   - **WER.** Word error rate over non-number words only, since amounts are scored separately.
   - **$/min.** Computed from `usage.cost` divided by audio seconds.
   - Amount metrics cover the 9 phrases that contain an amount. Key noun and WER cover all 12.

Models tested (prices are list prices per the models API): `openai/whisper-large-v3-turbo` ($0.0002/min DeepInfra, $0.00067/min Groq), `openai/gpt-4o-mini-transcribe` ($1.25/M in, $5/M out tokens), `mistralai/voxtral-mini-transcribe-3-0` ($0.0035/min) and `google/gemini-3.5-transcribe` ($2/M in, $12/M out). The API lists 28 STT models in total, ranging from about $0.0002/min (Qwen3-ASR 0.6B, Nemotron) to $0.006/min (whisper-1). These four were picked as the cheapest and fastest well-known options.

Total spend: about $0.15 for STT plus a few cents for TTS.

## Results (all formats, clean and noisy)

| model | calls | amount exact | lenient | digits heard | key noun | WER | p50 | p90 | $/min billed | rejected |
|---|---|---|---|---|---|---|---|---|---|---|
| **gpt-4o-mini-transcribe + prompt** | 144 | **96.3%** | 96.3% | 100% | 98.6% | 8.6% | 0.62s | **1.04s** | $0.0026 | 0 |
| whisper-large-v3-turbo | 144 | 77.8% | 82.4% | 99.1% | 96.5% | 13.9% | 0.69s | 1.71s | **$0.0003** | 0 |
| gpt-4o-mini-transcribe | 144 | 75.9% | 75.9% | 98.1% | 98.6% | 8.6% | 0.67s | 1.33s | $0.0016 | 0 |
| voxtral-mini-transcribe-3-0 | 144 | 67.6% | 73.1% | 100% | 99.3% | 9.4% | **0.55s** | 1.21s | $0.0030 | 0 |
| gemini-3.5-transcribe | 144 | 58.3% | 60.2% | 100% | 95.8% | **7.0%** | 1.71s | 2.17s | $0.0049 | 0 |

`results/table.md` has the same table broken down by format and by clean or noisy audio. Format made no consistent difference: every model moves by at most about 6 points between OGG, WebM and MP4, with no format consistently best. Noise cost Whisper about 7 points on amounts and changed little for the others.

**Main finding: every model hears the numbers correctly (98–100% digits heard), and the losses are formatting.** Without a prompt, the models write money as clock times or drop the decimal point. Only gpt-4o-mini-transcribe changes its formatting when given a prompt.

### Prompt experiments

| model + prompt | effect |
|---|---|
| gpt-4o-mini-transcribe, neutral prompt (above) | 75.9% → 96.3% amount exact; it writes "$23.50", "$17.99" |
| whisper-large-v3-turbo, prompt via `groq` / `deepinfra` options | **Harmful.** 29 of 48 OGG calls returned `""`; one probe returned `"Grab $12.00."` for "grab twelve fifty". OpenRouter does not let you pin the provider for STT, so the behaviour depends on which provider serves the request. |
| voxtral-mini-transcribe-3-0, prompt via `mistral` options | Ignored; results are identical to no prompt. |
| gemini-3.5-transcribe, prompt via `google-ai-studio` options | Rejected: `400 Provider returned 400` on all 48 calls. |

An earlier prompt contained the test's own amounts and merchant names and scored 100%. That number is not reported because the prompt leaked the answers. The neutral prompt in `neutral_prompt.txt` shares nothing with the test set.

## Failures (verbatim quotes)

Amount formatting, without a prompt:
- "lunch at maxwell eight forty" → Gemini/Voxtral/gpt-4o-mini/Whisper: `"Lunch at Maxwell 8:40."`. Voxtral and gpt-4o-mini on noisy audio: `"Lunch at Maxwell 840."`
- "taxi home twenty three fifty last friday" → Whisper/Voxtral/Gemini: `"Taxi home 2350 last Friday."`; Gemini/Voxtral/gpt-4o-mini: `"Taxi home 23:50 last Friday."`
- "seventeen ninety nine for netflix" → Gemini/gpt-4o-mini: `"1799 for Netflix."` (Whisper and Voxtral wrote `17.99`)
- "grab twelve fifty" → Whisper/Voxtral: `"Grab 12. 50."`; Gemini/Voxtral: `"Grab 1250."`, `"Grab 12:50."`
- "dinner sixty at din tai fung…" (noisy, AU) → Gemini: `"Dinner 6:00 at Din Tai Fung split with Ann."`

With the prompt (gpt-4o-mini-transcribe, all 6 misses):
- maxwell-in clean/noisy: `"Lunch at Maxwell 8:40."` / `"Lunch at Maxwell 840."` (4 of 6 calls)
- payback-au, mp4: `"M paid me back $40."` (2 of 6; Ann lost)

Words and names:
- "paid the rent" (IN) → `"Pay the rent."`, `"Feed the rent."` (gpt-4o-mini, no prompt); Voxtral: `"पेय द रेन।"` once (Hindi script on noisy IN webm, even with `language: "en"`)
- "dinner sixty at din tai fung, split with ann" (noisy, AU) → gpt-4o-mini: `"Janus Sixty at Din Tai Fung, split with M."`; Whisper: `"Dinner 60 at Dim Tai Fung, split with N."`
- "ann paid me back forty" → Gemini: `"And paid me back forty."`; Whisper: `" and paid me back $40.  We'll be right back."` (an invented phrase)
- "last friday" → Whisper: `"Loss  Friday"` (noisy, IN)

All failures are in `results/failures.json`. Every transcript is in `results/transcripts.jsonl`.

## Caveats

- The voices are TTS, not real people, and the noise is synthetic. Real Telegram audio from a hawker centre will be harder. There is no Singlish or en-SG voice, so the result for local accents is unknown.
- n is small: 24 base clips and 9 with amounts. A difference of a few points is noise.
- The `netflix-gb` clip has a TTS artifact at the end. All four models transcribe it as `"Don't."` or `"Dunked."`, which slightly inflates WER for every model equally.
- Latency was measured from a cloud container through a proxy. Expect different absolute numbers from the bot's host, though the ranking should hold.
- Whisper-turbo routes to DeepInfra or Groq. Groq bills a 10-second minimum, so a 3-second note costs about 3× the list price there.

## Files

- `manifest.json`: per clip, the expected text, amount, key noun, date words, accent, noise and duration
- `clips/{ogg,webm,mp4}/`: the 144 test files (2.4 MB)
- `scripts/gen.py`: TTS generation and noise mixing (the ffmpeg encode commands are listed in Method above)
- `scripts/run.py`: the STT runner; it reads `OPENROUTER_API_KEY` from the environment
- `scripts/score.py`: the scorer
- `results/`: the per-slice table, all transcripts and the failures
