# ready-to-submit/

Finished task ZIPs for Terminus-3-Prod upload.

## Contents

| File | Purpose |
|------|---------|
| `your-task-name-preview.zip` | Local preview — contains `your-task-name/` folder |
| `your-task-name-submit.zip` | Platform upload — flat layout, no wrapper folder |

## Platform submission ZIP rules

The `-submit.zip` file includes **only**:

- `task.toml`
- `instruction.md`
- `environment/`
- `solution/`
- `tests/`

Do **not** include `rubrics.txt`, `README.md`, or the enclosing task folder name.

## Upload workflow (Phase F)

1. Upload `*-submit.zip` to Terminus-3-Prod
2. Check **generate rubric**, leave **Send to Reviewer** unchecked → submit for CI
3. Edit the generated rubric in the platform UI
4. Uncheck rubric generation before the next submission
5. When CI + rubric are clean, check **Send to Reviewer** and submit
