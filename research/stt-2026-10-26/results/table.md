| model | slice | calls | amount exact (strict) | amount (lenient) | amount digits heard | key noun | WER (non-number words) | p50 | p90 | $/min (billed) | rejected |
|---|---|---|---|---|---|---|---|---|---|---|---|
| google/gemini-3.5-transcribe | all | 144 | 58.3% | 60.2% | 100.0% | 95.8% | 7.0% | 1.71s | 2.17s | $0.0049 | 0 |
| google/gemini-3.5-transcribe | ogg | 48 | 55.6% | 58.3% | 100.0% | 93.8% | 7.5% | 1.70s | 2.34s | $0.0050 | 0 |
| google/gemini-3.5-transcribe | webm | 48 | 58.3% | 61.1% | 100.0% | 97.9% | 6.1% | 1.66s | 1.91s | $0.0049 | 0 |
| google/gemini-3.5-transcribe | mp4 | 48 | 61.1% | 61.1% | 100.0% | 95.8% | 7.5% | 1.78s | 2.21s | $0.0050 | 0 |
| google/gemini-3.5-transcribe | clean | 72 | 61.1% | 61.1% | 100.0% | 97.2% | 6.7% | 1.72s | 2.17s | $0.0050 | 0 |
| google/gemini-3.5-transcribe | noisy | 72 | 55.6% | 59.3% | 100.0% | 94.4% | 7.3% | 1.68s | 2.17s | $0.0049 | 0 |
| mistralai/voxtral-mini-transcribe-3-0 | all | 144 | 67.6% | 73.1% | 100.0% | 99.3% | 9.4% | 0.55s | 1.21s | $0.0030 | 0 |
| mistralai/voxtral-mini-transcribe-3-0 | ogg | 48 | 66.7% | 72.2% | 100.0% | 100.0% | 8.8% | 0.55s | 0.97s | $0.0030 | 0 |
| mistralai/voxtral-mini-transcribe-3-0 | webm | 48 | 66.7% | 72.2% | 100.0% | 97.9% | 11.0% | 0.54s | 1.33s | $0.0030 | 0 |
| mistralai/voxtral-mini-transcribe-3-0 | mp4 | 48 | 69.4% | 75.0% | 100.0% | 100.0% | 8.3% | 0.55s | 1.07s | $0.0030 | 0 |
| mistralai/voxtral-mini-transcribe-3-0 | clean | 72 | 68.5% | 74.1% | 100.0% | 100.0% | 7.3% | 0.55s | 1.27s | $0.0030 | 0 |
| mistralai/voxtral-mini-transcribe-3-0 | noisy | 72 | 66.7% | 72.2% | 100.0% | 98.6% | 11.4% | 0.54s | 1.04s | $0.0030 | 0 |
| mistralai/voxtral-mini-transcribe-3-0 +prompt | all | 48 | 66.7% | 72.2% | 100.0% | 100.0% | 8.8% | 0.54s | 1.33s | $0.0030 | 0 |
| mistralai/voxtral-mini-transcribe-3-0 +prompt | ogg | 48 | 66.7% | 72.2% | 100.0% | 100.0% | 8.8% | 0.54s | 1.33s | $0.0030 | 0 |
| mistralai/voxtral-mini-transcribe-3-0 +prompt | clean | 24 | 66.7% | 72.2% | 100.0% | 100.0% | 7.0% | 0.54s | 0.69s | $0.0030 | 0 |
| mistralai/voxtral-mini-transcribe-3-0 +prompt | noisy | 24 | 66.7% | 72.2% | 100.0% | 100.0% | 10.5% | 0.55s | 1.44s | $0.0030 | 0 |
| openai/gpt-4o-mini-transcribe | all | 144 | 75.9% | 75.9% | 98.1% | 98.6% | 8.6% | 0.67s | 1.33s | $0.0016 | 0 |
| openai/gpt-4o-mini-transcribe | ogg | 48 | 75.0% | 75.0% | 100.0% | 97.9% | 8.8% | 0.66s | 1.41s | $0.0016 | 0 |
| openai/gpt-4o-mini-transcribe | webm | 48 | 75.0% | 75.0% | 97.2% | 97.9% | 10.1% | 0.67s | 1.14s | $0.0016 | 0 |
| openai/gpt-4o-mini-transcribe | mp4 | 48 | 77.8% | 77.8% | 97.2% | 100.0% | 7.0% | 0.68s | 1.33s | $0.0016 | 0 |
| openai/gpt-4o-mini-transcribe | clean | 72 | 74.1% | 74.1% | 100.0% | 100.0% | 7.9% | 0.70s | 1.48s | $0.0016 | 0 |
| openai/gpt-4o-mini-transcribe | noisy | 72 | 77.8% | 77.8% | 96.3% | 97.2% | 9.4% | 0.67s | 1.27s | $0.0016 | 0 |
| openai/gpt-4o-mini-transcribe +neutral-prompt | all | 144 | 96.3% | 96.3% | 100.0% | 98.6% | 8.6% | 0.62s | 1.04s | $0.0026 | 0 |
| openai/gpt-4o-mini-transcribe +neutral-prompt | ogg | 48 | 97.2% | 97.2% | 100.0% | 100.0% | 9.6% | 0.61s | 1.38s | $0.0026 | 0 |
| openai/gpt-4o-mini-transcribe +neutral-prompt | webm | 48 | 97.2% | 97.2% | 100.0% | 100.0% | 8.8% | 0.64s | 0.86s | $0.0026 | 0 |
| openai/gpt-4o-mini-transcribe +neutral-prompt | mp4 | 48 | 94.4% | 94.4% | 100.0% | 95.8% | 7.5% | 0.62s | 0.74s | $0.0026 | 0 |
| openai/gpt-4o-mini-transcribe +neutral-prompt | clean | 72 | 96.3% | 96.3% | 100.0% | 98.6% | 7.9% | 0.62s | 1.03s | $0.0026 | 0 |
| openai/gpt-4o-mini-transcribe +neutral-prompt | noisy | 72 | 96.3% | 96.3% | 100.0% | 98.6% | 9.4% | 0.62s | 1.04s | $0.0026 | 0 |
| openai/whisper-large-v3-turbo | all | 144 | 77.8% | 82.4% | 99.1% | 96.5% | 13.9% | 0.69s | 1.71s | $0.0003 | 0 |
| openai/whisper-large-v3-turbo | ogg | 48 | 75.0% | 77.8% | 97.2% | 95.8% | 12.7% | 0.67s | 1.37s | $0.0003 | 0 |
| openai/whisper-large-v3-turbo | webm | 48 | 77.8% | 83.3% | 100.0% | 97.9% | 14.0% | 0.72s | 1.77s | $0.0004 | 0 |
| openai/whisper-large-v3-turbo | mp4 | 48 | 80.6% | 86.1% | 100.0% | 95.8% | 14.9% | 0.71s | 1.46s | $0.0004 | 0 |
| openai/whisper-large-v3-turbo | clean | 72 | 81.5% | 87.0% | 100.0% | 98.6% | 12.0% | 0.71s | 1.71s | $0.0003 | 0 |
| openai/whisper-large-v3-turbo | noisy | 72 | 74.1% | 77.8% | 98.1% | 94.4% | 15.8% | 0.68s | 1.61s | $0.0004 | 0 |
