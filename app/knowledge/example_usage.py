#!/usr/bin/env python3
"""
Example usage of the knowledge graph system.

This script demonstrates how agents can use the knowledge graph.
"""

from app.knowledge import get_knowledge_graph, GraphQueryEngine


def example_skincare_flow():
    """Example: Skincare consultation flow"""
    print("\n" + "=" * 70)
    print("EXAMPLE: Skincare Consultation Flow")
    print("=" * 70)

    # User input: "I have dark spots on my face"
    user_input = "hyperpigmentation"

    print(f"\n1. User says: 'I have {user_input}'")

    # Router Agent: Find problem using synonym matching
    problem = GraphQueryEngine.extract_problem_from_text("skincare", user_input)

    if problem:
        print(f"\n2. Router matched to problem: '{problem['display_name']}' (ID: {problem['id']})")
    else:
        print(f"\n2. Router could not find problem for: '{user_input}'")
        return

    # Interviewer Agent: Get questions to ask
    print(f"\n3. Interviewer getting required questions...")

    questions = GraphQueryEngine.get_interview_questions("skincare", problem['id'])

    for i, q_data in enumerate(questions[:3], 1):  # Show first 3
        question = q_data['question']
        print(f"\n   Question {i} (priority={q_data['priority']}):")
        print(f"   {question['text']}")
        print(f"   Options: {', '.join(question.get('options', []))}")
        print(f"   Reason: {q_data['reason']}")

    # Simulate user answering
    print(f"\n4. User answers: 'Oily skin'")

    user_attributes = {
        "skin_type": "skin_type_oily"
    }

    # Search Architect: Build search query
    print(f"\n5. Search Architect building query...")

    search_query = GraphQueryEngine.build_search_query(
        "skincare",
        problem['id'],
        user_attributes
    )

    print(f"\n   Primary ingredients: {', '.join(search_query['primary_ingredients'])}")
    print(f"\n   Boost scores:")
    for ing, score in list(search_query['boost_scores'].items())[:5]:
        print(f"     - {ing}: {score:.2f}")

    # Reranker: Check constraints
    print(f"\n6. Reranker checking constraints...")

    # Simulate product with vitamin C
    product_ingredients = ["vitamin_c", "hyaluronic_acid"]
    user_constraints = {"pregnancy": False}

    safety = GraphQueryEngine.filter_by_constraints(
        "skincare",
        product_ingredients,
        user_constraints
    )

    print(f"\n   Product ingredients: {', '.join(product_ingredients)}")
    print(f"   Is safe: {safety['is_safe']}")
    if not safety['is_safe']:
        for violation in safety['violations']:
            print(f"   ⚠ {violation['reason']}")
            print(f"     Alternatives: {', '.join(violation['alternatives'])}")


def example_wellness_flow():
    """Example: Wellness supplement flow"""
    print("\n" + "=" * 70)
    print("EXAMPLE: Wellness Supplement Flow")
    print("=" * 70)

    # User input: "I'm always tired"
    user_input = "fatigue"

    print(f"\n1. User says: 'I'm experiencing {user_input}'")

    # Router Agent
    problem = GraphQueryEngine.extract_problem_from_text("wellness", user_input)

    if problem:
        print(f"\n2. Router matched to problem: '{problem['display_name']}' (ID: {problem['id']})")
    else:
        print(f"\n2. Router could not find problem for: '{user_input}'")
        return

    # Interviewer Agent
    print(f"\n3. Interviewer getting required questions...")

    questions = GraphQueryEngine.get_interview_questions("wellness", problem['id'])

    for i, q_data in enumerate(questions[:2], 1):
        question = q_data['question']
        print(f"\n   Question {i} (priority={q_data['priority']}):")
        print(f"   {question['text']}")
        print(f"   Options: {', '.join(question.get('options', []))}")

    # Simulate user answering
    print(f"\n4. User answers: 'Female'")

    user_attributes = {
        "gender": "gender_female"
    }

    # Search Architect
    print(f"\n5. Search Architect building query...")

    search_query = GraphQueryEngine.build_search_query(
        "wellness",
        problem['id'],
        user_attributes
    )

    print(f"\n   Primary ingredients: {', '.join(search_query['primary_ingredients'])}")
    print(f"\n   Boost scores:")
    for ing, score in list(search_query['boost_scores'].items())[:5]:
        print(f"     - {ing}: {score:.2f}")

    # Reranker: Check vegan constraint
    print(f"\n6. Reranker checking constraints (vegan diet)...")

    product_ingredients = ["marine_collagen"]
    user_constraints = {"dietary": "vegan"}

    safety = GraphQueryEngine.filter_by_constraints(
        "wellness",
        product_ingredients,
        user_constraints
    )

    print(f"\n   Product ingredients: {', '.join(product_ingredients)}")
    print(f"   Is safe: {safety['is_safe']}")
    if not safety['is_safe']:
        for violation in safety['violations']:
            print(f"   ⚠ {violation['reason']}")
            print(f"     Alternatives: {', '.join(violation['alternatives'])}")


def show_graph_overview():
    """Show overview of available graphs"""
    print("\n" + "=" * 70)
    print("KNOWLEDGE GRAPH OVERVIEW")
    print("=" * 70)

    for domain in ["skincare", "wellness"]:
        stats = GraphQueryEngine.get_graph_stats(domain)

        print(f"\n{domain.upper()} (v{stats['version']})")
        print(f"  Total: {stats['total_nodes']} nodes, {stats['total_edges']} edges")
        print(f"  Problems: {stats['nodes_by_type'].get('problem', 0)}")
        print(f"  Ingredients: {stats['nodes_by_type'].get('ingredient', 0)}")
        print(f"  Attributes: {stats['nodes_by_type'].get('attribute', 0)}")


def main():
    """Run all examples"""
    show_graph_overview()
    example_skincare_flow()
    example_wellness_flow()

    print("\n" + "=" * 70)
    print("Examples complete!")
    print("=" * 70 + "\n")


if __name__ == '__main__':
    main()
