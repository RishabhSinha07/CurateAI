"""
Knowledge graph loader using NetworkX.

Loads YAML-defined graphs into NetworkX DiGraph structures for fast traversal.
"""

import yaml
import networkx as nx
from pathlib import Path
from typing import Dict, List, Optional, Any
import logging

from .schemas import KnowledgeGraphSchema, NodeType, RelationType

logger = logging.getLogger(__name__)


class KnowledgeGraph:
    """
    Knowledge graph for a specific domain.

    Loads graph structure from YAML and provides traversal methods.
    """

    def __init__(self, domain: str):
        """
        Initialize knowledge graph for a domain.

        Args:
            domain: Domain name (e.g., 'skincare', 'wellness')
        """
        self.domain = domain
        self.graph = nx.DiGraph()
        self.metadata = None
        self._node_type_map: Dict[str, str] = {}  # node_id -> node_type
        self._load_graph()

    def _load_graph(self):
        """Load graph from YAML file"""
        graph_path = Path(__file__).parent / "graphs" / f"{self.domain}.yaml"

        if not graph_path.exists():
            raise FileNotFoundError(
                f"Knowledge graph not found: {graph_path}\n"
                f"Available graphs: {self._list_available_graphs()}"
            )

        logger.info(f"Loading knowledge graph from {graph_path}")

        with open(graph_path, 'r') as f:
            data = yaml.safe_load(f)

        # Validate schema
        try:
            schema = KnowledgeGraphSchema(**data)
        except Exception as e:
            raise ValueError(f"Invalid graph schema in {graph_path}: {e}")

        # Validate edges reference existing nodes
        edge_errors = schema.validate_edges()
        if edge_errors:
            raise ValueError(
                f"Edge validation failed in {graph_path}:\n" +
                "\n".join(edge_errors)
            )

        self.metadata = schema.metadata

        # Load nodes by type
        node_type_lists = {
            'problem': schema.nodes.problems,
            'attribute': schema.nodes.attributes,
            'ingredient': schema.nodes.ingredients,
            'constraint': schema.nodes.constraints,
            'question': schema.nodes.questions,
            'product': schema.nodes.products,
            'domain': schema.nodes.domains,
            'subdomain': schema.nodes.subdomains,
        }

        for node_type, node_list in node_type_lists.items():
            for node in node_list:
                node_id = node.id
                node_data = node.model_dump()

                # Add node to graph
                self.graph.add_node(
                    node_id,
                    node_type=node_type,
                    **node_data
                )

                # Track node type for quick lookup
                self._node_type_map[node_id] = node_type

        # Load edges
        for edge in schema.edges:
            self.graph.add_edge(
                edge.source,
                edge.target,
                relation=edge.relation.value,
                **edge.properties
            )

        logger.info(
            f"Loaded graph '{self.domain}' v{self.metadata.version}: "
            f"{self.graph.number_of_nodes()} nodes, {self.graph.number_of_edges()} edges"
        )

    def _list_available_graphs(self) -> List[str]:
        """List available graph YAML files"""
        graphs_dir = Path(__file__).parent / "graphs"
        if not graphs_dir.exists():
            return []
        return [f.stem for f in graphs_dir.glob("*.yaml")]

    def get_node(self, node_id: str) -> Optional[Dict[str, Any]]:
        """
        Get node attributes by ID.

        Args:
            node_id: Node identifier

        Returns:
            Dictionary of node attributes, or None if not found
        """
        if node_id not in self.graph:
            return None
        return dict(self.graph.nodes[node_id])

    def get_node_type(self, node_id: str) -> Optional[str]:
        """Get node type by ID"""
        return self._node_type_map.get(node_id)

    def find_nodes_by_type(self, node_type: str) -> List[Dict[str, Any]]:
        """
        Find all nodes of a given type.

        Args:
            node_type: Type to filter by (e.g., 'problem', 'ingredient')

        Returns:
            List of node dictionaries with 'id' included
        """
        return [
            {**data, 'id': node_id}
            for node_id, data in self.graph.nodes(data=True)
            if data.get('node_type') == node_type
        ]

    def find_problem_by_synonym(self, text: str) -> Optional[str]:
        """
        Find problem node ID by matching text against name and synonyms.

        Args:
            text: Text to match (case-insensitive)

        Returns:
            Problem node ID if found, None otherwise
        """
        text_lower = text.lower().strip()
        # Also try with underscores (e.g., "low energy" → "low_energy")
        text_underscore = text_lower.replace(' ', '_')

        for node_id, data in self.graph.nodes(data=True):
            if data.get('node_type') != 'problem':
                continue

            node_name = data.get('name', '').lower()

            # Check exact name match (with both space and underscore variants)
            if node_name == text_lower or node_name == text_underscore:
                return node_id

            # Check display name match
            if data.get('display_name', '').lower() == text_lower:
                return node_id

            # Check synonyms
            synonyms = [s.lower() for s in data.get('synonyms', [])]
            if text_lower in synonyms or text_underscore in synonyms:
                return node_id

        return None

    def get_outgoing_edges(
        self,
        node_id: str,
        relation: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get outgoing edges from a node.

        Args:
            node_id: Source node ID
            relation: Optional relation type to filter by

        Returns:
            List of edge dictionaries with 'target' and all properties
        """
        if node_id not in self.graph:
            return []

        edges = []
        for target in self.graph.successors(node_id):
            edge_data = dict(self.graph.edges[node_id, target])

            if relation is None or edge_data.get('relation') == relation:
                edges.append({
                    'source': node_id,
                    'target': target,
                    **edge_data
                })

        return edges

    def get_incoming_edges(
        self,
        node_id: str,
        relation: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get incoming edges to a node.

        Args:
            node_id: Target node ID
            relation: Optional relation type to filter by

        Returns:
            List of edge dictionaries with 'source' and all properties
        """
        if node_id not in self.graph:
            return []

        edges = []
        for source in self.graph.predecessors(node_id):
            edge_data = dict(self.graph.edges[source, node_id])

            if relation is None or edge_data.get('relation') == relation:
                edges.append({
                    'source': source,
                    'target': node_id,
                    **edge_data
                })

        return edges

    def get_required_attributes(self, problem_id: str) -> List[Dict[str, Any]]:
        """
        Get attributes required for a problem, sorted by priority.

        Args:
            problem_id: Problem node ID

        Returns:
            List of attribute edges with node data, sorted by priority (1=highest)
        """
        edges = self.get_outgoing_edges(problem_id, relation='REQUIRES_KNOWING')

        # Enrich with target node data
        enriched = []
        for edge in edges:
            target_data = self.get_node(edge['target'])
            if target_data:
                enriched.append({
                    'attribute_id': edge['target'],
                    'attribute_data': target_data,
                    'priority': edge.get('priority', 999),
                    'is_optional': edge.get('is_optional', False),
                    'reason': edge.get('reason', '')
                })

        # Sort by priority (lower = higher priority)
        enriched.sort(key=lambda x: x['priority'])

        return enriched

    def get_treating_ingredients(
        self,
        problem_id: str,
        min_efficacy: float = 0.0
    ) -> List[Dict[str, Any]]:
        """
        Get ingredients that treat a problem.

        Args:
            problem_id: Problem node ID
            min_efficacy: Minimum efficacy threshold (0.0-1.0)

        Returns:
            List of ingredient dictionaries with efficacy data, sorted by efficacy
        """
        edges = self.get_incoming_edges(problem_id, relation='TREATS')

        ingredients = []
        for edge in edges:
            efficacy = edge.get('efficacy', 0.0)

            if efficacy >= min_efficacy:
                node_data = self.get_node(edge['source'])
                if node_data:
                    ingredients.append({
                        **node_data,
                        'efficacy': efficacy,
                        'mechanism': edge.get('mechanism', ''),
                        'onset_time': edge.get('onset_time', ''),
                        'evidence_level': edge.get('evidence_level', '')
                    })

        # Sort by efficacy (highest first)
        ingredients.sort(key=lambda x: x.get('efficacy', 0), reverse=True)

        return ingredients

    def check_contraindications(
        self,
        ingredient_id: str,
        constraints: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Check if ingredient has contraindications for given constraints.

        Args:
            ingredient_id: Ingredient node ID
            constraints: User constraints (e.g., {'pregnancy': True, 'allergy': 'dairy'})

        Returns:
            List of violation dictionaries
        """
        edges = self.get_outgoing_edges(ingredient_id, relation='CONTRAINDICATED_FOR')

        violations = []
        for edge in edges:
            constraint_node = self.get_node(edge['target'])
            if not constraint_node:
                continue

            constraint_type = constraint_node.get('type')
            constraint_value = constraint_node.get('value')

            # Check if user has this constraint active
            user_value = constraints.get(constraint_type)

            # Handle different value types
            if constraint_value == 'true' and user_value is True:
                match = True
            elif constraint_value == 'false' and user_value is False:
                match = True
            elif str(user_value).lower() == constraint_value.lower():
                match = True
            else:
                match = False

            if match:
                violations.append({
                    'ingredient_id': ingredient_id,
                    'ingredient_name': self.get_node(ingredient_id).get('display_name', ingredient_id),
                    'constraint_type': constraint_type,
                    'constraint_value': constraint_value,
                    'reason': edge.get('reason', ''),
                    'severity': edge.get('severity', 'avoid'),
                    'alternatives': edge.get('alternative_ingredients', [])
                })

        return violations

    def get_recommended_ingredients_for_attribute(
        self,
        attribute_id: str,
        min_strength: float = 0.7
    ) -> List[Dict[str, Any]]:
        """
        Get ingredients recommended for a user attribute.

        Args:
            attribute_id: Attribute node ID
            min_strength: Minimum recommendation strength (0.0-1.0)

        Returns:
            List of ingredient dictionaries with strength data, sorted by strength
        """
        edges = self.get_incoming_edges(attribute_id, relation='RECOMMENDED_FOR')

        ingredients = []
        for edge in edges:
            strength = edge.get('strength', 0.0)

            if strength >= min_strength:
                node_data = self.get_node(edge['source'])
                if node_data:
                    ingredients.append({
                        **node_data,
                        'strength': strength,
                        'evidence': edge.get('evidence', '')
                    })

        # Sort by strength (highest first)
        ingredients.sort(key=lambda x: x.get('strength', 0), reverse=True)

        return ingredients

    def get_question_for_attribute(
        self,
        attribute_id: str,
        context: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get question to elicit an attribute.

        Args:
            attribute_id: Attribute node ID (e.g., 'skin_type_oily')
            context: Optional context for conditional questions

        Returns:
            Question dictionary with condition and timing, or None
        """
        # Get the attribute's category to find the question
        attr_node = self.get_node(attribute_id)
        if not attr_node:
            return None

        attr_category = attr_node.get('category')

        # Find question for this attribute category
        # Note: We match by category, not by specific value
        # So 'skin_type_oily' -> finds question for 'skin_type'
        edges = self.get_outgoing_edges(attribute_id, relation='ELICITS_QUESTION')

        if not edges:
            # Try to find by category across all attributes with same category
            all_attrs = self.find_nodes_by_type('attribute')
            for attr in all_attrs:
                if attr.get('category') == attr_category:
                    edges = self.get_outgoing_edges(attr['id'], relation='ELICITS_QUESTION')
                    if edges:
                        break

        if not edges:
            return None

        # Take first matching question
        edge = edges[0]
        question = self.get_node(edge['target'])

        if question:
            return {
                **question,
                'condition': edge.get('condition', 'always'),
                'timing': edge.get('timing', 'immediate')
            }

        return None

    def find_similar_problems(
        self,
        problem_id: str,
        min_similarity: float = 0.7
    ) -> List[Dict[str, Any]]:
        """
        Find problems similar to the given problem.

        Args:
            problem_id: Problem node ID
            min_similarity: Minimum similarity threshold (0.0-1.0)

        Returns:
            List of similar problem dictionaries, sorted by similarity
        """
        edges = self.get_outgoing_edges(problem_id, relation='SIMILAR_TO')

        similar = []
        for edge in edges:
            similarity = edge.get('similarity_score', 0.0)

            if similarity >= min_similarity:
                node_data = self.get_node(edge['target'])
                if node_data:
                    similar.append({
                        **node_data,
                        'similarity_score': similarity,
                        'shared_symptoms': edge.get('shared_symptoms', [])
                    })

        # Sort by similarity (highest first)
        similar.sort(key=lambda x: x.get('similarity_score', 0), reverse=True)

        return similar

    def find_ingredient_by_name(self, name: str) -> Optional[str]:
        """
        Find ingredient node ID by name (exact or display name).

        Args:
            name: Ingredient name to match

        Returns:
            Ingredient node ID if found, None otherwise
        """
        name_lower = name.lower().strip()

        for node_id, data in self.graph.nodes(data=True):
            if data.get('node_type') != 'ingredient':
                continue

            if data.get('name', '').lower() == name_lower:
                return node_id

            if data.get('display_name', '').lower() == name_lower:
                return node_id

        return None


# Singleton cache for graphs
_graph_cache: Dict[str, KnowledgeGraph] = {}


def get_knowledge_graph(domain: str) -> KnowledgeGraph:
    """
    Get or create knowledge graph for a domain.

    Args:
        domain: Domain name (e.g., 'skincare', 'wellness')

    Returns:
        KnowledgeGraph instance
    """
    if domain not in _graph_cache:
        _graph_cache[domain] = KnowledgeGraph(domain)

    return _graph_cache[domain]


def reload_graph(domain: str) -> KnowledgeGraph:
    """
    Force reload a knowledge graph (useful for development).

    Args:
        domain: Domain name

    Returns:
        Freshly loaded KnowledgeGraph instance
    """
    if domain in _graph_cache:
        del _graph_cache[domain]

    return get_knowledge_graph(domain)


def list_available_graphs() -> List[str]:
    """List all available knowledge graphs"""
    graphs_dir = Path(__file__).parent / "graphs"
    if not graphs_dir.exists():
        return []
    return [f.stem for f in graphs_dir.glob("*.yaml")]


def get_all_active_domains() -> List[Dict[str, Any]]:
    """
    Get all active domains from knowledge graphs.

    Scans all YAML files in the graphs directory and extracts metadata
    for domains that are marked as active.

    Returns:
        List of domain metadata dictionaries containing:
        - domain: Domain slug (e.g., 'skincare', 'wellness')
        - display_name: User-facing display name
        - persona: Agent personality/instructions
        - is_active: Active status (always True in results)
        - parent_domain: Parent domain slug or None
        - version: Semantic version
        - description: Human-readable description
    """
    graphs_dir = Path(__file__).parent / "graphs"
    if not graphs_dir.exists():
        logger.warning(f"Graphs directory not found: {graphs_dir}")
        return []

    active_domains = []

    for yaml_file in graphs_dir.glob("*.yaml"):
        try:
            with open(yaml_file, 'r') as f:
                data = yaml.safe_load(f)

            # Validate schema to ensure metadata is complete
            try:
                schema = KnowledgeGraphSchema(**data)
                metadata = schema.metadata
            except Exception as e:
                logger.error(f"Invalid schema in {yaml_file}: {e}")
                continue

            # Only include active domains
            if metadata.is_active:
                active_domains.append({
                    'domain': metadata.domain,
                    'display_name': metadata.display_name,
                    'persona': metadata.persona,
                    'is_active': metadata.is_active,
                    'parent_domain': metadata.parent_domain,
                    'version': metadata.version,
                    'description': metadata.description,
                })

        except Exception as e:
            logger.error(f"Error loading domain from {yaml_file}: {e}")
            continue

    logger.info(f"Loaded {len(active_domains)} active domains")
    return active_domains
