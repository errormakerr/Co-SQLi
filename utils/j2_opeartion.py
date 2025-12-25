from jinja2 import Environment, FileSystemLoader


def load_prompt_template(path: str, filename: str) -> str:
    env = Environment(
        loader=FileSystemLoader(path, encoding="utf-8"),
        autoescape=False,
    )
    template = env.get_template(filename)
    return template