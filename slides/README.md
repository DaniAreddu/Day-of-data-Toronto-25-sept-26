# Slides

The final deck for *Why AI Projects Fail: Data Platform Lessons Every Architect Should Know*
(Day of Data Toronto 2026, Saturday, 26 September 2026) belongs in this folder:

* `why-ai-projects-fail.pptx`: editable source deck;
* `why-ai-projects-fail.pdf`: exported PDF shared with attendees after the session.

Neither file is committed yet; the deck is authored separately. Screenshots used in the deck
should be taken from the local app (`streamlit run app/streamlit_app.py`) so that every figure
on a slide matches the data in this repository.

Suggested slide anchors that map to the demo:

1. The confidently wrong answer (Act 1)
2. "The model did not hallucinate. The platform gave it the wrong truth."
3. Failure modes ([docs/failure-modes.md](../docs/failure-modes.md))
4. Architecture ([architecture/trusted-platform.md](../architecture/trusted-platform.md))
5. Live demo
6. Refusal as a feature (Act 2)
7. Governance, observability, semantic contracts
8. Checklist ([docs/architecture-checklist.md](../docs/architecture-checklist.md))
9. "Production AI does not begin with a prompt. It begins with a trustworthy data contract."
