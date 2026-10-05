"""generate_apology: draft the apology email."""

from review_responder.graph.nodes.generate import make_generate
from review_responder.graph.state import Deps


def make_generate_apology(deps: Deps):
    return make_generate(deps, "apology")
