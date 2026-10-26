# Making it yours: business profiles

The analyst works on **any** MySQL database out of the box: it reads the live schema, including primary keys,
foreign keys and column comments, and writes SQL from that. A *business profile* makes it noticeably better and safer
for your organisation, without touching code.

```bash
cp config/domain.example.yaml config/domain.yaml      # edit it
echo 'ANALYST_DOMAIN_FILE=config/domain.yaml' >> .env
python -m ai_database_analyst check                   # validates the profile against your live schema
```

Edits apply to the next question. No restart.

## What a profile can say

| Key | Purpose | Effect |
| --- | --- | --- |
| `title`, `subtitle`, `eyebrow` | Branding | Page header |
| `organization`, `description` | Who you are and what the data is | Context in every prompt |
| `preferred_sources` | Curated tables or views to try first, and for which questions | Prompt guidance. **The biggest accuracy gain** |
| `metrics` | How your organisation defines its numbers (with SQL) | Prompt: one definition of "revenue" everywhere |
| `glossary` | Internal terms and acronyms | Prompt |
| `rules` | Business rules, one sentence each ("exclude void invoices") | Prompt |
| `tables`, `columns` | Descriptions shown next to the schema (override database comments) | Prompt |
| `examples` | Starter questions shown to users | UI |
| `sql_examples` | Up to 5 worked question → SQL pairs | Few-shot examples; each is validated against the live schema and dropped if invalid |
| `hidden_tables`, `hidden_columns` | Data that must stay invisible (glob patterns) | **Enforced** by the validator, see below |

## Getting the best accuracy

1. **Point the analyst at a curated view.** Small local models do far better on one wide, readable view
   (`invoices_view`: one row per invoice line, already joined to customer and product, with friendly column names) than on
   twelve normalised tables. Create the view, grant `SELECT` on it, and list it under `preferred_sources`.
2. **Define the metrics once.** If "revenue" excludes refunds, say so under `metrics`. The model then answers consistently.
3. **Add 3–5 `sql_examples`** that show your conventions (fiscal year, status filters, naming). `python -m ai_database_analyst check`
   tells you if any no longer match the schema.
4. **Use comments in the database** (`COMMENT 'draft, sent, paid or void'`). They are picked up automatically.
5. **Pick a model to match the difficulty.** The 3B default is quick on simple questions; set `ANALYST_MODEL` to a larger model
   for multi-table analytics and raise `ANALYST_NUM_CTX` if you have a big profile.

## Hiding sensitive data

```yaml
hidden_tables:
  - "payroll"
  - "audit_*"
hidden_columns:
  - "employees.salary"
  - "*.email"
  - "*.tax_id"
```

Hidden data is removed from the schema the model sees **and** blocked in the validator, which rejects `SELECT *`, `t.*`, bare column
names, aliases, subqueries and CTEs that would reach it. (`COUNT(*)` is fine because it exposes no values.) Columns named like
`password`, `secret`, `api_key`, `ssn`, `credit_card`, `card_number` or `cvv` are hidden by default; set
`hide_sensitive_defaults: false` to turn that off.

> Hiding is a safety net for *this app*, not a replacement for database permissions. Prefer to grant the analyst account
> `SELECT` only on the views and columns people may see, and use the profile as a second lock.

## Example profiles

| File | Domain |
| --- | --- |
| `config/domain.retail.yaml` | The bundled retail demo database |
| `config/examples/finance.yaml` | Revenue, receivables, spend |
| `config/examples/hr.yaml` | Headcount, hiring, attrition (salary and personal data hidden) |
| `config/examples/support.yaml` | Tickets, backlog, resolution time, satisfaction |

They are starting points: change the table and column names to match your database.

## Follow-up questions and self-repair

- **Follow-ups.** After a result, tick *Follow-up to my previous question* to ask things like "and only for Europe?" or "now by month".
  The previous question and its (validated) SQL are given to the model as context.
- **Self-repair.** If the model's SQL uses a column that does not exist, has a syntax error, or MySQL rejects it as malformed,
  the model is shown the problem and tries again (`ANALYST_SQL_RETRIES`, default 1). Safety violations such as writes or file access
  are **never** retried. The result page tells you when a correction was needed, and the audit log records `attempts`.
