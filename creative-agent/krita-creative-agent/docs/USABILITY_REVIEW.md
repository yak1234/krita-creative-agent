# Creative Agent — release usability session

Status: **prepared, not run**. This protocol does not establish participant evidence. The product goal requires one non-artist and two practicing artists; they must complete the tasks in actual Krita. No participants have been contacted.

## Record the tested installation

- Date and participant identifier (avoid personal information in the repository):
- Experience: non-artist / practicing artist; usual painting software:
- Mac model, architecture, macOS version and display scaling:
- Krita version:
- UI, companion and native bridge build IDs from diagnostics:
- Installation method and whether this Mac had development tools or an earlier plugin:
- Model/provider; result and date of the image/tool capability check:
- Panel width, docked/floating, theme and text size:
- Test artwork and isolated project folder:

Use disposable copies. Keep the participant's original artwork outside the test project. Explain the exercise and recording consent, but do not teach where the controls are before the discovery tasks. Record assistance rather than silently steering the participant.

## Tasks

| Task given to participant | Observable success | Record |
|---|---|---|
| “Ask what is visible in the painting already open.” | Finds chat and Ask; sees canvas attachment and sent snapshot; answer concerns that painting; no artwork change/save | Time, wrong turns, assistance |
| “Ask about only the upper field, then remove that context.” | Discovers Selected area; understands rectangular crop; previews/removes it without changing painting permission | Time, mistaken beliefs |
| “Use this reference for its material, keeping your composition.” | Attaches reference; states or edits its purpose; sees which image goes to which provider | Time, assistance |
| “Plan a painting of Mara with a red coat and curly hair. Then make her expression gentler while keeping her outfit and pose.” | Understands the plan; edits/clarifies a requirement; unrelated character facts stay intact | Lost/unclear requirements |
| “Let the assistant test the texture on the upper field, and stop before a full painting pass.” | Recognizes target/stage/allowance; explicitly starts; stops at calibration boundary; can explain current activity | Accidental actions, confusion |
| “Pause it, add a direction, then continue.” | Finds Pause immediately; knows in-flight work settles; resumes once; no repeated pass | Delay, repeated actions |
| “Compare the result, reduce the texture and reject it.” | Understands before/after; finds strength/rejection; manual work on another layer remains intact | Wrong contribution selected, lost work |
| “Find the painting in Finder, rename/move this test copy, and restore the conversation.” | Finds ordinary filename; uses Locate painting when needed; original old path is not recreated; restore stays paused | Help, unexpected files |
| “Read an earlier answer while the next answer arrives.” | Stream does not pull the view down or lose selection; Jump to latest works; composer and Stop remain visible | Scroll/selection failures |
| “Resize and float the panel, switch theme, and use it with the keyboard.” | Essential controls stay visible; focus order and labels are understandable; text remains comfortable | Clipping, focus traps, contrast |

## Observe without coaching

Ask the participant to explain: “What can the assistant see right now?”, “What is it allowed to change?”, “What is it doing?”, and “Where will the painting be saved?” A wrong answer is a product finding even if the underlying operation works.

For each finding, record the exact trigger, expected behavior, actual behavior, screenshot/build identity, severity and proposed correction. Do not store API keys, private reference images without consent, or identifying participant details in shared evidence.

## Release decision

Any unintended Ask/Plan mutation, wrong-document edit, lost manual work, duplicate native operation or silent recreation of an obsolete painting path blocks release. Participants should find canvas context, mode, Pause and the saved painting without instruction. Confusion and assistance are counted as failures to improve; successful completion after coaching is not unassisted success.

Complete the record for all three participants. Recheck affected tasks after changes on the final build. Report remaining accessibility, OS/Krita compatibility, signing/notarization and clean-install gaps separately from usability and artistic quality.
