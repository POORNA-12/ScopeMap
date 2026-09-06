"""Shared Tree-sitter engine for TypeScript/JavaScript parsers (P4.1).

Lazy loading only: this module must import cleanly when ``tree-sitter``
is NOT installed. All grammar access goes through ``is_available()``
and the cached ``_parser()`` constructor, both of which raise/degrade
without crashing the scan.

Conservative like the Python parser: syntax-derived DEFINES, CONTAINS,
IMPORTS and direct-only CALLS edges. Anything unresolvable is preserved
as an unresolved/dynamic edge, never silently dropped. Cross-language
references are never guessed.
"""

from __future__ import annotations

import hashlib
import posixpath
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from scopemap.models import Edge, Evidence, Node
from scopemap.parser_api import Parser

_BUILTIN_ROOTS: frozenset[str] = frozenset(
    {
        "console",
        "Math",
        "JSON",
        "Object",
        "Array",
        "Promise",
        "Reflect",
        "Proxy",
        "Number",
        "String",
        "Boolean",
        "Symbol",
        "BigInt",
        "Date",
        "RegExp",
        "Error",
        "Map",
        "Set",
        "WeakMap",
        "WeakSet",
        "Intl",
        "process",
        "Buffer",
        "setTimeout",
        "clearTimeout",
        "setInterval",
        "clearInterval",
        "setImmediate",
        "require",
        "module",
        "exports",
        "__dirname",
        "__filename",
        "globalThis",
    }
)

_INDEX_BASENAMES: tuple[str, ...] = ("index",)


def _text(node: Any) -> str:
    """Source text of a node, truncated for evidence."""
    try:
        raw = node.text
        text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
        return text[:160]
    except (ValueError, AttributeError):
        return ""


def _body_hash(text: str) -> str:
    """Hash normalized body lines excluding the declaration line itself."""
    lines = [line.strip() for line in text.splitlines()[1:] if line.strip()]
    body = "\n".join(lines)
    return hashlib.sha256(body.encode("utf-8")).hexdigest() if body else ""


def _child_by_type(node: Any, *types: str) -> Any | None:
    for child in node.children:
        if child.type in types:
            return child
    return None


def _named_children(node: Any, *types: str) -> list[Any]:
    return [child for child in node.children if child.type in types]


@dataclass
class _Import:
    """One imported name with its spec and resolved file (if any)."""

    alias: str
    spec: str
    symbol: str | None
    namespace: bool = False
    target: Path | None = None
    target_rel: str | None = None
    external: bool = False


@dataclass
class _FileSymbols:
    """Collected definitions for one file."""

    relative: str
    functions: set[str] = field(default_factory=set)
    classes: set[str] = field(default_factory=set)
    methods: dict[str, str] = field(default_factory=dict)  # Class.method -> owner class


