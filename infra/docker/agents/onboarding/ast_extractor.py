"""
AST Extractor — Parses source files using tree-sitter and extracts module
signatures, import graphs, and public API surfaces.

Design ref: §3.4 AST Extractor (tree-sitter)
"""

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import tree_sitter_languages

logger = logging.getLogger("fde-onboarding.ast_extractor")

# Language mapping: file extension → tree-sitter language name
EXTENSION_TO_LANGUAGE = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".java": "java",
    ".rs": "rust",
    ".tf": "hcl",
    ".hcl": "hcl",
}


@dataclass
class ImportEdge:
    """A directed dependency edge between two modules."""

    source_module: str
    target_module: str
    dependency_type: str  # "import" | "call" | "inherit"


@dataclass
class ModuleSignature:
    """Extracted signature for a single module/file."""

    name: str
    path: str
    type: str  # "package" | "class" | "namespace" | "module"
    functions: list[str] = field(default_factory=list)
    classes: list[str] = field(default_factory=list)
    exports: list[str] = field(default_factory=list)
    imports: list[ImportEdge] = field(default_factory=list)


@dataclass
class ExtractionResult:
    """Aggregate result of AST extraction."""

    modules: list[ModuleSignature]
    edges: list[ImportEdge]
    total_modules: int
    total_edges: int
    parse_errors: int
    duration_ms: int


def extract_ast(
    workspace_path: str,
    source_files: list[str],
) -> ExtractionResult:
    """
    Parse source files with tree-sitter and extract module signatures + dependency graph.

    Args:
        workspace_path: Root directory of the repository.
        source_files: List of relative file paths to parse (from File Scanner).

    Returns:
        ExtractionResult with modules, edges, and metadata.
    """
    start = time.time()
    modules: list[ModuleSignature] = []
    all_edges: list[ImportEdge] = []
    parse_errors = 0

    for rel_path in source_files:
        ext = Path(rel_path).suffix
        language_name = EXTENSION_TO_LANGUAGE.get(ext)
        if not language_name:
            continue

        full_path = os.path.join(workspace_path, rel_path)
        if not os.path.isfile(full_path):
            continue

        try:
            signature = _parse_file(full_path, rel_path, language_name)
            if signature:
                modules.append(signature)
                all_edges.extend(signature.imports)
        except Exception as e:
            logger.debug("Parse error for %s: %s", rel_path, e)
            parse_errors += 1

    duration_ms = int((time.time() - start) * 1000)

    logger.info(
        "AST extraction complete: %d modules, %d edges, %d parse errors, %dms",
        len(modules),
        len(all_edges),
        parse_errors,
        duration_ms,
    )

    return ExtractionResult(
        modules=modules,
        edges=all_edges,
        total_modules=len(modules),
        total_edges=len(all_edges),
        parse_errors=parse_errors,
        duration_ms=duration_ms,
    )


def _parse_file(
    full_path: str,
    rel_path: str,
    language_name: str,
) -> Optional[ModuleSignature]:
    """Parse a single file and extract its signature."""
    try:
        with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
            source_code = f.read()
    except (OSError, PermissionError):
        return None

    if not source_code.strip():
        return None

    # Get tree-sitter parser for this language
    try:
        parser = tree_sitter_languages.get_parser(language_name)
    except Exception:
        return None

    tree = parser.parse(source_code.encode("utf-8"))
    root_node = tree.root_node

    # Extract module name from path
    module_name = _path_to_module_name(rel_path, language_name)

    # Extract functions, classes, and imports
    functions = _extract_functions(root_node, language_name, source_code)
    classes = _extract_classes(root_node, language_name, source_code)
    imports = _extract_imports(root_node, language_name, source_code, module_name)

    # Determine module type
    module_type = _infer_module_type(rel_path, classes, language_name)

    return ModuleSignature(
        name=module_name,
        path=rel_path,
        type=module_type,
        functions=functions,
        classes=classes,
        exports=functions + classes,
        imports=imports,
    )


def _path_to_module_name(rel_path: str, language: str) -> str:
    """Convert a file path to a module name."""
    path = Path(rel_path)

    if language == "python":
        parts = list(path.parts)
        if parts[-1] == "__init__.py":
            parts = parts[:-1]
        else:
            parts[-1] = path.stem
        return ".".join(parts)

    elif language in ("javascript", "typescript"):
        return str(path.with_suffix(""))

    elif language == "go":
        return str(path.parent) if path.parent != Path(".") else path.stem

    elif language == "java":
        return ".".join(path.with_suffix("").parts)

    elif language == "rust":
        return str(path.with_suffix("")).replace("/", "::")

    return str(path.with_suffix(""))


