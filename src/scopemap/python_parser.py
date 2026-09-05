"""Python AST extraction with conservative import/call resolution.

Produces file/symbol nodes plus DEFINES, IMPORTS, INHERITS and
direct-only CALLS edges. Anything unresolvable is preserved as an
unresolved/dynamic edge, never silently dropped. Stdlib is ignored.
"""

from __future__ import annotations

import ast
import builtins
import sys
from dataclasses import dataclass, field
from pathlib import Path

from scopemap.models import Edge, Evidence, Node, Resolution
from scopemap.scanner import discover_python_files

_STDLIB: frozenset[str] = frozenset(sys.stdlib_module_names)
_BUILTINS: frozenset[str] = frozenset(dir(builtins))


def _module_name(path: Path, root: Path) -> str:
    """Dotted module name for a file relative to root."""
    relative = path.relative_to(root).with_suffix("")
    parts = list(relative.parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _module_index(root: Path) -> dict[str, Path]:
    """Map dotted module names to files for import resolution."""
    index: dict[str, Path] = {}
    for path in discover_python_files(root):
        name = _module_name(path, root)
        if name:
            index.setdefault(name, path)
    return index


def _file_id(relative: str) -> str:
    return f"file:{relative}"


def _symbol_id(module: str, name: str) -> str:
    return f"python:{module}:{name}"


@dataclass
class _Import:
    """One imported name with its alias and resolved file (if any)."""

    alias: str
    module: str
    symbol: str | None
    target: Path | None
    dynamic: bool = False
    external: bool = False


@dataclass
class _CallSite:
    """A call expression with its enclosing scope and class (if method)."""

    dotted: str
    line: int
    expression: str
    scope: str
    owner: str | None


@dataclass
class _FileSymbols:
    """Collected definitions for one file."""

    module: str
    relative: str
    node: Node
    functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = field(default_factory=dict)
    classes: dict[str, ast.ClassDef] = field(default_factory=dict)
    methods: dict[str, str] = field(default_factory=dict)  # Class.method -> owner class


class _Collector(ast.NodeVisitor):
    """First pass: definitions, raw imports, call sites, bases."""

    def __init__(self, module: str) -> None:
        self.module = module
        self.symbols: _FileSymbols | None = None
        self.raw_imports: list[ast.Import | ast.ImportFrom] = []
        self.calls: list[_CallSite] = []
        self.bases: list[tuple[str, str, int, str]] = []  # (class, base expr, line, expr text)
        self._scope = "<module>"
        self._owner: str | None = None
        self._class_stack: list[str] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        assert self.symbols is not None
        self.symbols.classes[node.name] = node
        for base in node.bases:
            self.bases.append((node.name, _dotted(base), base.lineno, _text(base)))
        self._class_stack.append(node.name)
        previous_owner, self._owner = self._owner, node.name
        previous_scope, self._scope = self._scope, node.name
        self.generic_visit(node)
        self._owner = previous_owner
        self._scope = previous_scope
        self._class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        assert self.symbols is not None
        if self._owner is not None:
            self.symbols.methods[f"{self._owner}.{node.name}"] = self._owner
        else:
            self.symbols.functions[node.name] = node
        previous_scope, self._scope = self._scope, node.name
        self.generic_visit(node)
        self._scope = previous_scope

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Import(self, node: ast.Import) -> None:
        self.raw_imports.append(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        self.raw_imports.append(node)

    def visit_Call(self, node: ast.Call) -> None:
        dotted = _dotted(node.func)
        if dotted:
            self.calls.append(
                _CallSite(
                    dotted=dotted,
                    line=node.lineno,
                    expression=_text(node),
                    scope=self._scope,
                    owner=self._owner,
                )
            )
        self.generic_visit(node)


def _dotted(node: ast.AST) -> str:
    """Dotted name for Name/Attribute chains, else empty."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _dotted(node.value)
        if parent:
            return f"{parent}.{node.attr}"
    return ""


def _text(node: ast.AST) -> str:
    """Source text of a node, truncated for evidence."""
    try:
        return ast.unparse(node)[:160]
    except (ValueError, SyntaxError):
        return ""


def _absolute_name(node: ast.ImportFrom, current: str, is_package: bool) -> str:
    """Resolve a from-import module to an absolute dotted name."""
    level: int = node.level
    module = node.module or ""
    if level == 0:
        return module
    if is_package:
        anchor = current.split(".") if current else []
    else:
        anchor = current.split(".")[:-1] if current else []
    keep = max(len(anchor) - level + 1, 0)
    base = anchor[:keep]
    if module:
        base.append(module)
    return ".".join(base)


def _resolve_imports(
    collector: _Collector,
    file_node: Node,
    index: dict[str, Path],
    root: Path,
    relative: str,
) -> tuple[list[Edge], dict[str, _Import]]:
    """Emit IMPORTS edges and build the alias map for call resolution."""
    edges: list[Edge] = []
    aliases: dict[str, _Import] = {}
    is_package = file_node.file.endswith("__init__.py")
    current = collector.module

    for node in collector.raw_imports:
        if isinstance(node, ast.Import):
            for entry in node.names:
                top = entry.name.split(".")[0]
                if top in _STDLIB:
                    continue
                target = index.get(entry.name)
                alias = entry.asname or entry.name.split(".")[0]
                if target is None:
                    edges.append(
                        Edge(
                            source=file_node.id,
                            target=f"unknown:{entry.name}",
                            kind="IMPORTS",
                            resolution="unresolved",
                            evidence=Evidence(file=relative, line=node.lineno, expression=_text(node)),
                        )
                    )
                    aliases[alias] = _Import(alias=alias, module=entry.name, symbol=None, target=None)
                else:
                    edges.append(
                        Edge(
                            source=file_node.id,
                            target=_file_id(target.relative_to(root).as_posix()),
                            kind="IMPORTS",
                            resolution="import-resolved",
                            evidence=Evidence(file=relative, line=node.lineno, expression=_text(node)),
                        )
                    )
                    aliases[alias] = _Import(alias=alias, module=entry.name, symbol=None, target=target)
        else:
            absolute = _absolute_name(node, current, is_package)
            top = absolute.split(".")[0] if absolute else ""
            if top in _STDLIB:
                continue
            if any(entry.name == "*" for entry in node.names):
                edges.append(
                    Edge(
                        source=file_node.id,
                        target=f"unknown:{absolute or '.'}",
                        kind="IMPORTS",
                        resolution="dynamic",
                        evidence=Evidence(file=relative, line=node.lineno, expression=_text(node)),
                    )
                )
                continue
            target = index.get(absolute) if absolute else None
            if target is None and absolute:
                submodule = next(
                    (path for name, path in index.items() if name.startswith(absolute + ".")),
                    None,
                )
                target = submodule
            if target is None:
                edges.append(
                    Edge(
                        source=file_node.id,
                        target=f"unknown:{absolute or '.'}",
                        kind="IMPORTS",
                        resolution="unresolved",
                        evidence=Evidence(file=relative, line=node.lineno, expression=_text(node)),
                    )
                )
                for entry in node.names:
                    alias = entry.asname or entry.name
                    aliases[alias] = _Import(alias=alias, module=absolute, symbol=entry.name, target=None)
            else:
                edges.append(
                    Edge(
                        source=file_node.id,
                        target=_file_id(target.relative_to(root).as_posix()),
                        kind="IMPORTS",
                        resolution="import-resolved",
                        evidence=Evidence(file=relative, line=node.lineno, expression=_text(node)),
                    )
                )
                for entry in node.names:
                    alias = entry.asname or entry.name
                    aliases[alias] = _Import(alias=alias, module=absolute, symbol=entry.name, target=target)
    return edges, aliases


def _resolve_calls(
    collector: _Collector,
    symbols: _FileSymbols,
    aliases: dict[str, _Import],
    index: dict[str, Path],
    root: Path,
    relative: str,
    module_files: dict[str, str],
) -> list[Edge]:
    """Emit CALLS edges; unresolvable non-builtin calls are preserved."""
    edges: list[Edge] = []
    for call in collector.calls:
        root_name = call.dotted.split(".")[0]
        if root_name in _BUILTINS:
            continue
        target = _resolve_call(call, symbols, aliases, index, module_files)
        if target is None:
            if root_name in aliases and (aliases[root_name].external or _is_stdlib_root(aliases[root_name])):
                continue
            if root_name in _STDLIB:
                continue
            edges.append(
                Edge(
                    source=_scope_id(symbols, call),
                    target=f"unknown:{call.dotted}",
                    kind="CALLS",
                    resolution="dynamic" if _is_dynamic(call) else "unresolved",
                    evidence=Evidence(file=relative, line=call.line, expression=call.expression),
                )
            )
            continue
        target_id, resolution = target
        edges.append(
            Edge(
                source=_scope_id(symbols, call),
                target=target_id,
                kind="CALLS",
                resolution=resolution,
                evidence=Evidence(file=relative, line=call.line, expression=call.expression),
            )
        )
    return edges


def _is_stdlib_root(imp: _Import) -> bool:
    return imp.module.split(".")[0] in _STDLIB if imp.module else False


def _is_dynamic(call: _CallSite) -> bool:
    return call.dotted.startswith(("getattr(", "get(")) or "[" in call.dotted


def _scope_id(symbols: _FileSymbols, call: _CallSite) -> str:
    if call.owner is not None and call.scope != call.owner:
        return _symbol_id(symbols.module, f"{call.owner}.{call.scope}")
    if call.scope != "<module>":
        return _symbol_id(symbols.module, call.scope)
    return _file_id(symbols.relative)


def _resolve_call(
    call: _CallSite,
    symbols: _FileSymbols,
    aliases: dict[str, _Import],
    index: dict[str, Path],
    module_files: dict[str, str],
) -> tuple[str, Resolution] | None:
    """Map a call to (target id, resolution), or None if unresolvable."""
    parts = call.dotted.split(".")
    head, rest = parts[0], parts[1:]

    if head == "self" and call.owner is not None and rest:
        candidate = f"{call.owner}.{rest[0]}"
        if candidate in symbols.methods:
            return _symbol_id(symbols.module, candidate), "same-module"
        return None
    if not rest:
        if head in symbols.functions:
            return _symbol_id(symbols.module, head), "same-module"
        if head in symbols.classes:
            return _symbol_id(symbols.module, head), "same-module"
        imp = aliases.get(head)
        if imp is None or imp.target is None or imp.symbol is None:
            return None
        return _symbol_id(_module_of(imp.target, index), imp.symbol), "direct"

    imp = aliases.get(head)
    if imp is not None and imp.target is not None and imp.symbol is None:
        module = imp.module
        symbol = rest[0]
        return _symbol_id(module, symbol), "direct"
    if imp is not None and imp.target is not None and imp.symbol is not None and len(rest) == 1:
        return _symbol_id(imp.module, imp.symbol), "direct"
    if head in index:
        return _symbol_id(head, rest[0]), "direct"
    if symbols.module and f"{symbols.module}.{head}" in module_files:
        return _symbol_id(symbols.module, head), "same-module"
    return None


def _module_of(target: Path, index: dict[str, Path]) -> str:
    for name, path in index.items():
        if path == target:
            return name
    return ""


def parse_file(path: Path, root: Path) -> tuple[list[Node], list[Edge]]:
    """Extract nodes and edges from one Python file.

    Syntax errors yield the file node only, never a crash.
    """
    relative = path.relative_to(root).as_posix()
    file_node = Node(
        id=_file_id(relative),
        kind="file",
        name=path.name,
        qualified_name=_module_name(path, root),
        file=relative,
        line_start=0,
        line_end=0,
    )
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
    except (SyntaxError, UnicodeDecodeError, OSError):
        return [file_node], []

    module = _module_name(path, root)
    symbols = _FileSymbols(module=module, relative=relative, node=file_node)
    collector = _Collector(module)
    collector.symbols = symbols
    collector.visit(tree)

    nodes: list[Node] = [file_node]
    edges: list[Edge] = []
    for name, node in collector.symbols.classes.items():
        nodes.append(
            Node(
                id=_symbol_id(module, name),
                kind="class",
                name=name,
                qualified_name=f"{module}.{name}" if module else name,
                file=relative,
                line_start=node.lineno,
                line_end=node.end_lineno or node.lineno,
            )
        )
        edges.append(
            Edge(
                source=file_node.id,
                target=_symbol_id(module, name),
                kind="DEFINES",
                resolution="direct",
                evidence=Evidence(file=relative, line=node.lineno, expression=f"class {name}"),
            )
        )
    for name, node in collector.symbols.functions.items():
        nodes.append(
            Node(
                id=_symbol_id(module, name),
                kind="function",
                name=name,
                qualified_name=f"{module}.{name}" if module else name,
                file=relative,
                line_start=node.lineno,
                line_end=node.end_lineno or node.lineno,
            )
        )
        edges.append(
            Edge(
                source=file_node.id,
                target=_symbol_id(module, name),
                kind="DEFINES",
                resolution="direct",
                evidence=Evidence(file=relative, line=node.lineno, expression=f"def {name}"),
            )
        )
    for dotted, owner in collector.symbols.methods.items():
        method = dotted.split(".")[-1]
        key = f"{module}.{dotted}" if module else dotted
        nodes.append(
            Node(
                id=_symbol_id(module, dotted),
                kind="method",
                name=method,
                qualified_name=key,
                file=relative,
                line_start=0,
                line_end=0,
            )
        )
        edges.append(
            Edge(
                source=_symbol_id(module, owner),
                target=_symbol_id(module, dotted),
                kind="CONTAINS",
                resolution="direct",
                evidence=Evidence(file=relative, line=0, expression=f"{owner}.{method}"),
            )
        )

    index = _module_index(root)
    module_files = {name: path.relative_to(root).as_posix() for name, path in index.items()}
    import_edges, aliases = _resolve_imports(collector, file_node, index, root, relative)
    edges.extend(import_edges)
    edges.extend(_resolve_calls(collector, symbols, aliases, index, root, relative, module_files))

    for class_name, base_expr, line, expression in collector.bases:
        base_root = base_expr.split(".")[0]
        if base_root in _BUILTINS or base_root in _STDLIB or not base_root:
            continue
        imp = aliases.get(base_root)
        if imp is not None and imp.target is not None:
            target_module = imp.symbol and imp.module or imp.module
            symbol = imp.symbol or base_expr
            edges.append(
                Edge(
                    source=_symbol_id(module, class_name),
                    target=_symbol_id(target_module, symbol),
                    kind="INHERITS",
                    resolution="import-resolved",
                    evidence=Evidence(file=relative, line=line, expression=expression),
                )
            )
        elif base_root in symbols.classes:
            edges.append(
                Edge(
                    source=_symbol_id(module, class_name),
                    target=_symbol_id(module, base_root),
                    kind="INHERITS",
                    resolution="same-module",
                    evidence=Evidence(file=relative, line=line, expression=expression),
                )
            )
        else:
            edges.append(
                Edge(
                    source=_symbol_id(module, class_name),
                    target=f"unknown:{base_expr}",
                    kind="INHERITS",
                    resolution="unresolved",
                    evidence=Evidence(file=relative, line=line, expression=expression),
                )
            )
    return nodes, edges
