# Requirements document intake implementation contract

This adds a document-first entry to existing TeamBlocks; no credentials in frontend and no change to runtime node semantics.

## HTTP
- POST `/api/requirements/extract` JSON `{filename:string, content_base64:string}`. Maximum upload 5 MiB, PDF <= 40 pages, extracted text <= 60,000 characters; reject above limits with clear errors, no silent truncation. `.pdf`, `.txt`, `.md` only. Returns `{document: RequirementDocument}`.
- POST `/api/requirements/analyze` JSON `{document:RequirementDocument, planner:{provider,model,credential_ref,base_url?}}`. Uses configured real planning model and existing safe providers.complete; no template/mock fallback. Returns `{analysis:RequirementAnalysis}`.
- Existing `/api/plan` unchanged request shape. Project goal/deliverable and resources supplied by frontend reflect the reviewed requirement analysis. Planner schema will accept omission of server-owned `project` and `resources` from model response and inject originals; supplied fields must still match exactly, never accept fabricated resources. Requirement content must reach model through resources; avoid forcing the model to echo full uploaded content in its output.

```ts
type RequirementDocument = {
  filename:string; source_type:'pdf'|'text'; sha256:string;
  page_count:number; text:string;
  pages:{number:number;text:string}[];
  warnings:string[];
};
type RequirementAnalysis = {
  project_name:string; goal:string;
  deliverables:string[];
  tasks:{title:string;description:string;acceptance:string;source_pages:number[]}[];
  constraints:string[]; missing_information:string[];
};
```

Document parser in `backend/documents.py`: `extract_document(filename,content_base64)->dict`, `DocumentError(message,status=400)`; raw PDF processed locally, not saved in repository nor passed as executable contents. Reject encrypted/malformed/empty/no-text PDF. Warn on any page without extractable text; mixed documents can proceed with visible warnings. Use pypdf bounded text extraction in a separate subprocess with hard timeout when practical. PDF original is not part of runtime ZIP, only the extracted UTF-8 content resource. No OCR claim. Bound decompressed content/page where possible; external URLs, actions, links in a PDF are not followed.

AI requirements module `backend/requirements.py`: `analyze_requirements(document,planner,*,model_call=None)->dict`, raises PlanningError for safe user-facing errors. Verify document shape, text limits, page counts, source_pages valid, nonempty goal/deliverables/tasks, <=12 tasks, and arrays types. Accept at most initial call + one schema repair. Document is untrusted project data, cannot override system/tool/permission constraints. Extract only supported facts and tasks, list missing details instead of inventing. Mark unsupported requested outputs (e.g. PPT) clearly in missing_information; downstream workflow can prepare supported Markdown/CSV/JSON intermediates rather than pretend to create unsupported formats. Do not assume member skills. Requirements analysis uses no tool grants. Result is editable by user before generating.

## Frontend
New `RequirementIntake` component used in AI designer, with file input/drop zone; text preview editable (editing invalidates old analysis), analysis button, structured editable task/deliverable/constraint/missing-info fields, then Generate workflow from requirements button. Existing planner fields remain in an advanced/model section below document intake. Upload and text preview require no key; real analysis/generation requires configured planner. Upload never modifies canvas by itself.

Persist intake document/analysis only when user explicitly chooses use/generate, as normal workflow resources so save/import/export share the schema. Suggested resource IDs `requirements-source-<hash8>` and `requirements-analysis-<hash8>`, paths `inputs/requirements-<hash8>.txt` and `inputs/requirements-analysis-<hash8>.json`; name includes source filename, description includes source provenance and `[Page N]` markers. `example:false`. `project.goal` becomes extracted goal + reviewed tasks/constraints/missing info; `project.deliverable` from reviewed deliverables. Keep project name and existing members; fill a generated name only for default/empty project name. Preserve unrelated resource entries; replace only selected requirement source/analysis entries. Cancel leaves old workflow intact. User confirmation to generate invokes standard `/api/plan`; one undo restores previous workflow.

AI designer always includes a visible editable brief from current project.goal and deliverable, even without an uploaded document. Onboarding offers upload requirements path without requiring manual goal/deliverable first, collects member count/name then opens the same intake flow. Template explicitly independent.

Tests must include actual text-PDF extraction, scanned/malformed/oversized rejection, analysis fixture + invalid schema repair/fail/no key, document text passed into planner, preservation in saved/ZIP workflow, and browser upload->preview->analysis (explicit response fixture when no live model test)->canvas edit/export. Do not print/read .env contents.
