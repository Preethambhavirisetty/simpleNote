"""Held-out routing cases: question -> the playbook and plan that should run.

None of these appear in any playbook's `examples`, so the router cannot win by
matching text it was shown. Where a request genuinely admits more than one
reasonable plan, every acceptable plan is listed and any of them counts as
correct - that ambiguity is real, and scoring it as a miss would measure the
labeller's taste rather than the router.

Keep this file honest: if a label is changed because the domain changed, say so
in a comment, and never add a case that copies a playbook example.
"""

from __future__ import annotations

from typing import NamedTuple


class Case(NamedTuple):
    question: str
    playbook: str
    plans: tuple[str, ...]


CASES: list[Case] = [
    # ── notes_qa: answer grounded in the content of the notes ───────────────
    Case("What conclusion did I reach about the caching layer?", "notes_qa", ("answer_from_notes",)),
    Case("According to my notes, who owns the billing service?", "notes_qa", ("answer_from_notes",)),
    Case("What are the tradeoffs I wrote down for Kafka vs SQS?", "notes_qa", ("answer_from_notes",)),
    Case("Do my notes explain why we dropped the legacy importer?", "notes_qa", ("answer_from_notes",)),
    Case("What budget number did I record for the offsite?", "notes_qa", ("answer_from_notes",)),
    Case("Based on my notes, what is the deployment procedure?", "notes_qa", ("answer_from_notes",)),
    Case("What did the team agree on regarding code review turnaround?", "notes_qa", ("answer_from_notes",)),
    # Broad "everything I have on X" reads either way.
    Case("Tell me what I know about the customer churn analysis.", "notes_qa", ("answer_from_notes", "summarize_topic")),
    Case("Give me the key points from my research on vector databases.", "notes_qa", ("answer_from_notes", "summarize_topic")),

    # ── search_notes: find the notes themselves ─────────────────────────────
    Case("Locate any note that talks about the security audit.", "search_notes", ("find_notes",)),
    Case("Which of my notes reference the payments API?", "search_notes", ("find_notes",)),
    Case("Show me everything in the Archive folder.", "search_notes", ("browse_notes",)),
    Case("I need the note where I kept the wifi password.", "search_notes", ("find_notes",)),
    Case("List all notes that aren't in a folder.", "search_notes", ("browse_notes",)),
    Case("Search for notes mentioning Kubernetes.", "search_notes", ("find_notes",)),
    Case("Give me my folder list.", "search_notes", ("browse_folders",)),
    # Title lookup is a filter or a search depending on how you read it.
    Case("Do I have a note titled Interview Loop?", "search_notes", ("find_notes", "browse_notes")),
    Case("Pull up the notes tagged with research.", "search_notes", ("find_notes", "browse_notes")),
    # Relabelled when `list_tags` moved out of direct_tool: listing is a read.
    Case("What tags do I have set up?", "search_notes", ("browse_tags",)),
    Case("Open the note called Sprint Retro and read it to me.", "search_notes", ("open_note", "find_notes")),
    # From production traffic: routed to notes_qa, which answers in prose when
    # the user plainly asked for the notes themselves.
    Case("find me the notes where i wrote about food", "search_notes", ("find_notes",)),

    # ── note_timeline: anchored to a period ─────────────────────────────────
    Case("What notes did I create in the last three days?", "note_timeline", ("recent_notes",)),
    Case("Show me everything I captured during January.", "note_timeline", ("recent_notes",)),
    Case("Which note did I touch most recently?", "note_timeline", ("recent_notes",)),
    Case("What did I add between Monday and Friday?", "note_timeline", ("recent_notes",)),
    Case("Anything new since our last conversation yesterday?", "note_timeline", ("recent_notes",)),
    Case("What was I working on at the end of last quarter?", "note_timeline", ("timeline_digest", "recent_notes")),
    Case("Walk me through my notes chronologically.", "note_timeline", ("timeline_digest",)),
    Case("Summarize my week based on my notes.", "note_timeline", ("timeline_digest",)),
    Case("Give me the history of edits on my project notes.", "note_timeline", ("timeline_digest", "recent_notes")),

    # ── direct_tool: change the workspace. 12 plans - the hard case for
    #    picking a plan, and the reason this eval exists. ──────────────────
    Case("Make a new note titled Grocery List.", "direct_tool", ("create_note",)),
    Case("Put the budget note in the Finance folder.", "direct_tool", ("move_note",)),
    Case("Get rid of the note about the cancelled trip.", "direct_tool", ("delete_note",)),
    Case("Add a folder for Q4 planning.", "direct_tool", ("create_folder",)),
    Case("Change the title of my standup note to Daily Sync.", "direct_tool", ("update_note",)),
    Case("Attach the important tag to my roadmap note.", "direct_tool", ("add_tag_to_note",)),
    Case("Remove the draft tag from that note.", "direct_tool", ("remove_tag_from_note",)),
    Case("Unpin the onboarding note.", "direct_tool", ("update_note",)),
    Case("Rename my Personal folder to Life Admin.", "direct_tool", ("update_folder",)),
    Case("Delete the Archive folder entirely.", "direct_tool", ("delete_folder",)),
    Case("Create a tag called urgent.", "direct_tool", ("create_tag",)),
    Case("Rename the tag research to reading.", "direct_tool", ("update_tag",)),

    # ── direct_llm: nothing to do with the user's notes ─────────────────────
    Case("Can you make this email sound friendlier?", "direct_llm", ("generic_answer",)),
    Case("What is the difference between a mutex and a semaphore?", "direct_llm", ("generic_answer",)),
    Case("Never mind, forget I asked.", "direct_llm", ("generic_answer",)),
    Case("Translate this sentence into Spanish for me.", "direct_llm", ("generic_answer",)),
    Case("Write a haiku about deadlines.", "direct_llm", ("generic_answer",)),
    Case("Repeat your last answer but shorter.", "direct_llm", ("generic_answer",)),
    Case("Thanks!", "direct_llm", ("generic_answer",)),
    Case("Fix the grammar in this paragraph I'm pasting.", "direct_llm", ("generic_answer",)),
    Case("How does TCP handshaking work?", "direct_llm", ("generic_answer",)),
]
