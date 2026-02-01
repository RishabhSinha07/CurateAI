"""
High-level query engine for knowledge graph operations.

This module provides agent-friendly interfaces for common graph queries.
"""

from typing import Dict, List, Optional, Any
import logging

from .graph_loader import get_knowledge_graph

logger = logging.getLogger(__name__)


class GraphQueryEngine:
    """
    High-level query interface for agents.

    Provides semantic query methods that combine multiple graph traversals.
    """

    @staticmethod
    def extract_problem_from_text(domain: str, text: str) -> Optional[Dict[str, Any]]:
        """
        Extract problem from user text using synonym matching.

        This is typically used after LLM extracts an entity from user input.

        Args:
            domain: Domain to search in
            text: Problem text (e.g., "hyperpigmentation", "dark spots")

        Returns:
            Problem node dictionary if found, None otherwise

        Example:
            >>> problem = extract_problem_from_text("skincare", "hyperpigmentation")
            >>> problem['id']  # 'dark_spots'
        """
        graph = get_knowledge_graph(domain)
        problem_id = graph.find_problem_by_synonym(text)

        if problem_id:
            return graph.get_node(problem_id)

        logger.debug(f"Problem not found for text: '{text}' in domain '{domain}'")
        return None

    @staticmethod
    def get_interview_questions(
        domain: str,
        problem_id: str,
        context: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Get prioritized interview questions for slot-filling.

        Returns questions in priority order based on REQUIRES_KNOWING edges.

        Args:
            domain: Domain to query
            problem_id: Problem node ID
            context: Optional context for conditional questions

        Returns:
            List of question dictionaries with priority and metadata

        Example:
            >>> questions = get_interview_questions("skincare", "dark_spots")
            >>> questions[0]['priority']  # 1 (highest priority)
            >>> questions[0]['question']['text']  # "What is your skin type?"
        """
        graph = get_knowledge_graph(domain)
        context = context or {}

        # Get required attributes
        required_attrs = graph.get_required_attributes(problem_id)

        questions = []
        for attr_edge in required_attrs:
            attr_id = attr_edge['attribute_id']
            attr_data = attr_edge['attribute_data']

            # Get question for this attribute category
            # Pass problem_id in context for better dynamic question generation
            question_context = {**context, 'problem_id': problem_id}
            question = graph.get_question_for_attribute(attr_id, question_context)

            if question:
                questions.append({
                    'attribute_id': attr_id,
                    'attribute_category': attr_data.get('category'),
                    'priority': attr_edge['priority'],
                    'is_optional': attr_edge['is_optional'],
                    'reason': attr_edge['reason'],
                    'question': question
                })
            else:
                # Question generation failed (both predefined and dynamic)
                logger.warning(
                    f"Could not get or generate question for attribute '{attr_id}' "
                    f"(category: {attr_data.get('category')}) in domain '{domain}'"
                )

        return questions

    @staticmethod
    def build_search_query(
        domain: str,
        problem_id: str,
        user_attributes: Dict[str, str],
        boost_factor: float = 0.2
    ) -> Dict[str, Any]:
        """
        Build ingredient-based search query with attribute boosting.

        Finds ingredients that treat the problem, then boosts those
        recommended for the user's specific attributes.

        Args:
            domain: Domain to query
            problem_id: Problem node ID
            user_attributes: User's extracted attributes (attr_id -> value)
            boost_factor: Boost amount for matching attributes (0.0-1.0)

        Returns:
            Search query dictionary with prioritized ingredients

        Example:
            >>> query = build_search_query(
            ...     "skincare",
            ...     "dark_spots",
            ...     {"skin_type": "skin_type_oily"}
            ... )
            >>> query['primary_ingredients']  # ['niacinamide', 'vitamin_c', ...]
        """
        graph = get_knowledge_graph(domain)

        # Get ingredients that treat the problem
        treating_ingredients = graph.get_treating_ingredients(problem_id, min_efficacy=0.5)

        if not treating_ingredients:
            logger.warning(f"No treating ingredients found for problem '{problem_id}'")
            return {
                'primary_ingredients': [],
                'all_ingredients': [],
                'problem': problem_id,
                'boost_scores': {}
            }

        # Boost ingredients recommended for user's attributes
        boosted_ingredients = []
        for ing in treating_ingredients:
            boost_score = ing['efficacy']

            # Check if recommended for any user attributes
            for attr_id in user_attributes.values():
                if not attr_id:
                    continue

                recommended = graph.get_recommended_ingredients_for_attribute(
                    attr_id,
                    min_strength=0.0  # Get all to check
                )

                # Check if this ingredient is in the recommended list
                if any(r['id'] == ing['id'] for r in recommended):
                    # Find the strength to boost proportionally
                    strength = next(
                        (r['strength'] for r in recommended if r['id'] == ing['id']),
                        0.0
                    )
                    boost_score += boost_factor * strength

            boosted_ingredients.append({
                **ing,
                'boost_score': min(boost_score, 1.0)  # Cap at 1.0
            })

        # Sort by boosted score
        boosted_ingredients.sort(key=lambda x: x['boost_score'], reverse=True)

        # Extract top 3 as primary
        primary = [i['name'] for i in boosted_ingredients[:3]]
        all_ing = [i['name'] for i in boosted_ingredients]

        return {
            'primary_ingredients': primary,
            'all_ingredients': all_ing,
            'problem': problem_id,
            'boost_scores': {
                i['name']: i['boost_score']
                for i in boosted_ingredients
            }
        }

    @staticmethod
    def filter_by_constraints(
        domain: str,
        product_ingredients: List[str],
        user_constraints: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Check if product violates any user constraints.

        Args:
            domain: Domain to query
            product_ingredients: List of ingredient names in the product
            user_constraints: User constraints (e.g., {'pregnancy': True, 'allergy': 'dairy'})

        Returns:
            Safety check dictionary with violations

        Example:
            >>> safety = filter_by_constraints(
            ...     "skincare",
            ...     ["retinol", "hyaluronic_acid"],
            ...     {"pregnancy": True}
            ... )
            >>> safety['is_safe']  # False
            >>> safety['violations'][0]['reason']  # "May cause birth defects"
        """
        graph = get_knowledge_graph(domain)

        violations = []
        for ingredient_name in product_ingredients:
            # Find ingredient node
            ingredient_id = graph.find_ingredient_by_name(ingredient_name)

            if not ingredient_id:
                logger.debug(
                    f"Ingredient '{ingredient_name}' not found in graph '{domain}'"
                )
                continue

            # Check contraindications
            ingredient_violations = graph.check_contraindications(
                ingredient_id,
                user_constraints
            )

            violations.extend(ingredient_violations)

        return {
            'is_safe': len(violations) == 0,
            'violations': violations,
            'checked_ingredients': len(product_ingredients),
            'found_in_graph': sum(
                1 for ing in product_ingredients
                if graph.find_ingredient_by_name(ing) is not None
            )
        }

    @staticmethod
    def get_attribute_question(
        domain: str,
        attribute_category: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get question for an attribute category.

        Args:
            domain: Domain to query
            attribute_category: Attribute category (e.g., 'skin_type', 'age_group')

        Returns:
            Question dictionary if found, None otherwise
        """
        graph = get_knowledge_graph(domain)

        # Find an attribute with this category
        all_attrs = graph.find_nodes_by_type('attribute')

        for attr in all_attrs:
            if attr.get('category') == attribute_category:
                question = graph.get_question_for_attribute(attr['id'])
                if question:
                    return question

        logger.debug(
            f"No question found for attribute category '{attribute_category}' "
            f"in domain '{domain}'"
        )
        return None

    @staticmethod
    def expand_problem_search(
        domain: str,
        problem_id: str,
        min_similarity: float = 0.7
    ) -> List[str]:
        """
        Expand problem search to include similar problems.

        Useful for query expansion in search.

        Args:
            domain: Domain to query
            problem_id: Primary problem node ID
            min_similarity: Minimum similarity threshold

        Returns:
            List of problem IDs (including the original)

        Example:
            >>> problems = expand_problem_search("skincare", "dark_spots", 0.8)
            >>> problems  # ['dark_spots', 'uneven_tone', 'sun_damage']
        """
        graph = get_knowledge_graph(domain)

        similar = graph.find_similar_problems(problem_id, min_similarity)

        # Include original problem
        problem_ids = [problem_id]

        # Add similar problems
        problem_ids.extend(p['id'] for p in similar)

        return problem_ids

    @staticmethod
    def get_domain_for_problem(domain: str, problem_id: str) -> Optional[str]:
        """
        Get the domain/subdomain for a problem.

        Useful for routing decisions.

        Args:
            domain: Domain to query
            problem_id: Problem node ID

        Returns:
            Domain/subdomain name if found
        """
        graph = get_knowledge_graph(domain)

        # Find BELONGS_TO edges from problem
        edges = graph.get_outgoing_edges(problem_id, relation='BELONGS_TO')

        if edges:
            target_id = edges[0]['target']
            target_node = graph.get_node(target_id)

            if target_node:
                return target_node.get('name')

        return None

    @staticmethod
    def validate_attribute_value(
        domain: str,
        attribute_category: str,
        value: str
    ) -> bool:
        """
        Validate if an attribute value is valid for a category.

        Args:
            domain: Domain to query
            attribute_category: Attribute category
            value: Value to validate

        Returns:
            True if valid, False otherwise
        """
        graph = get_knowledge_graph(domain)

        # Find all attributes with this category
        all_attrs = graph.find_nodes_by_type('attribute')

        valid_values = [
            attr['value']
            for attr in all_attrs
            if attr.get('category') == attribute_category
        ]

        return value in valid_values

    @staticmethod
    def get_alternatives_for_contraindicated_ingredient(
        domain: str,
        ingredient_id: str,
        constraint_type: str
    ) -> List[str]:
        """
        Get alternative ingredients when one is contraindicated.

        Args:
            domain: Domain to query
            ingredient_id: Contraindicated ingredient ID
            constraint_type: Type of constraint (e.g., 'pregnancy')

        Returns:
            List of alternative ingredient names
        """
        graph = get_knowledge_graph(domain)

        # Get contraindication edges
        edges = graph.get_outgoing_edges(ingredient_id, relation='CONTRAINDICATED_FOR')

        for edge in edges:
            constraint_node = graph.get_node(edge['target'])

            if constraint_node and constraint_node.get('type') == constraint_type:
                return edge.get('alternative_ingredients', [])

        return []

    @staticmethod
    def get_graph_stats(domain: str) -> Dict[str, Any]:
        """
        Get statistics about the knowledge graph.

        Useful for debugging and monitoring.

        Args:
            domain: Domain to query

        Returns:
            Dictionary with graph statistics
        """
        graph = get_knowledge_graph(domain)

        # Count nodes by type
        node_counts = {}
        for node_id, data in graph.graph.nodes(data=True):
            node_type = data.get('node_type', 'unknown')
            node_counts[node_type] = node_counts.get(node_type, 0) + 1

        # Count edges by relation
        edge_counts = {}
        for source, target, data in graph.graph.edges(data=True):
            relation = data.get('relation', 'unknown')
            edge_counts[relation] = edge_counts.get(relation, 0) + 1

        return {
            'domain': domain,
            'version': graph.metadata.version if graph.metadata else 'unknown',
            'total_nodes': graph.graph.number_of_nodes(),
            'total_edges': graph.graph.number_of_edges(),
            'nodes_by_type': node_counts,
            'edges_by_relation': edge_counts
        }
