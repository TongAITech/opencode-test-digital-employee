# OpenCode Test Digital Employee

RC7 closed-loop runtime is developed on `work/rc7-closed-loop-runtime`.

## RC7 administration platform

The administration platform is a lightweight, dependency-free local web UI backed directly by the R1 Event Stream projection. It does not use `aitest.db` or a shadow business database.

Start on Windows:

```bat
packaging\rc7\START-RC7-ADMIN.cmd
```

Start on macOS/Linux:

```sh
packaging/rc7/START-RC7-ADMIN.sh
```

Use `PFC_RC7_R1_PATH` to point at the canonical RC7 R1 JSONL stream. The default listener is `127.0.0.1:4097` and can be changed with `PFC_RC7_ADMIN_HOST` / `PFC_RC7_ADMIN_PORT`.

The UI is Chinese and provides left-side navigation, filters, list/detail views, pagination, Mission/Task/Gap/Evidence/Defect/Report projections, and controlled Test Case revision append operations.
