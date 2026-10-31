# Engine contract (for Part 2 and Part 3)

The platform (Part 1) calls your code over HTTP. You can keep it inside this repo (edit the file in
`shinri/engines/`) or host it elsewhere and set `ENGINE_<NAME>_URL`.

| Endpoint | Owner | Replace this file | Called |
|---|---|---|---|
| `POST /engines/claim` | Part 2 | `shinri/engines/claim.py` | first, in parallel with media |
| `POST /engines/media` | Part 3 | `shinri/engines/media.py` | only if the check has an image, video or audio |
| `POST /engines/origin` | Part 3 | `shinri/engines/origin.py` | after claim and media; it receives the extracted claims |
| `POST /engines/verdict` | Part 2 | `shinri/engines/verdict.py` | last; gets every signal |

**Change from the plan:** the plan had `/engines/claim` return the verdict. Because the verdict needs the
media and origin signals too, fusion is its own step, `/engines/verdict`. Until it returns something other than
501, the platform uses `shinri/fusion.py` (the same log-odds formula) and marks the result `fusion: platform-fallback`.

## Request (all four)
The full check record, plus two fields:

```json
{
  "checkId": "chk_ab12cd34ef",
  "channel": "telegram",
  "input": {"type": "image", "text": "caption", "mediaRef": "chk_ab12cd34ef.jpg", "mediaSha256": "…",
            "mediaMime": "image/jpeg", "mediaBytes": 81234, "language": null, "transcript": null},
  "claims": [], "signals": [], "engineRuns": [],
  "mediaPath": "/abs/path/to/data/media/chk_ab12cd34ef.jpg",
  "mediaUrl": "/media/chk_ab12cd34ef"
}
```
`mediaPath` is a local file when you run in the same container; use `GET {platform}/media/{checkId}` if remote.

## Response of claim / media / origin
```json
{
  "signals": [{"engine": "claim", "kind": "factcheck_match", "strength": -0.8, "weight": 1.5,
               "summary": "Fact-checker X rated this false",
               "evidence": {"source": "X", "url": "https://…", "seenAt": "2026-10-31T10:00:00Z"},
               "limitation": "Matched by similarity 0.84"}],
  "claims": [{"id": "c1", "text": "atomic claim", "quote": "exact words from the input", "numbers": []}],
  "language": "te", "transcript": "…", "notes": ["NumberCheck unavailable: no matching official dataset"],
  "mock": false
}
```
* `strength` is −1 to +1: negative = against the claim being true / the media being authentic, positive = for it.
* `weight` is fixed by you (0 to 10), never chosen by the LLM.
* A signal that fails validation is dropped and noted. One bad signal never fails the check.
* Return `"mock": true` while you use placeholder data. The UI then says "placeholder".
* `claims` (claim engine only) replaces the stored claims. `language` and `transcript` are stored on the check.
* Return `notes` for anything the user should know (a source was down, no official data found).
* Raise HTTP 5xx or time out and the platform retries, then continues without you and tells the user.

### Suggested `kind` values
| engine | kinds |
|---|---|
| claim | `factcheck_match`, `nli`, `numbercheck`, `news_corroboration` |
| media | `c2pa`, `metadata`, `metadata_edit`, `ela`, `ai_image`, `ai_image_2`, `ai_voice`, `caption_mismatch` |
| origin | `earlier_copy`, `wayback_earlier`, `phash_match_earlier`, `burst` |

The fallback fusion maps the largest negative signal to a label: `earlier_copy`, `wayback_earlier`,
`phash_match_earlier`, `caption_mismatch` → `old_or_out_of_context`; `ai_image`, `ai_image_2`, `ai_voice` →
`possible_ai_generated`; `ela`, `metadata_edit`, `c2pa_edited` → `signs_of_editing`; anything else → `contradicted`.

## Response of verdict
```json
{
  "verdict": {"label": "old_or_out_of_context", "confidence": 0.91, "topReasons": ["…"],
              "contributions": [{"engine": "origin", "kind": "earlier_copy", "strength": -0.9, "weight": 2.0,
                                 "contribution": -1.8, "summary": "…", "url": "https://…"}],
              "byEngine": {"origin": -1.8, "claim": -1.2}},
  "explanation": {"language": "te", "text": "…", "citations": ["https://…"], "generatedBy": "llm"},
  "mock": false
}
```
`label` must be one of: `supported`, `contradicted`, `old_or_out_of_context`, `signs_of_editing`,
`possible_ai_generated`, `not_enough_evidence`. An invalid response is ignored and the fallback is used.
Citations must come only from the signals' evidence URLs.

## Rules the platform enforces
* File type is decided from the file's first bytes. Limits: image 10 MB, video 20 MB, audio 20 MB (Telegram bots cannot read more).
* A check can never stay `processing` longer than `CHECK_TIMEOUT` (150 s); it becomes `failed` with a clear message.
* `media_index` (the perceptual-hash index) belongs to Part 3. Add the table in `shinri/db.py`, same SQLite file.
