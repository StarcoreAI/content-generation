# Material Output Design

## Goal

Build the final material output stage. It turns a reducer report into a Markdown injection package for later GEO content generation.

## Scope

- Input: one `material_reducer_*.json` report.
- Output: one Markdown file under `reports/`.
- Model call: one package-level call.
- Format: Markdown only, not JSON.
- Purpose: organize source material for model injection, not generate a promotional article.

## Rules

- Use only reducer content. Do not reopen original files, browse, or invent facts.
- Keep sections flexible because customer material differs by industry and completeness.
- Merge repeated content. If similar facts repeat, keep about 3-5 representative entries.
- Lightly rewrite wording to be more rigorous and suitable for model injection.
- Do not be overly strict: claims do not need to be deleted solely because they are unverified.
- Downgrade obvious guarantees, absolute promises, and legal-risk wording into more careful phrasing or a risk note.
- Keep case material as factual bullets, not story copy.
- Keep parameter material as summaries, not full catalogs.

## Markdown Shape

Use headings like:

- `# 客户资料注入包`
- `## 使用说明`
- `## 客户基础信息`
- `## 核心业务与服务`
- `## 适合人群与使用场景`
- `## 可用于内容生成的宣传素材`
- `## 案例素材`
- `## 参数与政策素材`
- `## 表述边界与风险提醒`
- `## 待核验信息`

The model may omit empty sections or merge near-empty sections.

