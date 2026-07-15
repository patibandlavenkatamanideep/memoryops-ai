# Playground screenshots — capture guide

This folder holds the public screenshots + demo GIF referenced by the main
`README.md` hero section. Screenshots should be produced from a **running**
playground, so they are an operator step (a live browser is required); this guide
makes them reproducible. The checked-in `demo.gif` is a short lifecycle explainer
asset for the README.

## Capture

```bash
cd apps/playground
pip install -r requirements.txt
streamlit run streamlit_app.py   # http://localhost:8501
```

In the app, click **🌱 Seed demo memories** in the sidebar, then capture one image
per tab into this folder:

| File | Tab | What it should show |
|------|-----|---------------------|
| `01-capture.png` | Capture & ask | A message + the policy decisions (`SAVE`/`DROP_LOW_UTILITY`/`BLOCK`) and the memories used to answer a follow-up question. |
| `02-governance.png` | Memories & governance | A memory under **legal hold** with a blocked delete (the HTTP-409 message), and the lifecycle-worker run table. |
| `03-retention.png` | Retention preview | The retention decision table with `held` / `expired` / `retain` outcomes and `blocked_by`. |
| `04-audit.png` | Audit trace | The content-free audit-event timeline. |
| `demo.gif` | (whole flow) | Capture → ask → legal hold → blocked delete → withdraw consent → run workers → audit. |

## Recording the GIF

Any screen recorder works; e.g. with `ffmpeg` + a screen capture, or a tool like
LICEcap / Kap. Keep it under ~15s and scoped to the four-step story above.

## Naming / referencing

Keep the filenames above so the `README.md` image links resolve without edits.
Images are demo-only (no real data) and safe to publish.
