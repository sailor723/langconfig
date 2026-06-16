import sys, os
sys.path.insert(0, '.')
from langchain_core.prompts import ChatPromptTemplate

# Our template
template = ChatPromptTemplate.from_messages([
    ("system", "Test system prompt."),
    ("human", "Generate a Python function `{fn_name}` for this description:\n\nDescription: {desc}\nPrompt: {usr_prompt}\n\nReturn the function in ```python ... ``` markers followed by # EXPLAIN:"),
])

print(f"Template input variables: {template.input_variables}")

# Now test with values that DON'T contain curly braces
try:
    result = template.invoke({
        "fn_name": "get_pdf_context",
        "desc": "test description",
        "usr_prompt": "A simple function without special chars"
    })
    print(f"Test 1 (simple values): OK - {len(result.messages)} messages")
except Exception as e:
    print(f"Test 1 FAILED: {e}")

# Test with values that contain {session_id}
try:
    result = template.invoke({
        "fn_name": "get_pdf_context",
        "desc": "test description",
        "usr_prompt": "A function that retrieves stored PDF text by session_id from a directory"
    })
    print(f"Test 2 (session_id in value): OK - {len(result.messages)} messages")
except Exception as e:
    print(f"Test 2 FAILED: {e}")

# Test with more complex curly braces
try:
    result = template.invoke({
        "fn_name": "get_pdf_context",
        "desc": "test description",
        "usr_prompt": "Use os.path.join(dir, f'{session_id}.txt') for the file path"
    })
    print(f"Test 3 (f-string in value): OK - {len(result.messages)} messages")
except Exception as e:
    print(f"Test 3 FAILED: {e}")

print("\nDone!")
