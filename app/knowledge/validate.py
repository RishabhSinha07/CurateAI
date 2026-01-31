#!/usr/bin/env python3
"""
Knowledge graph validation utility.

Usage:
    python -m app.knowledge.validate              # Validate all graphs
    python -m app.knowledge.validate skincare     # Validate specific graph
    python -m app.knowledge.validate --stats      # Show graph statistics
"""

import sys
from pathlib import Path
from typing import List, Optional
import yaml

from .schemas import KnowledgeGraphSchema
from .graph_loader import list_available_graphs, get_knowledge_graph
from .query_engine import GraphQueryEngine


def validate_graph_file(graph_name: str) -> tuple[bool, List[str]]:
    """
    Validate a graph YAML file.

    Returns:
        Tuple of (is_valid, error_messages)
    """
    errors = []

    graph_path = Path(__file__).parent / "graphs" / f"{graph_name}.yaml"

    if not graph_path.exists():
        return False, [f"Graph file not found: {graph_path}"]

    # Load YAML
    try:
        with open(graph_path, 'r') as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        return False, [f"Invalid YAML: {e}"]

    # Validate schema
    try:
        schema = KnowledgeGraphSchema(**data)
    except Exception as e:
        return False, [f"Schema validation failed: {e}"]

    # Validate edges reference existing nodes
    edge_errors = schema.validate_edges()
    if edge_errors:
        errors.extend(edge_errors)

    # Check for duplicate node IDs
    all_node_ids = []
    for node_list in [
        schema.nodes.problems,
        schema.nodes.attributes,
        schema.nodes.ingredients,
        schema.nodes.constraints,
        schema.nodes.questions,
        schema.nodes.products,
        schema.nodes.domains,
        schema.nodes.subdomains,
    ]:
        all_node_ids.extend(node.id for node in node_list)

    duplicates = [nid for nid in all_node_ids if all_node_ids.count(nid) > 1]
    if duplicates:
        errors.append(f"Duplicate node IDs: {set(duplicates)}")

    # Check that REQUIRES_KNOWING edges have priority
    for edge in schema.edges:
        if edge.relation.value == 'REQUIRES_KNOWING':
            if 'priority' not in edge.properties:
                errors.append(
                    f"REQUIRES_KNOWING edge {edge.source} -> {edge.target} "
                    f"missing 'priority' property"
                )

    # Check that TREATS edges have efficacy
    for edge in schema.edges:
        if edge.relation.value == 'TREATS':
            if 'efficacy' not in edge.properties:
                errors.append(
                    f"TREATS edge {edge.source} -> {edge.target} "
                    f"missing 'efficacy' property"
                )

    return len(errors) == 0, errors


def test_graph_loading(graph_name: str) -> tuple[bool, List[str]]:
    """
    Test that graph can be loaded into NetworkX.

    Returns:
        Tuple of (is_valid, error_messages)
    """
    try:
        graph = get_knowledge_graph(graph_name)
        return True, []
    except Exception as e:
        return False, [f"Failed to load graph: {e}"]


def show_graph_stats(graph_name: str):
    """Show statistics for a graph"""
    stats = GraphQueryEngine.get_graph_stats(graph_name)

    print(f"\n{'=' * 60}")
    print(f"Graph Statistics: {graph_name}")
    print(f"{'=' * 60}")
    print(f"Version: {stats['version']}")
    print(f"Total Nodes: {stats['total_nodes']}")
    print(f"Total Edges: {stats['total_edges']}")

    print(f"\nNodes by Type:")
    for node_type, count in sorted(stats['nodes_by_type'].items()):
        print(f"  {node_type:15s}: {count:3d}")

    print(f"\nEdges by Relation:")
    for relation, count in sorted(stats['edges_by_relation'].items()):
        print(f"  {relation:25s}: {count:3d}")

    print(f"{'=' * 60}\n")


def validate_all_graphs():
    """Validate all available graphs"""
    graphs = list_available_graphs()

    if not graphs:
        print("No graphs found in app/knowledge/graphs/")
        return False

    print(f"Found {len(graphs)} graph(s): {', '.join(graphs)}\n")

    all_valid = True

    for graph_name in graphs:
        print(f"Validating '{graph_name}'...")

        # Validate schema
        is_valid, errors = validate_graph_file(graph_name)

        if not is_valid:
            print(f"  ✗ Schema validation FAILED")
            for error in errors:
                print(f"    - {error}")
            all_valid = False
            continue

        print(f"  ✓ Schema validation passed")

        # Test loading
        is_valid, errors = test_graph_loading(graph_name)

        if not is_valid:
            print(f"  ✗ Graph loading FAILED")
            for error in errors:
                print(f"    - {error}")
            all_valid = False
            continue

        print(f"  ✓ Graph loading passed")

        # Show stats
        try:
            stats = GraphQueryEngine.get_graph_stats(graph_name)
            print(
                f"  ℹ {stats['total_nodes']} nodes, "
                f"{stats['total_edges']} edges"
            )
        except Exception as e:
            print(f"  ! Could not get stats: {e}")

        print()

    return all_valid


def main():
    """Main entry point"""
    args = sys.argv[1:]

    if '--help' in args or '-h' in args:
        print(__doc__)
        return

    if '--stats' in args:
        # Show stats for all graphs
        graphs = list_available_graphs()
        for graph_name in graphs:
            show_graph_stats(graph_name)
        return

    if not args:
        # Validate all graphs
        print("Validating all knowledge graphs...\n")
        all_valid = validate_all_graphs()

        if all_valid:
            print("✓ All graphs are valid!")
            sys.exit(0)
        else:
            print("✗ Some graphs have errors")
            sys.exit(1)

    else:
        # Validate specific graph
        graph_name = args[0]

        print(f"Validating '{graph_name}'...\n")

        is_valid, errors = validate_graph_file(graph_name)

        if not is_valid:
            print(f"✗ Schema validation FAILED\n")
            for error in errors:
                print(f"  - {error}")
            sys.exit(1)

        print(f"✓ Schema validation passed")

        is_valid, errors = test_graph_loading(graph_name)

        if not is_valid:
            print(f"✗ Graph loading FAILED\n")
            for error in errors:
                print(f"  - {error}")
            sys.exit(1)

        print(f"✓ Graph loading passed")

        # Show stats
        show_graph_stats(graph_name)

        print("✓ Graph is valid!")
        sys.exit(0)


if __name__ == '__main__':
    main()
