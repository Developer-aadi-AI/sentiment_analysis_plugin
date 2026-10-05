"""generate_appreciation: draft the appreciation email."""

from review_responder.graph.nodes.generate import make_generate
from review_responder.graph.state import Deps


def make_generate_appreciation(deps: Deps):
    return make_generate(deps, "appreciation")
