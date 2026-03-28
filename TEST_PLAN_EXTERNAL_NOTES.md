# Comprehensive Test Plan: `feat/external-notes`

This plan covers database migrations, model logic, service integration, and async task execution.

## 1. Database Migration (Local Postgres)
- **Goal:** Verify data is correctly migrated and downgrade is safe.
- **Steps:**
  1. `alembic upgrade head`
  2. Insert test data: `INSERT INTO meetings (id, organization_id, scheduled_start, summary, summary_doc_id, status) VALUES (gen_random_uuid(), 'org-id', now(), 'Legacy summary', 'doc-123', 'completed');`
  3. Verify migration: `SELECT external_notes FROM meetings WHERE summary_doc_id = 'doc-123';`
     - *Expected:* `{"gemini": [{"content": "Legacy summary", "doc_id": "doc-123", ...}]}`
  4. Test downgrade: `alembic downgrade -1`
  5. Verify restoration: `SELECT summary, summary_doc_id FROM meetings WHERE id = '...';`
     - *Expected:* `summary` is "Legacy summary", `summary_doc_id` is "doc-123".

## 2. Model Logic (`Meeting.set_notes`)
- **Goal:** Verify deduplication and boolean return values.
- **Steps:**
  1. Initialize `Meeting` object.
  2. Call `set_notes("granola", "test 1")`.
     - *Expected:* Returns `True`. `external_notes["granola"]` has 1 entry.
  3. Call `set_notes("granola", "test 1")` again.
     - *Expected:* Returns `False`. `external_notes["granola"]` still has 1 entry.
  4. Call `set_notes("gemini", "test 2")`.
     - *Expected:* Returns `True`. `external_notes` has both "granola" and "gemini" keys.

## 3. Dedup Service Integration (`find_or_create_meeting`)
- **Goal:** Verify notes update existing meetings and trigger summaries.
- **Steps:**
  1. Mock `workers.tasks.sync.generate_meeting_summary.apply_async`.
  2. Call `find_or_create_meeting` with `notes_source="granola"`, `notes_text="First note"`.
     - *Expected:* Meeting created, `apply_async` called once.
  3. Call again with same params.
     - *Expected:* Existing meeting found, `apply_async` NOT called (due to `set_notes` returning `False`).
  4. Call again with `notes_text="Second note"`.
     - *Expected:* Existing meeting found, `apply_async` called again.

## 4. Async Task Logic (`generate_meeting_summary`)
- **Goal:** Verify LLM synthesis of multiple sources.
- **Steps:**
  1. Create a meeting with notes from two sources (`granola` and `fireflies`).
  2. Run `_generate_meeting_summary` manually (or mock Claude response).
  3. Verify `meeting.summary` is updated with the synthesized content.
  4. Ensure `external_notes` themselves are NOT modified/deleted by the task.

## 5. Connector-Specific Flows (Google Calendar)
- **Goal:** Verify inline fetch vs. async fallback.
- **Steps:**
  1. Mock Google Drive API response for a specific `gemini_doc_id`.
  2. Run `sync_activities` with an event containing that attachment.
  3. Verify `meeting.external_notes["gemini"]` is populated immediately during sync.
  4. Verify `generate_meeting_summary` is scheduled.

## 6. Regression Check
- **Goal:** Ensure legacy `summary` parameter still works for unmigrated connectors.
- **Steps:**
  1. Call `find_or_create_meeting(summary="Legacy fallback")`.
  2. Verify `meeting.summary` is set directly and `external_notes` remains `None`.
