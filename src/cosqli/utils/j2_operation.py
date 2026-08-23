"""
Jinja2 template utility for loading and rendering prompt templates.
"""

from __future__ import annotations

from jinja2 import Environment, FileSystemLoader, Template


def load_prompt_template(path: str, filename: str) -> Template:
    """Load a Jinja2 prompt template from the specified directory.

    Args:
        path:     Directory path containing the template file.
        filename: Template filename (e.g., ``"generate_comment.j2"``).

    Returns:
        A Jinja2 :class:`Template` object ready for rendering via
        ``template.render(**context)``.
    """
    env = Environment(
        loader=FileSystemLoader(path, encoding="utf-8"),
        autoescape=False,
    )
    return env.get_template(filename)
