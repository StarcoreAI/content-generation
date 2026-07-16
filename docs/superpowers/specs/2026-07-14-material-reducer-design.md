# Material Reducer Design

## Goal

Build the second-stage material reducer after the package filter. The reducer turns retained customer material units into concise source material for GEO article generation. It removes repeated, irrelevant, internal, and risky text inside otherwise retained files.

## Scope

- Input: one material filter report plus the original package path recorded in that report.
- Selection: only reduce units already kept by the filter.
- Extraction: re-use the existing package extractor to load full unit text for those kept unit IDs.
- Model call: one package-level call for the selected units.
- Output: one JSON report containing each input `unit_id` and its `reduced_text`.
- Empty `reduced_text` means the unit should not enter the output worker.

No chunking, master/worker split, memory system, RAG, multi-model review, or strict golden assertions in this version.

## Reducer Rules

The prompt must be domain-neutral. It must not include customer-specific examples, industry-specific examples, or province/category names from the current sample package.

Keep concise facts that are reusable in public GEO content:

- customer identity, brand, official channels, locations, coverage, audience, products or services
- service process, delivery boundaries, conditions, compliance limits, prohibitions, and red lines
- concrete claims that are directly supported by the provided material

Remove text that is not useful source material:

- form instructions, placeholders, blank fields, template explanations, and metadata about how to fill a document
- internal execution notes, operational handoff notes, and agency-side workflow text
- unrelated industry examples, competitor notes, duplicated rows, and repeated statements
- generic promotional adjectives without concrete facts
- unsupported strong claims, guarantees, rankings, absolute success statements, or statistics without evidence
- third-party catalogs or listings that do not add customer-specific facts

If a relevant customer-specific fact conflicts across selected units, keep a short `待核验` line inside `reduced_text` instead of resolving it by guessing.

## Output Contract

The model response must be parseable JSON:

```json
{
  "results": [
    {
      "unit_id": "same unit id as input",
      "reduced_text": "concise reduced material, or empty string"
    }
  ]
}
```

Every input unit must appear exactly once. Unknown unit IDs are invalid. No `useful`, score, category, confidence, or risk object is needed.

## Runner

Add a small script:

```powershell
.\.venv\Scripts\python.exe scripts\run_material_reducer.py reports\<filter_report>.json --max-tokens 8192
```

The script should write `reports/material_reducer_<package>_<timestamp>.json` with:

- source filter report path
- package path
- input count
- reduced count
- model name
- results
- package-level error if the model call fails

## Evaluation

Run the reducer on the latest real filter report and inspect the report manually. The first check is directional, not a deterministic unit test:

- retained intro-style material should keep factual customer identity and services while removing generic praise
- retained high-density workbook material should keep concrete facts and compliance boundaries while removing template, internal, unrelated, and unsupported claims
- retained third-party listing material with no customer-specific facts should reduce to empty text