class TreeSitterParser(Parser):
    """Base engine; subclasses set lang/extensions/grammar/ownership."""

    lang: str = ""
    extensions: frozenset[str] = frozenset()
    commonjs: bool = False
    skip_suffixes: tuple[str, ...] = ()
    version: int = 1

    _cached_parser: Any | None = None
    _cached_error: bool = False

    def grammar(self) -> Any:
        """Return the tree-sitter Language (override; lazy import here)."""
        raise NotImplementedError

    def is_available(self) -> bool:
        try:
            self.grammar()
            return True
        except ImportError:
            return False

    def _parser(self) -> Any:
        from tree_sitter import Parser as TSParser

        if self._cached_parser is None:
            self._cached_parser = TSParser(self.grammar())
        return self._cached_parser

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"

    # -- index ---------------------------------------------------------

    def build_index(self, root: Path) -> dict[str, Path]:
        """Map module keys (with/without extension, index dirs) to files."""
        from scopemap.scanner import discover_files

        index: dict[str, Path] = {}
        for path in discover_files(root, self.extensions):
            relative = path.relative_to(root).as_posix()
            index.setdefault(relative, path)
            stem = relative[: -len(path.suffix)] if path.suffix else relative
            index.setdefault(stem, path)
            if Path(relative).stem in _INDEX_BASENAMES:
                index.setdefault(str(Path(relative).parent.as_posix()), path)
        return index

    def _resolve_spec(self, spec: str, owner: Path, root: Path, index: dict[str, Path]) -> Path | None:
        """Resolve a relative spec to a repo file, else None (never guesses)."""
        if not spec.startswith("."):
            return None
        # owner is an absolute path; resolve the spec against its
        # repo-relative parent so candidates match relative index keys.
        owner_rel = owner.relative_to(root).as_posix() if owner.is_absolute() else owner.as_posix()
        base = posixpath.normpath(posixpath.join(posixpath.dirname(owner_rel), spec))
        candidates = [base, *[base + ext for ext in sorted(self.extensions)]]
        candidates.extend(f"{base}/{name}{ext}" for name in _INDEX_BASENAMES for ext in sorted(self.extensions))
        if "." in Path(base).suffix:
            candidates.insert(0, base)
        for candidate in candidates:
            target = index.get(candidate)
            if target is not None:
                return target
        return None

    # -- parse ----------------------------------------------------------

    def parse_file(self, path: Path, root: Path, index: dict[str, Path] | None = None) -> tuple[list[Node], list[Edge]]:
        """Extract nodes and edges from one file; never raises on bad input."""
        relative = path.relative_to(root).as_posix()
        file_node = Node(id=f"file:{relative}", kind="file", name=path.name, qualified_name=relative, file=relative)
        if any(path.name.endswith(suffix) for suffix in self.skip_suffixes):
            return [file_node], []
        try:
            source = path.read_bytes()
            tree = self._parser().parse(source)
        except (OSError, ValueError, AttributeError):
            return [file_node], []
        if tree is None or tree.root_node is None or tree.root_node.has_error and not tree.root_node.children:
            return [file_node], []
        symbols = _FileSymbols(relative=relative)
        self._collect_definitions(tree.root_node, symbols)
        if index is None:
            index = self.build_index(root)
        import_edges, aliases = self._resolve_imports(tree.root_node, path, root, index, relative)
        nodes = self._symbol_nodes(symbols, file_node, tree.root_node)
        edges = [edge for edge in self._defines_edges(symbols, file_node)]
        edges.extend(import_edges)
        edges.extend(self._resolve_calls(tree.root_node, symbols, aliases, file_node, relative))
        return [file_node, *nodes], edges

    # -- definitions -----------------------------------------------------

    def _declaration_name(self, node: Any) -> str | None:
        name_node = _child_by_type(node, "identifier", "type_identifier", "property_identifier")
        if name_node is None:
            return None
        return _text(name_node)

    def _collect_definitions(self, root_node: Any, symbols: _FileSymbols) -> None:
        """Walk the tree collecting functions, classes, methods, interfaces."""
        stack: list[tuple[Any, str | None]] = [(root_node, None)]
        while stack:
            node, owner = stack.pop()
            node_type = node.type
            if node_type == "class_declaration":
                name = self._declaration_name(node)
                if name:
                    symbols.classes.add(name)
                    for child in node.children:
                        stack.append((child, name))
                    continue
            elif node_type in ("function_declaration", "function", "generator_function_declaration"):
                name = self._declaration_name(node)
                if name and owner is None:
                    symbols.functions.add(name)
            elif node_type == "method_definition":
                name = self._declaration_name(node)
                if name and owner:
                    symbols.methods[f"{owner}.{name}"] = owner
            elif node_type == "interface_declaration":
                name = self._declaration_name(node)
                if name:
                    symbols.classes.add(name)
            elif node_type == "variable_declarator" and owner is None:
                self._collect_declarator(node, symbols)
            for child in node.children:
                stack.append((child, owner))

    def _collect_declarator(self, node: Any, symbols: _FileSymbols) -> None:
        """Record `const X = (...) =>` / `const X = function` as functions."""
        name_node = _child_by_type(node, "identifier")
        if name_node is None:
            return
        for child in node.children:
            if child.type in ("arrow_function", "function_expression", "function"):
                symbols.functions.add(_text(name_node))
                return

    # -- node/edge construction --------------------------------------------

    def _symbol_id(self, relative: str, dotted: str) -> str:
        return f"{self.lang}:{relative}:{dotted}"

    def _symbol_nodes(self, symbols: _FileSymbols, file_node: Node, root_node: Any) -> list[Node]:
        nodes: list[Node] = []
        bodies = self._definition_bodies(root_node)
        for name in sorted(symbols.functions | symbols.classes):
            kind = "class" if name in symbols.classes else "function"
            line = self._definition_line(root_node, name) or 0
            nodes.append(
                Node(
                    id=self._symbol_id(symbols.relative, name),
                    kind=kind,
                    name=name,  # type: ignore[arg-type]
                    qualified_name=f"{symbols.relative}#{name}",
                    file=symbols.relative,
                    line_start=line,
                    line_end=line,
                    content_hash=_body_hash(bodies.get(name, "")),
                )
            )
        for dotted in sorted(symbols.methods):
            method = dotted.split(".")[-1]
            line = self._definition_line(root_node, method) or 0
            nodes.append(
                Node(
                    id=self._symbol_id(symbols.relative, dotted),
                    kind="method",
                    name=method,
                    qualified_name=f"{symbols.relative}#{dotted}",
                    file=symbols.relative,
                    line_start=line,
                    line_end=line,
                    content_hash=_body_hash(bodies.get(dotted, "")),
                )
            )
        _ = file_node
        return nodes

    def _definition_bodies(self, root_node: Any) -> dict[str, str]:
        """Map declared names to their full source text for hashing."""
        bodies: dict[str, str] = {}
        stack: list[tuple[Any, str | None]] = [(root_node, None)]
        while stack:
            node, owner = stack.pop()
            node_type = node.type
            if node_type == "class_declaration":
                name = self._declaration_name(node)
                if name:
                    bodies.setdefault(name, _text(node))
                    for child in node.children:
                        stack.append((child, name))
                    continue
            elif node_type in ("function_declaration", "function", "interface_declaration"):
                name = self._declaration_name(node)
                if name and owner is None:
                    bodies.setdefault(name, _text(node))
            elif node_type == "method_definition" and owner:
                name = self._declaration_name(node)
                if name:
                    bodies.setdefault(f"{owner}.{name}", _text(node))
            for child in node.children:
                stack.append((child, owner))
        return bodies

    def _definition_line(self, root_node: Any, name: str) -> int:
        """1-based line of the first declaration matching name (best effort)."""
        stack: list[Any] = [root_node]
        while stack:
            node = stack.pop()
            if node.type in (
                "function_declaration",
                "function",
                "class_declaration",
                "interface_declaration",
                "method_definition",
            ):
                if self._declaration_name(node) == name.split(".")[-1]:
                    try:
                        return int(node.start_point[0]) + 1
                    except (AttributeError, TypeError, IndexError):
                        return 0
            stack.extend(node.children)
        return 0

    def _defines_edges(self, symbols: _FileSymbols, file_node: Node) -> list[Edge]:
        edges: list[Edge] = []
        for name in sorted(symbols.functions | symbols.classes):
            edges.append(
                Edge(
                    source=file_node.id,
                    target=self._symbol_id(symbols.relative, name),
                    kind="DEFINES",
                    resolution="direct",
                    evidence=Evidence(file=symbols.relative, line=0, expression=f"declare {name}"),
                )
            )
        for dotted, owner_name in sorted(symbols.methods.items()):
            edges.append(
                Edge(
                    source=self._symbol_id(symbols.relative, owner_name),
                    target=self._symbol_id(symbols.relative, dotted),
                    kind="CONTAINS",
                    resolution="direct",
                    evidence=Evidence(file=symbols.relative, line=0, expression=dotted),
                )
            )
        return edges

    # -- imports ------------------------------------------------------------

    def _string_value(self, node: Any) -> str | None:
        for child in node.children:
            if child.type == "string_fragment":
                return _text(child)
        text = _text(node)
        return text.strip("\"'") or None

    def _iter_import_statements(self, root_node: Any) -> Any:
        stack: list[Any] = [root_node]
        while stack:
            node = stack.pop()
            if node.type in ("import_statement", "export_statement", "call_expression", "variable_declarator"):
                yield node
            stack.extend(reversed(node.children))

    def _resolve_imports(
        self, root_node: Any, path: Path, root: Path, index: dict[str, Path], relative: str
    ) -> tuple[list[Edge], dict[str, _Import]]:
        edges: list[Edge] = []
        aliases: dict[str, _Import] = {}
        for node in self._iter_import_statements(root_node):
            if node.type == "import_statement":
                self._handle_import(node, path, root, index, relative, edges, aliases)
            elif node.type == "export_statement":
                self._handle_export_from(node, path, root, index, relative, edges)
            elif node.type == "call_expression" and self.commonjs:
                self._handle_require(node, path, root, index, relative, edges, aliases)
            elif node.type == "variable_declarator" and self.commonjs:
                self._handle_require_declarator(node, path, root, index, relative, edges, aliases)
        return edges, aliases

    def _record_import(
        self,
        spec: str,
        names: list[tuple[str, str | None, bool]],
        path: Path,
        root: Path,
        index: dict[str, Path],
        relative: str,
        line: int,
        expression: str,
        edges: list[Edge],
        aliases: dict[str, _Import],
    ) -> None:
        """Emit an IMPORTS edge and alias entries for one module spec."""
        target = self._resolve_spec(spec, path, root, index)
        target_rel = target.relative_to(root).as_posix() if target is not None else None
        if target is None:
            edges.append(
                Edge(
                    source=f"file:{relative}",
                    target=f"unknown:{spec}",
                    kind="IMPORTS",
                    resolution="unresolved",
                    evidence=Evidence(file=relative, line=line, expression=expression),
                )
            )
            for alias, symbol, namespace in names:
                aliases[alias] = _Import(
                    alias=alias,
                    spec=spec,
                    symbol=symbol,
                    namespace=namespace,
                    target=None,
                    target_rel=None,
                    external=not spec.startswith("."),
                )
        else:
            edges.append(
                Edge(
                    source=f"file:{relative}",
                    target=f"file:{target_rel}",
                    kind="IMPORTS",
                    resolution="import-resolved",
                    evidence=Evidence(file=relative, line=line, expression=expression),
                )
            )
            for alias, symbol, namespace in names:
                aliases[alias] = _Import(
                    alias=alias, spec=spec, symbol=symbol, namespace=namespace, target=target, target_rel=target_rel
                )

    def _node_line(self, node: Any) -> int:
        try:
            return int(node.start_point[0]) + 1
        except (AttributeError, TypeError, IndexError):
            return 0

    def _handle_import(
        self,
        node: Any,
        path: Path,
        root: Path,
        index: dict[str, Path],
        relative: str,
        edges: list[Edge],
        aliases: dict[str, _Import],
    ) -> None:
        string_node = _child_by_type(node, "string")
        if string_node is None:
            return
        spec = self._string_value(string_node)
        if not spec:
            return
        names: list[tuple[str, str | None, bool]] = []
        for child in node.children:
            if child.type == "import_clause":
                for clause in child.children:
                    if clause.type == "identifier":
                        names.append((_text(clause), None, False))  # default import
                    elif clause.type == "namespace_import":
                        ident = _child_by_type(clause, "identifier")
                        if ident is not None:
                            names.append((_text(ident), None, True))
                    elif clause.type == "named_imports":
                        for specifier in clause.children:
                            if specifier.type == "import_specifier":
                                imported = alias_name = None
                                for part in specifier.children:
                                    if part.type == "identifier" and imported is None:
                                        imported = _text(part)
                                    elif part.type == "identifier":
                                        alias_name = _text(part)
                                if imported:
                                    names.append((alias_name or imported, imported, False))
        if not names:
            names = []
        self._record_import(
            spec, names, path, root, index, relative, self._node_line(node), _text(node), edges, aliases
        )

    def _handle_export_from(
        self, node: Any, path: Path, root: Path, index: dict[str, Path], relative: str, edges: list[Edge]
    ) -> None:
        string_node = _child_by_type(node, "string")
        if string_node is None:
            return
        spec = self._string_value(string_node)
        if not spec:
            return
        self._record_import(spec, [], path, root, index, relative, self._node_line(node), _text(node), edges, {})

    def _require_spec(self, node: Any) -> str | None:
        """Spec string when a call_expression is require('...'), else None."""
        func = _child_by_type(node, "identifier")
        if func is None or _text(func) != "require":
            return None
        args = _child_by_type(node, "arguments")
        if args is None:
            return None
        string_node = _child_by_type(args, "string")
        if string_node is None:
            return None
        return self._string_value(string_node)

    def _handle_require(
        self,
        node: Any,
        path: Path,
        root: Path,
        index: dict[str, Path],
        relative: str,
        edges: list[Edge],
        aliases: dict[str, _Import],
    ) -> None:
        spec = self._require_spec(node)
        if spec is None:
            return
        self._record_import(spec, [], path, root, index, relative, self._node_line(node), _text(node), edges, {})

    def _handle_require_declarator(
        self,
        node: Any,
        path: Path,
        root: Path,
        index: dict[str, Path],
        relative: str,
        edges: list[Edge],
        aliases: dict[str, _Import],
    ) -> None:
        call = _child_by_type(node, "call_expression")
        if call is None:
            return
        spec = self._require_spec(call)
        if spec is None:
            return
        names: list[tuple[str, str | None, bool]] = []
        first = node.children[0] if node.children else None
        if first is not None and first.type == "identifier":
            names.append((_text(first), None, False))
        elif first is not None and first.type == "object_pattern":
            for part in first.children:
                if part.type in ("shorthand_property_identifier_pattern", "shorthand_property_identifier"):
                    text = _text(part)
                    if text:
                        names.append((text, text, False))
        self._record_import(
            spec, names, path, root, index, relative, self._node_line(node), _text(node), edges, aliases
        )

    # -- calls -----------------------------------------------------------------

    def _iter_calls(self, root_node: Any) -> Any:
        stack: list[Any] = [root_node]
        while stack:
            node = stack.pop()
            if node.type == "call_expression":
                yield node
            stack.extend(reversed(node.children))

    def _call_dotted(self, node: Any) -> str:
        func = node.children[0] if node.children else None
        if func is None:
            return ""
        if func.type == "identifier":
            return _text(func)
        if func.type == "member_expression":
            obj = prop = None
            for child in func.children:
                if child.type == "identifier" and obj is None:
                    obj = _text(child)
                elif child.type == "property_identifier":
                    prop = _text(child)
            if obj and prop:
                return f"{obj}.{prop}"
            return obj or ""
        return ""

    def _scope_of(self, root_node: Any, call: Any, symbols: _FileSymbols) -> str:
        """Best-effort enclosing symbol id for a call site (file fallback)."""
        try:
            line = int(call.start_point[0]) + 1
        except (AttributeError, TypeError, IndexError):
            return f"file:{symbols.relative}"
        best: str | None = None
        best_line = -1
        stack: list[tuple[Any, str | None]] = [(root_node, None)]
        while stack:
            node, owner = stack.pop()
            node_type = node.type
            current_owner = owner
            if node_type == "class_declaration":
                current_owner = self._declaration_name(node)
            if node_type in ("function_declaration", "function", "method_definition"):
                name = self._declaration_name(node)
                try:
                    start = int(node.start_point[0]) + 1
                    end = int(node.end_point[0]) + 1
                except (AttributeError, TypeError, IndexError):
                    continue
                if start <= line <= max(end, start):
                    if node_type == "method_definition" and current_owner:
                        best, best_line = f"{current_owner}.{name}", start
                    elif name and best_line < start:
                        best, best_line = name, start
            for child in node.children:
                stack.append((child, current_owner))
        if best is None:
            return f"file:{symbols.relative}"
        return self._symbol_id(symbols.relative, best)

    def _resolve_calls(
        self,
        root_node: Any,
        symbols: _FileSymbols,
        aliases: dict[str, _Import],
        file_node: Node,
        relative: str,
    ) -> list[Edge]:
        edges: list[Edge] = []
        seen: set[tuple[str, str, int]] = set()
        for call in self._iter_calls(root_node):
            dotted = self._call_dotted(call)
            if not dotted:
                continue
            if self.commonjs and dotted == "require":
                continue  # import mechanics, already an IMPORTS edge
            head, _, rest = dotted.partition(".")
            if head in _BUILTIN_ROOTS:
                continue
            try:
                line = int(call.start_point[0]) + 1
            except (AttributeError, TypeError, IndexError):
                line = 0
            key = (dotted, relative, line)
            if key in seen:
                continue
            seen.add(key)
            source = self._scope_of(root_node, call, symbols)
            target = self._resolve_call(dotted, symbols, aliases)
            if target is None:
                imp = aliases.get(head)
                if imp is not None and imp.external:
                    continue
                edges.append(
                    Edge(
                        source=source,
                        target=f"unknown:{dotted}",
                        kind="CALLS",
                        resolution="dynamic" if "[" in dotted else "unresolved",
                        evidence=Evidence(file=relative, line=line, expression=_text(call)),
                    )
                )
                continue
            edges.append(
                Edge(
                    source=source,
                    target=target,
                    kind="CALLS",
                    resolution="direct",
                    evidence=Evidence(file=relative, line=line, expression=_text(call)),
                )
            )
        return edges

    def _resolve_call(self, dotted: str, symbols: _FileSymbols, aliases: dict[str, _Import]) -> str | None:
        """Map a call to a target symbol id, or None if unresolvable."""
        head, _, rest = dotted.partition(".")
        if not rest:
            if head in symbols.functions or head in symbols.classes:
                return self._symbol_id(symbols.relative, head)
            imp = aliases.get(head)
            if imp is not None and imp.target is not None and imp.symbol is not None:
                return self._aliased_symbol(imp, imp.symbol)
            return None
        if head == "this":
            return None
        imp = aliases.get(head)
        if imp is not None and imp.namespace and imp.target is not None:
            return self._aliased_symbol(imp, rest)
        if head in symbols.classes and rest:
            if f"{head}.{rest}" in symbols.methods:
                return self._symbol_id(symbols.relative, f"{head}.{rest}")
            return self._symbol_id(symbols.relative, head)
        return None

    def _aliased_symbol(self, imp: _Import, symbol: str) -> str | None:
        """Symbol id for an imported name inside its target file."""
        if imp.target is None or imp.target_rel is None:
            return None
        return f"{self.lang}:{imp.target_rel}:{symbol}"
