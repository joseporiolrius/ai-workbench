# S5 compatibility pin (read-only)

At S5 the **hello-world** app gains its release pipeline; the **workbench** does
NOT change. This ref is a **read-only compatibility checkpoint**: it confirms the
S4 workbench scaffold (pinned pi-web-ui:1.0.0 + qdrant:v1.15.0) stays compatible
through S5. Importing or checking it introduces **no** workbench CD workflow and
does **not** replace the configured Compose files. The workbench's own release
work arrives later (S9+).
