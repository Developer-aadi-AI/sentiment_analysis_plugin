"""Graph construction.

ingest → classify → route ─┬─ generate_appreciation ──┐
                           ├─ generate_apology ───────┼─ guard → deliver → END
                           ├─ generate_acknowledgement┘
                           └─ hold ───────────────────────────→ deliver
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from review_responder.graph.nodes.classify import make_classify
from review_responder.graph.nodes.deliver import make_deliver
from review_responder.graph.nodes.generate_acknowledgement import make_generate_acknowledgement
from review_responder.graph.nodes.generate_apology import make_generate_apology
from review_responder.graph.nodes.generate_appreciation import make_generate_appreciation
from review_responder.graph.nodes.guard import make_guard
from review_responder.graph.nodes.ingest import make_ingest
from review_responder.graph.nodes.route import Route, route_review
from review_responder.graph.state import Deps, ReviewState, audit


def route_edge(state: ReviewState) -> Route:
    return route_review(state["review"], state.get("classification"))


async def hold(state: ReviewState) -> dict[str, Any]:
    review, c = state["review"], state.get("classification")
    reasons: list[str] = []
    if c is not None and c.is_spam_or_abusive:
        reasons.append("spam or abusive review")
    if not reasons and not state.get("hold_reasons"):
        reasons.append("not routable")
    return {"response": None, "hold_reasons": reasons, "audit": audit("hold", review_id=review.id)}


def build_graph(deps: Deps):
    g = StateGraph(ReviewState)
    g.add_node("ingest", make_ingest(deps))
    g.add_node("classify", make_classify(deps))
    g.add_node("generate_appreciation", make_generate_appreciation(deps))
    g.add_node("generate_apology", make_generate_apology(deps))
    g.add_node("generate_acknowledgement", make_generate_acknowledgement(deps))
    g.add_node("hold", hold)
    g.add_node("guard", make_guard(deps))
    g.add_node("deliver", make_deliver(deps))

    g.add_edge(START, "ingest")
    g.add_edge("ingest", "classify")
    g.add_conditional_edges(
        "classify",
        route_edge,
        {
            "appreciate": "generate_appreciation",
            "apologize": "generate_apology",
            "acknowledge": "generate_acknowledgement",
            "hold": "hold",
        },
    )
    for node in ("generate_appreciation", "generate_apology", "generate_acknowledgement"):
        g.add_edge(node, "guard")
    g.add_edge("guard", "deliver")
    g.add_edge("hold", "deliver")
    g.add_edge("deliver", END)
    return g.compile()
