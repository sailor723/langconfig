import os
from dotenv import load_dotenv
load_dotenv("../.env")

import dspy
from dspy.teleprompt import BootstrapFewShot

lm = dspy.LM(
    model=f"openai/{os.getenv('MINIMAX_MODEL', 'minimax-M3')}",
    api_base=os.getenv("MINIMAX_BASE_URL", "https://api.minimax.chat/v1"),
    api_key=os.getenv("MINIMAX_API_KEY"),
)
dspy.configure(lm=lm)


class ExtractFields(dspy.Signature):
    """Extract product, quantity, and unit price from a messy order line."""
    line: str = dspy.InputField()
    product: str = dspy.OutputField()
    quantity: int = dspy.OutputField()
    unit_price: float = dspy.OutputField()


class Extractor(dspy.Module):
    def __init__(self):
        super().__init__()
        self.extract = dspy.Predict(ExtractFields)

    def forward(self, line):
        return self.extract(line=line)


def metric(gold, pred, trace=None):
    return (
        gold.product == pred.product
        and gold.quantity == pred.quantity
        and abs(gold.unit_price - pred.unit_price) < 0.01
    )


def example(line, product, quantity, unit_price):
    return dspy.Example(
        line=line, product=product, quantity=quantity, unit_price=unit_price
    ).with_inputs("line")


trainset = [
    example("2x iPhone 15 Pro @ 999 each", "iPhone 15 Pro", 2, 999.0),
    example("AirPods Pro, qty 3, $249.00/unit", "AirPods Pro", 3, 249.0),
    example("USB-C cable x5 at 12.5", "USB-C cable", 5, 12.5),
    example("MacBook Air M3, 1 unit, 1099 USD", "MacBook Air M3", 1, 1099.0),
]

devset = [
    example("Apple Watch Ultra 2, 2 pcs @ 799", "Apple Watch Ultra 2", 2, 799.0),
    example("Magic Mouse x1 99.99", "Magic Mouse", 1, 99.99),
    example("Studio Display 1 unit 1599", "Studio Display", 1, 1599.0),
    example("USB-A to C adapter qty 10 @ 8.90", "USB-A to C adapter", 10, 8.9),
]


def accuracy(module):
    ok = sum(1 for ex in devset if metric(ex, module(line=ex.line)))
    return ok / len(devset)


base = Extractor()
before = accuracy(base)
print(f"baseline accuracy: {before:.0%}")

teleprompter = BootstrapFewShot(
    metric=metric, max_bootstrapped_demos=2, max_labeled_demos=2
)
compiled = teleprompter.compile(base, trainset=trainset)
after = accuracy(compiled)
print(f"compiled accuracy: {after:.0%}")
print(f"improvement: {after - before:+.0%}")
