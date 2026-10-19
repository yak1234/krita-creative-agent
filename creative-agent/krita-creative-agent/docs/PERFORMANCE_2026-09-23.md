# Latest painting performance — 23 September 2026

The `test.kra` conversation `4e4c71bc-887c-43f4-ae4a-40e16e7de93c` ran from 17:35:55 to 18:10:29 UTC and paused during a review. The persisted diagnostic timeline covers its final 29 minutes. macOS power logs show idle sleep from 13:43:57–13:49:16 and 13:54:39–14:10:29 EDT. Those intervals account for about 21 of the 34.5 wall-clock minutes and coincide with both apparent model stalls. The 90-second model-idle timer fired when the machine resumed; the evidence does not establish a 5- or 16-minute awake provider response time.

In the available timeline, 39 native bridge calls total about 36 seconds of recorded elapsed time. The painting session has 33 assistant messages, 31 tool-use turns, 13 passes, three context compactions, and about 2.79 million cumulative tokens, mostly cached reads. Its 158-layer tree occupied about 32 KB of each observation result; each new model direction included the tree twice and used 61–71 KB of text. Paint receipts returned another 30–46 KB of text each. The latest conversation's TypeSafe mode was Off; routing did not affect this run.

Changes in the installed release `55ae42f63ddb8eedf9df90c96029a8f68f5130d211731a7208b44a06fd310a55`:

- Agent directions hold a macOS `PreventUserIdleSystemSleep` assertion via `caffeinate` while running. Stop, pause, completion and errors release it. The child also exits when the companion process dies. This does not prevent deliberate sleep and does not keep the display awake.
- The model context retains one full observed layer tree and a small separate document/revision receipt, rather than embedding the tree twice.
- Mutation tool replies retain the full native details for the host/UI but send the model a compact all-layer ID/name index plus complete records for affected layers. A fresh `observe_canvas` still supplies full layer properties when needed.

Local checks: 110 Node unit tests and six packaging tests passed, including guard lifecycle, single-copy stage context and receipt size/identity. A direct macOS assertion check showed `caffeinate` acquiring `PreventUserIdleSystemSleep`. After installation, live diagnostics reported matching UI, companion and bridge build IDs, a compatible connection and Krita 5.3.3. These checks do not establish a faster live painting run; measure the next matched active run before claiming a speedup. Batching independent color samples and related layer changes remains a follow-up opportunity.
