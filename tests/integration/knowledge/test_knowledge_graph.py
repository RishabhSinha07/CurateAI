"""
Integration tests for knowledge graph with Router and Interviewer agents.

These tests verify that the agents correctly use the knowledge graph.
"""

import pytest
import uuid
from typing import Dict, Any

from app.knowledge.query_engine import GraphQueryEngine
from app.knowledge.graph_loader import get_knowledge_graph


class TestRouterGraphIntegration:
    """Test Router agent's knowledge graph integration."""

    def test_problem_extraction_wellness(self):
        """Test problem extraction for wellness domain."""
        # Test various synonyms
        test_cases = [
            ("fatigue", "low_energy"),
            ("tired", "low_energy"),
            ("can't sleep", "poor_sleep"),
            ("insomnia", "poor_sleep"),
            ("hair loss", "hair_thinning"),
            ("weak hair", "hair_thinning"),
        ]

        for input_text, expected_problem in test_cases:
            problem = GraphQueryEngine.extract_problem_from_text("wellness", input_text)
            assert problem is not None, f"Failed to find problem for: {input_text}"
            assert problem['id'] == expected_problem, (
                f"Wrong problem for '{input_text}': "
                f"expected {expected_problem}, got {problem['id']}"
            )

    def test_problem_not_found(self):
        """Test behavior when problem is not in graph."""
        problem = GraphQueryEngine.extract_problem_from_text("wellness", "random nonsense")
        assert problem is None

    def test_graph_domain_mapping(self):
        """Test that problems are correctly mapped to domains."""
        # Wellness problems
        wellness_problem = GraphQueryEngine.extract_problem_from_text("wellness", "low energy")
        assert wellness_problem is not None

        # Skincare problems (if skincare.yaml exists)
        try:
            skincare_problem = GraphQueryEngine.extract_problem_from_text("skincare", "dark spots")
            assert skincare_problem is not None
        except FileNotFoundError:
            # Skincare graph not created yet
            pass


class TestInterviewerGraphIntegration:
    """Test Interviewer agent's knowledge graph integration."""

    def test_get_interview_questions_wellness(self):
        """Test getting interview questions for wellness problems."""
        # Get questions for low_energy problem
        questions = GraphQueryEngine.get_interview_questions("wellness", "low_energy")

        assert len(questions) > 0, "No questions returned for low_energy"

        # Verify question structure
        for q in questions:
            assert 'attribute_category' in q
            assert 'priority' in q
            assert 'is_optional' in q
            assert 'reason' in q
            assert 'question' in q
            assert 'text' in q['question']
            assert 'options' in q['question']

        # Questions should be sorted by priority
        priorities = [q['priority'] for q in questions]
        assert priorities == sorted(priorities), "Questions not sorted by priority"

    def test_question_priority_ordering(self):
        """Test that questions are returned in priority order."""
        questions = GraphQueryEngine.get_interview_questions("wellness", "low_energy")

        if len(questions) > 1:
            # First question should have lower priority number (higher importance)
            assert questions[0]['priority'] <= questions[-1]['priority']

    def test_question_reasons_provided(self):
        """Test that each question has a reason explaining why it's needed."""
        questions = GraphQueryEngine.get_interview_questions("wellness", "low_energy")

        for q in questions:
            assert q['reason'] != "", f"Missing reason for question: {q['question']['text']}"

    def test_optional_vs_required_questions(self):
        """Test that questions correctly indicate if they're optional."""
        questions = GraphQueryEngine.get_interview_questions("wellness", "aging_skin")

        # Should have at least one required question for diet (vegan vs marine collagen)
        required_questions = [q for q in questions if not q['is_optional']]
        assert len(required_questions) > 0, "No required questions found"


class TestSearchQueryBuilding:
    """Test search query building with graph attributes."""

    def test_build_search_query_basic(self):
        """Test basic search query building."""
        query = GraphQueryEngine.build_search_query(
            domain="wellness",
            problem_id="low_energy",
            user_attributes={}
        )

        assert 'primary_ingredients' in query
        assert 'all_ingredients' in query
        assert 'boost_scores' in query

        # Should recommend iron and vitamin B12 for low energy
        all_ingredients = query['all_ingredients']
        assert 'iron' in all_ingredients or 'vitamin_b12' in all_ingredients

    def test_build_search_query_with_attributes(self):
        """Test that user attributes boost recommended ingredients."""
        # Without gender attribute
        query_no_attr = GraphQueryEngine.build_search_query(
            domain="wellness",
            problem_id="low_energy",
            user_attributes={}
        )

        # With female gender (iron should be boosted)
        query_with_attr = GraphQueryEngine.build_search_query(
            domain="wellness",
            problem_id="low_energy",
            user_attributes={"gender": "gender_female"}
        )

        # Iron should have higher boost score with female attribute
        iron_score_no_attr = query_no_attr['boost_scores'].get('iron', 0)
        iron_score_with_attr = query_with_attr['boost_scores'].get('iron', 0)

        assert iron_score_with_attr >= iron_score_no_attr, (
            "Iron should be boosted for female users"
        )

    def test_primary_ingredients_limited(self):
        """Test that primary ingredients are limited to top 3."""
        query = GraphQueryEngine.build_search_query(
            domain="wellness",
            problem_id="low_energy",
            user_attributes={}
        )

        assert len(query['primary_ingredients']) <= 3


