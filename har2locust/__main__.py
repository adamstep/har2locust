from argparse import Namespace
import importlib
import json
import logging
import os
import pathlib
import ast
import sys
import jinja2
from .argument_parser import get_parser
from .plugin import entriesprocessor, entriesprocessor_with_args, astprocessor, outputstringprocessor


def __main__(arguments=None):
    args = get_parser().parse_args(arguments)
    logging.basicConfig(level=args.loglevel.upper())
    load_plugins(args.plugins.split(",") if args.plugins else [])
    har_path = pathlib.Path(args.input)
    name = har_path.stem.replace("-", "_").replace(".", "_")  # build class name from filename
    with open(har_path, encoding="utf8", errors="ignore") as f:
        har = json.load(f)
    logging.debug(f"loaded {har_path}")

    pp_dict = process(har, args)
    py = rendering(args.template, {"name": name, **pp_dict})
    print(py)


def process(har: dict, args: Namespace) -> dict:
    if har["log"]["version"] != "1.2":
        logging.warning(f"Untested har version {har['log']['version']}")

    entries = har["log"]["entries"]

    logging.debug(f"found {len(entries)} entries")

    for e in entries:
        # set defaults
        e["request"]["fname"] = "client.request"
        e["request"]["extraparams"] = [("catch_response", True)]

    values = {}

    for p in entriesprocessor.processors:
        values |= p(entries) or {}

    for p in entriesprocessor_with_args.processors:
        values |= p(entries, args) or {}

    logging.debug(f"{len(entries)} entries after applying entriesprocessors")

    return dict(**values, entries=entries)


def rendering(template_name: str, values: dict) -> str:
    logging.debug(f'about to load template "{template_name}"')
    if pathlib.Path(template_name).exists():
        template_path = pathlib.Path(template_name)
    else:
        template_path = pathlib.Path(__file__).parents[0] / template_name
        if not template_path.exists():
            raise Exception(f"Template {template_name} does not exist, neither in current directory nor as built in")

    template_dir = template_path.parents[0]

    env = jinja2.Environment(loader=jinja2.FileSystemLoader(template_dir))
    template = env.get_template(template_path.name)
    logging.debug("template loaded")

    py = template.render(values)
    logging.debug("template rendered")

    try:
        tree = ast.parse(py, type_comments=True)
    except SyntaxError as e:
        logging.debug(py)
        levelmessage = " (set log level DEBUG to see the whole output)" if logging.DEBUG < logging.root.level else ""
        logging.error(f"{e.msg} when parsing rendered template{levelmessage}")
        raise

    for p in astprocessor.processors:
        p(tree, values)
    py = ast.unparse(ast.fix_missing_locations(tree))
    logging.debug("astprocessors applied")

    for p in outputstringprocessor.processors:
        py = p(py)
    logging.debug("outputstringprocessors applied")

    return py


def load_plugins(plugins: list[str] = []):
    package_root_dir = pathlib.Path(__file__).parents[1]
    plugin_dir = package_root_dir / "har2locust/default_plugins"
    logging.debug(f"loading default plugins from {plugin_dir}")
    default_plugins = [str(d.relative_to(package_root_dir)) for d in plugin_dir.glob("*.py")]
    default_and_extra_plugins = default_plugins + plugins
    sys.path.append(os.path.curdir)  # accept plugins by relative path
    for plugin in default_and_extra_plugins:
        import_path = plugin.replace("/", ".").rstrip(".py")
        importlib.import_module(import_path)
    logging.debug(f"loaded plugins {default_and_extra_plugins}")


if __name__ == "__main__":
    __main__()