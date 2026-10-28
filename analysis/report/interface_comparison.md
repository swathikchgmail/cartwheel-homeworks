# Interface comparison

My review interface is `analysis/review_app/` (run with `uv run python -m analysis.review_app.server`). The reference is `analysis/server.py` with `analysis/ui/index.html`.

## Retained: AI suggestions stay separate until I decide

As in the reference, suggestions from the coding agent look different from my own notes (dashed cards marked "not yours until accepted") and never count as open codes on their own. Accepting one creates a human annotation that records which suggestion it came from. I added one rule: rejecting a suggestion requires a reason, so every rejection is kept in the saved state.

## Changed: a whole conversation on one screen

Langfuse writes one trace per turn, and the reference shows one trace at a time. In my traces, 80 of the 250 support conversations have two or more turns (up to six). Reviewing turn 2 without turn 1 hid what the agent had already promised or looked up. My interface groups traces by `cartwheel.session_id` and shows every turn in order: user message, each tool call as a one-line summary (full JSON one click away), then the reply. A note is anchored to a specific turn and step, so it still maps to exactly one Langfuse trace.

## Limitation: no cluster map

The reference has a map view that plots traces so similar ones sit together. My interface has no such view, so the 15 cluster representatives in the first batch must be chosen by a script outside the app and loaded through the sample manifest. While reviewing, I also cannot see which region of the collection a conversation comes from.
