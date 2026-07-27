# Provider setup

Credentials are read from the environment only and never printed, persisted, or committed.

| Provider | Env var | SDK |
|----------|---------|-----|
| Gemini | `GOOGLE_API_KEY` | `google-genai` |
| OpenAI | `OPENAI_API_KEY` | `openai` |
| Anthropic | `ANTHROPIC_API_KEY` | `anthropic` |

Model IDs live in `configs/*.yaml` (never hardcoded). Every run records the configured
**and** API-reported model id, provider SDK version, generation settings, and prompt
hash. Verify availability offline:
```bash
python -c "from research.extraction_eval.providers import build_provider as b; print({p: b(p,'m').available() for p in ['gemini','openai','anthropic']})"
```
All `False` without keys is expected. One shared logical prompt (`prompts/extraction_v1.txt`)
is used across providers; only structured-output *syntax* differs per SDK.
