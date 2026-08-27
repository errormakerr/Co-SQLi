"""
Bracket and quote balance validation for SQL strings.
"""

from __future__ import annotations


class SymbolChecker:
    """
    Validate bracket and quote balance in a SQL string.

    Single quotes that are intentionally unbalanced (i.e., the SQL-injection
    quote-escaping trick) are **not** flagged here — callers should pass only
    the fragment before any SQL line-comment terminator.
    """

    def __init__(self):
        self.bracket_pairs = {"(": ")", "[": "]", "{": "}"}
        self.quote_symbols = ["'", '"', "`"]

    def check_balanced(self, text: str):
        """
        Check whether all brackets and quotes in *text* are balanced.

        Args:
            text: The SQL fragment to check.

        Returns:
            A ``(bool, message)`` tuple where ``bool`` is ``True`` when the
            text is balanced and ``message`` describes any imbalance found.
        """
        if not isinstance(text, str):
            return False, "Input is not a string"

        stack = []
        quote_stack = []
        i = 0

        while i < len(text):
            char = text[i]

            # Skip escaped characters
            if i > 0 and text[i - 1] == "\\":
                i += 1
                continue

            # Inside a quoted string — only watch for its closing quote
            if quote_stack:
                if char == quote_stack[-1]:
                    quote_stack.pop()
                i += 1
                continue

            # Quotes
            if char in self.quote_symbols:
                quote_stack.append(char)
            # Opening brackets
            elif char in self.bracket_pairs:
                stack.append(char)
            # Closing brackets
            elif char in self.bracket_pairs.values():
                if not stack:
                    return False, f"Position {i}: unexpected closing symbol '{char}'"
                last_open = stack.pop()
                if self.bracket_pairs[last_open] != char:
                    return False, f"Position {i}: mismatched symbols '{last_open}' and '{char}'"

            i += 1

        errors = []
        if stack:
            errors.append(f"Unclosed brackets: {stack}")
        if quote_stack:
            errors.append(f"Unclosed quotes: {quote_stack}")

        if errors:
            return False, "; ".join(errors)
        return True, "All symbols are correctly balanced"
