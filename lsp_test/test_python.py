def greet(name: str) -> str:
    return f"Hello, {name}"

result = greet(42)  # type error: int passed where str expected
