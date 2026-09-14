"""Go (Golang) parser via Tree-sitter (optional extra).

Zero-dependency abstraction on import: importing this module never imports ``tree_sitter``.
``is_available()`` reports whether the optional ``go`` extra is installed.

Semantics & Capabilities:
- Package-level resolution: all files in the same directory belong to the same package
- Module-level resolution via ``go.mod`` (e.g. ``github.com/org/repo/pkg`` -> ``pkg``)
- Top-level function declarations: ``func Name(...)``
- Method declarations with value and pointer receivers: ``func (r *Receiver) Name(...)``
- Struct and Interface type declarations: ``type Name struct { ... }``, ``type Name interface { ... }``
- Cross-package call resolution (e.g. ``pkg.Func()``) and intra-package un-imported calls
- Stdlib and third-party imports preserved conservatively as unresolved edges
"""

from __future__ import annotations

import hashlib
import posixpath
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from scopemap.models import Edge, Evidence, Node
from scopemap.parser_api import Parser

GO_PARSER_VERSION = 1

_GO_BUILTINS: frozenset[str] = frozenset(
    {
        "append",
        "cap",
        "close",
        "complex",
        "copy",
        "delete",
        "imag",
        "len",
        "make",
        "new",
        "panic",
        "print",
        "println",
        "real",
        "recover",
        "clear",
        "min",
        "max",
    }
)


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


def _clean_str(text: str) -> str:
    """Clean string literal delimiters."""
    return text.strip("\"'`")


def _child_by_type(node: Any, *types: str) -> Any | None:
    for child in node.children:
        if child.type in types:
            return child
    return None


def _named_children(node: Any, *types: str) -> list[Any]:
    return [child for child in node.children if child.type in types]


def _extract_receiver_type(type_node: Any) -> str | None:
    """Extract receiver type name from method parameter declaration."""
    if type_node is None:
        return None
    if type_node.type == "pointer_type":
        for child in type_node.children:
            if child.type in ("type_identifier", "generic_type"):
                return _extract_receiver_type(child)
    elif type_node.type == "generic_type":
        for child in type_node.children:
            if child.type == "type_identifier":
                return _text(child)
    elif type_node.type == "type_identifier":
        return _text(type_node)
    text = _text(type_node).lstrip("*").split("[")[0].strip()
    return text if text else None


@dataclass
class _GoFileSymbols:
    """Symbols defined in a single Go file."""

    relative: str
    package_name: str = ""
    functions: set[str] = field(default_factory=set)
    types: set[str] = field(default_factory=set)
    methods: dict[str, str] = field(default_factory=dict)  # Receiver.Method -> Receiver
    bodies: dict[str, str] = field(default_factory=dict)
    lines: dict[str, int] = field(default_factory=dict)


@dataclass
class _GoIndex:
    """Repository-wide Go module and package index."""

    root: Path
    module_name: str | None = None
    dir_to_files: dict[str, list[Path]] = field(default_factory=dict)
    dir_to_pkg: dict[str, str] = field(default_factory=dict)
    pkg_to_dirs: dict[str, list[str]] = field(default_factory=dict)
    module_path_to_dir: dict[str, str] = field(default_factory=dict)
    file_symbols: dict[str, _GoFileSymbols] = field(default_factory=dict)
    pkg_symbols: dict[str, dict[str, str]] = field(default_factory=dict)  # dir -> symbol -> relative_file
    pkg_methods: dict[str, dict[str, str]] = field(default_factory=dict)  # dir -> Receiver.Method -> relative_file


def _find_module_name(root: Path) -> str | None:
    """Extract module path from go.mod if present."""
    curr = root
    while True:
        mod_file = curr / "go.mod"
        if mod_file.is_file():
            try:
                for line in mod_file.read_text(encoding="utf-8", errors="replace").splitlines():
                    line = line.strip()
                    if line.startswith("module "):
                        parts = line.split(None, 1)
                        if len(parts) > 1:
                            return parts[1].strip().strip("\"'")
            except OSError:
                pass
        if curr.parent == curr:
            break
        curr = curr.parent
    return None


