# LangGraph tutorial: random number 1-10, route odd/even into two lists.
# No LLM involved - pure LangGraph StateGraph to learn: State, Nodes, Edges,
# conditional edges (branching), and reducers (state merging).
#
# Run:  backend/.venv/bin/python backend/scripts/langgraph_tutorial_odd_even.py
import random
from typing import Annotated, Literal, TypedDict
from operator import add

from langgraph.graph import START, END, StateGraph


# ---- 1. State: shared data container (a TypedDict) --------------------------
# `Annotated[list[int], add]` is a reducer: when a node returns {"evens": [x]},
# LangGraph APPENDS x to the existing evens list instead of overwriting it.
class NumbersState(TypedDict):
    evens: Annotated[list[int], add]  # accumulator list for even numbers
    odds: Annotated[list[int], add]   # accumulator list for odd numbers
    last_number: int                  # the number generated this round


# ---- 2. Nodes: plain functions taking state, returning partial updates -------
def generate(state: NumbersState) -> dict:
    """Entry node: roll a random number 1-10 and store it in state."""
    num = random.randint(1, 10)
    return {"last_number": num}


def handle_even(state: NumbersState) -> dict:
    """Append the current number to the evens list (reducer merges it)."""
    return {"evens": [state["last_number"]]}


def handle_odd(state: NumbersState) -> dict:
    """Append the current number to the odds list (reducer merges it)."""
    return {"odds": [state["last_number"]]}


# ---- 3. Conditional routing function: decides which node runs next -----------
# The function reads state and returns the NAME of the next node.
# LangGraph uses this return value as the key into the path_map of
# add_conditional_edges().
def route_odd_even(state: NumbersState) -> Literal["handle_even", "handle_odd"]:
    return "handle_even" if state["last_number"] % 2 == 0 else "handle_odd"


# ---- 4. Build + compile the graph --------------------------------------------
builder = StateGraph(NumbersState)

# Add all nodes
builder.add_node("generate", generate)
builder.add_node("handle_even", handle_even)
builder.add_node("handle_odd", handle_odd)

# Entry: START -> generate
builder.add_edge(START, "generate")

# Branch: after generate, call route_odd_even() and map its return value to a node
builder.add_conditional_edges(
    "generate",
    route_odd_even,
    {"handle_even": "handle_even", "handle_odd": "handle_odd"},  # path_map
)

# Both branches end the graph
builder.add_edge("handle_even", END)
builder.add_edge("handle_odd", END)

app = builder.compile()


# ---- 5. Run it -----------------------------------------------------------------
def main() -> None:
    # Visualize the compiled graph structure (mermaid - no extra deps needed)
    print(app.get_graph().draw_mermaid())
    print("=" * 60)

    # Run 10 rounds; each round seeds fresh empty lists.
    # Because of the `add` reducer, values returned by nodes are appended.
    all_evens: list[int] = []
    all_odds: list[int] = []
    for i in range(1, 11):
        result = app.invoke({"evens": [], "odds": []})
        num = result["last_number"]
        all_evens += result["evens"]
        all_odds += result["odds"]
        print(f"round {i:>2}: rolled {num:>2} -> {num % 2 == 0 and 'even' or 'odd'}")

    print("=" * 60)
    print(f"evens collected: {sorted(all_evens)}")
    print(f"odds  collected: {sorted(all_odds)}")


if __name__ == "__main__":
    main()
