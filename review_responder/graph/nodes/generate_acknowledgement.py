"""generate_acknowledgement: draft the acknowledgement email."""

from review_responder.graph.nodes.generate import make_generate
from review_responder.graph.state import Deps


def make_generate_acknowledgement(deps: Deps):
    return make_generate(deps, "acknowledgement")