def _extract_functions(root_node, language: str, source: str) -> list[str]:
    """Extract top-level function names from the AST."""
    functions = []
    query_patterns = {
        "python": "function_definition",
        "javascript": "function_declaration",
        "typescript": "function_declaration",
        "go": "function_declaration",
        "java": "method_declaration",
        "rust": "function_item",
    }

    node_type = query_patterns.get(language)
    if not node_type:
        return functions

    for child in root_node.children:
        if child.type == node_type:
            name_node = child.child_by_field_name("name")
            if name_node:
                name = source[name_node.start_byte:name_node.end_byte]
                if language == "python" and name.startswith("_") and not name.startswith("__"):
                    continue
                functions.append(name)

    return functions


def _extract_classes(root_node, language: str, source: str) -> list[str]:
    """Extract top-level class names from the AST."""
    classes = []
    class_types = {
        "python": "class_definition",
        "javascript": "class_declaration",
        "typescript": "class_declaration",
        "java": "class_declaration",
        "rust": "struct_item",
        "go": "type_declaration",
    }

    node_type = class_types.get(language)
    if not node_type:
        return classes

    for child in root_node.children:
        if child.type == node_type:
            name_node = child.child_by_field_name("name")
            if name_node:
                classes.append(source[name_node.start_byte:name_node.end_byte])

    return classes


def _extract_imports(root_node, language: str, source: str, module_name: str) -> list[ImportEdge]:
    """Extract import statements and build ImportEdge list."""
    if language == "python":
        return _extract_python_imports(root_node, source, module_name)
    elif language in ("javascript", "typescript"):
        return _extract_js_imports(root_node, source, module_name)
    elif language == "go":
        return _extract_go_imports(root_node, source, module_name)
    elif language == "java":
        return _extract_java_imports(root_node, source, module_name)
    elif language == "rust":
        return _extract_rust_imports(root_node, source, module_name)
    return []


def _extract_python_imports(root_node, source: str, module_name: str) -> list[ImportEdge]:
    """Extract Python import/from-import statements."""
    edges = []
    for child in root_node.children:
        if child.type == "import_statement":
            name_node = child.child_by_field_name("name")
            if name_node:
                target = source[name_node.start_byte:name_node.end_byte]
                edges.append(ImportEdge(module_name, target, "import"))
        elif child.type == "import_from_statement":
            module_node = child.child_by_field_name("module_name")
            if module_node:
                target = source[module_node.start_byte:module_node.end_byte]
                edges.append(ImportEdge(module_name, target, "import"))
    return edges


def _extract_js_imports(root_node, source: str, module_name: str) -> list[ImportEdge]:
    """Extract JavaScript/TypeScript import statements."""
    edges = []
    for child in root_node.children:
        if child.type == "import_statement":
            source_node = child.child_by_field_name("source")
            if source_node:
                target = source[source_node.start_byte:source_node.end_byte].strip("'\"")
                edges.append(ImportEdge(module_name, target, "import"))
    return edges


def _extract_go_imports(root_node, source: str, module_name: str) -> list[ImportEdge]:
    """Extract Go import statements."""
    edges = []
    for child in root_node.children:
        if child.type == "import_declaration":
            for spec in _walk_children(child, "import_spec"):
                path_node = spec.child_by_field_name("path")
                if path_node:
                    target = source[path_node.start_byte:path_node.end_byte].strip('"')
                    edges.append(ImportEdge(module_name, target, "import"))
    return edges


def _extract_java_imports(root_node, source: str, module_name: str) -> list[ImportEdge]:
    """Extract Java import declarations."""
    edges = []
    for child in root_node.children:
        if child.type == "import_declaration":
            for node in child.children:
                if node.type == "scoped_identifier":
                    target = source[node.start_byte:node.end_byte]
                    edges.append(ImportEdge(module_name, target, "import"))
                    break
    return edges


def _extract_rust_imports(root_node, source: str, module_name: str) -> list[ImportEdge]:
    """Extract Rust use declarations."""
    edges = []
    for child in root_node.children:
        if child.type == "use_declaration":
            arg_node = child.child_by_field_name("argument")
            if arg_node:
                target = source[arg_node.start_byte:arg_node.end_byte]
                edges.append(ImportEdge(module_name, target, "import"))
    return edges


def _walk_children(node, target_type: str):
    """Recursively find children of a specific type."""
    for child in node.children:
        if child.type == target_type:
            yield child
        yield from _walk_children(child, target_type)


def _infer_module_type(rel_path: str, classes: list[str], language: str) -> str:
    """Infer the module type from path and content."""
    path = Path(rel_path)

    if language == "python" and path.name == "__init__.py":
        return "package"
    if language == "java" and classes:
        return "class"
    if language == "go":
        return "package"
    if language == "rust" and path.name in ("mod.rs", "lib.rs"):
        return "namespace"

    return "module"