class TestConstraintFiltering:
    """Test constraint-based product filtering."""

    def test_vegan_constraint(self):
        """Test that marine collagen is excluded for vegans."""
        safety = GraphQueryEngine.filter_by_constraints(
            domain="wellness",
            product_ingredients=["marine_collagen"],
            user_constraints={"dietary": "vegan"}
        )

        assert not safety['is_safe'], "Marine collagen should be unsafe for vegans"
        assert len(safety['violations']) > 0

        # Check for alternatives
        violation = safety['violations'][0]
        assert 'alternatives' in violation
        assert 'vegan_collagen' in violation['alternatives']

    def test_pregnancy_constraint(self):
        """Test that contraindicated ingredients are flagged for pregnancy."""
        safety = GraphQueryEngine.filter_by_constraints(
            domain="wellness",
            product_ingredients=["ashwagandha"],
            user_constraints={"medical": "true", "pregnancy": True}
        )

        assert not safety['is_safe'], "Ashwagandha should be flagged for pregnancy"

        # Check reason
        violation = safety['violations'][0]
        assert 'uterine' in violation['reason'].lower()

    def test_safe_product(self):
        """Test that safe products pass constraint checking."""
        safety = GraphQueryEngine.filter_by_constraints(
            domain="wellness",
            product_ingredients=["vitamin_b12", "vitamin_d3"],
            user_constraints={"pregnancy": False}
        )

        assert safety['is_safe'], "Vitamins should be safe"
        assert len(safety['violations']) == 0

    def test_ingredient_not_in_graph(self):
        """Test behavior when ingredient is not in graph."""
        safety = GraphQueryEngine.filter_by_constraints(
            domain="wellness",
            product_ingredients=["unknown_ingredient"],
            user_constraints={"pregnancy": True}
        )

        # Should default to safe if ingredient not in graph
        assert safety['is_safe']


class TestGraphStats:
    """Test graph statistics and metadata."""

    def test_get_graph_stats(self):
        """Test retrieving graph statistics."""
        stats = GraphQueryEngine.get_graph_stats("wellness")

        assert 'domain' in stats
        assert stats['domain'] == "wellness"
        assert 'total_nodes' in stats
        assert 'total_edges' in stats
        assert 'nodes_by_type' in stats
        assert 'edges_by_relation' in stats

        # Should have problems
        assert stats['nodes_by_type'].get('problem', 0) > 0

        # Should have ingredients
        assert stats['nodes_by_type'].get('ingredient', 0) > 0

    def test_wellness_graph_structure(self):
        """Test that wellness graph has expected structure."""
        graph = get_knowledge_graph("wellness")

        # Should have problems
        problems = graph.find_nodes_by_type('problem')
        assert len(problems) >= 8, "Expected at least 8 problems in wellness graph"

        # Should have ingredients
        ingredients = graph.find_nodes_by_type('ingredient')
        assert len(ingredients) >= 10, "Expected at least 10 ingredients"

        # Should have TREATS relationships
        low_energy_problem = graph.get_node("low_energy")
        assert low_energy_problem is not None

        treating_ingredients = graph.get_treating_ingredients("low_energy")
        assert len(treating_ingredients) > 0, "No treating ingredients for low_energy"


class TestEndToEndFlow:
    """Test complete flow from problem extraction to search query."""

    def test_complete_wellness_flow(self):
        """Test complete flow: problem → questions → search."""
        # Step 1: Router extracts problem
        problem = GraphQueryEngine.extract_problem_from_text("wellness", "I'm always tired")
        assert problem is not None
        assert problem['id'] == "low_energy"

        # Step 2: Interviewer gets questions
        questions = GraphQueryEngine.get_interview_questions("wellness", problem['id'])
        assert len(questions) > 0

        # Step 3: User provides attributes (simulated)
        user_attributes = {
            "gender": "gender_female",
            "activity_level": "activity_sedentary"
        }

        # Step 4: Search builds query
        search_query = GraphQueryEngine.build_search_query(
            domain="wellness",
            problem_id=problem['id'],
            user_attributes=user_attributes
        )

        assert len(search_query['primary_ingredients']) > 0

        # Iron should be highly ranked for female + low energy
        assert 'iron' in search_query['all_ingredients']

    def test_skincare_flow_if_available(self):
        """Test skincare flow if graph exists."""
        try:
            # Step 1: Extract problem
            problem = GraphQueryEngine.extract_problem_from_text("skincare", "dark spots")
            assert problem is not None

            # Step 2: Get questions
            questions = GraphQueryEngine.get_interview_questions("skincare", problem['id'])
            assert len(questions) > 0

        except FileNotFoundError:
            # Skincare graph not created yet, skip test
            pytest.skip("Skincare graph not available")


# Run tests with: pytest tests/test_graph_integration.py -v
