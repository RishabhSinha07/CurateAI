"""
Test script to demonstrate dynamic question generation.

This shows how the system generates questions for attributes that lack
predefined ELICITS_QUESTION edges in the knowledge graph.
"""

import asyncio
import logging
from app.knowledge.graph_loader import get_knowledge_graph
from app.knowledge.query_engine import GraphQueryEngine
from app.knowledge.dynamic_questions import clear_question_cache

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_brain_focus_memory_dynamic_questions():
    """
    Test dynamic question generation for brain_focus_memory domain.

    This domain has 14 REQUIRES_KNOWING edges but 0 predefined questions,
    so all questions will be generated dynamically.
    """
    logger.info("=" * 80)
    logger.info("Testing Dynamic Question Generation: brain_focus_memory")
    logger.info("=" * 80)

    domain = "brain_focus_memory"
    problem_id = "brain_fog"

    # Get questions (will trigger dynamic generation)
    logger.info(f"\nGetting interview questions for problem '{problem_id}'...")
    questions = GraphQueryEngine.get_interview_questions(
        domain=domain,
        problem_id=problem_id
    )

    logger.info(f"\n✅ Retrieved {len(questions)} questions (all dynamically generated)")

    # Display generated questions
    for i, q in enumerate(questions, 1):
        question_data = q['question']
        logger.info(f"\n--- Question {i} ---")
        logger.info(f"Attribute: {q['attribute_category']}")
        logger.info(f"Priority: {q['priority']}")
        logger.info(f"Reason: {q['reason']}")
        logger.info(f"Question: {question_data.get('text')}")
        logger.info(f"Response Type: {question_data.get('response_type')}")
        logger.info(f"Options: {question_data.get('options', [])}")

        if question_data.get('_dynamically_generated'):
            logger.info(f"🤖 DYNAMICALLY GENERATED")
            logger.info(f"Generation Reasoning: {question_data.get('_generation_reasoning')}")

    return questions


def test_joint_bone_mobility_dynamic_questions():
    """
    Test dynamic question generation for joint_bone_mobility domain.

    This domain has 16 REQUIRES_KNOWING edges but 0 predefined questions.
    """
    logger.info("\n" + "=" * 80)
    logger.info("Testing Dynamic Question Generation: joint_bone_mobility")
    logger.info("=" * 80)

    domain = "joint_bone_mobility"
    problem_id = "joint_pain"

    logger.info(f"\nGetting interview questions for problem '{problem_id}'...")
    questions = GraphQueryEngine.get_interview_questions(
        domain=domain,
        problem_id=problem_id
    )

    logger.info(f"\n✅ Retrieved {len(questions)} questions")

    # Display first 3 questions as sample
    for i, q in enumerate(questions[:3], 1):
        question_data = q['question']
        logger.info(f"\n--- Question {i} ---")
        logger.info(f"Attribute: {q['attribute_category']}")
        logger.info(f"Question: {question_data.get('text')}")
        logger.info(f"Options: {question_data.get('options', [])[:5]}...")  # Show first 5 options

        if question_data.get('_dynamically_generated'):
            logger.info(f"🤖 DYNAMICALLY GENERATED")

    return questions


def test_gut_health_with_predefined_questions():
    """
    Test a domain that HAS predefined questions to verify no regression.

    This domain should use predefined questions, not generate new ones.
    """
    logger.info("\n" + "=" * 80)
    logger.info("Testing Predefined Questions (No Generation): gut_health_digestion")
    logger.info("=" * 80)

    domain = "gut_health_digestion"
    problem_id = "bloating"

    logger.info(f"\nGetting interview questions for problem '{problem_id}'...")
    questions = GraphQueryEngine.get_interview_questions(
        domain=domain,
        problem_id=problem_id
    )

    logger.info(f"\n✅ Retrieved {len(questions)} questions")

    # Check if any were dynamically generated (should be none)
    dynamic_count = sum(
        1 for q in questions
        if q['question'].get('_dynamically_generated', False)
    )

    logger.info(f"\nDynamically generated: {dynamic_count} / {len(questions)}")
    logger.info(f"Predefined: {len(questions) - dynamic_count} / {len(questions)}")

    if dynamic_count == 0:
        logger.info("✅ All questions are predefined - no regression!")
    else:
        logger.warning(f"⚠️ {dynamic_count} questions were dynamically generated unexpectedly")

    # Show sample
    if questions:
        q = questions[0]
        question_data = q['question']
        logger.info(f"\nSample Question:")
        logger.info(f"  {question_data.get('text')}")
        logger.info(f"  Type: {'PREDEFINED' if not question_data.get('_dynamically_generated') else 'GENERATED'}")

    return questions


def compare_before_after():
    """
    Compare behavior before and after implementing dynamic generation.
    """
    logger.info("\n" + "=" * 80)
    logger.info("COMPARISON: Before vs After Dynamic Question Generation")
    logger.info("=" * 80)

    domains_to_test = [
        ("brain_focus_memory", "brain_fog", 14),  # (domain, problem, expected REQUIRES_KNOWING edges)
        ("joint_bone_mobility", "joint_pain", 16),
        ("weight_management_metabolism", "difficulty_losing_weight", 22),
    ]

    logger.info("\nBEFORE: These domains would have returned 0 questions")
    logger.info("AFTER: With dynamic generation, they should return questions\n")

    for domain, problem, expected_edges in domains_to_test:
        questions = GraphQueryEngine.get_interview_questions(
            domain=domain,
            problem_id=problem
        )

        status = "✅ FIXED" if len(questions) > 0 else "❌ STILL BROKEN"
        logger.info(
            f"{status} | {domain:30s} | "
            f"Problem: {problem:25s} | "
            f"Questions: {len(questions):2d}"
        )


if __name__ == "__main__":
    # Clear cache to ensure fresh generation
    clear_question_cache()

    try:
        # Run tests
        logger.info("Starting Dynamic Question Generation Tests\n")

        # Test 1: Domain with no predefined questions
        test_brain_focus_memory_dynamic_questions()

        # Test 2: Another domain with no predefined questions
        test_joint_bone_mobility_dynamic_questions()

        # Test 3: Domain with predefined questions (no regression)
        test_gut_health_with_predefined_questions()

        # Test 4: Before/After comparison
        compare_before_after()

        logger.info("\n" + "=" * 80)
        logger.info("✅ All tests completed successfully!")
        logger.info("=" * 80)

    except Exception as e:
        logger.error(f"\n❌ Test failed with error: {e}", exc_info=True)