class GoParser(Parser):
    """Tree-sitter Go adapter implementing the Parser protocol."""

    lang: str = "go"
    extensions: frozenset[str] = frozenset({".go"})
    version: int = GO_PARSER_VERSION

    _cached_parser: Any | None = None

    def grammar(self) -> Any:
        import tree_sitter_go as go_grammar
        from tree_sitter import Language

        return Language(go_grammar.language())

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
        return "GoParser()"

    # -- indexing --------------------------------------------------------

    def build_index(self, root: Path) -> _GoIndex:
        """Build repository-wide Go package and symbol index."""
        from scopemap.scanner import discover_files

        index = _GoIndex(root=root, module_name=_find_module_name(root))
        files = discover_files(root, self.extensions)

        # 1. Discover files and map directories
        for path in files:
            rel = path.relative_to(root).as_posix()
            rel_dir = path.parent.relative_to(root).as_posix() if path.parent != root else "."
            index.dir_to_files.setdefault(rel_dir, []).append(path)

        # 2. Extract package and definitions for each file
        for path in files:
            rel = path.relative_to(root).as_posix()
            rel_dir = path.parent.relative_to(root).as_posix() if path.parent != root else "."
            syms = self._scan_definitions(path, root)
            index.file_symbols[rel] = syms

            if syms.package_name:
                index.dir_to_pkg[rel_dir] = syms.package_name
                index.pkg_to_dirs.setdefault(syms.package_name, []).append(rel_dir)

            pkg_sym_map = index.pkg_symbols.setdefault(rel_dir, {})
            for name in syms.functions | syms.types:
                pkg_sym_map.setdefault(name, rel)

            pkg_method_map = index.pkg_methods.setdefault(rel_dir, {})
            for method in syms.methods:
                pkg_method_map.setdefault(method, rel)

        # 3. Map module import paths
        if index.module_name:
            for rel_dir in index.dir_to_files:
                if rel_dir == ".":
                    index.module_path_to_dir[index.module_name] = "."
                else:
                    mod_path = f"{index.module_name}/{rel_dir}"
                    index.module_path_to_dir[mod_path] = rel_dir

        return index

    def _scan_definitions(self, path: Path, root: Path) -> _GoFileSymbols:
        """Quickly collect symbols and bodies from a single Go file."""
        rel = path.relative_to(root).as_posix()
        syms = _GoFileSymbols(relative=rel)
        try:
            source = path.read_bytes()
            tree = self._parser().parse(source)
        except (OSError, ValueError, AttributeError):
            return syms

        if tree is None or tree.root_node is None:
            return syms

        for child in tree.root_node.children:
            if child.type == "package_clause":
                pkg_id = child.child_by_field_name("name") or _child_by_type(child, "package_identifier")
                if pkg_id:
                    syms.package_name = _text(pkg_id)
            elif child.type == "function_declaration":
                name_node = child.child_by_field_name("name") or _child_by_type(child, "identifier")
                if name_node:
                    name = _text(name_node)
                    syms.functions.add(name)
                    syms.bodies[name] = _text(child)
                    syms.lines[name] = child.start_point[0] + 1
            elif child.type == "method_declaration":
                rcv = child.child_by_field_name("receiver")
                name_node = child.child_by_field_name("name") or _child_by_type(child, "field_identifier", "identifier")
                if rcv and name_node:
                    rcv_name: str | None = None
                    for param in rcv.children:
                        if param.type == "parameter_declaration":
                            t = param.child_by_field_name("type")
                            rcv_name = _extract_receiver_type(t)
                            if rcv_name:
                                break
                    if rcv_name:
                        method_name = _text(name_node)
                        dotted = f"{rcv_name}.{method_name}"
                        syms.methods[dotted] = rcv_name
                        syms.bodies[dotted] = _text(child)
                        syms.lines[dotted] = child.start_point[0] + 1
            elif child.type == "type_declaration":
                for spec in child.children:
                    if spec.type == "type_spec":
                        name_node = spec.child_by_field_name("name") or _child_by_type(spec, "type_identifier")
                        if name_node:
                            name = _text(name_node)
                            syms.types.add(name)
                            syms.bodies[name] = _text(spec)
                            syms.lines[name] = spec.start_point[0] + 1

        return syms

    # -- parsing & graph construction ------------------------------------

    def parse_file(
        self,
        path: Path,
        root: Path,
        index: _GoIndex | None = None,
    ) -> tuple[list[Node], list[Edge]]:
        """Extract nodes and edges from one Go file. Never raises on bad input."""
        rel = path.relative_to(root).as_posix()
        file_node = Node(id=f"file:{rel}", kind="file", name=path.name, qualified_name=rel, file=rel)

        if index is None:
            index = self.build_index(root)

        syms = index.file_symbols.get(rel) or self._scan_definitions(path, root)
        try:
            source = path.read_bytes()
            tree = self._parser().parse(source)
        except (OSError, ValueError, AttributeError):
            return [file_node], []

        if tree is None or tree.root_node is None:
            return [file_node], []

        # 1. Symbol Nodes
        nodes = self._build_symbol_nodes(syms, rel)

        # 2. DEFINES & CONTAINS Edges
        defines_edges: list[Edge] = []
        for name in sorted(syms.functions | syms.types):
            line = syms.lines.get(name, 1)
            defines_edges.append(
                Edge(
                    source=file_node.id,
                    target=f"go:{rel}:{name}",
                    kind="DEFINES",
                    resolution="direct",
                    evidence=Evidence(file=rel, line=line, expression=name),
                )
            )
        for dotted, owner_name in sorted(syms.methods.items()):
            line = syms.lines.get(dotted, 1)
            # Link from owner struct/type if declared in same file, else from file
            source_id = f"go:{rel}:{owner_name}" if owner_name in syms.types else file_node.id
            kind: Literal["CONTAINS", "DEFINES"] = "CONTAINS" if owner_name in syms.types else "DEFINES"
            defines_edges.append(
                Edge(
                    source=source_id,
                    target=f"go:{rel}:{dotted}",
                    kind=kind,
                    resolution="direct",
                    evidence=Evidence(file=rel, line=line, expression=dotted),
                )
            )

        # 3. Imports & Import Edges
        import_edges, import_aliases = self._resolve_imports(tree.root_node, path, root, index, file_node)

        # 4. Calls & Call Edges
        call_edges = self._resolve_calls(tree.root_node, path, root, index, syms, import_aliases, file_node)

        all_edges = [*defines_edges, *import_edges, *call_edges]
        return [file_node, *nodes], all_edges

    def _build_symbol_nodes(self, syms: _GoFileSymbols, rel: str) -> list[Node]:
        """Convert collected file symbols into graph Nodes."""
        nodes: list[Node] = []
        for name in sorted(syms.functions):
            line = syms.lines.get(name, 1)
            nodes.append(
                Node(
                    id=f"go:{rel}:{name}",
                    kind="function",
                    name=name,
                    qualified_name=f"{rel}#{name}",
                    file=rel,
                    line_start=line,
                    line_end=line,
                    content_hash=_body_hash(syms.bodies.get(name, "")),
                )
            )
        for name in sorted(syms.types):
            line = syms.lines.get(name, 1)
            nodes.append(
                Node(
                    id=f"go:{rel}:{name}",
                    kind="class",
                    name=name,
                    qualified_name=f"{rel}#{name}",
                    file=rel,
                    line_start=line,
                    line_end=line,
                    content_hash=_body_hash(syms.bodies.get(name, "")),
                )
            )
        for dotted in sorted(syms.methods):
            line = syms.lines.get(dotted, 1)
            method_name = dotted.split(".")[-1]
            nodes.append(
                Node(
                    id=f"go:{rel}:{dotted}",
                    kind="method",
                    name=method_name,
                    qualified_name=f"{rel}#{dotted}",
                    file=rel,
                    line_start=line,
                    line_end=line,
                    content_hash=_body_hash(syms.bodies.get(dotted, "")),
                )
            )
        return nodes

    def _resolve_imports(
        self,
        root_node: Any,
        path: Path,
        root: Path,
        index: _GoIndex,
        file_node: Node,
    ) -> tuple[list[Edge], dict[str, str]]:
        """Resolve import statements to IMPORTS edges and build alias->target_dir mapping."""
        rel = file_node.file
        cur_dir = path.parent.relative_to(root).as_posix() if path.parent != root else "."
        edges: list[Edge] = []
        aliases: dict[str, str] = {}  # alias -> relative_dir

        for child in root_node.children:
            if child.type != "import_declaration":
                continue
            specs: list[Any] = []
            for item in child.children:
                if item.type == "import_spec":
                    specs.append(item)
                elif item.type == "import_spec_list":
                    specs.extend(_named_children(item, "import_spec"))

            for spec in specs:
                name_node = spec.child_by_field_name("name") or _child_by_type(
                    spec, "package_identifier", "identifier"
                )
                path_node = spec.child_by_field_name("path") or _child_by_type(
                    spec, "interpreted_string_literal", "raw_string_literal"
                )
                if not path_node:
                    continue

                raw_spec = _clean_str(_text(path_node))
                alias = _text(name_node) if name_node else None

                target_dir: str | None = None
                # Check module path match
                if raw_spec in index.module_path_to_dir:
                    target_dir = index.module_path_to_dir[raw_spec]
                elif raw_spec.startswith("."):
                    # Relative import
                    candidate = posixpath.normpath(posixpath.join(cur_dir, raw_spec))
                    if candidate in index.dir_to_files:
                        target_dir = candidate
                elif raw_spec in index.dir_to_files:
                    target_dir = raw_spec

                line = spec.start_point[0] + 1
                snippet = _text(spec)

                if target_dir is not None and target_dir in index.dir_to_files:
                    # Resolved internal package
                    target_pkg_name = index.dir_to_pkg.get(target_dir, posixpath.basename(target_dir))
                    effective_alias = alias or target_pkg_name
                    if effective_alias not in (".", "_"):
                        aliases[effective_alias] = target_dir

                    for target_file in index.dir_to_files[target_dir]:
                        target_rel = target_file.relative_to(root).as_posix()
                        edges.append(
                            Edge(
                                source=file_node.id,
                                target=f"file:{target_rel}",
                                kind="IMPORTS",
                                resolution="import-resolved",
                                evidence=Evidence(file=rel, line=line, expression=snippet),
                            )
                        )
                else:
                    # External / stdlib import
                    effective_alias = alias or raw_spec.split("/")[-1]
                    if effective_alias not in (".", "_"):
                        aliases[effective_alias] = f"unknown:{raw_spec}"
                    edges.append(
                        Edge(
                            source=file_node.id,
                            target=f"unknown:{raw_spec}",
                            kind="IMPORTS",
                            resolution="unresolved",
                            evidence=Evidence(file=rel, line=line, expression=snippet),
                        )
                    )

        return edges, aliases

    def _resolve_calls(
        self,
        root_node: Any,
        path: Path,
        root: Path,
        index: _GoIndex,
        syms: _GoFileSymbols,
        aliases: dict[str, str],
        file_node: Node,
    ) -> list[Edge]:
        """Walk call expressions and resolve direct, intra-package, and package-qualified calls."""
        rel = file_node.file
        cur_dir = path.parent.relative_to(root).as_posix() if path.parent != root else "."
        edges: list[Edge] = []
        seen_calls: set[tuple[str, str]] = set()

        caller_stack: list[tuple[Any, str]] = []

        def _find_caller(node: Any) -> str:
            for ancestor, caller_id in reversed(caller_stack):
                if ancestor.start_byte <= node.start_byte and node.end_byte <= ancestor.end_byte:
                    return caller_id
            return file_node.id

        def _walk(node: Any) -> None:
            nonlocal caller_stack
            pushed = False

            if node.type == "function_declaration":
                name_node = node.child_by_field_name("name") or _child_by_type(node, "identifier")
                if name_node:
                    caller_stack.append((node, f"go:{rel}:{_text(name_node)}"))
                    pushed = True
            elif node.type == "method_declaration":
                rcv = node.child_by_field_name("receiver")
                name_node = node.child_by_field_name("name") or _child_by_type(node, "field_identifier", "identifier")
                if rcv and name_node:
                    for param in rcv.children:
                        if param.type == "parameter_declaration":
                            t = param.child_by_field_name("type")
                            rcv_name = _extract_receiver_type(t)
                            if rcv_name:
                                caller_stack.append((node, f"go:{rel}:{rcv_name}.{_text(name_node)}"))
                                pushed = True
                                break

            if node.type == "call_expression":
                fn_node = node.child_by_field_name("function") or (node.children[0] if node.children else None)
                if fn_node:
                    caller_id = _find_caller(node)
                    edge = self._match_call(fn_node, node, caller_id, rel, cur_dir, index, syms, aliases)
                    if edge and (edge.source, edge.target) not in seen_calls:
                        seen_calls.add((edge.source, edge.target))
                        edges.append(edge)

            for child in node.children:
                _walk(child)

            if pushed:
                caller_stack.pop()

        _walk(root_node)
        return edges

    def _match_call(
        self,
        fn_node: Any,
        call_node: Any,
        caller_id: str,
        rel: str,
        cur_dir: str,
        index: _GoIndex,
        syms: _GoFileSymbols,
        aliases: dict[str, str],
    ) -> Edge | None:
        """Resolve a single call node to a target node ID."""
        line = call_node.start_point[0] + 1
        snippet = _text(call_node)

        # 1. Direct call: identifier
        if fn_node.type == "identifier":
            name = _text(fn_node)
            if name in _GO_BUILTINS:
                return None

            # Check defined in current file
            if name in syms.functions or name in syms.types:
                return Edge(
                    source=caller_id,
                    target=f"go:{rel}:{name}",
                    kind="CALLS",
                    resolution="direct",
                    evidence=Evidence(file=rel, line=line, expression=snippet),
                )

            # Check defined in same package (intra-package call)
            pkg_defs = index.pkg_symbols.get(cur_dir, {})
            if name in pkg_defs:
                target_rel = pkg_defs[name]
                return Edge(
                    source=caller_id,
                    target=f"go:{target_rel}:{name}",
                    kind="CALLS",
                    resolution="direct",
                    evidence=Evidence(file=rel, line=line, expression=snippet),
                )

            return Edge(
                source=caller_id,
                target=f"unknown:{name}",
                kind="CALLS",
                resolution="unresolved",
                evidence=Evidence(file=rel, line=line, expression=snippet),
            )

        # 2. Selector call: operand.field (e.g. rbac.NewPolicy() or s.Start())
        if fn_node.type == "selector_expression":
            operand_node = fn_node.child_by_field_name("operand") or (fn_node.children[0] if fn_node.children else None)
            field_node = fn_node.child_by_field_name("field") or (fn_node.children[-1] if fn_node.children else None)
            if not operand_node or not field_node:
                return None

            operand = _text(operand_node)
            field_name = _text(field_node)

            # Check if operand is an imported package alias
            if operand in aliases:
                target_dir = aliases[operand]
                if target_dir.startswith("unknown:"):
                    # External / stdlib call
                    return Edge(
                        source=caller_id,
                        target=f"unknown:{operand}.{field_name}",
                        kind="CALLS",
                        resolution="unresolved",
                        evidence=Evidence(file=rel, line=line, expression=snippet),
                    )

                pkg_defs = index.pkg_symbols.get(target_dir, {})
                if field_name in pkg_defs:
                    target_rel = pkg_defs[field_name]
                    return Edge(
                        source=caller_id,
                        target=f"go:{target_rel}:{field_name}",
                        kind="CALLS",
                        resolution="direct",
                        evidence=Evidence(file=rel, line=line, expression=snippet),
                    )

                # Check if it is a method on an exported type in target package
                pkg_methods = index.pkg_methods.get(target_dir, {})
                for dotted, target_rel in pkg_methods.items():
                    if dotted.endswith(f".{field_name}"):
                        return Edge(
                            source=caller_id,
                            target=f"go:{target_rel}:{dotted}",
                            kind="CALLS",
                            resolution="direct",
                            evidence=Evidence(file=rel, line=line, expression=snippet),
                        )

            # Check if method on type in current package
            cur_pkg_methods = index.pkg_methods.get(cur_dir, {})
            for dotted, target_rel in cur_pkg_methods.items():
                if dotted.endswith(f".{field_name}"):
                    return Edge(
                        source=caller_id,
                        target=f"go:{target_rel}:{dotted}",
                        kind="CALLS",
                        resolution="direct",
                        evidence=Evidence(file=rel, line=line, expression=snippet),
                    )

            # Preserved as unresolved call
            return Edge(
                source=caller_id,
                target=f"unknown:{operand}.{field_name}",
                kind="CALLS",
                resolution="unresolved",
                evidence=Evidence(file=rel, line=line, expression=snippet),
            )

        return None
