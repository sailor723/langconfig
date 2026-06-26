import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from web_search import internet_search

# Search 1
print("=== SEARCH 1: latest AI developments 2025 ===")
r1 = internet_search("latest AI developments 2025", max_results=5, topic="news", include_raw_content=True)
print(r1)

print("\n\n=== SEARCH 2: breakthrough AI news this month ===")
r2 = internet_search("breakthrough AI news this month", max_results=5, topic="news", include_raw_content=True)
print(r2)

print("\n\n=== SEARCH 3: AI large language model updates 2025 ===")
r3 = internet_search("AI large language model updates 2025", max_results=5, topic="news", include_raw_content=True)
print(r3)

print("\n\n=== SEARCH 4: AI regulation policy developments 2025 ===")
r4 = internet_search("AI regulation policy developments 2025", max_results=5, topic="news", include_raw_content=True)
print(r4)
