import math


def run_python(code: str) -> str:
    """Evaluate a mathematical expression safely.

    Args:
        code: Python code like "15 + 27" or "import math; math.sqrt(16)"

    Returns:
        Execution result as string
    """
    try:
        allowed_names = {
            k: v for k, v in math.__dict__.items() if not k.startswith("_")
        }
        allowed_names.update({
            "abs": abs,
            "round": round,
            "min": min,
            "max": max,
            "sum": sum,
            "pow": pow,
        })

        result = eval(code, {"__builtins__": {}}, allowed_names)

        if isinstance(result, float):
            if result == int(result):
                result = int(result)
            else:
                result = round(result, 10)

        return str(result)
    except ZeroDivisionError:
        return "Error: Division by zero"
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"