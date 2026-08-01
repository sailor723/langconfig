import os
from dotenv import load_dotenv
load_dotenv("../.env")

import dspy

lm = dspy.LM(
    model=f"openai/{os.getenv('MINIMAX_MODEL', 'minimax-M3')}",
    api_base=os.getenv("MINIMAX_BASE_URL", "https://api.minimax.chat/v1"),
    api_key=os.getenv("MINIMAX_API_KEY"),
)
dspy.configure(lm=lm)


class Sentiment(dspy.Signature):
    """Classify a product review as positive, negative, or neutral."""
    review: str = dspy.InputField()
    sentiment: str = dspy.OutputField()


predict = dspy.Predict(Sentiment)
for review in [
    "Fast delivery and the battery lasts all day.",
    "The screen cracked after one week.",
    "It is okay for the price.",
]:
    print(review, "->", predict(review=review).sentiment)
