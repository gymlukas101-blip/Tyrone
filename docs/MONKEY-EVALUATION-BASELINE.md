# Monkey evaluation baseline (2026-11-20)

**Labels:**
- **measured (container):** the Linux cloud container.
- **measured (Windows CI):** the GitHub `windows-latest` runner.
- **not yet measured:** needs the owner's Dell or a Claude key.

## Functional

| Measure | Value | Where |
|---|---|---|
| Unit and integration suite | 469 passed, 4 skipped (after Milestone 1 and its review fixes) | container |
| End-to-end course runs (6 scenario mixes, incl. Canvas/embed/quiz/SSO) | 6/6 verified by the course server | container |
| Browser fixtures (20 situations) | 20/20 | container + Windows CI |
| Windows native tasks (13) | Monkey UIA 13/13; agent-desktop 8/12; Windows-MCP 10/12 | Windows CI |
| Hybrid browser → Notepad + Save As → browser | pass, 8.7 s | Windows CI |
| Own Chrome via extension (full course) | pass, 0 unauthorized actions | container (real Chromium + extension) |
| Routing rules | 28/28 correct on the 28 of 42 bench cases they handle; 14 go to the classifier | container (offline) |
| Live classifier accuracy | — | not yet measured (needs a key) |
| Memory eval (`tests/test_memory_eval.py`, M1 tests) | pass: forget purges; sensitive not auto-recalled | container |
| Wake-word false activations, STT accuracy | — | not yet measured (Dell) |

## Performance

| Measure | Value | Where |
|---|---|---|
| `import monkey.app` cold | ≈1.05 s (0.86 s of it is the anthropic SDK) | container |
| UIA snapshot of a 21-control window | 0.06–0.33 s | Windows CI |
| Browser action latency, p50 (fixtures) | 51–1865 ms depending on the action (waits dominate) | container |
| Managed browser startup | 430–610 ms | container |
| Time to first audio / turn latency p50/p95 | — | not yet measured (instrumentation in Milestone 2) |
| Idle CPU/GPU, RAM growth | — | not yet measured (Dell; render tiers in Milestone 4) |
| Cost per successful computer task with the model planner | — | not yet measured (needs a key) |

## Security checks in the suite

| Check | Expected result | Test |
|---|---|---|
| Enter/Space on Send/Delete; Enter in a message box; dangerous chords (also pywinauto syntax); typed line breaks; arrows on quiz options | asks for approval, or is yours to do | `test_key_presses_are_as_risky_as_what_they_press`, browser test |
| Injection fixture "press Delete account" | refused | `run_browser` `injection` fixture |
| Typed navigation that carries data (query, fragment or path) to another site, under "Any website" | asks for approval | `test_any_website_still_asks_before_carrying_data_to_another_site` |
| Markdown image exfiltration | 0 requests | `test_markdown_images_from_the_model_never_load` |
| Taint across turns; outside links | memory writes blocked; outside links not opened | M1 tests |
| Logs | free of keys, tokens, ICS links, emails | `test_logs_never_carry_keys_tokens_or_private_calendar_links` |
| Wrong pairing code; foreign origins on the Chrome bridge | refused | `tests/test_chrome_bridge.py` |
